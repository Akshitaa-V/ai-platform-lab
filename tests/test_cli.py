import httpx
import pytest

from aiplat import cli
from aiplat.gateway import GatewayClient


@pytest.fixture
def patched(monkeypatch, fake_gateway, tmp_path):
    """Point the CLI at the fake gateway and fake health endpoints."""
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-test-key")
    monkeypatch.setenv("GATEWAY_URL", "http://gateway:4000")
    monkeypatch.setenv("LANGFUSE_URL", "")
    monkeypatch.setattr(
        cli,
        "_client",
        lambda s: GatewayClient(s.gateway_url, s.gateway_key, transport=fake_gateway.transport),
    )
    real_run_checks = cli.run_checks
    monkeypatch.setattr(
        cli,
        "run_checks",
        lambda checks, timeout=5: real_run_checks(
            checks, transport=httpx.MockTransport(lambda r: httpx.Response(200))
        ),
    )
    monkeypatch.chdir(tmp_path)
    return fake_gateway


def test_status_exit_code(patched, capsys):
    assert cli.main(["status"]) == 0
    assert "gateway" in capsys.readouterr().out


def test_models_and_chat(patched, capsys):
    assert cli.main(["models"]) == 0
    assert capsys.readouterr().out.split() == ["llama3.2-1b", "qwen2.5-0.5b"]
    assert cli.main(["chat", "llama3.2-1b", "Capital of Bavaria?"]) == 0
    assert "Munich" in capsys.readouterr().out


def test_eval_writes_leaderboard(patched, tmp_path, capsys):
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(
        '{"id": "c", "prompt": "Capital?", "check": "contains", "expected": "munich"}\n'
    )
    assert cli.main(["eval", "--tasks", str(tasks), "--out", "reports"]) == 0
    assert (tmp_path / "reports" / "leaderboard.md").exists()
    assert "| 1 | llama3.2-1b | 1/1 |" in capsys.readouterr().out


def test_gateway_errors_exit_with_code_2(patched, capsys):
    patched.fail_models.add("llama3.2-1b")
    assert cli.main(["chat", "llama3.2-1b", "hi"]) == 2
    assert "error:" in capsys.readouterr().err


def test_smoke_reports_mcp_failure(patched, monkeypatch, capsys):
    async def broken(url):
        raise ConnectionError("no server")

    monkeypatch.setattr(cli, "_mcp_smoke", broken)
    assert cli.main(["smoke"]) == 1
    out = capsys.readouterr().out
    assert "[PASS] chat through gateway" in out and "[FAIL] MCP server" in out


def test_secrets_init_and_check(tmp_path, capsys):
    assert cli.main(["secrets", "init", "--root", str(tmp_path)]) == 0
    assert cli.main(["secrets", "check", "--root", str(tmp_path)]) == 0
    (tmp_path / "leak.txt").write_text((tmp_path / "secrets/postgres_password.txt").read_text())
    assert cli.main(["secrets", "check", "--root", str(tmp_path)]) == 1
    assert "leak.txt" in capsys.readouterr().out
