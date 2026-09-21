import json
import os
from pathlib import Path

import main
from actions import file_controller as file_module
from actions.dev_agent import (
    _classify_error,
    _has_error,
    _is_pizzeria_request,
    _is_transient_model_error,
    _is_web_project,
    _project_directory,
)


def test_main_window_mini_mode_round_trip_is_safe():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from ui import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow("assets/3d/README.md")
    window.enter_mini_mode()
    assert window._mini_mode is True
    window.restore_presentation()
    assert window._mini_mode is False


def test_dev_agent_can_emit_an_offline_project_scaffold_fallback(tmp_path):
    from actions.dev_agent import _make_fallback_project_scaffold

    result = _make_fallback_project_scaffold(tmp_path, "A Python CLI that reads CSV files", "python", "csv_tool")

    assert "pyproject.toml" in result
    assert "README.md" in result
    assert "src" in result
    assert "csv_tool" in result


def test_pomodoro_plugin_file_has_been_removed_from_the_workspace():
    assert not Path("plugins/pomodoro.py").exists()


def test_public_tool_declarations_do_not_expose_code_writing_actions():
    tool_names = {tool["name"] for tool in main.TOOL_DECLARATIONS}

    assert "code_helper" not in tool_names
    assert "dev_agent" not in tool_names


def test_create_work_session_tool_is_exposed_as_a_public_tool_declaration():
    tool_names = {tool["name"] for tool in main.TOOL_DECLARATIONS}

    assert "create_work_session" in tool_names


def test_restart_jarvis_is_exposed_as_a_public_tool_declaration():
    tool_names = {tool["name"] for tool in main.TOOL_DECLARATIONS}

    assert "restart_jarvis" in tool_names


def test_file_controller_exposes_code_and_project_scaffolding_helpers():
    assert hasattr(file_module, "write_code_to_file")
    assert hasattr(file_module, "create_project_structure")


def test_nonzero_process_exit_is_an_error_even_without_error_text():
    output = "PROCESS_EXIT_CODE: 1\nSTDOUT:\nfinished"

    assert _has_error(output, "python main.py")


def test_import_error_is_not_treated_as_missing_dependency():
    assert _classify_error("ImportError: cannot import name 'Widget'") == "import_error"
    assert _classify_error("ModuleNotFoundError: No module named 'requests'") == "dependency_error"


def test_transient_model_errors_are_detected():
    assert _is_transient_model_error(Exception("503 UNAVAILABLE. This model is currently experiencing high demand."))
    assert _is_transient_model_error(Exception("504 DEADLINE_EXCEEDED. Deadline expired before operation could complete."))
    assert _is_transient_model_error(Exception("Model temporarily unavailable; try again later."))
    assert not _is_transient_model_error(Exception("400 BAD_REQUEST. Invalid input."))


def test_italian_web_request_uses_requested_directory():
    description = (
        r"Crea un sito nel percorso `C:\Users\gabri\Downloads\Mark-LII-main-20260901T174448Z-1-001\Mark-LII-main\desktop\sito1` "
        "crea un sito che parla di te, con lo scopo di convincere la gente a scaricarti"
    )

    assert _is_web_project(description, "python")
    assert _project_directory(description, "").as_posix().endswith("/desktop/sito1")
    assert _project_directory(description, "sito1_jarvis").as_posix().endswith("/desktop/sito1")


def test_pizzeria_request_is_detected():
    description = "Crea un sito di una pizzeria con home, menu, prenotazione tavolo e ordinazione da sito"

    assert _is_pizzeria_request(description)


def test_live_stream_disconnect_pattern_is_classified_as_network_error():
    assert main._looks_like_live_stream_error(Exception("APIError: 1011 None. Internal error occurred."))
    assert not main._looks_like_live_stream_error(Exception("Some unrelated tool error"))


def test_format_memory_for_prompt_surfaces_recent_session_context():
    from memory import memory_manager

    memory = {
        "identity": {},
        "preferences": {},
        "projects": {},
        "relationships": {},
        "wishes": {},
        "notes": {},
        "sessions": [
            {"date": "2026-09-14", "summary": "Ha iniziato il sito di portfolio"}
        ],
    }

    prompt_text = memory_manager.format_memory_for_prompt(memory)

    assert "Recent Session Context" in prompt_text
    assert "portfolio" in prompt_text.lower()


def test_save_generic_conversation_context_and_append_work_session_note(monkeypatch, tmp_path):
    from memory import memory_manager

    primary = tmp_path / "long_term.json"
    backup = tmp_path / "long_term.json.bak"
    primary.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(memory_manager, "MEMORY_PATH", primary)
    monkeypatch.setattr(memory_manager, "BACKUP_MEMORY_PATH", backup)

    session = memory_manager.create_work_session(
        title="Sito portfolio",
        topic="web project",
        summary="Preparare il briefing del sito portfolio",
        scope="project",
    )

    memory_manager.append_work_session_note(session["id"], "Il briefing preso in mano oggi: home page, brand, landing page.")
    memory_manager.save_generic_conversation_context("Ho parlato di layout e della scelta del colore del sito.")

    saved = memory_manager.load_memory()

    assert isinstance(saved.get("work_sessions"), list)
    assert saved["work_sessions"][0]["notes"][0]["text"].startswith("Il briefing preso in mano oggi")
    assert any("layout" in (v.get("value") or "") for v in saved["notes"].values())


def test_load_memory_recovers_from_backup_when_primary_file_is_corrupt(monkeypatch, tmp_path):
    from memory import memory_manager

    good = {"identity": {"name": {"value": "Ada", "updated": "2026-09-14"}}}
    primary = tmp_path / "long_term.json"
    backup = tmp_path / "long_term.json.bak"

    primary.parent.mkdir(parents=True, exist_ok=True)
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(json.dumps(good), encoding="utf-8")
    primary.write_text("{ not valid json", encoding="utf-8")

    monkeypatch.setattr(memory_manager, "MEMORY_PATH", primary)
    monkeypatch.setattr(memory_manager, "BACKUP_MEMORY_PATH", backup)

    recovered = memory_manager.load_memory()

    assert recovered["identity"]["name"]["value"] == "Ada"


def test_build_project_returns_error_message_without_preset_for_web_planner_runtime_error(monkeypatch, tmp_path):
    from actions import dev_agent

    monkeypatch.setattr(dev_agent, "_project_directory", lambda description, project_name: tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("Cannot connect to Ollama at http://localhost:11434")

    monkeypatch.setattr(dev_agent, "_plan_project", boom)

    result = dev_agent._build_project(
        description="crea la struttura di un sito di una pizzeria, funzionante, con home e menu in C:\\Users\\renat\\Desktop\\programma",
        language="web",
        project_name="programma",
        timeout=30,
    )

    assert "No preset fallback website was generated" in result
    assert not (tmp_path / "index.html").exists()
