import base64

from plugins import google_workspace as google


def _encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def test_gmail_parts_do_not_duplicate_text_parts():
    payload = {
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _encoded("Hello")}},
            {"mimeType": "text/html", "body": {"data": _encoded("<b>World</b>")}},
        ]
    }

    assert google._gmail_parts(payload) == ["Hello", "World"]


def test_gmail_parts_walk_nested_multipart():
    payload = {
        "parts": [{
            "mimeType": "multipart/alternative",
            "parts": [{"mimeType": "text/plain", "body": {"data": _encoded("Nested")}}],
        }]
    }

    assert google._gmail_parts(payload) == ["Nested"]


def test_strip_html_removes_markup():
    assert google._strip_html("<p>Hello&nbsp;world</p>") == "Hello world"
