"""The `api` fixture for the unit tests that drive the Streamlit screens (see streamlit_harness)."""
import pytest

from tests.unit.streamlit_harness import FakeApi  # first: it puts streamlit_app on sys.path
import api_client  # noqa: E402


@pytest.fixture
def api(monkeypatch):
    fake = FakeApi()
    monkeypatch.setattr(api_client, "request", fake)
    return fake
