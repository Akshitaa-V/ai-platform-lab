import os
import shutil
import stat
import subprocess
import sys

import pytest

from aiplat.config import read_secret
from aiplat.secrets import SECRET_SPECS, init_secrets, load_secrets, scan_for_secrets

# Built at runtime so this file does not trip the repository scan itself.
PEM_HEADER = "-----BEGIN RSA " + "PRIVATE KEY-----\n"


def test_init_creates_every_secret_with_the_right_prefix(tmp_path):
    created = init_secrets(tmp_path)
    assert set(created) == set(SECRET_SPECS)
    values = load_secrets(tmp_path)
    for name, prefix in SECRET_SPECS.items():
        assert values[name].startswith(prefix)
        assert len(values[name]) >= len(prefix) + 40
    assert len(set(values.values())) == len(values)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_secret_files_are_private(tmp_path):
    init_secrets(tmp_path)
    for path in [*(tmp_path / "secrets").glob("*.txt"), tmp_path / ".env.observability"]:
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_init_never_overwrites_unless_forced(tmp_path):
    init_secrets(tmp_path)
    before = load_secrets(tmp_path)
    assert init_secrets(tmp_path) == []
    assert load_secrets(tmp_path) == before
    assert set(init_secrets(tmp_path, force=True)) == set(SECRET_SPECS)
    assert load_secrets(tmp_path)["litellm_master_key"] != before["litellm_master_key"]


def test_env_observability_matches_secret_files(tmp_path):
    init_secrets(tmp_path)
    values = load_secrets(tmp_path)
    env = (tmp_path / ".env.observability").read_text()
    assert f":{values['postgres_password']}@postgres:5432/langfuse" in env
    assert f"LANGFUSE_INIT_PROJECT_SECRET_KEY={values['langfuse_secret_key']}" in env


def test_scan_finds_planted_secrets_and_ignores_secret_dir(tmp_path):
    init_secrets(tmp_path)
    key = load_secrets(tmp_path)["litellm_master_key"]
    (tmp_path / "config.yaml").write_text(f"master_key: {key}\n")
    (tmp_path / "notes.md").write_text("aws " + "AKIA" + "ABCDEFGHIJKLMNOP" + "\n")
    (tmp_path / "ok.md").write_text("set the key to sk-... in your client\n")
    findings = scan_for_secrets(tmp_path)
    paths = {f.path for f in findings}
    assert paths == {"config.yaml", "notes.md"}


def test_repository_contains_no_secrets():
    assert scan_for_secrets(".") == []


def test_read_secret_prefers_env_then_files(tmp_path, monkeypatch):
    monkeypatch.setenv("AIPLAT_SECRETS_DIR", str(tmp_path))
    monkeypatch.delenv("DEMO_TOKEN", raising=False)
    assert read_secret("demo_token") is None
    (tmp_path / "demo_token.txt").write_text("from-file\n")
    assert read_secret("demo_token") == "from-file"
    monkeypatch.setenv("DEMO_TOKEN", "from-env")
    assert read_secret("demo_token") == "from-env"


@pytest.mark.skipif(not shutil.which("git"), reason="git not installed")
def test_scan_in_git_repo_catches_force_added_secret_files(tmp_path):
    git = ["git", "-C", str(tmp_path)]
    subprocess.run([*git, "init", "-q"], check=True)
    (tmp_path / ".gitignore").write_text("secrets/*\n.venv/\n")
    init_secrets(tmp_path)
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "vendored.py").write_text(PEM_HEADER)
    assert scan_for_secrets(tmp_path) == []

    subprocess.run([*git, "add", "-f", "secrets/postgres_password.txt"], check=True)
    findings = scan_for_secrets(tmp_path)
    assert [f.path for f in findings] == [os.path.join("secrets", "postgres_password.txt")]


def test_walk_mode_skips_virtualenvs(tmp_path):
    venv = tmp_path / "env-any-name"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text("home = /usr\n")
    (venv / "lib.py").write_text(PEM_HEADER)
    assert scan_for_secrets(tmp_path) == []
