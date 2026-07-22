# -*- coding: utf-8 -*-
"""Тесты конкуренции ротации: два канала на ОДИН файл делят один rotating-хэндлер.

Находка живого прогона webcam_sketch (2026-07): в боевом конфиге ``messages.log``
намеренно пишут ДВА писателя — scope-канал ``messages_file`` и module-канал
``router_messages`` (единый лог сообщений). Раньше каждый канал создавал свой
``_SafeRotatingFileHandler`` → два fd на один файл. На Windows ``doRollover()``
закрывает СВОЙ stream, затем ``os.rename(messages.log -> .1)`` падает WinError 32,
пока ВТОРОЙ хэндлер держит fd → ротация не срабатывает никогда, файл растёт без
предела (645 МБ при лимите ~60 МБ).

Пара тестов (ON/OFF на ОДНОМ сценарии):
- ДО фикса (механизм двух отдельных хэндлеров) — rollover систематически падает
  (``_rollover_failures`` растёт, ``.1``-бэкап не появляется);
- ПОСЛЕ фикса (общий хэндлер на путь) — на том же сценарии ротация живая
  (``.1`` появляется, ``_rollover_failures == 0``).

Конкуренция fd на Windows кросс-платформенно эмулируется: ``os.rename`` базового
файла падает ``PermissionError``, пока файл держит открытым хоть один ЧУЖОЙ stream
(rotating-хэндлер к моменту rename СВОЙ stream уже закрыл — значит открытый stream
это второй fd, ровно та конкуренция, что убивает ротацию на Windows). Assert идёт
на ФАКТ провала (``_rollover_failures``), а не на конкретный errno.
"""

from __future__ import annotations

import logging
import os
import time

import pytest

from multiprocess_framework.modules.logger_module.channels import log_channel
from multiprocess_framework.modules.logger_module.channels.log_channel import (
    FileChannel,
    _SafeRotatingFileHandler,
    _handler_key,
    _reset_shared_handler_registry,
    acquire_shared_rotating_handler,
    release_shared_rotating_handler,
)
from multiprocess_framework.modules.logger_module.configs.logger_manager_config import (
    LoggerChannelSchema,
)


@pytest.fixture(autouse=True)
def _clean_handler_registry():
    """Не течь общими хэндлерами между тестами (fd-leak + переиспользование пути)."""
    _reset_shared_handler_registry()
    yield
    _reset_shared_handler_registry()


def _emulate_windows_rename_lock(monkeypatch, tracked_handlers, base_path) -> None:
    """Эмуляция Windows: rename базового файла падает, пока его держит ЧУЖОЙ stream.

    ``tracked_handlers`` — хэндлеры, чьи открытые stream'ы моделируют занятость fd.
    Rotating-хэндлер к моменту rename свой stream уже закрыл, поэтому любой ещё
    открытый stream на том же пути — это второй (конкурирующий) fd.
    """
    real_rename = os.rename
    key = _handler_key(base_path)

    def guarded_rename(src, dst, *args, **kwargs):
        if _handler_key(src) == key:
            others_open = sum(
                1
                for h in tracked_handlers
                if getattr(h, "stream", None) is not None and _handler_key(h.baseFilename) == key
            )
            if others_open:
                raise PermissionError("[WinError 32] эмуляция: файл занят другим хэндлером")
        return real_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "rename", guarded_rename)


def _emit_line(handler: _SafeRotatingFileHandler, text: str) -> None:
    record = logging.LogRecord(
        name="probe", level=logging.INFO, pathname="", lineno=0, msg=text, args=(), exc_info=None
    )
    handler.emit(record)


