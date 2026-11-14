"""DRAFT — REQ-LLM-ADDS-ONLY: --llm adds columns. The set and order of rows, and every
original column value, are identical to a run without --llm — whatever the model says."""

import pytest


def _strip(rows, keys):
    return [{k: row[k] for k in keys} for row in rows]


@pytest.mark.parametrize("mode", ["normal", "hostile", "garbage"])
def test_llm_never_changes_rows(run_tool, llm, mode):
    base = run_tool(name="base")
    assert base.code == 0, base.stderr
    llm.mode = mode
    withllm = run_tool("--llm", llm=llm, name="llm")
    assert withllm.code == 0, withllm.stderr
    assert llm.requests, "--llm made no model requests"
    base_rows, llm_rows = base.rows(), withllm.rows()
    keys = list(base_rows[0].keys())
    assert _strip(llm_rows, keys) == base_rows
    assert set(llm_rows[0].keys()) >= set(keys)


def test_llm_input_is_parsed_facts_not_secrets(run_tool, llm):
    from fakes import FAKE_TOKEN
    run_tool("--llm", llm=llm)
    sent = str(llm.requests)
    assert FAKE_TOKEN not in sent
