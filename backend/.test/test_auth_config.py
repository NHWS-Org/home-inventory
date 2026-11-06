from concurrent.futures import ThreadPoolExecutor
import logging
import os
from pathlib import Path
import subprocess
import sys

import jwt
import pytest

import auth_config


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY_FILE", raising=False)
    monkeypatch.setattr(auth_config, "__file__", str(tmp_path / "auth_config.py"))
    auth_config.get_secret_key.cache_clear()
    yield tmp_path / "data" / "jwt-secret.key"
    auth_config.get_secret_key.cache_clear()


def create_key(path):
    return auth_config.persistent_secret(Path(path))


def test_auto_persists_private_key_and_reuses_after_restart(config, caplog):
    caplog.set_level(logging.WARNING)
    first = auth_config.get_secret_key()
    assert len(first) >= 64
    assert config.read_text() == first
    assert config.stat().st_mode & 0o777 == 0o600
    auth_config.get_secret_key.cache_clear()
    assert auth_config.get_secret_key() == first
    assert "generated" in caplog.text
    assert "reused" in caplog.text
    assert first not in caplog.text
    assert list(config.parent.glob(".jwt-secret-*")) == []


def test_concurrent_callers_publish_only_one_complete_key(config):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(create_key, [str(config)] * 8))
    assert len({key for key, _ in results}) == 1
    assert sum(generated for _, generated in results) == 1
    assert config.read_text() == results[0][0]


def test_explicit_environment_key_and_cache(config, monkeypatch, caplog):
    secret = "a" * 64
    monkeypatch.setenv("SECRET_KEY", secret)
    assert auth_config.get_secret_key() == secret
    assert not config.exists()
    assert "supplied by configuration" in caplog.text
    assert secret not in caplog.text


def test_explicit_secret_file(config, tmp_path, monkeypatch, caplog):
    secret = "b" * 64
    supplied = tmp_path / "docker-secret"
    supplied.write_text(secret + "\n")
    monkeypatch.setenv("SECRET_KEY", "AUTO")
    monkeypatch.setenv("SECRET_KEY_FILE", str(supplied))
    assert auth_config.get_secret_key() == secret
    assert not config.exists()
    assert "SECRET_KEY_FILE" in caplog.text
    assert secret not in caplog.text


@pytest.mark.parametrize("value", ["short", "x" * 31])
def test_weak_explicit_keys_fail_without_generation(config, monkeypatch, caplog, value):
    monkeypatch.setenv("SECRET_KEY", value)
    with pytest.raises(RuntimeError, match="32 bytes"):
        auth_config.get_secret_key()
    assert not config.exists()
    assert value not in caplog.text


def test_conflicting_sources_fail(config, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x" * 64)
    monkeypatch.setenv("SECRET_KEY_FILE", "missing")
    with pytest.raises(RuntimeError, match="only one"):
        auth_config.get_secret_key()
    assert not config.exists()


def test_missing_secret_file_does_not_fall_back(config, monkeypatch):
    monkeypatch.setenv("SECRET_KEY_FILE", "missing")
    with pytest.raises(RuntimeError, match="Cannot read"):
        auth_config.get_secret_key()
    assert not config.exists()


def test_invalid_existing_key_does_not_get_overwritten(config):
    config.parent.mkdir()
    config.write_text("invalid")
    config.chmod(0o600)
    with pytest.raises(RuntimeError, match="32 bytes"):
        auth_config.get_secret_key()
    assert config.read_text() == "invalid"


def test_public_generated_key_rejected(config):
    config.parent.mkdir()
    config.write_text("x" * 64)
    config.chmod(0o644)
    with pytest.raises(RuntimeError, match="only to its owner"):
        auth_config.get_secret_key()


def test_symlink_not_followed(config, tmp_path):
    target = tmp_path / "other.key"
    target.write_text("x" * 64)
    config.parent.mkdir()
    config.symlink_to(target)
    with pytest.raises(RuntimeError, match="Cannot read"):
        auth_config.get_secret_key()


def test_unwritable_storage_does_not_generate_ephemeral_key(config):
    config.parent.write_text("not a directory")
    with pytest.raises(RuntimeError, match="persist"):
        auth_config.get_secret_key()


def test_environment_precedes_dotenv_in_fresh_process(tmp_path):
    secret = "c" * 64
    result = subprocess.run(
        [
            sys.executable, "-c",
            "import os; from auth_config import get_secret_key; "
            "assert get_secret_key() == os.environ['SECRET_KEY']",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "SECRET_KEY": secret, "SECRET_KEY_FILE": ""},
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert secret not in result.stdout + result.stderr


def test_auto_key_is_reused_by_independent_processes(tmp_path):
    directory = Path(__file__).resolve().parents[1]
    script = (
        "import sys; from pathlib import Path; import auth_config; "
        "auth_config.__file__ = str(Path(sys.argv[1]) / 'auth_config.py'); "
        "key = auth_config.get_secret_key(); "
        "import hashlib; print(hashlib.sha256(key.encode()).hexdigest())"
    )
    outputs = []
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path)], cwd=directory,
            env={**os.environ, "SECRET_KEY": "AUTO", "SECRET_KEY_FILE": ""},
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0, result.stderr
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]
    assert (tmp_path / "data" / "jwt-secret.key").read_text() not in "".join(outputs)


def test_rotation_invalidates_token_but_not_password_hash(config, monkeypatch):
    from routes.auth import hash_password, verify_password

    password = "test-only-password"
    hashed = hash_password(password)
    first = auth_config.get_secret_key()
    token = jwt.encode({"sub": "test"}, first, algorithm="HS256")
    assert jwt.decode(token, first, algorithms=["HS256"])["sub"] == "test"
    monkeypatch.setenv("SECRET_KEY", "d" * 64)
    auth_config.get_secret_key.cache_clear()
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, auth_config.get_secret_key(), algorithms=["HS256"])
    assert verify_password(password, hashed)


def test_docker_context_excludes_runtime_secrets():
    backend = Path(__file__).resolve().parents[1]
    ignored = (backend / ".dockerignore").read_text().splitlines()
    assert all(value in ignored for value in (".env", ".env.*", "data", "*.key", "*.pem"))
    assert "!.env.example" in ignored
    assert "SECRET_KEY=AUTO" in (backend / ".env.example").read_text()
    example = (backend / ".env.example").read_text()
    version = next(line for line in example.splitlines() if line.startswith("API_VERSION="))
    assert version in (backend / "Dockerfile").read_text()
    workflow = backend.parent / ".github" / "workflows" / "publish-images.yml"
    assert "backend/.env.example" in workflow.read_text()
