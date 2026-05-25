import json
from pathlib import Path


def test_railway_start_command_sets_src_pythonpath_and_uses_module_uvicorn():
    config = json.loads(Path("railway.json").read_text(encoding="utf-8"))
    command = config["deploy"]["startCommand"]

    assert "PYTHONPATH=.railway-deps:src" in command
    assert "python -m uvicorn" in command
    assert "${PORT:-8000}" in command


def test_railway_build_command_installs_runtime_dependencies_explicitly():
    config = json.loads(Path("railway.json").read_text(encoding="utf-8"))
    command = config["build"]["buildCommand"]

    assert "python -m pip install" in command
    assert "--target ./.railway-deps" in command
    assert "-r requirements.txt" in command


def test_runtime_requirements_file_exists_for_railpack_pip_install():
    requirements = Path("requirements.txt").read_text(encoding="utf-8")

    assert "fastapi" in requirements
    assert "uvicorn" in requirements
    assert "pydantic-settings" in requirements
