"""The mission: what "done" means, what may never be touched, and what each phase may write.

mission.yaml is the human's file. The agent can read it but never write it; the same holds
for .mission/ (state) and .claude/ (the hooks that enforce all this) — those three are
protected implicitly, whatever the file says.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

MISSION_FILE = "mission.yaml"
STATE_DIR = ".mission"
STATE_FILE = f"{STATE_DIR}/state.json"
ALWAYS_PROTECTED = (MISSION_FILE, f"{STATE_DIR}/**", ".claude/**")
ALWAYS_WRITABLE = ("change-requests/**",)   # the agent's only channel to ask for a change
GATES = ("human", "checks")


class MissionError(ValueError):
    """mission.yaml is missing or malformed. Hooks treat this as deny, never as allow."""


@dataclass(frozen=True)
class Requirement:
    id: str
    check: str
    description: str = ""


@dataclass(frozen=True)
class Phase:
    name: str
    writes: tuple[str, ...]
    next: str | None
    gate: str
    stop_requires_checks: bool


@dataclass(frozen=True)
class Mission:
    root: Path
    title: str
    goal: tuple[Requirement, ...]
    protected: tuple[str, ...]
    phases: dict[str, Phase]
    initial_phase: str
    forbidden_bash: tuple[str, ...]
    stop_blocks: int
    check_timeout: int

    def requirement(self, rid: str) -> Requirement:
        for r in self.goal:
            if r.id == rid:
                return r
        raise KeyError(rid)


def find_root(start: Path) -> Path:
    for p in (start, *start.parents):
        if (p / MISSION_FILE).is_file():
            return p
    raise MissionError(f"no {MISSION_FILE} in {start} or its parents")


def load_mission(root: Path) -> Mission:
    path = root / MISSION_FILE
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as e:
        raise MissionError(f"cannot read {path}: {e}") from e
    if not isinstance(data, dict):
        raise MissionError(f"{path}: not a mapping")

    goal = []
    for i, g in enumerate(data.get("goal") or []):
        if not isinstance(g, dict) or not g.get("id") or not g.get("check"):
            raise MissionError(f"goal[{i}]: needs id and check")
        goal.append(Requirement(str(g["id"]), str(g["check"]), str(g.get("description", ""))))
    ids = [r.id for r in goal]
    if len(ids) != len(set(ids)):
        raise MissionError("goal: duplicate requirement ids")

    raw_phases = data.get("phases") or {}
    if not raw_phases:
        raise MissionError("phases: at least one phase is required")
    phases = {}
    for name, p in raw_phases.items():
        p = p or {}
        gate = p.get("gate", "human")
        if gate not in GATES:
            raise MissionError(f"phase {name}: gate must be one of {GATES}")
        phases[name] = Phase(name=name, writes=tuple(p.get("writes") or ()), next=p.get("next"),
                             gate=gate, stop_requires_checks=bool(p.get("stop_requires_checks", False)))
    for ph in phases.values():
        if ph.next is not None and ph.next != "done" and ph.next not in phases:
            raise MissionError(f"phase {ph.name}: next={ph.next!r} is not a phase")
    initial = data.get("initial_phase") or next(iter(phases))
    if initial not in phases:
        raise MissionError(f"initial_phase {initial!r} is not a phase")

    limits = data.get("limits") or {}
    return Mission(
        root=root,
        title=str(data.get("title", root.name)),
        goal=tuple(goal),
        protected=tuple(dict.fromkeys([*ALWAYS_PROTECTED, *(data.get("protected") or [])])),
        phases=phases,
        initial_phase=initial,
        forbidden_bash=tuple(data.get("forbidden_bash") or ()),
        stop_blocks=int(limits.get("stop_blocks", 5)),
        check_timeout=int(limits.get("check_timeout_s", 600)),
    )


# --- paths -------------------------------------------------------------------

def matches(rel: str, pattern: str) -> bool:
    """`dir/**` = the directory and everything under it; otherwise fnmatch on the whole path."""
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return rel == prefix or rel.startswith(prefix + "/")
    return fnmatch.fnmatchcase(rel, pattern)


def relative(root: Path, path: str, cwd: str | None = None) -> str | None:
    """Repository-relative POSIX path, or None if it points outside the repository."""
    p = Path(path)
    if not p.is_absolute():
        p = Path(cwd or root) / p
    try:
        return p.resolve(strict=False).relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


# --- state -------------------------------------------------------------------

@dataclass
class State:
    phase: str
    stop_blocks: int = 0
    last_check: dict[str, bool] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)

    def log(self, event: str, **kw) -> None:
        self.history.append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             "event": event, **kw})


def load_state(m: Mission) -> State:
    path = m.root / STATE_FILE
    if not path.exists():
        return State(phase=m.initial_phase)
    d = json.loads(path.read_text())
    st = State(phase=d["phase"], stop_blocks=d.get("stop_blocks", 0),
               last_check=d.get("last_check", {}), history=d.get("history", []))
    if st.phase != "done" and st.phase not in m.phases:
        raise MissionError(f"state phase {st.phase!r} is not in {MISSION_FILE}")
    return st


def save_state(m: Mission, st: State) -> None:
    path = m.root / STATE_FILE
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(st.__dict__, indent=2) + "\n")
