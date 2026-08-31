# -*- coding: utf-8 -*-
"""Приёмочный тест (независимый tester, RED-до-реализации): старт перестаёт шуметь.

Критерий приёмки (дан планом, план и implementation мне не показаны):

    «WARNING-константы старта перестают повторяться. `Failed to set priority` —
    не чаще одного раза за процесс и уровнем INFO. `ready via liveness-fallback`
    — INFO; WARNING только если подряд больше порога N. Обе точки — в
    process_manager_process.py.»

Расхождение со сверенным местом (называю прямо, «спека может врать»): грепом
по всему дереву `ready via liveness-fallback` НАЙДЕНА ровно в
``process_manager_module/process/process_manager_process.py``
(``_wait_processes_ready``, строка ~3901) — совпадает. А вот
`Failed to set priority` живёт в СОСЕДНЕМ файле
``process_manager_module/core/process_priority.py`` (``ProcessPriority.set_priority``)
— другой класс, тот же пакет. Тестирую обе точки по факту нахождения, а не по
заявленному пути.

Что уже есть СЕГОДНЯ (до реализации, сверено чтением обоих файлов):

* ``ProcessPriority.set_priority`` уже дедуплицирует «Failed to set priority» —
  но ПЕРМАНЕНТНО по имени приоритета (``_priority_warn_reasons: set[str]``,
  не окно по времени) и уровнем **WARNING** на первый отказ (не INFO — это и
  есть точка расхождения с критерием, тест на неё ниже КРАСНЫЙ).
* ``_wait_processes_ready`` при фолбэке зовёт ``self._log_warning(...)``
  БЕЗУСЛОВНО на КАЖДОЕ имя процесса, попавшее в фолбэк, — ни счётчика подряд
  идущих случаев, ни понижения до INFO нет вовсе.

Порог N для эскалации liveness-fallback в критерии не назван числом — беру
N=3 как литерал СВОЕГО теста (не вычисляю из кода) и называю это явным
допущением в отчёте тестера.
"""

from __future__ import annotations

from ..core.process_priority import ProcessPriority


