import pytest

from n64bot.config import load_settings


def test_load_settings_defaults():
    s = load_settings({"GEMINI_API_KEY": "k"})
    assert s.chat_model == "gemini-2.5-flash"
    assert s.embed_model == "gemini-embedding-001"
    assert s.port == 8000
    assert s.host == "0.0.0.0"
    assert s.pages_dir == s.data_dir / "pages"


def test_missing_key_raises():
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        load_settings({})


def test_port_override():
    assert load_settings({"GEMINI_API_KEY": "k", "N64_PORT": "9001"}).port == 9001
