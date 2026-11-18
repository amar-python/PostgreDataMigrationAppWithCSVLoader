"""The Streamlit upload screen (#255): its pure helpers, the api_client timeout, and the config. AppTest has no
file uploader, so the widgets are covered by e2e/test_streamlit_upload.py."""
import base64
import tomllib
from unittest.mock import Mock

import pytest
import requests

from tests.unit.streamlit_harness import APP_DIR, view  # first: it puts streamlit_app on sys.path
import api_client
from views import allowed_screens, upload
from views.upload import build_payload, prepare

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def test_prepare_refuses_non_utf8():
    assert prepare("a.csv", b"name\n\xe9t\xe9\n") == (None, 'a.csv isn\'t UTF-8 text. Save it as "CSV UTF-8" and try again.')


def test_prepare_returns_the_text():
    assert prepare("a.csv", b"a\n1\n") == ("a\n1\n", None)


def test_size_boundary(monkeypatch):
    monkeypatch.setattr(upload, "MAX_UPLOAD_BYTES", 1048576)
    assert prepare("a.csv", b"x" * 1048576)[1] is None
    assert prepare("a.csv", b"x" * 1048577)[1] == "a.csv is larger than the 1 MB the server accepts."


def test_default_limit_reads_50_mb():
    assert upload.MAX_UPLOAD_BYTES == 52428800
    assert prepare("a.csv", b"x" * 52428801)[1] == "a.csv is larger than the 50 MB the server accepts."


def test_dynamic_payload_sends_types_only_with_confirmation_and_mapping_only_when_renamed():
    p = build_payload("a.csv", b"a\n1\n", "a\n1\n", mode="dynamic", types=["int8"], confirmed=True, renames={"a": ""})
    assert p["types"] == ["int8"] and p["typesConfirmed"] is True and "headerMapping" not in p
    p = build_payload("a.csv", b"a\n1\n", "a\n1\n", mode="dynamic", types=["int8"], confirmed=True, renames={"a": "age"})
    assert p["headerMapping"] == [{"original": "a", "renamed": "age"}]


def test_te_payload_has_no_mapping_or_types():
    p = build_payload("o.csv", b"x", "x", mode="te", target="organisations")
    assert p["mode"] == "te" and p["targetTable"] == "organisations" and "types" not in p and "headerMapping" not in p
    assert "typesConfirmed" not in p
    assert base64.b64decode(p["contentBase64"]) == b"x"


def test_timeout_is_not_reported_as_unreachable(monkeypatch):
    monkeypatch.setattr(requests, "request", Mock(side_effect=requests.Timeout))
    with pytest.raises(api_client.TimedOut, match="check Import history") as e:
        api_client.request("POST", "/api/csv/upload", timeout=600)
    assert str(e.value).startswith("The server didn't answer within 600 s.") and e.value.status == 0


def test_other_request_errors_are_still_unreachable(monkeypatch):
    monkeypatch.setattr(requests, "request", Mock(side_effect=requests.ConnectionError))
    with pytest.raises(api_client.Unreachable):
        api_client.request("GET", "/x")


def test_upload_timeout_is_passed_through(monkeypatch):
    mock = Mock(return_value=Mock(ok=True, json=lambda: {}))
    monkeypatch.setattr(requests, "request", mock)
    api_client.request("POST", "/api/csv/upload", timeout=upload.UPLOAD_TIMEOUT_SECONDS)
    assert mock.call_args.kwargs["timeout"] == 600
    api_client.request("GET", "/x")
    assert mock.call_args.kwargs["timeout"] == api_client.TIMEOUT_SECONDS


def test_uploader_limit_is_above_the_apis():
    cfg = tomllib.loads((APP_DIR / ".streamlit" / "config.toml").read_text())
    assert cfg["server"]["maxUploadSize"] * 1_000_000 > 52428800
    assert cfg["browser"]["gatherUsageStats"] is False


def test_role_without_upload_sees_no_upload_screen():
    assert "upload" not in allowed_screens("reviewer") and allowed_screens("uploader")[0] == "upload"


def test_screen_renders_with_the_templates_note(api):
    at = view("upload", api=api)
    assert not at.exception and at.title[0].value == "Upload"
    assert any("Saved mapping templates aren't available in this version." in c.value for c in at.caption)
