"""PreToolUse: may this tool call happen inside the mission?

Edits are checked exactly: protected paths are absent, and each phase may write only its
own paths. Bash cannot be parsed reliably, so it gets a conservative heuristic; the real
backstop for Bash is a read-only filesystem for protected paths plus the CI check that
requirements did not change (see README, "Limits").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .mission import ALWAYS_WRITABLE, Mission, State, matches, relative

WRITE_TOOLS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path",
               "NotebookEdit": "notebook_path"}
HUMAN_ONLY = re.compile(r"\bmission\s+(approve|reset|init)\b")
WRITE_HINT = re.compile(
    r"(>|\btee\b|\bsed\s+(-\w*\s+)*-i|\brm\b|\bmv\b|\bcp\b|\bchmod\b|\bchown\b|\btruncate\b|"
    r"\bln\b|\binstall\b|\bdd\b|\bpatch\b|\btouch\b|\bunlink\b|"
    r"\bgit\s+(checkout|restore|rm|mv|apply|stash|reset)\b|\bpython3?\b|\bperl\b|\bnode\b|\bruby\b)")


@dataclass(frozen=True)
class Decision:
    allow: bool | None      # True allow, False deny, None = no opinion (normal permissions apply)
    reason: str = ""


def _literal_prefix(pattern: str) -> str:
    # "dir/**" -> "dir": `rm -rf .claude` names the directory without a trailing slash.
    # Conservative on purpose: `rm requirements_old.txt` is also refused.
    cut = min([i for i in (pattern.find(c) for c in "*?[") if i >= 0], default=len(pattern))
    return pattern[:cut].rstrip("/")


def check_tool(m: Mission, st: State, tool: str, tool_input: dict, cwd: str | None) -> Decision:
    if tool in WRITE_TOOLS:
        return _check_write(m, st, tool_input.get(WRITE_TOOLS[tool], ""), cwd)
    if tool == "Bash":
        return _check_bash(m, tool_input.get("command", ""))
    return Decision(None)


def _check_write(m: Mission, st: State, path: str, cwd: str | None) -> Decision:
    rel = relative(m.root, path, cwd)
    if rel is None:
        return Decision(False, f"{path} is outside the mission's repository")
    for pat in m.protected:
        if matches(rel, pat):
            return Decision(False, f"{rel} is protected by the mission ({pat}). It is the human's. "
                                   "If it must change, write change-requests/CR-<topic>.md and stop.")
    if any(matches(rel, p) for p in ALWAYS_WRITABLE):
        return Decision(True)
    if st.phase == "done":
        return Decision(False, "the mission is done; no further writes")
    phase = m.phases[st.phase]
    if any(matches(rel, p) for p in phase.writes):
        return Decision(True)
    allowed = ", ".join(phase.writes) or "nothing"
    return Decision(False, f"phase '{phase.name}' may write only: {allowed}. {rel} is not among them. "
                           "Finish this phase and run `mission advance` first.")


def _check_bash(m: Mission, cmd: str) -> Decision:
    for bad in m.forbidden_bash:
        if bad in cmd:
            return Decision(False, f"`{bad}` is forbidden by the mission")
    if HUMAN_ONLY.search(cmd):
        return Decision(False, "`mission approve/reset/init` are for the human only")
    if WRITE_HINT.search(cmd):
        for pat in m.protected:
            lit = _literal_prefix(pat)
            if lit and lit in cmd:
                return Decision(False, f"this command may write to protected {pat}; "
                                       "protected paths are read-only for the agent")
    return Decision(None)
