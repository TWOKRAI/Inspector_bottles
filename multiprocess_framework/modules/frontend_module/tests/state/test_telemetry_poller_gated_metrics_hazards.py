# -*- coding: utf-8 -*-
"""Авторские hazard-тесты влива ``gated_metrics`` в TelemetryPoller (Task 4.2,
план observation-port). Дополняют ``test_telemetry_poller_hazards.py`` (Task 3.3),
не заменяют — это тесты на СВОЙ, новый лист ответа, добавленный поверх ``levels``.

Опасность, которую этот файл целиком и держит: ``_on_result`` раньше писал в
read-model только если ``levels`` был непустым (``if not levels: return`` до
правки). ``gated_metrics`` — независимая секция того же ответа, и у процесса
БЕЗ ``ProcessHeartbeat`` (``levels=None`` — легальный случай, ADR-PM-035)
каталог метрик всё равно может быть непустым (метрики объявлены, сенсоров нет).
Наивная правка «дописать gated_metrics туда же» легко наследует старый ранний
``return`` и молча теряет каталог ровно там, где он нужнее всего — у процесса,
который сам о себе больше ничего не расскажет.
"""

from __future__ import annotations

import time

import pytest

from multiprocess_framework.modules.frontend_module.state import TelemetryPoller, TelemetryViewModel


class ImmediateSubmit:
    """submit-двойник: исполняет работу синхронно (см. test_telemetry_poller_hazards.py)."""

    def __init__(self) -> None:
        self.submit_calls = 0

    def __call__(self, fn, on_result) -> None:
        self.submit_calls += 1
        on_result(fn())


def _response(*, levels=None, gated_metrics=None, success: bool = True) -> dict:
    """Тот же боевой конверт, что и у ``levels`` (router.request заворачивает
    результат команды ``introspect.telemetry``), плюс лист ``gated_metrics``."""
    return {
        "success": success,
        "result": {
            "success": success,
            "process": "proc_a",
            "snapshot_ts": 0.0,
            "levels": levels,
            "gated_metrics": gated_metrics,
        },
    }


def _wait_until(qtbot, predicate, deadline_sec: float = 3.0, step_ms: int = 20) -> None:
    deadline = time.monotonic() + deadline_sec
    while not predicate() and time.monotonic() < deadline:
        qtbot.wait(step_ms)


class TestGatedMetricsSurvivesAbsentLevels:
    def test_gated_metrics_is_ingested_even_when_levels_is_none(self, qtbot) -> None:
        """Процесс без ProcessHeartbeat (levels=None) — каталог метрик не
        должен утонуть в раннем ``return`` по пустым уровням."""
        vm = TelemetryViewModel()
        submit = ImmediateSubmit()
        poller = TelemetryPoller(
            poll_fn=lambda name: _response(levels=None, gated_metrics=["fps", "letter_confidence"]),
            submit=submit,
            view_model=vm,
            interval_sec=0.02,
            targets=("proc_a",),
        )
        poller.set_active(True)
        _wait_until(qtbot, lambda: poller.polls_completed >= 1)
        poller.stop()

        assert vm.get("processes.proc_a.telemetry.gated_metrics") == ["fps", "letter_confidence"]
        # И старый инвариант «levels=None пишет ноль" держится рядом.
        assert vm.get("processes.proc_a.state.fps") is None

    def test_gated_metrics_and_levels_land_in_one_flush(self, qtbot) -> None:
        """Когда оба листа непустые — ОДИН ответ даёт ОДИН батч ``updated``,
        а не два ingest-вызова подряд (коалесинг read-model не нарушен).

        **Ред. по находке З4 ревью Ф4.** Прежняя редакция считала батчи за окно
        ожидания при периоде поллера 20 мс и окне ``qtbot.wait(20)``, то есть
        мерила ВРЕМЯ, а не заявленное свойство. Воспроизведено: 20 мс → 2 батча,
        60 мс → 3, 140 мс → 7 — тест был зелёным по совпадению чисел.

        Здесь ответ РОВНО один по построению: ``ImmediateSubmit`` исполняет
        работу синхронно внутри ``set_active(True)`` (тот делает первый опрос
        немедленно), поллер сразу останавливается, и только потом даётся такт
        коалесинг-таймеру. Число ответов не выводится из тайминга — оно
        утверждается литералом рядом.
        """
        vm = TelemetryViewModel()
        batches: list[list] = []
        vm.updated.connect(batches.append)

        submit = ImmediateSubmit()
        poller = TelemetryPoller(
            poll_fn=lambda name: _response(levels={"state.fps": 21.3}, gated_metrics=["fps"]),
            submit=submit,
            view_model=vm,
            # Период заведомо длиннее окна коалесинга: второй опрос по таймеру
            # физически не успеет, даже не будь `stop()` ниже.
            interval_sec=30.0,
            targets=("proc_a",),
        )
        poller.set_active(True)
        assert poller.polls_completed == 1, (
            f"предпосылка теста: синхронный submit даёт РОВНО один ответ, получено {poller.polls_completed}"
        )
        poller.stop()
        qtbot.wait(20)  # дать коалесинг-таймеру (0 мс) сработать

        assert poller.polls_completed == 1, "после stop() прилетел ещё ответ — счёт батчей ниже не про один ответ"
        assert len(batches) == 1, f"один ответ дал {len(batches)} батчей updated вместо одного"
        paths = {path for path, _ in batches[0]}
        assert "processes.proc_a.state.fps" in paths
        assert "processes.proc_a.telemetry.gated_metrics" in paths

    def test_two_answers_give_two_batches(self, qtbot) -> None:
        """Пара-контроль к предыдущему: «один батч» — про ОДИН ответ, а не всегда.

        Без этой половины тест выше зелен и у read-model, которая склеивает
        любое число ответов в один батч, — то есть теряет обновления.
        """
        vm = TelemetryViewModel()
        batches: list[list] = []
        vm.updated.connect(batches.append)

        submit = ImmediateSubmit()
        poller = TelemetryPoller(
            poll_fn=lambda name: _response(levels={"state.fps": 21.3}, gated_metrics=["fps"]),
            submit=submit,
            view_model=vm,
            interval_sec=30.0,
            targets=("proc_a",),
        )
        poller.set_active(True)
        qtbot.wait(20)  # первый батч слит
        poller._tick()  # второй ответ — синхронно, тем же submit
        poller.stop()
        qtbot.wait(20)

        assert poller.polls_completed == 2, poller.polls_completed
        assert len(batches) == 2, f"два ответа дали {len(batches)} батчей вместо двух"


