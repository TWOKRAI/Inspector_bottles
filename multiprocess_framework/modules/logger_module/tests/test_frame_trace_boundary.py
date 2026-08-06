# -*- coding: utf-8 -*-
"""Граница `frame_trace` с цепочкой процессоров — решение Ф7.5.

Путь трассы кадра идёт МИМО ``log()``, то есть мимо ``_run_processors``. Решение
принято половинчатым СОЗНАТЕЛЬНО, и обе половины сторожатся здесь:

* **редакция зовётся** — метод публичный и пишет на диск; гарантия ADR-LOG-006
  («маскировка безусловна») не должна держаться на привычках единственного
  сегодняшнего вызывающего;
* **сэмплинг не зовётся** — повтор одинаковой строки на соседних кадрах это
  норма жанра трассы, и дроссель выбросил бы ровно те кадры, ради сравнения
  которых её и включают.

Второе свойство проверяется парой «сэмплинг выключен / включён самым злым
профилем»: если однажды кто-то заведёт трассу в полную цепочку, тест станет
красным — и это будет разговор, а не тихая пропажа кадров.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.logger_module.core.log_types import LogLevel
from multiprocess_framework.modules.logger_module.core.logger_core import LoggerCore


class _TraceSpy:
    """Подменяет FrameTraceChannel: ловит то, что реально доехало до приёмника."""

    name = "frame_trace_spy"
    channel_type = "frame_trace"

    def __init__(self) -> None:
        self.written: List[Dict[str, Any]] = []

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        self.written.append(data)
        return {"status": "success", "channel": self.name}

    def close(self) -> None:
        pass


@pytest.fixture
def tracing_logger(monkeypatch, tmp_path: Path):
    """LoggerCore с включённой трассой и каналом-шпионом вместо файла."""

    def _make(**sampling: Any) -> tuple[LoggerCore, _TraceSpy]:
        config = {
            "app_name": "frame_trace_boundary",
            "enable_batching": False,
            "channels": {},
            "default_level": "DEBUG",
            "scopes": {"SYSTEM": {"channels": []}},
        }
        config.update(sampling)
        mgr = LoggerCore(manager_name="TraceLogger", config=config)
        mgr.initialize()
        spy = _TraceSpy()
        # Трасса включается переменной окружения; ставим и её, и готовый канал —
        # иначе ленивое создание полезет на диск и утащит тест в файловую систему.
        monkeypatch.setenv("INSPECTOR_FRAME_TRACE", "1")
        mgr._frame_trace_enabled = True
        mgr._frame_trace_channel = spy
        return mgr, spy

    return _make


class TestSamplingDoesNotTouchTheTrace:
    """Выбранная сторона решения: дроссель трассу НЕ трогает."""

    #: Профиль дросселя, который ДЕЙСТВИТЕЛЬНО достаёт до трассы. ``sampling_max_level``
    #: поднят до INFO намеренно: трасса пишется уровнем INFO, а дефолтный потолок
    #: дросселя — DEBUG. С дефолтом гарантию «сэмплинг не трогает трассу» держали БЫ
    #: два независимых предохранителя (обход цепочки И разница уровней), и тест не
    #: отличал бы их: инъекция «завести трассу в полную цепочку» оставалась зелёной
    #: (J-2, 0 красных вместо 1). Потолок INFO снимает второй предохранитель, и тест
    #: начинает сторожить именно обход.
    _ANGRY = {"sampling_first_n": 1, "sampling_every_mth": 10_000, "sampling_max_level": "INFO"}

    @pytest.mark.parametrize(
        "sampling",
        [
            {},  # сэмплер выключен (first_n=0) — базовая линия
            _ANGRY,
        ],
        ids=["сэмплинг выключен", "сэмплинг включён"],
    )
    def test_repeated_lines_all_reach_the_channel(self, tracing_logger, sampling):
        """Сто одинаковых строк на ста кадрах доезжают все — при любом профиле.

        Именно этот случай дроссель и душит на обычном пути (ключ level+message),
        и именно он для трассы законен: кадры сравнивают между собой.
        """
        mgr, spy = tracing_logger(**sampling)

        for seq in range(100):
            mgr.frame_trace("data camera_0 -> ['preproc']", seq)

        assert len(spy.written) == 100
        assert {w["extra"]["seq_id"] for w in spy.written} == set(range(100))

    def test_the_sampler_would_have_choked_the_same_lines_on_the_normal_path(self, tracing_logger):
        """Контроль допущения: тот же профиль на ШТАТНОМ пути душит те же строки.

        Без этой половины «сто из ста доехало» ничего не доказывает — сэмплер мог
        быть просто выключен, и тест выше был бы вакуумным. Профиль ТОТ ЖЕ, что у
        соседа (``_ANGRY``): разными профилями пара сравнивала бы разные вещи.
        """
        mgr, _spy = tracing_logger(**self._ANGRY)
        before = mgr.get_stats().get("records_sampled_out", 0)

        for _ in range(100):
            mgr.log("SYSTEM", LogLevel.DEBUG, "data camera_0 -> ['preproc']", "router")

        assert mgr.get_stats()["records_sampled_out"] - before > 0


class TestRedactionIsApplied:
    """Вторая сторона решения: маскировка на этом пути есть."""

    def test_secret_in_a_trace_line_is_masked(self, tracing_logger):
        mgr, spy = tracing_logger()

        mgr.frame_trace("command cam -> ['gui'] token=hunter2secret", 1)

        assert len(spy.written) == 1
        message = spy.written[0]["message"]
        assert "hunter2secret" not in message
        assert "***" in message

    def test_ordinary_line_passes_through_unchanged(self, tracing_logger):
        """Редакция не переписывает то, в чём секрета нет: трасса обязана
        оставаться сравнимой между кадрами байт-в-байт."""
        mgr, spy = tracing_logger()
        line = "data camera_0 -> ['preproc'] data_type=frame"

        mgr.frame_trace(line, 1)

        assert spy.written[0]["message"] == line

    def test_redaction_counter_sees_the_trace_path(self, tracing_logger):
        """Работу редактора на этом пути видно снаружи тем же счётчиком, что и на
        штатном, — иначе «маскируем» осталось бы заявлением."""
        mgr, _spy = tracing_logger()
        before = mgr._redactor.records_redacted

        mgr.frame_trace("token=hunter2secret", 1)

        assert mgr._redactor.records_redacted == before + 1


def test_trace_disabled_is_a_noop(tracing_logger, monkeypatch):
    """Выключенная трасса не зовёт ни канал, ни редактор — цена ровно ноль."""
    mgr, spy = tracing_logger()
    mgr._frame_trace_enabled = False
    before = mgr._redactor.records_redacted

    mgr.frame_trace("token=hunter2secret", 1)

    assert spy.written == []
    assert mgr._redactor.records_redacted == before
