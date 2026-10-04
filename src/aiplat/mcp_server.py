"""MCP server that gives LLM clients and coding agents access to the platform.

Tools:
  list_models      models currently served by the gateway
  ask_model        send a prompt to one model through the gateway
  platform_status  health of ollama, gateway and (if enabled) langfuse
  search_runbooks  find the right section of the platform runbooks

Runs over Streamable HTTP at /mcp, with a plain /health route for Docker.
"""

from __future__ import annotations

import os
from pathlib import Path

import anyio
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from aiplat.config import Settings
from aiplat.gateway import GatewayClient, GatewayError
from aiplat.health import default_checks, overall_ok, run_checks
from aiplat.runbooks import RunbookIndex

DEFAULT_RUNBOOK_DIR = Path(os.environ.get("RUNBOOK_DIR", "docs/runbooks"))
MAX_PROMPT_CHARS = 8000


def build_server(
    settings: Settings | None = None,
    client: GatewayClient | None = None,
    runbooks: RunbookIndex | None = None,
    health_transport=None,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    settings = settings or Settings.from_env()
    client = client or GatewayClient(settings.gateway_url, settings.gateway_key, settings.timeout)
    runbooks = runbooks or RunbookIndex.from_dir(DEFAULT_RUNBOOK_DIR)

    mcp = FastMCP("ai-platform", host=host, port=port, stateless_http=True, json_response=True)

    @mcp.tool()
    async def list_models() -> list[str]:
        """List the model names the gateway currently serves."""
        try:
            return await anyio.to_thread.run_sync(client.list_models)
        except GatewayError as exc:
            raise ValueError(str(exc)) from exc

    @mcp.tool()
    async def ask_model(model: str, prompt: str, max_tokens: int = 256) -> dict:
        """Send one prompt to a model through the gateway and return the answer with
        its latency and token usage."""
        if not prompt.strip():
            raise ValueError("prompt is empty")
        if len(prompt) > MAX_PROMPT_CHARS:
            raise ValueError(f"prompt is longer than {MAX_PROMPT_CHARS} characters")
        max_tokens = max(1, min(int(max_tokens), 2048))
        try:
            result = await anyio.to_thread.run_sync(
                lambda: client.chat(model, prompt, max_tokens=max_tokens)
            )
        except GatewayError as exc:
            raise ValueError(str(exc)) from exc
        return {
            "model": result.model,
            "answer": result.text,
            "latency_s": round(result.latency_s, 3),
            "total_tokens": result.total_tokens,
        }

    @mcp.tool()
    async def platform_status() -> dict:
        """Report whether each platform service is up, with HTTP status and latency."""
        checks = default_checks(settings, include_mcp=False)
        results = await anyio.to_thread.run_sync(
            lambda: run_checks(checks, transport=health_transport)
        )
        return {"healthy": overall_ok(results), "services": [r.as_dict() for r in results]}

    @mcp.tool()
    async def search_runbooks(query: str, top_k: int = 3) -> list[dict]:
        """Search the platform runbooks, for example 'add a new model' or 'gateway is down'."""
        return [hit.as_dict() for hit in runbooks.search(query, top_k=max(1, min(top_k, 10)))]

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "runbook_sections": len(runbooks.sections)})

    return mcp


def main() -> None:
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8000"))
    build_server(host=host, port=port).run(transport="streamable-http")


if __name__ == "__main__":
    main()
