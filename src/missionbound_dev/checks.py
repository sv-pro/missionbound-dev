"""Run the mission's goal checks. A check passes only on exit code 0 within the timeout."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .mission import Mission


@dataclass(frozen=True)
class Result:
    id: str
    passed: bool
    tail: str            # last lines of output, for the agent and the human


def run_checks(m: Mission, ids: list[str] | None = None) -> list[Result]:
    out = []
    for r in m.goal:
        if ids and r.id not in ids:
            continue
        try:
            p = subprocess.run(["bash", "-c", r.check], cwd=m.root, capture_output=True,
                               text=True, timeout=m.check_timeout)
            text = (p.stdout + p.stderr).strip().splitlines()
            out.append(Result(r.id, p.returncode == 0, "\n".join(text[-15:])))
        except subprocess.TimeoutExpired:
            out.append(Result(r.id, False, f"timed out after {m.check_timeout}s"))
        except OSError as e:
            out.append(Result(r.id, False, f"could not run: {e}"))
    return out
