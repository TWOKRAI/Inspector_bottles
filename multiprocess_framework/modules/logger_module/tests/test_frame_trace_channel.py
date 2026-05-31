# -*- coding: utf-8 -*-
"""Тесты FrameTraceChannel — overwrite-снимок одного кадра (Option A).

Контракт: буферизует записи по seq_id, перезаписывает файл при смене кадра
(один write на кадр через постоянный хэндл). Записи без seq_id игнорируются.
"""

from __future__ import annotations

from pathlib import Path

from multiprocess_framework.modules.logger_module.channels.log_channel import FrameTraceChannel
from multiprocess_framework.modules.logger_module.configs.logger_manager_config import LoggerChannelSchema


def _channel(tmp_path: Path) -> FrameTraceChannel:
    cfg = LoggerChannelSchema(
        name="ft",
        type="frame_trace",
        enabled=True,
        file_path=str(tmp_path / "cam.log"),
        format="%(message)s",
    )
    return FrameTraceChannel(cfg)


def test_overwrite_on_new_seq(tmp_path: Path) -> None:
    """Файл перезаписывается завершённым кадром при смене seq_id."""
    ch = _channel(tmp_path)
    ch.write({"message": "a1", "extra": {"seq_id": 1}})
    ch.write({"message": "a2", "extra": {"seq_id": 1}})
    # кадр 2 стартовал → кадр 1 (завершён) записан
    ch.write({"message": "b1", "extra": {"seq_id": 2}})

    content = (tmp_path / "cam.log").read_text(encoding="utf-8")
    assert "seq=1" in content and "a1" in content and "a2" in content
    assert "b1" not in content  # кадр 2 ещё в буфере


def test_close_flushes_last_frame(tmp_path: Path) -> None:
    ch = _channel(tmp_path)
    ch.write({"message": "x1", "extra": {"seq_id": 7}})
    ch.close()
    content = (tmp_path / "cam.log").read_text(encoding="utf-8")
    assert "seq=7" in content and "x1" in content


def test_records_without_seq_ignored(tmp_path: Path) -> None:
    ch = _channel(tmp_path)
    res = ch.write({"message": "noise"})
    assert res["status"] == "skipped"


def test_shorter_frame_truncates_tail(tmp_path: Path) -> None:
    """Короткий новый кадр не оставляет хвост предыдущего (truncate)."""
    ch = _channel(tmp_path)
    # длинный кадр 1
    for i in range(5):
        ch.write({"message": f"long{i}", "extra": {"seq_id": 1}})
    ch.write({"message": "s", "extra": {"seq_id": 2}})  # flush кадра 1
    ch.write({"message": "short", "extra": {"seq_id": 3}})  # flush кадра 2 (короткий)
    content = (tmp_path / "cam.log").read_text(encoding="utf-8")
    assert "long4" not in content  # хвост длинного кадра обрезан
    assert "seq=2" in content and content.strip().endswith("s")
    ch.close()
