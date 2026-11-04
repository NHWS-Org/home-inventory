import ast
from contextlib import asynccontextmanager
import os
from pathlib import Path
import subprocess
import warnings

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


@pytest.mark.parametrize("root_path", ["", "/api"])
def test_entrypoint_passes_root_path_to_uvicorn(tmp_path, root_path):
    executable = tmp_path / "uvicorn"
    executable.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    executable.chmod(0o755)
    entrypoint = (Path(__file__).resolve().parents[1] / "entrypoint.sh").read_text()
    command = next(line for line in entrypoint.splitlines() if line.startswith("exec uvicorn "))
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    env.pop("FASTAPI_ROOT_PATH", None)
    if root_path:
        env["FASTAPI_ROOT_PATH"] = root_path
    result = subprocess.run(
        ["sh", "-c", command], env=env, capture_output=True, text=True, check=True,
    )
    arguments = result.stdout.splitlines()
    assert arguments[-2:] == ["--root-path", root_path]


@pytest.mark.parametrize("root_path", ["", "/api"])
def test_server_root_path_keeps_routes_and_docs_working(root_path):
    @asynccontextmanager
    async def lifespan(app):
        yield

    tree = ast.parse((Path(__file__).resolve().parents[1] / "main.py").read_text())
    assignment = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "app" for target in node.targets)
    )
    namespace = {"FastAPI": FastAPI, "lifespan": lifespan, "api_version": "test"}
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        exec(compile(ast.Module(body=[assignment], type_ignores=[]), "main.py", "exec"), namespace)
    app = namespace["app"]

    @app.get("/system/health-check")
    def health_check():
        return {"status": "ok"}

    with TestClient(app, root_path=root_path) as client:
        assert client.get(f"{root_path}/system/health-check").json() == {"status": "ok"}
        docs = client.get(f"{root_path}/docs")
        assert docs.status_code == 200
        assert f"{root_path}/openapi.json" in docs.text
        schema = client.get(f"{root_path}/openapi.json").json()
        assert "/system/health-check" in schema["paths"]
        if root_path:
            assert {"url": root_path} in schema["servers"]
