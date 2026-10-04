import pytest

from aiplat.runbooks import RunbookIndex, load_sections


@pytest.fixture(scope="module")
def index():
    return RunbookIndex.from_dir("docs/runbooks")


def test_runbooks_split_into_sections():
    sections = load_sections("docs/runbooks")
    assert len(sections) >= 12
    assert all(s.text for s in sections)


@pytest.mark.parametrize(
    ("query", "doc"),
    [
        ("how do I rotate the gateway master key", "rotate-secrets.md"),
        ("add a new model to ollama and the gateway", "add-a-model.md"),
        ("gateway returns 401", "gateway-down.md"),
        ("connect a coding agent over mcp", "connect-a-client.md"),
        ("langfuse shows no traces", "gateway-down.md"),
    ],
)
def test_search_finds_the_right_runbook(index, query, doc):
    hits = index.search(query, top_k=3)
    assert hits[0].doc == doc


def test_search_handles_empty_and_unknown_queries(index):
    assert index.search("") == []
    assert index.search("the and of") == []
    assert index.search("zzzqqq") == []
