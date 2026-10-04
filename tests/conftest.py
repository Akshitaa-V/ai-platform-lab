from __future__ import annotations

import copy
import json

import httpx
import pytest

from aiplat.config import Settings
from aiplat.gateway import GatewayClient

ANSWERS = {
    "qwen2.5-0.5b": {"default": "I am not sure.", "ready": "ready"},
    "llama3.2-1b": {"default": "Munich", "ready": "Ready."},
}


class FakeGateway:
    """An OpenAI-compatible gateway in memory, recording every request."""

    def __init__(self, key: str = "sk-test-key", answers: dict | None = None) -> None:
        self.key = key
        self.answers = copy.deepcopy(answers if answers is not None else ANSWERS)
        self.requests: list[httpx.Request] = []
        self.fail_models: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("authorization") != f"Bearer {self.key}":
            return httpx.Response(401, json={"error": "invalid key"})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": m} for m in self.answers]})
        if request.url.path == "/v1/chat/completions":
            body = json.loads(request.content)
            model = body["model"]
            if model in self.fail_models:
                return httpx.Response(500, json={"error": "model crashed"})
            if model not in self.answers:
                return httpx.Response(400, json={"error": f"unknown model {model}"})
            prompt = body["messages"][-1]["content"]
            table = self.answers[model]
            text = next(
                (v for k, v in table.items() if k != "default" and k in prompt.lower()),
                table["default"],
            )
            return httpx.Response(
                200,
                json={
                    "model": model,
                    "choices": [{"message": {"role": "assistant", "content": text}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 3},
                },
            )
        return httpx.Response(404)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


@pytest.fixture
def fake_gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def client(fake_gateway: FakeGateway) -> GatewayClient:
    return GatewayClient("http://gateway:4000", "sk-test-key", transport=fake_gateway.transport)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        gateway_url="http://gateway:4000",
        gateway_key="sk-test-key",
        ollama_url="http://ollama:11434",
        mcp_url="http://mcp:8000",
        langfuse_url=None,
        timeout=5,
    )
