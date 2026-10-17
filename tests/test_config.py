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


def test_timeout_and_thinking_defaults_and_overrides():
    s = load_settings({"GEMINI_API_KEY": "k"})
    assert (s.gemini_timeout_s, s.thinking_budget) == (120, 0)
    s = load_settings(
        {"GEMINI_API_KEY": "k", "N64_GEMINI_TIMEOUT": "30", "N64_THINKING_BUDGET": "512"}
    )
    assert (s.gemini_timeout_s, s.thinking_budget) == (30, 512)
