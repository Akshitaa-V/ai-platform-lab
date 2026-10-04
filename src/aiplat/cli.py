"""Command line interface: `aiplat <command>`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import anyio

from aiplat.config import Settings
from aiplat.evals import load_tasks, run_eval, to_markdown, write_reports
from aiplat.gateway import GatewayClient, GatewayError
from aiplat.health import default_checks, format_table, overall_ok, run_checks
from aiplat.secrets import init_secrets, scan_for_secrets

EXPECTED_MCP_TOOLS = {"list_models", "ask_model", "platform_status", "search_runbooks"}


def _client(settings: Settings) -> GatewayClient:
    if not settings.gateway_key:
        print("warning: no gateway key found (run `aiplat secrets init`)", file=sys.stderr)
    return GatewayClient(settings.gateway_url, settings.gateway_key, settings.timeout)


def cmd_status(args: argparse.Namespace, settings: Settings) -> int:
    results = run_checks(default_checks(settings), timeout=args.timeout)
    if args.json:
        print(json.dumps([r.as_dict() for r in results], indent=2))
    else:
        print(format_table(results))
    return 0 if overall_ok(results) else 1


def cmd_models(_: argparse.Namespace, settings: Settings) -> int:
    with _client(settings) as client:
        for name in client.list_models():
            print(name)
    return 0


def cmd_chat(args: argparse.Namespace, settings: Settings) -> int:
    with _client(settings) as client:
        result = client.chat(args.model, args.prompt, max_tokens=args.max_tokens)
    print(result.text)
    print(
        f"\n[{result.model} | {result.latency_s:.2f}s | {result.total_tokens} tokens]",
        file=sys.stderr,
    )
    return 0


def cmd_eval(args: argparse.Namespace, settings: Settings) -> int:
    tasks = load_tasks(args.tasks)
    with _client(settings) as client:
        models = args.models.split(",") if args.models else client.list_models()
        reports = run_eval(client, models, tasks, max_tokens=args.max_tokens)
    path = write_reports(reports, tasks, args.out)
    print(to_markdown(reports, tasks))
    print(f"wrote {path} and {Path(args.out) / 'results.json'}")
    return 0


async def _mcp_smoke(url: str) -> tuple[set[str], list[str]]:
    from mcp import ClientSession

    try:  # newer SDKs renamed the client; keep working on both
        from mcp.client.streamable_http import streamable_http_client as connect
    except ImportError:  # pragma: no cover - mcp < 1.24
        from mcp.client.streamable_http import streamablehttp_client as connect

    async with connect(f"{url}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {t.name for t in (await session.list_tools()).tools}
            result = await session.call_tool("list_models", {})
    # Raised outside the session so callers see this error, not an ExceptionGroup.
    texts = [c.text for c in result.content if getattr(c, "text", None)]
    if result.isError:
        raise RuntimeError(f"list_models failed: {' '.join(texts)[:200]}")
    return tools, texts


def cmd_smoke(args: argparse.Namespace, settings: Settings) -> int:
    failures = 0

    def report(ok: bool, label: str, detail: str = "") -> None:
        nonlocal failures
        failures += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] {label}{': ' + detail if detail else ''}")

    results = run_checks(default_checks(settings), timeout=10)
    report(
        overall_ok(results),
        "required services healthy",
        ", ".join(f"{r.name}={'up' if r.ok else 'down'}" for r in results),
    )
    try:
        with _client(settings) as client:
            models = client.list_models()
            report(bool(models), "gateway lists models", ", ".join(models))
            model = args.model or (models[0] if models else "")
            answer = client.chat(model, "Reply with the single word: ready", max_tokens=10)
            report(
                "ready" in answer.text.lower(),
                f"chat through gateway ({model})",
                f"{answer.latency_s:.2f}s, {answer.text.strip()[:40]!r}",
            )
    except GatewayError as exc:
        report(False, "gateway", str(exc))
    try:
        tools, mcp_models = anyio.run(_mcp_smoke, settings.mcp_url)
        report(EXPECTED_MCP_TOOLS <= tools, "MCP server exposes tools", ", ".join(sorted(tools)))
        report(bool(mcp_models), "MCP tool call reaches the gateway", ", ".join(mcp_models))
    except Exception as exc:  # noqa: BLE001 - any MCP failure is a smoke failure
        while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
            exc = exc.exceptions[0]
        report(False, "MCP server", f"{type(exc).__name__}: {exc}")
    print(f"\n{'all checks passed' if failures == 0 else f'{failures} check(s) failed'}")
    return 0 if failures == 0 else 1


def cmd_secrets(args: argparse.Namespace, _: Settings) -> int:
    if args.action == "init":
        created = init_secrets(args.root, force=args.force)
        print(f"created: {', '.join(created) if created else 'nothing (all secrets exist)'}")
        print("wrote .env.observability (gitignored)")
        return 0
    findings = scan_for_secrets(args.root)
    for f in findings:
        print(f"{f.path}:{f.line}: possible secret ({f.kind})")
    print("no secrets found" if not findings else f"{len(findings)} finding(s)")
    return 1 if findings else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aiplat", description="Operate the AI platform lab.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="health of every service")
    p.add_argument("--json", action="store_true")
    p.add_argument("--timeout", type=float, default=5.0)
    p.set_defaults(func=cmd_status)

    sub.add_parser("models", help="models served by the gateway").set_defaults(func=cmd_models)

    p = sub.add_parser("chat", help="send one prompt through the gateway")
    p.add_argument("model")
    p.add_argument("prompt")
    p.add_argument("--max-tokens", type=int, default=256)
    p.set_defaults(func=cmd_chat)

    p = sub.add_parser("eval", help="compare models on a fixed task set")
    p.add_argument("--models", help="comma-separated; default: every gateway model")
    p.add_argument("--tasks", default="evals/tasks.jsonl")
    p.add_argument("--out", default="reports")
    p.add_argument("--max-tokens", type=int, default=200)
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("smoke", help="end-to-end check: health, gateway chat, MCP tool call")
    p.add_argument("--model")
    p.set_defaults(func=cmd_smoke)

    p = sub.add_parser("secrets", help="create or scan for secrets")
    p.add_argument("action", choices=["init", "check"])
    p.add_argument("--root", default=".")
    p.add_argument("--force", action="store_true", help="init: overwrite (rotates every secret)")
    p.set_defaults(func=cmd_secrets)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args, Settings.from_env())
    except GatewayError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
