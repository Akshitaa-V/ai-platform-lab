import httpx

from aiplat.health import Check, default_checks, format_table, overall_ok, run_checks


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "ollama":
        return httpx.Response(200, json={"models": []})
    if request.url.host == "gateway":
        return httpx.Response(503, text="model loading")
    raise httpx.ConnectError("refused", request=request)


def test_default_checks_cover_every_service(settings):
    names = [c.name for c in default_checks(settings)]
    assert names == ["ollama", "gateway", "mcp"]
    assert "mcp" not in [c.name for c in default_checks(settings, include_mcp=False)]


def test_langfuse_check_is_optional(settings):
    from dataclasses import replace

    checks = default_checks(replace(settings, langfuse_url="http://langfuse:3000"))
    langfuse = next(c for c in checks if c.name == "langfuse")
    assert langfuse.required is False


def test_run_checks_reports_up_down_and_unreachable():
    checks = [
        Check("ollama", "http://ollama/api/tags"),
        Check("gateway", "http://gateway/health/liveliness"),
        Check("langfuse", "http://langfuse/api/public/health", required=False),
    ]
    results = run_checks(checks, transport=httpx.MockTransport(handler))
    by_name = {r.name: r for r in results}
    assert by_name["ollama"].ok and by_name["ollama"].status == 200
    assert not by_name["gateway"].ok and by_name["gateway"].detail == "model loading"
    assert not by_name["langfuse"].ok and by_name["langfuse"].status is None
    assert overall_ok(results) is False
    table = format_table(results)
    assert "DOWN" in table and "down (optional)" in table


def test_optional_service_down_keeps_platform_healthy():
    checks = [
        Check("ollama", "http://ollama/api/tags"),
        Check("langfuse", "http://langfuse/api/public/health", required=False),
    ]
    assert overall_ok(run_checks(checks, transport=httpx.MockTransport(handler)))
