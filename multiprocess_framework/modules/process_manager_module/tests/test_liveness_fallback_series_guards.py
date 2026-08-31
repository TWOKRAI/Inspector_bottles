# -*- coding: utf-8 -*-
"""Сторож major 5 ревью Task 1.4 — штатная готовность РВЁТ серию фолбэков.

Находка, воспроизведённая ревью: заплатка
``self._voices().reset_repeat(self._LIVENESS_FALLBACK_KEY)`` → ``pass`` в
``process_manager_process.py`` оставляла **349 passed, ноль красных**. Это
единственное место, где серия прерывается, и комментарий над ним прямо
утверждает, что без него «подряд» молча превращается в «всего», — утверждение
было, воспроизведения и сторожа не было.

Почему это не косметика. Порог эскалации берётся один раз — накопленным за
жизнь процесса шумом, — и больше никогда не опускается: WARNING про
liveness-fallback снова звучит ВСЕГДА, только с задержкой, то есть ровно тот
дефект (m2, «список WARNING-констант бута»), ради которого задача и делалась.

Харнесс — тот же, что у приёмочного ``test_startup_voices_windowed_acceptance``:
реальный ``ProcessManagerProcess`` с обойдённым ``__init__`` и моками реестра из
``conftest``. Проверяется боевой вход ``_wait_processes_ready``, а не
``note_repeat``/``reset_repeat`` напрямую: спрашивается ПРОВОДКА, а прямой вызов
доказывал бы механизм, у которого свои сторожа лежат в logger_module.
"""

from __future__ import annotations

import threading
from typing import Iterator

import pytest

from multiprocess_framework.modules.logger_module.core.windowed_voice import (
    escalate_after_repeats,
    reset_voices_policy,
)


@pytest.fixture(autouse=True)
def _isolated_policy() -> Iterator[None]:
    """Порог — процессная политика; без сброса его мог сдвинуть сосед по сессии."""
    reset_voices_policy()
    yield
    reset_voices_policy()


def _make_pm():
    """Реальный ``ProcessManagerProcess`` без боевого ``__init__``."""
    from unittest.mock import MagicMock, patch

    from ..process.process_manager_process import ProcessManagerProcess
    from .conftest import MockProcess, MockProcessRegistry

    with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
        pm = ProcessManagerProcess.__new__(ProcessManagerProcess)
    pm._process_registry = MockProcessRegistry()
    pm._log_info = MagicMock()
    pm._log_warning = MagicMock()
    pm._log_error = MagicMock()
    return pm, MockProcess


def _fallback_once(pm, MockProcess, name: str) -> None:
    """Одна волна ожидания, которая заканчивается фолбэком по liveness."""
    pm._process_registry._processes[name] = MockProcess(name, alive=True)
    pm._wait_processes_ready([name], timeout_s=0.05, reason="switch")


#: Хвост ЭСКАЛАЦИИ — по нему сторожа отличают громкий голос серии от соседних
#: WARNING того же метода. Считать ``_log_warning.called`` целиком нельзя:
#: волна с мёртвым процессом пишет свой WARNING («умер до готовности»), и тест
#: на четвёртой точке стал бы вакуумным — зелёным при любой реализации серии.
_ESCALATION_MARK = "не приходят системно"


def _escalations(pm) -> list:
    """Только голоса эскалации серии среди всех WARNING'ов метода."""
    return [
        call for call in pm._log_warning.call_args_list if _ESCALATION_MARK in str(call.args[0] if call.args else "")
    ]


def _ready_once(pm, MockProcess, name: str) -> None:
    """Одна волна ожидания, которая заканчивается ШТАТНОЙ готовностью по event."""
    event = threading.Event()
    event.set()
    pm._process_registry._processes[name] = MockProcess(name, alive=True)
    pm._process_registry._ready_events[name] = event
    pm._wait_processes_ready([name], timeout_s=0.05, reason="switch")


class TestANormalReadyBreaksTheSeries:
    """«Подряд» обязано означать подряд, а не «всего за жизнь процесса»."""

    def test_the_threshold_is_the_literal_this_test_assumes(self) -> None:
        """Якорь: порог — 3, «строго больше». Сменится дефолт — тесты ниже врут.

        Литерал отдельной строкой, а не выражением внутри соседей: иначе те
        согласились бы с любым порогом, включая бесконечный.
        """
        assert escalate_after_repeats() == 3

    def test_a_ready_event_resets_the_run_and_the_next_wave_stays_quiet(self) -> None:
        pm, MockProcess = _make_pm()

        for i in range(3):  # ровно порог: до эскалации не хватает одного
            _fallback_once(pm, MockProcess, f"a{i}")
        assert _escalations(pm) == [], (
            f"три фолбэка — это не «больше трёх», эскалация обязана молчать: {_escalations(pm)!r}"
        )

        _ready_once(pm, MockProcess, "healthy")  # ← серия прервана

        for i in range(3):
            _fallback_once(pm, MockProcess, f"b{i}")

        assert _escalations(pm) == [], (
            "штатная готовность не прервала серию: шесть фолбэков за жизнь процесса "
            "с перерывом посередине дали эскалацию, то есть «подряд» превратилось "
            f"во «всего». Голоса эскалации: {_escalations(pm)!r}"
        )

    def test_without_the_break_the_same_number_of_fallbacks_does_escalate(self) -> None:
        """Пара-контроль: тест выше не проходит просто потому, что WARNING мёртв.

        Те же шесть фолбэков БЕЗ штатной готовности между ними обязаны дать
        эскалацию. Без этой половины предыдущий тест был бы вакуумен —
        одинаково зелёный и у механизма, и у заглушки.
        """
        pm, MockProcess = _make_pm()

        for i in range(6):
            _fallback_once(pm, MockProcess, f"c{i}")

        assert len(_escalations(pm)) == 3, (
            f"шесть фолбэков ПОДРЯД при пороге 3 обязаны дать ровно три громких "
            f"(4-й, 5-й, 6-й), получено {len(_escalations(pm))}: {_escalations(pm)!r}"
        )

    def test_the_series_survives_a_wave_that_did_not_end_in_ready(self) -> None:
        """Третья точка: рвёт серию именно ГОТОВНОСТЬ, а не всякая волна.

        Мёртвый процесс закрывает ожидание отказом (``not-ready``) и через
        ``reset_repeat`` не проходит: если бы серию рвало любое завершение
        волны, порог не брался бы никогда — то есть эскалация была бы мёртвой
        ручкой.
        """
        pm, MockProcess = _make_pm()

        for i in range(3):
            _fallback_once(pm, MockProcess, f"d{i}")
        pm._process_registry._processes["dead"] = MockProcess("dead", alive=False)
        pm._wait_processes_ready(["dead"], timeout_s=0.05, reason="switch")
        _fallback_once(pm, MockProcess, "d3")

        assert len(_escalations(pm)) == 1, (
            f"четвёртый фолбэк подряд при пороге 3 обязан быть громким ровно один раз; "
            f"волна, закончившаяся смертью процесса, серию не рвёт. Получено: {_escalations(pm)!r}"
        )