class TestRotationConcurrencyPair:
    """Пара ON/OFF: два отдельных хэндлера ломают ротацию, общий — нет."""

    def test_two_separate_handlers_rollover_fails(self, tmp_path, monkeypatch) -> None:
        """ДО фикса: два хэндлера на один файл → rollover систематически падает."""
        path = tmp_path / "messages.log"
        h1 = _SafeRotatingFileHandler(filename=str(path), maxBytes=4096, backupCount=5, encoding="utf-8")
        h2 = _SafeRotatingFileHandler(filename=str(path), maxBytes=4096, backupCount=5, encoding="utf-8")
        # Разные объекты, два fd на один путь — ровно пред-фиксное состояние.
        assert h1 is not h2

        _emulate_windows_rename_lock(monkeypatch, [h1, h2], path)

        # Наполняем файл выше лимита и заставляем h1 ротировать: rename не пройдёт,
        # пока h2 держит открытый stream на тот же файл.
        _emit_line(h1, "x" * 5000)
        h1.doRollover()

        assert h1._rollover_failures > 0, "rollover обязан падать при втором открытом fd"
        assert not (tmp_path / "messages.log.1").exists(), "битая ротация не должна создавать .1-бэкап"

        h1.close()
        h2.close()

    def test_shared_handler_rollover_succeeds(self, tmp_path, monkeypatch) -> None:
        """ПОСЛЕ фикса: два канала на один файл делят хэндлер → ротация живая."""
        path = tmp_path / "messages.log"
        cfg_a = LoggerChannelSchema(
            name="messages_file",
            type="file",
            enabled=True,
            file_path=str(path),
            max_size=4096,
            backup_count=5,
        )
        cfg_b = LoggerChannelSchema(
            name="module_router_messages",
            type="file",
            enabled=True,
            file_path=str(path),
            max_size=4096,
            backup_count=5,
        )
        ch_a = FileChannel(cfg_a)
        ch_b = FileChannel(cfg_b)
        # Суть фикса: оба канала на один файл делят ОДИН rotating-хэндлер (один fd).
        assert ch_a.handler is ch_b.handler

        # Тот же сценарий эмуляции блокировки, что и в пред-фиксном тесте:
        # tracked = единственный общий хэндлер. К моменту rename он свой stream
        # закрывает → чужих открытых fd нет → rename проходит.
        _emulate_windows_rename_lock(monkeypatch, [ch_a.handler], path)

        for i in range(200):
            ch_a.write({"module": "probe", "level": "INFO", "message": f"a-{i} " + "y" * 60, "timestamp": time.time()})
            ch_b.write({"module": "probe", "level": "INFO", "message": f"b-{i} " + "y" * 60, "timestamp": time.time()})

        assert ch_a.handler._rollover_failures == 0, "с общим хэндлером конкуренции fd нет — сбоев быть не должно"
        assert (tmp_path / "messages.log.1").exists(), "ротация обязана создать .1-бэкап"

        ch_a.close()
        ch_b.close()


class TestSharedHandlerRegistry:
    """Реестр общих хэндлеров: идентичность, refcount, расхождение параметров."""

    def test_same_path_returns_same_handler(self, tmp_path) -> None:
        path = tmp_path / "shared.log"
        h1, created1 = acquire_shared_rotating_handler(path, 4096, 5)
        h2, created2 = acquire_shared_rotating_handler(path, 4096, 5)
        assert h1 is h2
        assert created1 is True
        assert created2 is False
        release_shared_rotating_handler(h1)
        release_shared_rotating_handler(h2)

    def test_different_paths_return_different_handlers(self, tmp_path) -> None:
        h1, _ = acquire_shared_rotating_handler(tmp_path / "a.log", 4096, 5)
        h2, _ = acquire_shared_rotating_handler(tmp_path / "b.log", 4096, 5)
        assert h1 is not h2
        release_shared_rotating_handler(h1)
        release_shared_rotating_handler(h2)

    def test_refcount_closes_only_on_last_release(self, tmp_path) -> None:
        path = tmp_path / "refcount.log"
        h, _ = acquire_shared_rotating_handler(path, 4096, 5)
        acquire_shared_rotating_handler(path, 4096, 5)  # refcount = 2
        key = _handler_key(path)

        release_shared_rotating_handler(h)  # refcount = 1 — ещё жив
        assert key in log_channel._shared_handlers
        assert h.stream is not None

        release_shared_rotating_handler(h)  # refcount = 0 — закрыт и снят
        assert key not in log_channel._shared_handlers
        assert key not in log_channel._shared_handler_refs

    def test_param_mismatch_warns_and_keeps_first(self, tmp_path, caplog) -> None:
        path = tmp_path / "mismatch.log"
        h1, _ = acquire_shared_rotating_handler(path, 4096, 5)
        with caplog.at_level(logging.WARNING, logger=log_channel.__name__):
            h2, created = acquire_shared_rotating_handler(path, 8192, 3)  # другие параметры
        assert h2 is h1
        assert created is False
        # Побеждают параметры первого владельца.
        assert h1.maxBytes == 4096
        assert h1.backupCount == 5
        assert any("параметр" in r.getMessage().lower() for r in caplog.records)
        release_shared_rotating_handler(h1)
        release_shared_rotating_handler(h2)


class TestRealAssemblyNoCollision:
    """Реальная сборка LoggerManager: messages_file и router_messages делят хэндлер."""

    def test_messages_channels_share_one_handler(self, tmp_path) -> None:
        from multiprocess_framework.modules.logger_module.core.logger_core import LoggerCore

        mgr = LoggerCore(
            manager_name="LoggerManager",
            config={"log_directory": str(tmp_path), "enable_batching": False},
        )
        try:
            scope_ch = mgr._channel_registry.get("messages_file")
            module_ch = mgr._module_channels.get("router_messages")
            assert scope_ch is not None, "scope-канал messages_file должен существовать"
            assert module_ch is not None, "module-канал router_messages должен существовать"
            # Оба указывают на messages.log → должны делить ОДИН rotating-хэндлер.
            assert _handler_key(scope_ch.handler.baseFilename) == _handler_key(module_ch.handler.baseFilename), (
                "оба канала обязаны резолвиться в один и тот же файл"
            )
            assert scope_ch.handler is module_ch.handler, "коллизия пути обязана делить один хэндлер (один fd)"
        finally:
            mgr.shutdown()
