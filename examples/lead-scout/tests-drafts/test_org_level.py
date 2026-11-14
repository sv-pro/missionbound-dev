"""DRAFT — REQ-ORG-LEVEL: rows are organisations; personal accounts and personal emails
never reach the output."""

import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def test_rows_are_organisations_only(run_tool):
    r = run_tool()
    assert r.code == 0, r.stderr
    orgs = [row["org"] for row in r.rows()]
    assert set(orgs) == {"acme-demo", "globex-demo"}
    assert len(orgs) == len(set(orgs)), "one row per organisation"


def test_personal_account_and_email_absent(run_tool):
    r = run_tool()
    text = r.all_text()
    assert "jdoe-demo" not in text
    assert "jdoe@example.com" not in text
    assert not EMAIL.findall(text), f"email addresses in output: {EMAIL.findall(text)[:3]}"
