# missionbound-dev

> Run a coding agent inside a mission: requirements it cannot edit, phases it cannot skip,
> and a goal it cannot declare early.

**Status:** scaffold. Tested against hook inputs shaped like Claude Code's; not yet run
inside a real Claude Code session (that is the first dogfooding step).

A prompt is a request. A mission is a boundary. Asked to build a mission-bound chatbot, a
coding agent once kept every safety test green by quietly dropping the main requirement
("talks freely") and said so in its own design doc. Nothing stopped it, because the
requirements lived in the prompt. Here they live in the environment.

## How the mission maps onto Claude Code

| Mission concept | Claude Code hook | What happens |
|---|---|---|
| Constraints: protected paths are absent, each phase writes only its own paths | `PreToolUse` → `mission hook guard` | Edit/Write outside the phase, or anywhere in a protected path, is denied with a reason |
| Goal: "done" is a predicate, not a feeling | `Stop` → `mission hook stop` | While required checks fail, stopping is refused and the failures are fed back (bounded: `limits.stop_blocks`) |
| The mandate is always in view | `SessionStart`, `UserPromptSubmit` → `mission hook session-start` / `prompt` | Phase, writable paths, protected paths and requirement status are added to context every turn |
| Readback: a human confirms what cannot be undone | human-only commands | `mission approve` passes human gates; the agent's Bash cannot run it. The agent's only channel to change a requirement is `change-requests/CR-*.md`, after which it may stop |

`mission.yaml`, `.mission/` (state) and `.claude/` (the hooks themselves) are always
protected, whatever the file says: an agent that could edit its mission or switch off its
hooks would not be bound by anything.

## Use

```bash
pipx install git+https://github.com/sv-pro/missionbound-dev     # or: uv tool install ...
cd your-project
mission init            # mission.yaml template, .claude/settings.json hooks, state
$EDITOR mission.yaml    # requirements and their checks FIRST, then phases
# write the acceptance tests the checks run; they are protected from the agent
claude                  # work as usual; the hooks keep the agent inside the mission
mission status          # where things stand
mission approve         # you, after reading the design (human gate)
```

`mission advance` moves past a `checks` gate only when every requirement check passes.
`examples/lead-scout/mission.yaml` is the mission for the first real run.

## Limits (read these)

- **Bash is a heuristic.** Edits are checked exactly, but a shell command cannot be parsed
  reliably. The guard refuses commands that combine a write-ish operation with a protected
  path, and refuses forbidden patterns; a determined agent can still get around it. The
  backstop is outside the agent: make protected paths read-only for the agent's OS user,
  and have CI fail when the requirement files changed or the checks fail.
- **Phase write rules apply to edit tools, not to Bash.**
- **Hooks are only as strong as their configuration.** Anyone who edits
  `~/.claude/settings.json` or runs without project hooks runs without the mission.
- **Checks are the requirements' teeth.** A requirement with a weak check is a weak
  requirement; a requirement with no check (like "talks naturally") needs one before it can
  be held, e.g. a corpus of real user lines with a pass threshold.

## Layers

This is the mission layer: which work may happen in which phase, and what "done" means.
Underneath, [ai2rules](https://github.com/sv-pro/ai2rules) is the execution layer that can
make the agent's actions absent rather than refused.

## Develop

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest -q
```
