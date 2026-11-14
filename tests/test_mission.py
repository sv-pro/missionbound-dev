"""Hook inputs below have the shape Claude Code sends (session_id, cwd, hook_event_name,
tool_name, tool_input). Each test builds a small project in a temp directory."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from missionbound_dev import cli
from missionbound_dev.hooks import context_text, on_pre_tool_use, on_stop
from missionbound_dev.mission import STATE_FILE, load_mission, load_state

MISSION = """\
title: demo
goal:
  - {id: REQ-1, description: ok file exists, check: "test -f src/ok.txt"}
  - {id: REQ-2, description: ok file says hello, check: "grep -q hello src/ok.txt"}
protected: ["requirements/**", "tests/acceptance/**"]
initial_phase: design
phases:
  design:    {writes: ["docs/**"], next: implement, gate: human}
  implement: {writes: ["src/**", "tests/**", "docs/**"], next: verify, gate: checks, stop_requires_checks: true}
  verify:    {writes: ["docs/**"], next: done, gate: human, stop_requires_checks: true}
forbidden_bash: ["git push --force"]
limits: {stop_blocks: 2, check_timeout_s: 20}
"""


@pytest.fixture
def proj(tmp_path, monkeypatch):
    (tmp_path / "mission.yaml").write_text(MISSION)
    (tmp_path / "src").mkdir()
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    return tmp_path


def pre(proj, tool, **tool_input):
    return on_pre_tool_use({"session_id": "s", "cwd": str(proj), "hook_event_name": "PreToolUse",
                            "tool_name": tool, "tool_input": tool_input})


def denied(res):
    return res is not None and res["hookSpecificOutput"]["permissionDecision"] == "deny"


def stop(proj):
    return on_stop({"session_id": "s", "cwd": str(proj), "hook_event_name": "Stop",
                    "stop_hook_active": False})


def phase(proj):
    return load_state(load_mission(proj)).phase


# --- protected paths are absent for the agent ---------------------------------

@pytest.mark.parametrize("rel", ["mission.yaml", ".claude/settings.json", STATE_FILE,
                                 "requirements/r1.md", "tests/acceptance/test_a.py"])
def test_protected_paths_cannot_be_written(proj, rel):
    for tool in ("Write", "Edit", "MultiEdit"):
        assert denied(pre(proj, tool, file_path=str(proj / rel))), (tool, rel)


def test_paths_outside_the_repository_are_denied(proj):
    assert denied(pre(proj, "Write", file_path="/etc/passwd"))
    assert denied(pre(proj, "Write", file_path=str(proj / ".." / "elsewhere.txt")))


# --- phases decide what may be written ----------------------------------------

def test_design_phase_writes_only_docs(proj):
    assert phase(proj) == "design"
    assert pre(proj, "Write", file_path=str(proj / "docs/design.md")) is None
    assert denied(pre(proj, "Write", file_path=str(proj / "src/main.py")))
    assert pre(proj, "Write", file_path=str(proj / "change-requests/CR-REQ-1.md")) is None


def test_relative_paths_resolve_against_cwd(proj):
    (proj / "docs").mkdir()
    ev = {"cwd": str(proj / "docs"), "tool_name": "Write", "tool_input": {"file_path": "x.md"}}
    assert on_pre_tool_use(ev) is None
    ev["tool_input"]["file_path"] = "../src/x.py"
    assert denied(on_pre_tool_use(ev))


def test_after_human_approval_implement_may_write_src(proj):
    assert cli.main(["approve"]) == 0
    assert phase(proj) == "implement"
    assert pre(proj, "Write", file_path=str(proj / "src/main.py")) is None


# --- Bash -----------------------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    "echo x > requirements/r1.md",
    "sed -i 's/a/b/' tests/acceptance/test_a.py",
    "rm -rf .claude",
    "python -c \"open('mission.yaml','w').write('')\"",
    "git push --force origin main",
    "mission approve",
    "cd x && mission reset",
])
def test_bash_denied(proj, cmd):
    assert denied(pre(proj, "Bash", command=cmd)), cmd


@pytest.mark.parametrize("cmd", ["ls -la", "cat requirements/r1.md", "pytest -q", "mission status",
                                 "mission advance", "git diff"])
def test_bash_allowed(proj, cmd):
    assert pre(proj, "Bash", command=cmd) is None, cmd


def test_denials_are_logged(proj):
    pre(proj, "Write", file_path=str(proj / "mission.yaml"))
    hist = load_state(load_mission(proj)).history
    assert hist[-1]["event"] == "deny" and "protected" in hist[-1]["reason"]


def test_broken_mission_denies_writes_and_bash(proj):
    (proj / "mission.yaml").write_text("phases: [this, is, not, a, mapping")
    assert denied(pre(proj, "Write", file_path=str(proj / "docs/x.md")))
    assert denied(pre(proj, "Bash", command="ls"))
    assert pre(proj, "Read", file_path=str(proj / "docs/x.md")) is None


# --- Stop: the goal cannot be declared early ---------------------------------------

def test_stop_is_free_in_design(proj):
    assert stop(proj) is None


def test_stop_blocked_while_checks_fail_then_bounded(proj):
    cli.main(["approve"])
    r1 = stop(proj)
    assert r1["decision"] == "block" and "REQ-1" in r1["reason"] and "REQ-2" in r1["reason"]
    r2 = stop(proj)
    assert r2["decision"] == "block" and "2/2" in r2["reason"]
    assert stop(proj) is None                        # limit reached: stop with a report
    assert load_state(load_mission(proj)).history[-1]["why"].startswith("block limit")


def test_stop_allowed_when_checks_pass(proj):
    cli.main(["approve"])
    (proj / "src/ok.txt").write_text("hello\n")
    assert stop(proj) is None
    st = load_state(load_mission(proj))
    assert st.last_check == {"REQ-1": True, "REQ-2": True} and st.stop_blocks == 0


def test_change_request_after_a_block_lets_the_agent_stop(proj):
    cli.main(["approve"])
    assert stop(proj)["decision"] == "block"
    time.sleep(1.1)                                  # history timestamps have 1 s resolution
    assert cli.main(["request-change", "REQ-2", "greeting text is not specified"]) == 0
    assert stop(proj) is None


# --- phase gates -----------------------------------------------------------------

def test_gates(proj):
    assert cli.main(["advance"]) == 2                # design: human gate
    assert cli.main(["approve"]) == 0
    assert cli.main(["advance"]) == 1                # implement: checks fail
    (proj / "src/ok.txt").write_text("hello\n")
    assert cli.main(["advance"]) == 0
    assert phase(proj) == "verify"
    assert cli.main(["advance"]) == 2                # verify: human gate
    assert cli.main(["approve"]) == 0
    assert phase(proj) == "done"
    assert denied(pre(proj, "Write", file_path=str(proj / "src/late.py")))


def test_context_states_phase_rules_and_requirements(proj):
    text = context_text(str(proj))
    assert "phase: design" in text and "docs/**" in text and "requirements/**" in text
    assert "REQ-1 [not run]" in text and "Do not weaken" in text


def test_init_is_idempotent(proj):
    assert cli.main(["init"]) == 0
    hooks = json.loads((proj / ".claude/settings.json").read_text())["hooks"]
    assert {k: len(v) for k, v in hooks.items()} == {"SessionStart": 1, "UserPromptSubmit": 1,
                                                     "PreToolUse": 1, "Stop": 1}


# --- the real entry point, as Claude Code calls it ---------------------------------

def test_hook_cli_end_to_end(proj):
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    ev = {"session_id": "s", "cwd": str(proj), "hook_event_name": "PreToolUse",
          "tool_name": "Write", "tool_input": {"file_path": str(proj / "mission.yaml"), "content": ""}}
    p = subprocess.run([sys.executable, "-m", "missionbound_dev.cli", "hook", "guard"],
                       input=json.dumps(ev), capture_output=True, text=True, env=env, cwd=proj)
    assert p.returncode == 0
    out = json.loads(p.stdout)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    p = subprocess.run([sys.executable, "-m", "missionbound_dev.cli", "hook", "session-start"],
                       input=json.dumps({"cwd": str(proj)}), capture_output=True, text=True, env=env)
    assert "[mission] demo — phase: design" in p.stdout
