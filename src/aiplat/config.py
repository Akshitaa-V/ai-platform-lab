"""Settings and secret lookup.

Secrets are never read from source code or compose files. A secret is looked up,
in order, from an environment variable, a Docker secret mounted at
/run/secrets/<name>, and the local secrets/<name>.txt file created by
`aiplat secrets init`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DOCKER_SECRETS_DIR = Path("/run/secrets")


def secrets_dir() -> Path:
    return Path(os.environ.get("AIPLAT_SECRETS_DIR", "secrets"))


def read_secret(name: str) -> str | None:
    """Return the secret called `name`, or None if it is not configured anywhere."""
    env_value = os.environ.get(name.upper())
    if env_value:
        return env_value.strip()
    for path in (DOCKER_SECRETS_DIR / name, secrets_dir() / f"{name}.txt"):
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return None


@dataclass(frozen=True)
class Settings:
    gateway_url: str
    gateway_key: str | None
    ollama_url: str
    mcp_url: str
    langfuse_url: str | None
    timeout: float

    @classmethod
    def from_env(cls) -> Settings:
        langfuse = os.environ.get("LANGFUSE_URL", "http://127.0.0.1:3000").strip()
        return cls(
            gateway_url=os.environ.get("GATEWAY_URL", "http://127.0.0.1:4000").rstrip("/"),
            gateway_key=read_secret("litellm_master_key"),
            ollama_url=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
            mcp_url=os.environ.get("MCP_URL", "http://127.0.0.1:8000").rstrip("/"),
            langfuse_url=langfuse.rstrip("/") or None,
            timeout=float(os.environ.get("AIPLAT_TIMEOUT", "120")),
        )
