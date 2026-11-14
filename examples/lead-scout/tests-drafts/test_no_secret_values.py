"""DRAFT — REQ-NO-SECRETS: a secret-looking literal is reported as owner/repo/path:line;
its value never appears in any output file, stdout or stderr."""

import json

from fakes import FAKE_TOKEN, SECRET_LINE


def test_secret_value_never_appears(run_tool):
    r = run_tool()
    assert r.code == 0, r.stderr
    assert FAKE_TOKEN not in r.all_text()
    assert FAKE_TOKEN not in r.stdout + r.stderr
    assert FAKE_TOKEN[:12] not in r.all_text(), "a prefix of the secret leaked"


def test_secret_location_is_reported(run_tool):
    r = run_tool()
    org = json.loads((r.out / "orgs" / "acme-demo.json").read_text())
    assert f"acme-demo/tools/.mcp.json:{SECRET_LINE}" in org["secret_findings"]


def test_env_var_names_are_kept(run_tool):
    # Names are useful evidence, values are not: GITHUB_TOKEN and AWS_PROFILE should be visible.
    r = run_tool()
    text = (r.out / "orgs" / "acme-demo.json").read_text()
    assert "GITHUB_TOKEN" in text and "AWS_PROFILE" in text
