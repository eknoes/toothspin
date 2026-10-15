from toothspin import build_info


def test_commit_is_shortened_and_keeps_dirty(monkeypatch) -> None:
    monkeypatch.setenv("TOOTHSPIN_COMMIT", "0c0be64a1b2c3d4e5f60718293a4b5c6d7e8f901")
    assert build_info()["commit"] == "0c0be64"
    monkeypatch.setenv("TOOTHSPIN_COMMIT", "0c0be64-dirty")
    assert build_info()["commit"] == "0c0be64-dirty"
    monkeypatch.delenv("TOOTHSPIN_COMMIT")
    assert build_info()["commit"] is None
    assert build_info()["version"]
