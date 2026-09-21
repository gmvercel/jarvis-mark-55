"""VS Code workspace integration for JARVIS."""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
_EXCLUDED = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}


def _workspace_path(raw: str | None) -> Path:
    path = Path(raw).expanduser() if raw else BASE_DIR
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


def _code_command() -> str | None:
    candidates = [
        shutil.which("code"),
        shutil.which("code.cmd"),
        rf"C:\Users\{Path.home().name}\AppData\Local\Programs\Microsoft VS Code\bin\code.cmd",
        r"C:\Program Files\Microsoft VS Code\bin\code.cmd",
    ]
    return next((candidate for candidate in candidates if candidate and Path(candidate).exists()), None)


def _open_in_vscode(target: Path, line: int | None = None, column: int | None = None) -> str:
    command = _code_command()
    if not command:
        return "VS Code CLI non trovato. Abilita 'code' nel PATH oppure reinstalla VS Code con l'opzione CLI."

    target_arg = str(target)
    if line:
        target_arg += f":{line}"
        if column:
            target_arg += f":{column}"
    try:
        subprocess.Popen(
            [command, "--reuse-window", target_arg],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return f"Aperto in VS Code: {target}"
    except Exception as exc:
        return f"Impossibile aprire VS Code: {exc}"


def _list_workspace(workspace: Path) -> str:
    if not workspace.is_dir():
        return f"Workspace non trovato: {workspace}"
    files = []
    for path in workspace.rglob("*"):
        if path.is_file() and not any(part in _EXCLUDED for part in path.relative_to(workspace).parts):
            files.append(str(path.relative_to(workspace)))
    files.sort(key=str.lower)
    if not files:
        return f"Workspace vuoto: {workspace}"
    shown = files[:200]
    suffix = f"\n... e altri {len(files) - len(shown)} file" if len(files) > len(shown) else ""
    return f"Workspace: {workspace}\n" + "\n".join(shown) + suffix


def _run_command(command: str, workspace: Path, timeout: int) -> str:
    if not command:
        return "Specifica il comando da eseguire nel workspace."
    if not workspace.is_dir():
        return f"Workspace non trovato: {workspace}"
    try:
        result = subprocess.run(
            command,
            cwd=str(workspace),
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, min(timeout, 300)),
        )
        output = (result.stdout + (f"\nSTDERR:\n{result.stderr}" if result.stderr else "")).strip()
        return f"Exit code: {result.returncode}\n{output or '(nessun output)'}"
    except subprocess.TimeoutExpired:
        return f"Comando interrotto dopo {timeout} secondi."
    except Exception as exc:
        return f"Errore comando: {exc}"


def _test_workspace(workspace: Path, timeout: int) -> str:
    if (workspace / "pyproject.toml").exists() or (workspace / "pytest.ini").exists() or (workspace / "tests").is_dir():
        command = f'"{sys.executable}" -m pytest -q'
    elif (workspace / "package.json").exists():
        command = "npm test -- --runInBand"
    else:
        command = f'"{sys.executable}" -m compileall -q .'
    return _run_command(command, workspace, timeout)


def vscode_control(parameters: dict | None = None, **_) -> str:
    """Perform a VS Code workspace operation."""
    params = parameters or {}
    action = str(params.get("action", "open_workspace")).strip().lower()
    workspace = _workspace_path(params.get("workspace") or params.get("path"))

    if action in {"open", "open_workspace", "workspace"}:
        return _open_in_vscode(workspace)
    if action in {"open_file", "file"}:
        file_path = _workspace_path(params.get("file_path") or params.get("file"))
        if not file_path.is_file():
            return f"File non trovato: {file_path}"
        return _open_in_vscode(file_path, int(params["line"]) if params.get("line") else None, int(params["column"]) if params.get("column") else None)
    if action in {"list", "inspect", "workspace_files"}:
        return _list_workspace(workspace)
    if action in {"test", "tests", "run_tests"}:
        return _test_workspace(workspace, int(params.get("timeout", 120)))
    if action in {"run", "command", "terminal"}:
        return _run_command(str(params.get("command", "")), workspace, int(params.get("timeout", 30)))
    if action in {"diagnostics", "check", "lint"}:
        command = str(params.get("command") or f'"{sys.executable}" -m compileall -q .')
        return _run_command(command, workspace, int(params.get("timeout", 120)))
    if action in {"debug", "debug_file"}:
        file_path = _workspace_path(params.get("file_path") or params.get("file"))
        opened = _open_in_vscode(file_path if file_path.is_file() else workspace, int(params["line"]) if params.get("line") else None)
        return f"{opened}\nUsa il pannello Run and Debug di VS Code per avviare il debugger sul file aperto."
    return "Azione VS Code non riconosciuta: open_workspace, open_file, list, test, run, diagnostics, debug."
