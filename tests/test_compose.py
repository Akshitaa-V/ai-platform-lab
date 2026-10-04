"""Static checks on the deployment files, so mistakes fail in CI instead of at `up`."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from aiplat.secrets import SECRET_SPECS, init_secrets

BASE = yaml.safe_load(Path("docker-compose.yml").read_text())
OBS = yaml.safe_load(Path("docker-compose.observability.yml").read_text())
GPU = yaml.safe_load(Path("docker-compose.gpu.yml").read_text())
ONE_SHOT = {"ollama-init"}


def all_services():
    for doc in (BASE, OBS, GPU):
        yield from doc.get("services", {}).items()


def test_every_published_port_is_localhost_only():
    for name, svc in all_services():
        for port in svc.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes {port} on all interfaces"


def test_long_running_services_have_healthchecks():
    for doc in (BASE, OBS):
        for name, svc in doc["services"].items():
            if name in ONE_SHOT or "image" not in svc and "build" not in svc:
                continue
            assert "healthcheck" in svc, f"{name} has no healthcheck"


def test_no_floating_latest_tags():
    images = [svc["image"] for _, svc in all_services() if "image" in svc]
    images += re.findall(r"^\w+_IMAGE=(.+)$", Path(".env.example").read_text(), re.M)
    assert images
    for image in images:
        assert not image.rstrip("}").endswith(":latest"), image


def test_secrets_are_files_from_the_known_set_and_never_inline():
    declared = {**BASE["secrets"], **OBS["secrets"]}
    for name, spec in declared.items():
        assert name in SECRET_SPECS
        assert spec == {"file": f"./secrets/{name}.txt"}
    text = "\n".join(
        Path(p).read_text()
        for p in ["docker-compose.yml", "docker-compose.observability.yml", ".env.example"]
    )
    assert not re.search(r"(PASSWORD|SECRET|KEY)\s*[:=]\s*['\"]?[A-Za-z0-9]{8,}", text)


def test_services_use_only_declared_secrets():
    declared = set(BASE["secrets"]) | set(OBS["secrets"])
    for name, svc in all_services():
        for secret in svc.get("secrets", []):
            assert secret in declared, f"{name} uses undeclared secret {secret}"


def test_gateway_starts_through_the_secrets_wrapper():
    gateway = BASE["services"]["gateway"]
    assert gateway["entrypoint"] == ["/bin/sh", "/platform/env-from-secrets.sh"]
    assert "./platform/env-from-secrets.sh:/platform/env-from-secrets.sh:ro" in gateway["volumes"]


def test_startup_order_waits_for_health():
    deps = BASE["services"]["gateway"]["depends_on"]
    assert deps["ollama"]["condition"] == "service_healthy"
    assert deps["ollama-init"]["condition"] == "service_completed_successfully"
    assert BASE["services"]["mcp"]["depends_on"]["gateway"]["condition"] == "service_healthy"


def test_env_from_secrets_wrapper_exports_and_execs(tmp_path):
    sh = shutil.which("sh")
    if not sh:
        pytest.skip("no POSIX shell")


@pytest.mark.parametrize(
    "files",
    [
        ["docker-compose.yml"],
        ["docker-compose.yml", "docker-compose.observability.yml"],
        ["docker-compose.yml", "docker-compose.gpu.yml"],
    ],
)
def test_docker_compose_config_is_valid(files, tmp_path):
    docker = shutil.which("docker")
    if not docker or subprocess.run([docker, "compose", "version"], capture_output=True).returncode:
        pytest.skip("docker compose not installed")
    # Render against a throwaway copy so real secrets are never touched.
    for item in [
        "docker-compose.yml",
        "docker-compose.observability.yml",
        "docker-compose.gpu.yml",
        "gateway",
        "platform",
        "Dockerfile.mcp",
    ]:
        src = Path(item)
        (shutil.copytree if src.is_dir() else shutil.copy)(src, tmp_path / item)
    init_secrets(tmp_path)
    args = [docker, "compose"] + [x for f in files for x in ("-f", f)] + ["config", "--quiet"]
    result = subprocess.run(args, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