class _RecordingLogger:
    """Логгер-счётчик уровней — независимая копия паттерна из test_process_priority.py."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.infos: list[str] = []
        self.debugs: list[str] = []

    def _log_warning(self, msg, **kw):
        self.warnings.append(msg)

    def _log_info(self, msg, **kw):
        self.infos.append(msg)

    def _log_debug(self, msg, **kw):
        self.debugs.append(msg)


class _FailingPlatform:
    def apply_priority(self, process, priority_name) -> bool:
        return False


class _FakeProc:
    def __init__(self, name: str) -> None:
        self.name = name


class TestFailedToSetPriorityIsInfoNotWarning:
    """Критерий 5а: «Failed to set priority» — уровень INFO, не WARNING."""

    def test_first_failure_voices_at_info_level(self) -> None:
        logger = _RecordingLogger()
        priority = ProcessPriority(logger=logger, platform_adapter=_FailingPlatform())

        ok = priority.set_priority(_FakeProc("proc-1"), "high")

        assert ok is False
        assert not logger.warnings, (
            f"первый отказ установки приоритета обязан идти уровнем INFO, а не WARNING; "
            f"получено WARNING: {logger.warnings!r}"
        )
        assert any("Failed to set priority" in m for m in logger.infos), (
            f"ожидалась ровно одна INFO-запись 'Failed to set priority ...', получено infos={logger.infos!r}"
        )

    def test_repeated_failures_same_process_voice_at_most_once(self) -> None:
        """«не чаще одного раза за процесс» — 5 попыток ОДНОГО и того же процесса."""
        logger = _RecordingLogger()
        priority = ProcessPriority(logger=logger, platform_adapter=_FailingPlatform())
        proc = _FakeProc("proc-1")

        for _ in range(5):
            priority.set_priority(proc, "high")

        total_voices_about_this_process = sum(
            1 for m in (logger.infos + logger.warnings) if "proc-1" in m and "Failed to set priority" in m
        )
        assert total_voices_about_this_process <= 1, (
            f"5 повторных отказов ОДНОГО процесса обязаны дать не больше одного голоса "
            f"про этот процесс, получено {total_voices_about_this_process}"
        )


class TestLivenessFallbackDowngradesToInfo:
    """Критерий 5б: «ready via liveness-fallback» — INFO, WARNING только после порога N подряд."""

    #: Собственный литерал теста — критерий не называет число, допущение тестера.
    _ASSUMED_THRESHOLD_N = 3

    def _make_pm_stub(self):
        """Минимальный ProcessManagerProcess-подобный объект без боевого __init__.

        Копирую фикстуру ``make_pm`` из conftest.py БЫЛО БЫ надёжнее, но она
        целиком настроена под ``apply_topology``/``TopologyManager`` — здесь
        нужен только ``_wait_processes_ready`` и его прямые зависимости
        (``_process_registry``, ``_log_info``/``_log_warning``). Беру реальный
        класс и обхожу ``__init__`` тем же приёмом, что и conftest.make_pm,
        чтобы не тянуть боевую инициализацию процесса.
        """
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

    def test_single_liveness_fallback_voices_at_info(self) -> None:
        pm, MockProcess = self._make_pm_stub()
        pm._process_registry._processes["n1"] = MockProcess("n1", alive=True)
        # без ready_event → фолбэк по liveness на дедлайне

        ready = pm._wait_processes_ready(["n1"], timeout_s=0.05, reason="switch")

        assert ready == {"n1": True}
        assert not pm._log_warning.called, (
            f"единичный фолбэк обязан идти INFO, а не WARNING; вызовы WARNING: {pm._log_warning.call_args_list!r}"
        )
        assert pm._log_info.called and any(
            "liveness-fallback" in str(call.args[0] if call.args else "") for call in pm._log_info.call_args_list
        ), "ожидалась INFO-запись про liveness-fallback, её нет среди вызовов _log_info"

    def test_fallback_stays_at_info_below_threshold(self) -> None:
        """Ниже порога N подряд идущих фолбэков — WARNING НЕ звучит вовсе.

        Без этой пары «эскалация после N» неотличима от «WARNING звучит всегда»
        (текущее поведение до реализации) — единственный способ отличить их
        друг от друга и есть проверка «до порога тихо».
        """
        pm, MockProcess = self._make_pm_stub()

        n_calls = self._ASSUMED_THRESHOLD_N - 1
        for i in range(n_calls):
            name = f"n{i}"
            pm._process_registry._processes[name] = MockProcess(name, alive=True)
            pm._wait_processes_ready([name], timeout_s=0.05, reason="switch")

        assert not pm._log_warning.called, (
            f"{n_calls} подряд идущих фолбэков — это МЕНЬШЕ порога N="
            f"{self._ASSUMED_THRESHOLD_N}, WARNING обязан молчать; вызовы: "
            f"{pm._log_warning.call_args_list!r}"
        )

    def test_fallback_escalates_to_warning_after_threshold_in_a_row(self) -> None:
        """Больше N подряд идущих фолбэков (по разным волнам wait) → WARNING."""
        pm, MockProcess = self._make_pm_stub()

        n_calls = self._ASSUMED_THRESHOLD_N + 2
        for i in range(n_calls):
            name = f"n{i}"
            pm._process_registry._processes[name] = MockProcess(name, alive=True)
            pm._wait_processes_ready([name], timeout_s=0.05, reason="switch")

        assert pm._log_warning.called, (
            f"после {n_calls} подряд идущих фолбэков (порог теста N="
            f"{self._ASSUMED_THRESHOLD_N}) ожидалась хотя бы одна эскалация до WARNING, "
            f"но WARNING не вызывался ни разу"
        )
