"""Client for the OpenAI-compatible API exposed by the LiteLLM gateway."""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx


class GatewayError(RuntimeError):
    """Raised when the gateway cannot be reached or returns an error."""


@dataclass(frozen=True)
class ChatResult:
    model: str
    text: str
    latency_s: float
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class GatewayClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout, transport=transport
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> GatewayClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: object) -> dict:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise GatewayError(f"gateway timed out on {path}") from exc
        except httpx.TransportError as exc:
            raise GatewayError(f"gateway unreachable on {path}: {exc}") from exc
        if response.status_code >= 400:
            raise GatewayError(f"gateway returned {response.status_code}: {response.text[:300]}")
        try:
            return response.json()
        except ValueError as exc:
            raise GatewayError(f"gateway returned non-JSON on {path}") from exc

    def list_models(self) -> list[str]:
        data = self._request("GET", "/v1/models")
        return sorted(item["id"] for item in data.get("data", []))

    def chat(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 256,
        temperature: float = 0.0,
        system: str | None = None,
    ) -> ChatResult:
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        start = time.perf_counter()
        data = self._request("POST", "/v1/chat/completions", json=payload)
        latency = time.perf_counter() - start
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise GatewayError("gateway response has no message content") from exc
        usage = data.get("usage") or {}
        return ChatResult(
            model=data.get("model", model),
            text=text,
            latency_s=latency,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
        )
