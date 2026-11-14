"""DRAFT — REQ-RATE-LIMIT: on 429 (Retry-After) or 403 with X-RateLimit-Remaining: 0, the tool
waits and retries; it does not hammer the API and does not lose results."""

import pytest


@pytest.mark.parametrize("mode", ["429", "403"])
def test_backs_off_and_still_completes(run_tool, github, mode):
    github.world["rate_limit_first"] = mode
    r = run_tool()
    assert r.code == 0, r.stderr
    searches = [e for e in github.log if e.path == "/search/code"]
    limited, retry = searches[0], searches[1]
    assert limited.status in (403, 429)
    assert retry.at - limited.at >= 0.9, "retried before the limit reset"
    assert {row["org"] for row in r.rows()} == {"acme-demo", "globex-demo"}
