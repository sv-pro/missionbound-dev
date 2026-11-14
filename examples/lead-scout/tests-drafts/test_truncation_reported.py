"""DRAFT — REQ-TRUNCATION: when a search reports more results than GitHub will return
(1000), the run says so in run.json and in leads.md. Never silent."""


def test_truncation_is_reported(run_tool, github):
    github.world["search_total_override"]["CLAUDE.md"] = 1500
    r = run_tool()
    assert r.code == 0, r.stderr
    trunc = r.run_json().get("truncated", [])
    assert any(t.get("total_count") == 1500 and "CLAUDE.md" in t.get("query", "") for t in trunc), trunc
    assert "truncat" in (r.out / "leads.md").read_text().lower()


def test_no_truncation_no_warning(run_tool):
    r = run_tool()
    assert r.run_json().get("truncated", []) == []
