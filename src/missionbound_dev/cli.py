"""mission — run a coding agent inside a mission.

  mission init                      write mission.yaml (if absent), hooks, state      [human]
  mission status                    phase, what may be written, requirement status
  mission check [ID ...]            run requirement checks
  mission advance                   next phase, if this phase's gate is `checks` and they pass
  mission approve [--to PHASE]      pass a human gate                                  [human]
  mission request-change ID TEXT    write change-requests/CR-<ID>-<time>.md
  mission hook guard|stop|session-start|prompt   (called by Claude Code, JSON on stdin)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .checks import run_checks
from .hooks import context_text, run_hook
from .mission import (MISSION_FILE, STATE_DIR, MissionError, State, find_root, load_mission,
                      load_state, save_state)

TEMPLATE = """\
title: {title}
# What "done" means. Each check is a shell command; exit 0 = the requirement holds.
# Write these (and the tests they run) BEFORE the agent starts. The agent cannot edit them.
goal:
  - id: REQ-1
    description: replace with the first requirement
    check: "pytest -q tests/acceptance"
# Paths the agent may never write (mission.yaml, .mission/ and .claude/ are always protected).
protected:
  - requirements/**
  - tests/acceptance/**
initial_phase: design
phases:
  design:
    writes: ["docs/**"]
    next: implement
    gate: human              # you run `mission approve` after reading the design
  implement:
    writes: ["src/**", "tests/**", "docs/**", "README.md", "pyproject.toml"]
    next: verify
    gate: checks             # `mission advance` succeeds only when every check passes
    stop_requires_checks: true
  verify:
    writes: ["docs/**", "README.md"]
    next: done
    gate: human
    stop_requires_checks: true
forbidden_bash: ["git push --force", "git reset --hard", "rm -rf /", "--no-verify"]
limits:
  stop_blocks: 5             # after this many refused stops, let the agent stop and report
  check_timeout_s: 600
"""

HOOKS = {
    "SessionStart": [{"hooks": [{"type": "command", "command": "mission hook session-start"}]}],
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "mission hook prompt"}]}],
    "PreToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash",
                    "hooks": [{"type": "command", "command": "mission hook guard"}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "mission hook stop"}]}],
}


def cmd_init(root: Path) -> int:
    mf = root / MISSION_FILE
    if not mf.exists():
        mf.write_text(TEMPLATE.format(title=root.resolve().name))
        print(f"wrote {MISSION_FILE} (edit it: requirements and their checks first)")
    settings = root / ".claude" / "settings.json"
    settings.parent.mkdir(exist_ok=True)
    data = json.loads(settings.read_text()) if settings.exists() else {}
    hooks = data.setdefault("hooks", {})
    for event, entries in HOOKS.items():
        cur = hooks.setdefault(event, [])
        for e in entries:
            if e not in cur:
                cur.append(e)
    settings.write_text(json.dumps(data, indent=2) + "\n")
    print("wrote .claude/settings.json hooks")
    gi = root / ".gitignore"
    lines = gi.read_text().splitlines() if gi.exists() else []
    if f"{STATE_DIR}/" not in lines:
        gi.write_text("\n".join([*lines, f"{STATE_DIR}/"]) + "\n")
    m = load_mission(root)
    if not (root / STATE_DIR / "state.json").exists():
        st = State(phase=m.initial_phase)
        st.log("init")
        save_state(m, st)
    print(f"phase: {load_state(m).phase}")
    return 0


def cmd_check(root: Path, ids: list[str]) -> int:
    m = load_mission(root)
    st = load_state(m)
    results = run_checks(m, ids or None)
    st.last_check.update({r.id: r.passed for r in results})
    save_state(m, st)
    for r in results:
        print(f"{'pass' if r.passed else 'FAIL'}  {r.id}  {m.requirement(r.id).description}")
        if not r.passed and r.tail:
            print("      " + r.tail.replace("\n", "\n      "))
    return 0 if all(r.passed for r in results) else 1


def _move(m, st, to: str, how: str) -> None:
    st.log("phase", frm=st.phase, to=to, how=how)
    st.phase, st.stop_blocks = to, 0
    save_state(m, st)
    print(f"phase: {to}")


def cmd_advance(root: Path) -> int:
    m = load_mission(root)
    st = load_state(m)
    if st.phase == "done":
        print("mission is done"); return 0
    ph = m.phases[st.phase]
    if ph.gate == "human":
        print(f"phase '{ph.name}' has a human gate: the human runs `mission approve`"); return 2
    results = run_checks(m)
    st.last_check = {r.id: r.passed for r in results}
    failing = [r.id for r in results if not r.passed]
    if failing:
        save_state(m, st)
        print(f"cannot advance: failing {', '.join(failing)}"); return 1
    _move(m, st, ph.next or "done", "checks")
    return 0


def cmd_approve(root: Path, to: str | None) -> int:
    m = load_mission(root)
    st = load_state(m)
    if st.phase == "done" and not to:
        print("mission is done"); return 0
    target = to or m.phases[st.phase].next or "done"
    if target != "done" and target not in m.phases:
        print(f"no phase {target}"); return 2
    _move(m, st, target, "human")
    return 0


def cmd_request_change(root: Path, rid: str, text: str) -> int:
    d = root / "change-requests"
    d.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    p = d / f"CR-{rid}-{stamp}.md"
    p.write_text(f"# Change request for {rid}\n\n{text}\n")
    print(f"wrote {p.relative_to(root)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mission", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init"); sub.add_parser("status"); sub.add_parser("advance")
    c = sub.add_parser("check"); c.add_argument("ids", nargs="*")
    a = sub.add_parser("approve"); a.add_argument("--to")
    r = sub.add_parser("request-change"); r.add_argument("id"); r.add_argument("text")
    h = sub.add_parser("hook"); h.add_argument("kind")
    args = ap.parse_args(argv)

    if args.cmd == "hook":
        out, code = run_hook(args.kind, sys.stdin.read())
        if out:
            print(out)
        return code
    try:
        if args.cmd == "init":
            return cmd_init(Path.cwd())
        root = find_root(Path.cwd())
        if args.cmd == "status":
            print(context_text(str(root))); return 0
        if args.cmd == "check":
            return cmd_check(root, args.ids)
        if args.cmd == "advance":
            return cmd_advance(root)
        if args.cmd == "approve":
            return cmd_approve(root, args.to)
        if args.cmd == "request-change":
            return cmd_request_change(root, args.id, args.text)
    except MissionError as e:
        print(f"mission: {e}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
