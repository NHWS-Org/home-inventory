import os
from pathlib import Path
import shutil
import subprocess


def test_setup_uses_its_own_directory_and_requirements(tmp_path):
    backend_dir = tmp_path / "backend source"
    backend_dir.mkdir()
    script = backend_dir / "setup_venv.sh"
    shutil.copyfile(Path(__file__).resolve().parents[1] / "setup_venv.sh", script)
    (backend_dir / "requirements.txt").write_text("sqlalchemy\n")
    venv_bin = backend_dir / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "activate").write_text(
        'export PATH="$PWD/.venv/bin:$PATH"\n'
    )
    python = venv_bin / "python"
    python.write_text('#!/bin/sh\nprintf "%s|%s\\n" "$PWD" "$*" >> "$SETUP_TEST_LOG"\n')
    python.chmod(0o755)
    log = tmp_path / "calls.log"

    result = subprocess.run(
        ["bash", str(script)],
        cwd=tmp_path,
        env={**os.environ, "SETUP_TEST_LOG": str(log)},
        capture_output=True,
        text=True,
        check=True,
    )

    assert log.read_text().splitlines() == [
        f"{backend_dir}|-m pip install --upgrade pip wheel setuptools",
        f"{backend_dir}|-m pip install -r requirements.txt",
    ]
    assert "Ambiente pronto" in result.stdout
    assert not (tmp_path / ".venv").exists()
    assert (backend_dir / "requirements.txt").read_text() == "sqlalchemy\n"


def test_setup_fails_if_requirements_are_missing(tmp_path):
    script = tmp_path / "setup_venv.sh"
    shutil.copyfile(Path(__file__).resolve().parents[1] / "setup_venv.sh", script)

    result = subprocess.run(
        ["bash", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "requirements.txt non trovato" in result.stderr
    assert not (tmp_path / ".venv").exists()
    assert not (tmp_path / "requirements.txt").exists()
