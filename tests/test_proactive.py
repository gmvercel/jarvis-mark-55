from ui import _file_category


def test_common_video_extensions_are_recognized():
    assert _file_category(__import__('pathlib').Path("clip.mp4")) == "video"
    assert _file_category(__import__('pathlib').Path("clip.3gp")) == "video"
    assert _file_category(__import__('pathlib').Path("clip.m2ts")) == "video"


def test_file_processor_accepts_upload_path_aliases(monkeypatch, tmp_path):
    from actions import file_processor as fp

    sample = tmp_path / "sample.txt"
    sample.write_text("hello world", encoding="utf-8")

    monkeypatch.setattr(fp, "_detect_type", lambda path: "text")
    monkeypatch.setattr(fp, "_process_text_doc", lambda path, file_type, action, params, speak: "read ok")

    result = fp.file_processor({"path": str(sample), "action": "summarize"}, player=None, speak=None)

    assert result == "read ok"


def test_proactive_engine_file_can_still_be_imported():
    from actions.proactive import ProactiveEngine

    assert ProactiveEngine is not None
