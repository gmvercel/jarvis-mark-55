from memory import memory_manager


def test_work_session_lifecycle_is_persistent(monkeypatch, tmp_path):
    primary = tmp_path / "long_term.json"
    backup = tmp_path / "long_term.json.bak"
    monkeypatch.setattr(memory_manager, "MEMORY_PATH", primary)
    monkeypatch.setattr(memory_manager, "BACKUP_MEMORY_PATH", backup)

    created = memory_manager.create_work_session(
        title="Audio feature",
        topic="jarvis",
        summary="Implement the settings and activation flow",
    )
    updated = memory_manager.append_work_session_note(created["id"], "UI panel is connected")

    assert updated is not None
    sessions = memory_manager.list_work_sessions()
    assert sessions[-1]["title"] == "Audio feature"
    assert sessions[-1]["notes"][-1]["text"] == "UI panel is connected"


def test_work_session_can_be_deleted(monkeypatch, tmp_path):
    memory_path = tmp_path / "long_term.json"
    backup_path = tmp_path / "long_term.json.bak"
    monkeypatch.setattr(memory_manager, "MEMORY_PATH", memory_path)
    monkeypatch.setattr(memory_manager, "BACKUP_MEMORY_PATH", backup_path)

    created = memory_manager.create_work_session("Delete me", "test", "temporary")
    assert memory_manager.delete_work_session(created["id"]) is True
    assert memory_manager.list_work_sessions() == []


def test_restart_context_round_trip(monkeypatch, tmp_path):
    resume = tmp_path / "restart_context.json"
    monkeypatch.setattr(memory_manager, "RESUME_PATH", resume)

    memory_manager.save_restart_context(["User: ricordati il progetto", "JARVIS: Certamente."])

    assert memory_manager.load_restart_context() == [
        "User: ricordati il progetto",
        "JARVIS: Certamente.",
    ]
    memory_manager.clear_restart_context()
    assert memory_manager.load_restart_context() == []