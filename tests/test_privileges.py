import os

from toothspin import privileges


def test_nothing_to_do_when_not_root(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    monkeypatch.setattr(os, "setuid", lambda uid: (_ for _ in ()).throw(AssertionError))
    privileges.drop_root(tmp_path)


def test_hands_over_files_then_switches(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    (tmp_path / "devices" / "AA").mkdir(parents=True)
    (tmp_path / "devices" / "AA" / "identity.json").write_text("{}")
    calls: list[tuple] = []
    monkeypatch.setattr(os, "getuid", lambda: 0)
    monkeypatch.setattr(os, "lchown", lambda path, uid, gid: calls.append(("chown", path.name)))
    monkeypatch.setattr(os, "setgroups", lambda groups: calls.append(("setgroups", groups)))
    monkeypatch.setattr(os, "setgid", lambda gid: calls.append(("setgid",)))
    monkeypatch.setattr(os, "setuid", lambda uid: calls.append(("setuid",)))
    monkeypatch.setattr(privileges.ctypes, "CDLL", lambda *a, **k: type("C", (), {"prctl": staticmethod(lambda *a: 0)}))
    monkeypatch.setattr(privileges.pwd, "getpwnam", lambda name: type("P", (), {"pw_uid": 4242, "pw_gid": 4242, "pw_dir": "/home/toothspin"}))
    monkeypatch.setenv("HOME", "/root")
    privileges.drop_root(tmp_path)
    assert [c for c in calls if c[0] == "chown"] == [
        ("chown", tmp_path.name), ("chown", "devices"), ("chown", "AA"), ("chown", "identity.json"),
    ]
    # The uid goes last: after it, nothing may be changed any more.
    assert calls[-3:] == [("setgroups", []), ("setgid",), ("setuid",)]
    assert os.environ["HOME"] == "/home/toothspin"


def test_stays_root_with_a_warning_without_the_capabilities(tmp_path, monkeypatch, caplog) -> None:  # noqa: ANN001
    monkeypatch.setattr(os, "getuid", lambda: 0)
    monkeypatch.setattr(privileges.pwd, "getpwnam", lambda name: type("P", (), {"pw_uid": 4242, "pw_gid": 4242, "pw_dir": "/x"}))

    def denied(*args: object) -> None:
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(os, "lchown", denied)
    privileges.drop_root(tmp_path)
    assert "couldn't switch" in caplog.text
