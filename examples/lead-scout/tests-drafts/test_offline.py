"""DRAFT — REQ-OFFLINE: everything runs against the given base URLs; no other host is
contacted. run_tool points all proxies at a closed port, so any other request fails."""


def test_full_run_offline(run_tool):
    r = run_tool()
    assert r.code == 0, r.stderr
    assert (r.out / "leads.csv").exists() and (r.out / "leads.md").exists()
    assert r.run_json().get("errors", []) == []


def test_full_run_offline_with_llm(run_tool, llm):
    r = run_tool("--llm", llm=llm)
    assert r.code == 0, r.stderr
    assert r.run_json().get("errors", []) == []
