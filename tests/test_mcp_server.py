import json
import socket
import threading
import time

import anyio
import httpx
import pytest
import uvicorn
from mcp.shared.memory import create_connected_server_and_client_session

from aiplat.cli import EXPECTED_MCP_TOOLS, _mcp_smoke
from aiplat.mcp_server import build_server
from aiplat.runbooks import RunbookIndex


def health_handler(request):
    return httpx.Response(200, json={})


@pytest.fixture
def server(settings, client):
    return build_server(
        settings=settings,
        client=client,
        runbooks=RunbookIndex.from_dir("docs/runbooks"),
        health_transport=httpx.MockTransport(health_handler),
    )


def call(server, tool, args=None):
    async def go():
        async with create_connected_server_and_client_session(server._mcp_server) as session:
            return await session.call_tool(tool, args or {})

    return anyio.run(go)


def texts(result):
    return [c.text for c in result.content]


def test_server_exposes_the_four_tools(server):
    async def go():
        async with create_connected_server_and_client_session(server._mcp_server) as session:
            return {t.name for t in (await session.list_tools()).tools}

    assert anyio.run(go) == EXPECTED_MCP_TOOLS


def test_list_models_goes_through_the_gateway(server):
    assert texts(call(server, "list_models")) == ["llama3.2-1b", "qwen2.5-0.5b"]


def test_ask_model_returns_answer_latency_and_tokens(server):
    result = call(server, "ask_model", {"model": "llama3.2-1b", "prompt": "Capital of Bavaria?"})
    payload = json.loads(texts(result)[0])
    assert payload["answer"] == "Munich" and payload["total_tokens"] == 13
    assert payload["latency_s"] >= 0


def test_ask_model_rejects_bad_input_and_reports_gateway_errors(server, fake_gateway):
    assert call(server, "ask_model", {"model": "llama3.2-1b", "prompt": "  "}).isError
    assert call(server, "ask_model", {"model": "m", "prompt": "x" * 9000}).isError
    fake_gateway.fail_models.add("llama3.2-1b")
    result = call(server, "ask_model", {"model": "llama3.2-1b", "prompt": "hi"})
    assert result.isError and "500" in texts(result)[0]


def test_platform_status_skips_itself(server):
    payload = json.loads(texts(call(server, "platform_status"))[0])
    assert payload["healthy"] is True
    assert [s["name"] for s in payload["services"]] == ["ollama", "gateway"]


def test_search_runbooks_tool(server):
    hits = [
        json.loads(t)
        for t in texts(call(server, "search_runbooks", {"query": "rotate master key", "top_k": 2}))
    ]
    assert hits[0]["doc"] == "rotate-secrets.md" and len(hits) <= 2


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_streamable_http_end_to_end(settings, client, fake_gateway):
    """Run the real HTTP app and talk to it with the same MCP client `aiplat smoke` uses."""
    port = _free_port()
    mcp = build_server(
        settings=settings, client=client, port=port, runbooks=RunbookIndex.from_dir("docs/runbooks")
    )
    config = uvicorn.Config(
        mcp.streamable_http_app(), host="127.0.0.1", port=port, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                if httpx.get(f"{base}/health").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.05)
        health = httpx.get(f"{base}/health").json()
        assert health["status"] == "ok" and health["runbook_sections"] > 0

        tools, models = anyio.run(_mcp_smoke, base)
        assert EXPECTED_MCP_TOOLS <= tools
        assert models == ["llama3.2-1b", "qwen2.5-0.5b"]

        # A tool error must fail the smoke check, not count as a model list.
        fake_gateway.key = "sk-rotated"
        with pytest.raises(RuntimeError, match="list_models failed"):
            anyio.run(_mcp_smoke, base)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
