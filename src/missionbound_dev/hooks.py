"""Claude Code hook handlers. Each reads the hook's JSON from stdin and answers on stdout.

  PreToolUse        -> guard:   deny with a reason, or stay silent (normal permissions apply)
  Stop              -> stop:    block stopping while required checks fail (bounded)
  SessionStart,
  UserPromptSubmit  -> context: plain text added to Claude's context every turn

Fail-safe: if mission.yaml cannot be read, writes and Bash are denied, not allowed.
"""

from __future__ import annotations

import json
from pathlib import Path

from .checks import run_checks
from .guard import check_tool
from .mission import (ALWAYS_WRITABLE, MissionError, find_root, load_mission, load_state,
                      save_state)


def _deny(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": f"[mission] {reason}"}}


def on_pre_tool_use(event: dict) -> dict | None:
    cwd = event.get("cwd") or "."
    tool = event.get("tool_name", "")
    try:
        m = load_mission(find_root(Path(cwd)))
        st = load_state(m)
    except MissionError as e:
        if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit", "Bash"):
            return _deny(f"mission unreadable ({e}); ask the human to fix mission.yaml")
        return None
    d = check_tool(m, st, tool, event.get("tool_input") or {}, cwd)
    if d.allow is False:
        st.log("deny", tool=tool, reason=d.reason)
        save_state(m, st)
        return _deny(d.reason)
    return None


def on_stop(event: dict) -> dict | None:
    try:
        m = load_mission(find_root(Path(event.get("cwd") or ".")))
        st = load_state(m)
    except MissionError:
        return None                     # nothing to enforce; never trap the agent on a broken file
    if st.phase == "done" or not m.phases[st.phase].stop_requires_checks:
        return None

    # A change request written since the last block = the agent is asking the human: let it stop.
    last_block = next((h["at"] for h in reversed(st.history) if h["event"] == "stop_blocked"), None)
    cr_dir = m.root / "change-requests"
    if last_block and cr_dir.is_dir():
        from datetime import datetime
        t0 = datetime.fromisoformat(last_block).timestamp()
        if any(p.stat().st_mtime > t0 for p in cr_dir.glob("*.md")):
            st.log("stop_allowed", why="change request pending")
            save_state(m, st)
            return None

    results = run_checks(m)
    st.last_check = {r.id: r.passed for r in results}
    failing = [r for r in results if not r.passed]
    if not failing:
        st.stop_blocks = 0
        st.log("stop_allowed", why="all checks pass")
        save_state(m, st)
        return None
    if st.stop_blocks >= m.stop_blocks:
        st.log("stop_allowed", why=f"block limit {m.stop_blocks} reached",
               failing=[r.id for r in failing])
        save_state(m, st)
        return None

    st.stop_blocks += 1
    st.log("stop_blocked", failing=[r.id for r in failing])
    save_state(m, st)
    lines = [f"Mission not done: {len(failing)} of {len(results)} requirement checks fail "
             f"(stop refused {st.stop_blocks}/{m.stop_blocks})."]
    for r in failing:
        req = m.requirement(r.id)
        lines.append(f"\n{r.id} {req.description}\n$ {req.check}\n{r.tail}")
    lines.append("\nFix the code, not the requirement. If a requirement cannot be met or conflicts "
                 "with another, write change-requests/CR-<id>.md explaining why, then stop.")
    return {"decision": "block", "reason": "\n".join(lines)}


def context_text(cwd: str) -> str:
    try:
        m = load_mission(find_root(Path(cwd)))
        st = load_state(m)
    except MissionError as e:
        return f"[mission] mission.yaml unreadable: {e}. Writes and Bash are denied until it is fixed."
    out = [f"[mission] {m.title} — phase: {st.phase}"]
    if st.phase != "done":
        ph = m.phases[st.phase]
        out.append(f"May write: {', '.join([*ph.writes, *ALWAYS_WRITABLE])}")
        nxt = ph.next or "—"
        how = "`mission advance` (checks must pass)" if ph.gate == "checks" else "the human approves"
        out.append(f"Next phase: {nxt}, via {how}.")
    out.append(f"Protected, never written: {', '.join(m.protected)}")
    if m.goal:
        status = {True: "pass", False: "FAIL"}
        out.append("Requirements: " + "; ".join(
            f"{r.id} [{status.get(st.last_check.get(r.id), 'not run')}] {r.description}" for r in m.goal))
    out.append("Do not weaken, reinterpret or drop a requirement. If one cannot be met, write "
               "change-requests/CR-<id>.md and stop.")
    return "\n".join(out)


def run_hook(kind: str, raw: str) -> tuple[str, int]:
    """Returns (stdout, exit code)."""
    event = json.loads(raw or "{}")
    if kind == "guard":
        res = on_pre_tool_use(event)
    elif kind == "stop":
        res = on_stop(event)
    elif kind in ("session-start", "prompt"):
        return context_text(event.get("cwd") or "."), 0
    else:
        raise SystemExit(f"unknown hook {kind}")
    return (json.dumps(res) if res else ""), 0
