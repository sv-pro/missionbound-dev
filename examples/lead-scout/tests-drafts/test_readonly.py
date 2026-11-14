"""DRAFT — REQ-READONLY: only GitHub's API is called, and only with GET.
Checked on the fake server's own log, not on anything the tool reports about itself."""


def test_only_get_requests_to_the_api(run_tool, github):
    r = run_tool()
    assert r.code == 0, r.stderr
    assert github.log, "the tool made no GitHub requests at all"
    methods = {e.method for e in github.log}
    assert methods == {"GET"}, f"non-GET requests: {methods - {'GET'}}"


def test_company_websites_are_never_fetched(run_tool, github):
    # The fake orgs list blogs on .example domains; the proxy points nowhere, so a fetch would
    # fail and show up as an error in run.json.
    r = run_tool()
    assert r.code == 0, r.stderr
    assert r.run_json().get("errors", []) == []
