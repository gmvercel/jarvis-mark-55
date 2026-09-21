from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_SPEC = spec_from_file_location("spotify_plugin", Path("plugins/spotify.py"))
spotify = module_from_spec(_SPEC)
_SPEC.loader.exec_module(spotify)


def test_spotify_uri_parser_accepts_urls_and_uris():
    assert spotify._spotify_ref("spotify:track:abc123") == ("track", "abc123")
    assert spotify._spotify_ref("https://open.spotify.com/playlist/pl123") == ("playlist", "pl123")


def test_play_track_searches_and_starts_playback():
    class FakeSpotify:
        def __init__(self):
            self.started = None

        def search(self, **kwargs):
            return {"tracks": {"items": [{
                "uri": "spotify:track:abc123",
                "name": "Song",
                "artists": [{"name": "Artist"}],
            }]}}

        def devices(self):
            return {"devices": [{"id": "device-1", "name": "Desktop", "is_active": True}]}

        def start_playback(self, **kwargs):
            self.started = kwargs

    client = FakeSpotify()
    result = spotify._play(client, {"query": "Song by Artist"})

    assert result == "Playing Song - Artist."
    assert client.started == {"device_id": "device-1", "uris": ["spotify:track:abc123"]}


def test_run_pause_uses_selected_device(monkeypatch):
    class FakeSpotify:
        def devices(self):
            return {"devices": [{"id": "phone-1", "name": "Phone", "is_active": False}]}

        def pause_playback(self, **kwargs):
            self.kwargs = kwargs

    client = FakeSpotify()
    monkeypatch.setattr(spotify, "_spotify", lambda: client)

    assert spotify.run({"action": "pause", "device": "Phone"}) == "Spotify playback paused."
    assert client.kwargs == {"device_id": "phone-1"}


def test_run_pause_falls_back_to_desktop_media_key(monkeypatch):
    keys = []
    monkeypatch.setattr(spotify, "_spotify", lambda: (_ for _ in ()).throw(RuntimeError("not configured")))
    monkeypatch.setattr(spotify, "_desktop_fallback", lambda action: keys.append(action) or True)

    assert spotify.run({"action": "pause"}) == (
        "Spotify playback paused using the desktop media control."
    )
    assert keys == ["pause"]