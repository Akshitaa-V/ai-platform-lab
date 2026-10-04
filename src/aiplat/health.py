"""Health checks for every platform service."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass

import httpx

from aiplat.config import Settings


@dataclass(frozen=True)
class Check:
    name: str
    url: str
    required: bool = True


@dataclass(frozen=True)
class CheckResult:
    name: str
    url: str
    required: bool
    ok: bool
    status: int | None
    latency_ms: float | None
    detail: str

    def as_dict(self) -> dict:
        return asdict(self)


def default_checks(settings: Settings, include_mcp: bool = True) -> list[Check]:
    checks = [
        Check("ollama", f"{settings.ollama_url}/api/tags"),
        Check("gateway", f"{settings.gateway_url}/health/liveliness"),
    ]
    if include_mcp:
        checks.append(Check("mcp", f"{settings.mcp_url}/health"))
    if settings.langfuse_url:
        checks.append(
            Check("langfuse", f"{settings.langfuse_url}/api/public/health", required=False)
        )
    return checks


def run_checks(
    checks: list[Check], timeout: float = 5.0, transport: httpx.BaseTransport | None = None
) -> list[CheckResult]:
    results = []
    with httpx.Client(timeout=timeout, transport=transport) as http:
        for check in checks:
            start = time.perf_counter()
            try:
                response = http.get(check.url)
            except httpx.HTTPError as exc:
                results.append(
                    CheckResult(
                        check.name, check.url, check.required, False, None, None, type(exc).__name__
                    )
                )
                continue
            latency = round((time.perf_counter() - start) * 1000, 1)
            ok = response.status_code < 400
            detail = "ok" if ok else response.text[:120]
            results.append(
                CheckResult(
                    check.name, check.url, check.required, ok, response.status_code, latency, detail
                )
            )
    return results


def overall_ok(results: list[CheckResult]) -> bool:
    return all(r.ok for r in results if r.required)


def format_table(results: list[CheckResult]) -> str:
    lines = [f"{'service':<10} {'state':<14} {'http':<5} {'ms':>8}  detail"]
    for r in results:
        state = "up" if r.ok else ("DOWN" if r.required else "down (optional)")
        status = str(r.status) if r.status is not None else "-"
        ms = f"{r.latency_ms:.1f}" if r.latency_ms is not None else "-"
        lines.append(f"{r.name:<10} {state:<14} {status:<5} {ms:>8}  {r.detail}")
    return "\n".join(lines)
