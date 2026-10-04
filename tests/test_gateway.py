import httpx
import pytest

from aiplat.gateway import GatewayClient, GatewayError


def test_list_models_sends_key_and_sorts(client, fake_gateway):
    assert client.list_models() == ["llama3.2-1b", "qwen2.5-0.5b"]
    assert fake_gateway.requests[0].headers["authorization"] == "Bearer sk-test-key"


def test_chat_returns_text_latency_and_tokens(client, fake_gateway):
    result = client.chat("llama3.2-1b", "Capital of Bavaria?", max_tokens=5, system="Be brief.")
    assert result.text == "Munich"
    assert result.total_tokens == 13
    assert result.latency_s >= 0
    sent = fake_gateway.requests[-1]
    assert b'"max_tokens":5' in sent.content.replace(b" ", b"")
    assert b'"role":"system"' in sent.content.replace(b" ", b"")


def test_wrong_key_raises_gateway_error(fake_gateway):
    bad = GatewayClient("http://gateway:4000", "sk-wrong", transport=fake_gateway.transport)
    with pytest.raises(GatewayError, match="401"):
        bad.list_models()


def test_server_error_raises_gateway_error(client, fake_gateway):
    fake_gateway.fail_models.add("llama3.2-1b")
    with pytest.raises(GatewayError, match="500"):
        client.chat("llama3.2-1b", "hi")


def test_timeout_and_connection_errors_become_gateway_errors():
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request):
        raise httpx.ConnectError("refused", request=request)

    for handler, match in ((timeout, "timed out"), (refused, "unreachable")):
        c = GatewayClient("http://gateway:4000", "k", transport=httpx.MockTransport(handler))
        with pytest.raises(GatewayError, match=match):
            c.list_models()


def test_malformed_response_raises_gateway_error():
    c = GatewayClient(
        "http://gateway:4000",
        "k",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"choices": []})),
    )
    with pytest.raises(GatewayError, match="no message content"):
        c.chat("m", "hi")
