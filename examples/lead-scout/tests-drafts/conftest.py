"""DRAFT. Shared fixtures: start the fake APIs, run lead-scout as a black box, read its output.

Every test talks to lead-scout only through its CLI, its environment and its output
directory (see README.md, "Contract"). Nothing here imports lead-scout's code.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from fakes import FakeGitHub, FakeLLM, default_world, serve


@dataclass
class Run:
    code: int
    stdout: str
    stderr: str
    out: Path

    def rows(self) -> list[dict]:
        with open(self.out / "leads.csv", newline="") as f:
            return list(csv.DictReader(f))

    def run_json(self) -> dict:
        return json.loads((self.out / "run.json").read_text())

    def all_text(self) -> str:
        return "\n".join(p.read_text(errors="replace") for p in self.out.rglob("*") if p.is_file())


@pytest.fixture
def github():
    fake = FakeGitHub(world=default_world())
    srv, url = serve(fake, "github")
    fake.url = url
    yield fake
    srv.shutdown()


@pytest.fixture
def llm():
    fake = FakeLLM()
    srv, url = serve(fake, "llm")
    fake.url = url
    yield fake
    srv.shutdown()


@pytest.fixture
def run_tool(tmp_path, github):
    """run_tool(*args, llm=None, timeout=120) -> Run. Proxies point nowhere, so any request to a
    host other than the fakes fails: the tool must work offline against the given base URLs."""

    def _run(*args: str, llm: FakeLLM | None = None, timeout: int = 120, name: str = "out") -> Run:
        out = tmp_path / name
        env = {k: v for k, v in os.environ.items() if not k.upper().endswith("_PROXY")}
        env.update({
            "GITHUB_API_URL": github.url,
            "GITHUB_TOKEN": "test-token",
            "GH_TOKEN": "test-token",
            "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",
            "http_proxy": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9",
            "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
        })
        if llm is not None:
            env.update({"ANTHROPIC_BASE_URL": llm.url, "ANTHROPIC_API_KEY": "test-key"})
        p = subprocess.run(["lead-scout", "run", "--out", str(out), *args], env=env,
                           capture_output=True, text=True, timeout=timeout)
        return Run(p.returncode, p.stdout, p.stderr, out)

    return _run
