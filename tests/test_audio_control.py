from array import array

from core import audio_control


def test_load_audio_settings_normalizes_adaptive_audio(tmp_path, monkeypatch):
    config_path = tmp_path / "api_keys.json"
    config_path.write_text(
        '{"adaptive_audio_enabled": true, "adaptive_audio_mode": "stop", '
        '"adaptive_audio_duck_percent": 99}',
        encoding="utf-8",
    )
    monkeypatch.setattr(audio_control, "_CONFIG_PATH", config_path)

    settings = audio_control.load_audio_settings()
    assert settings["adaptive_audio_mode"] == "stop"
    assert settings["adaptive_audio_duck_percent"] == 90


def test_push_to_talk_is_disabled_when_not_configured(tmp_path, monkeypatch):
    config_path = tmp_path / "api_keys.json"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(audio_control, "_CONFIG_PATH", config_path)

    assert audio_control.load_audio_settings()["push_to_talk_enabled"] is False


def test_apply_voice_volume_clamps_and_preserves_pcm_length():
    pcm = array("h", [1000, -1000, 32000]).tobytes()

    louder = audio_control.apply_voice_volume(pcm, 20)
    quieter = audio_control.apply_voice_volume(pcm, -50)

    assert len(louder) == len(pcm)
    assert len(quieter) == len(pcm)
    assert array("h", louder)[0] == 1200
    assert array("h", quieter)[0] == 500


def test_activate_media_ducks_and_restores(monkeypatch):
    keys = []
    monkeypatch.setattr(audio_control, "_media_key", keys.append)
    monkeypatch.setattr(audio_control, "_media_controls", lambda: [])

    steps = audio_control.activate_media("duck", 40)
    audio_control.restore_ducked_media(steps)

    assert steps == 8
    assert keys == ["volumedown"] * 8 + ["volumeup"] * 8


def test_activate_media_can_stop_playback(monkeypatch):
    keys = []
    monkeypatch.setattr(audio_control, "_media_key", keys.append)

    assert audio_control.activate_media("stop") == 0
    assert keys == ["playpause"]


def test_toggle_media_playback_uses_immediate_media_key(monkeypatch):
    keys = []
    monkeypatch.setattr(audio_control, "_media_key", keys.append)

    audio_control.toggle_media_playback(object())

    assert keys == ["playpause"]


def test_media_output_available_uses_active_sessions(monkeypatch):
    monkeypatch.setattr(audio_control, "_media_controls", lambda: [object()])

    assert audio_control.media_output_available() is True


def test_wake_word_detector_buffers_realtime_audio_chunks():
    class FakeNumpy:
        int16 = "int16"

        @staticmethod
        def frombuffer(data, dtype):
            assert dtype == "int16"
            return data

    class FakeModel:
        def __init__(self):
            self.calls = 0

        def predict(self, samples):
            self.calls += 1
            assert len(samples) == 1280 * 2
            return {"hey_jarvis": 0.4}

    detector = audio_control.WakeWordDetector.__new__(audio_control.WakeWordDetector)
    detector._np = FakeNumpy
    detector._model = FakeModel()
    detector._pending = bytearray()
    detector._positive_windows = 0

    assert detector.detected(b"x" * (1024 * 2)) is False
    assert detector._model.calls == 0
    assert detector.detected(b"x" * (256 * 2)) is False
    assert detector._model.calls == 1
    assert detector.detected(b"x" * (1280 * 2)) is True
    assert detector._model.calls == 2


def test_wake_word_detector_reset_discards_partial_audio():
    detector = audio_control.WakeWordDetector.__new__(audio_control.WakeWordDetector)
    detector._pending = bytearray(b"partial")
    detector._positive_windows = 1

    detector.reset()

    assert detector._pending == bytearray()
    assert detector._positive_windows == 0


def test_wake_word_detector_uses_highest_score_and_rearms_after_reset():
    class FakeModel:
        def predict(self, samples):
            return {"hey_jarvis": 0.4, "noise": 0.01}

    detector = audio_control.WakeWordDetector.__new__(audio_control.WakeWordDetector)
    detector._np = type("FakeNumpy", (), {
        "int16": "int16",
        "frombuffer": staticmethod(lambda data, dtype: data),
    })
    detector._model = FakeModel()
    detector._pending = bytearray()
    detector._positive_windows = 0
    detector._cooldown_until = 0.0

    chunk = b"x" * (1280 * 2)
    assert detector.detected(chunk) is False
    assert detector.detected(chunk) is True
    assert detector.detected(chunk) is False
    detector.reset()
    assert detector.detected(chunk) is False


