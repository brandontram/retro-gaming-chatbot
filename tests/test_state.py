import json

from n64bot.state import Exchange, StateStore


def test_set_game_persists_across_instances(tmp_path):
    p = tmp_path / "sub" / "state.json"
    s = StateStore(p)
    assert s.active_game() is None
    s.set_game("mario-kart-64")
    s.append("q", "a")
    s2 = StateStore(p)
    assert s2.active_game() == "mario-kart-64"
    assert s2.history() == [Exchange("q", "a")]


def test_swap_clears_history(tmp_path):
    s = StateStore(tmp_path / "state.json")
    s.set_game("a")
    s.append("q", "a")
    s.set_game("b")
    assert s.active_game() == "b"
    assert s.history() == []


def test_same_game_keeps_history(tmp_path):
    s = StateStore(tmp_path / "state.json")
    s.set_game("a")
    s.append("q", "a")
    s.set_game("a")
    assert len(s.history()) == 1


def test_history_capped_at_four(tmp_path):
    s = StateStore(tmp_path / "state.json")
    s.set_game("a")
    for i in range(6):
        s.append(f"q{i}", f"a{i}")
    assert [e.question for e in s.history()] == ["q2", "q3", "q4", "q5"]
    assert [e.question for e in StateStore(tmp_path / "state.json").history()] == [
        "q2", "q3", "q4", "q5"]


def test_corrupt_file_starts_empty(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json")
    s = StateStore(p)
    assert s.active_game() is None
    assert s.history() == []
    p.write_text(json.dumps({"game": 5, "history": "x"}))
    s = StateStore(p)
    assert s.active_game() is None
    assert s.history() == []


def test_invalid_utf8_starts_empty(tmp_path):
    p = tmp_path / "state.json"
    p.write_bytes(b"\xff\xfe")
    s = StateStore(p)
    assert s.active_game() is None
    assert s.history() == []


def test_clear_game_and_history_copy(tmp_path):
    s = StateStore(tmp_path / "state.json")
    s.set_game("a")
    s.append("q", "a")
    s.history().clear()
    assert len(s.history()) == 1
    s.clear_game()
    assert s.active_game() is None and s.history() == []
    assert StateStore(tmp_path / "state.json").active_game() is None