class TestMalformedGatedMetricsIsIgnored:
    @pytest.mark.parametrize(
        "gated_metrics",
        [None, "not-a-list", 42, {}, [], [None, 5, ""]],
        ids=["none", "string", "int", "dict", "empty-list", "only-invalid-entries"],
    )
    def test_degenerate_gated_metrics_writes_nothing_and_keeps_polling(self, qtbot, gated_metrics) -> None:
        vm = TelemetryViewModel()
        submit = ImmediateSubmit()
        poller = TelemetryPoller(
            poll_fn=lambda name: _response(levels=None, gated_metrics=gated_metrics),
            submit=submit,
            view_model=vm,
            interval_sec=0.02,
            targets=("proc_a",),
        )
        poller.set_active(True)
        _wait_until(qtbot, lambda: poller.polls_completed >= 3)
        poller.stop()

        assert poller.polls_completed >= 3, "опрос заглох на вырожденном gated_metrics"
        assert vm.get("processes.proc_a.telemetry.gated_metrics") is None

    def test_non_string_entries_are_filtered_but_valid_ones_survive(self, qtbot) -> None:
        vm = TelemetryViewModel()
        submit = ImmediateSubmit()
        poller = TelemetryPoller(
            poll_fn=lambda name: _response(levels=None, gated_metrics=[None, 5, "", "fps", "letter_confidence"]),
            submit=submit,
            view_model=vm,
            interval_sec=0.02,
            targets=("proc_a",),
        )
        poller.set_active(True)
        _wait_until(qtbot, lambda: poller.polls_completed >= 1)
        poller.stop()

        assert vm.get("processes.proc_a.telemetry.gated_metrics") == ["fps", "letter_confidence"]

    def test_failed_response_does_not_ingest_gated_metrics(self, qtbot) -> None:
        vm = TelemetryViewModel()
        submit = ImmediateSubmit()
        poller = TelemetryPoller(
            poll_fn=lambda name: _response(levels=None, gated_metrics=["fps"], success=False),
            submit=submit,
            view_model=vm,
            interval_sec=0.02,
            targets=("proc_a",),
        )
        poller.set_active(True)
        _wait_until(qtbot, lambda: poller.polls_completed >= 1)
        poller.stop()

        assert vm.get("processes.proc_a.telemetry.gated_metrics") is None
        assert poller.polls_failed >= 1
