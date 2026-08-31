# -*- coding: utf-8 -*-
"""Приёмочный тест (независимый tester, RED-до-реализации): базовый контракт log_windowed.

Критерий приёмки (дан планом, план и implementation мне не показаны):

    «log_windowed — базовый контракт. Первый вызов с новым ключом голосит
    немедленно. Последующие вызовы с тем же ключом внутри окна — молчат. По
    истечении окна следующий вызов голосит, и в его тексте есть число
    подавленных. Разные ключи не мешают друг другу.»

**Честно про самый слабый пункт этого файла.** У ``log_windowed`` дан только
СИГНАТУРА (``key, interval, level, msg, **ctx``) — ни модуля, ни того, КАК
он реально печатает запись (через ``self._log_*`` ObservableMixin, как
``RouterManager._report_send_error``, или через ``get_std_logger()``, как
``QueueRegistry``/``shared_resources_module`` — сверено ЖИВЫМ чтением обоих
образцов, и они используют РАЗНЫЕ каналы). Интерфейса (``interface.py``) для
этой задачи не существует — я не увидел от Manager/Developer ничего, куда
можно было бы посмотреть за контрактом.

Я развёл риск угадывания на ДВЕ независимые опоры:

1. Пытаюсь импортировать ``log_windowed`` из ТРЁХ архитектурно осмысленных
   адресов подряд (список ниже) — если механизм лежит НЕ там, тест упадёт
   ``ModuleNotFoundError`` по ПОСЛЕДНЕМУ адресу с явным списком опробованных
   путей, а не тихо мимо. Это осознанное отступление от «одна причина падения»
   — оправдано тем, что без него тест был бы бесполезен при верной реализации
   в ЛЮБОМ из трёх мест, а не только угаданном первым.
2. Если импорт удался — веду наблюдение ДВУМЯ независимыми путями:
   явным ``logger=`` (двойник с .info/.warning/...) на случай, если
   ``log_windowed`` принимает логгер явно, И через ``caplog`` (stdlib fallback
   ``get_std_logger`` — см. ``std_facade.py``: «резолв ленивый... фолбэк:
   запись уходит в обычный logging», и это уже рабочий паттерн теста в этом
   репозитории — ``shared_resources_module/tests/test_never_drop_loss_visibility.py``).
   Тест засчитывает ЛЮБОЙ канал, который реально принял записи.

Управление временем: ``time.monotonic`` подменяется ГЛОБАЛЬНО
(``monkeypatch.setattr(time, "monotonic", ...)``) — не на конкретном модуле,
раз модуль неизвестен заранее. Безопасно для синхронного однопоточного теста.
"""

from __future__ import annotations

import logging
import time

import pytest

_CANDIDATE_MODULES = (
    "multiprocess_framework.modules.logger_module.core.windowed_voice",
    "multiprocess_framework.modules.channel_routing_module.windowed_voice",
    "multiprocess_framework.modules.logger_module.windowed_voice",
)


def _import_log_windowed():
    errors = []
    for path in _CANDIDATE_MODULES:
        try:
            module = __import__(path, fromlist=["log_windowed"])
            return getattr(module, "log_windowed")
        except (ImportError, AttributeError) as exc:
            errors.append(f"{path}: {exc!r}")
    pytest.fail(
        "log_windowed не найден ни по одному из угаданных адресов "
        "(механизм не имеет interface.py, адрес не подтверждён никем):\n"
        + "\n".join(errors)
        + "\nПри реальной реализации в другом месте — поправить _CANDIDATE_MODULES."
    )


class _RecordingLogger:
    """Двойник на случай, если log_windowed принимает логгер явно (kwarg 'logger')."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []  # (level, message)

    def _record(self, level):
        def _fn(msg, *a, **kw):
            self.calls.append((level, msg % a if a else msg))

        return _fn

    def __getattr__(self, level):
        return self._record(level)


@pytest.fixture
def log_windowed():
    return _import_log_windowed()


def _voice(log_windowed_fn, logger_double, caplog, *, key, interval, level, msg, **ctx):
    """Позвать log_windowed и вернуть ОБЩЕЕ число голосов, увиденных ЛЮБЫМ каналом."""
    before_double = len(logger_double.calls)
    before_caplog = len(caplog.records)
    log_windowed_fn(key, interval, level, msg, logger=logger_double, **ctx)
    after_double = len(logger_double.calls) - before_double
    after_caplog = len(caplog.records) - before_caplog
    return max(after_double, after_caplog)  # какой канал реально сработал


class TestLogWindowedBaseContract:
    def test_first_call_with_new_key_voices_immediately(self, log_windowed, caplog):
        logger_double = _RecordingLogger()
        with caplog.at_level(logging.DEBUG):
            n = _voice(
                log_windowed,
                logger_double,
                caplog,
                key="k1",
                interval=10.0,
                level="warning",
                msg="первое событие",
            )
        assert n >= 1, "первый вызов с новым ключом обязан голосить немедленно"

    def test_second_call_within_window_is_silent(self, log_windowed, caplog, monkeypatch):
        logger_double = _RecordingLogger()
        clock = [100.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])

        with caplog.at_level(logging.DEBUG):
            _voice(log_windowed, logger_double, caplog, key="k2", interval=10.0, level="warning", msg="раз")
            clock[0] += 1.0  # внутри окна (10с)
            n2 = _voice(log_windowed, logger_double, caplog, key="k2", interval=10.0, level="warning", msg="два")

        assert n2 == 0, "второй вызов внутри окна обязан молчать"

    def test_call_after_window_voices_and_names_suppressed_count(self, log_windowed, caplog, monkeypatch):
        logger_double = _RecordingLogger()
        clock = [200.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])

        with caplog.at_level(logging.DEBUG):
            _voice(log_windowed, logger_double, caplog, key="k3", interval=5.0, level="warning", msg="раз")
            clock[0] += 0.5
            _voice(log_windowed, logger_double, caplog, key="k3", interval=5.0, level="warning", msg="два")  # подавлен
            clock[0] += 0.5
            _voice(log_windowed, logger_double, caplog, key="k3", interval=5.0, level="warning", msg="три")  # подавлен
            clock[0] += 10.0  # заведомо дальше окна
            before_double = len(logger_double.calls)
            before_caplog = len(caplog.records)
            log_windowed("k3", 5.0, "warning", "четыре", logger=logger_double)

        texts = [m for (_lvl, m) in logger_double.calls[before_double:]] + [
            r.getMessage() for r in caplog.records[before_caplog:]
        ]
        assert texts, "по истечении окна следующий вызов обязан голосить"
        assert any("2" in t for t in texts), (
            f"текст голоса после окна обязан называть число подавленных с прошлой "
            f"записи (2: 'два' и 'три'), получено: {texts!r}"
        )

    def test_different_keys_do_not_interfere(self, log_windowed, caplog, monkeypatch):
        logger_double = _RecordingLogger()
        clock = [300.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])

        with caplog.at_level(logging.DEBUG):
            n_a = _voice(log_windowed, logger_double, caplog, key="alpha", interval=10.0, level="info", msg="a1")
            n_b = _voice(log_windowed, logger_double, caplog, key="beta", interval=10.0, level="info", msg="b1")

        assert n_a >= 1 and n_b >= 1, (
            f"разные ключи обязаны голосить независимо (оба — первые для своего ключа), получено n_a={n_a}, n_b={n_b}"
        )
