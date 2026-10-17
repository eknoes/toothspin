import asyncio
import os

import pytest

from toothspin.audio_stack import AudioStack


def test_refuses_a_runtime_folder_others_can_reach(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o777)
    os.chmod(runtime, 0o777)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    with pytest.raises(RuntimeError, match="private"):
        asyncio.run(AudioStack().start())


def test_refuses_a_linked_runtime_folder(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    (tmp_path / "runtime").symlink_to(target)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    with pytest.raises(RuntimeError, match="private"):
        asyncio.run(AudioStack().start())
