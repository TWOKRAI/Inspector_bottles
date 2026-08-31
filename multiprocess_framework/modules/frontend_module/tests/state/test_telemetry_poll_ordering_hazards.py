# -*- coding: utf-8 -*-
"""Опасности ПРОВОДКИ сторожа порядка push/poll — авторский набор S-1 (нога B).

Правило отбраковки и его границы живут в ядре и там же испытаны
(``telemetry_readmodel_module/tests/test_write_seq_ordering_hazards.py``). Здесь —
проводка: кто снимает номер, где он лежит между отправкой и ответом, что едет во
влив, и что происходит с номером, когда запись о полёте не дожила до ответа.

Что каждый тест сторожит, если сформулировать ДО прогона:

* **Номер снимается в момент ОТПРАВКИ, а не в момент ответа.** Сними его в
  ``_on_result`` — и он всегда был бы «после всех push'ов», то есть сторож
  пропускал бы ВСЁ, оставаясь при этом зелёным на любом тесте, который не
  разводит два момента во времени. Ровно тот класс, который приёмка увидеть не
  может: наблюдаемый эффект совпал бы с «сторожа нет».
* **Номер переживает оборот запроса вместе с записью о полёте.** Он лежит в
  ``_in_flight`` рядом со штампом времени, а не в замыкании: запись о полёте —
  единственное, что уже привязано к цели и переживает оборот.
* **Ответ на выселенную запись судится консервативно.** TTL снял запись — номер
  отправки потерян. Применять такой ответ «как свежий» значило бы отдать самый
  старый из возможных ответов без всякой проверки.
* **Счётчик расхождения считает ПУТИ, а не ответы.** Один ответ несёт несколько
  путей и терять может часть; счётчик по ответам показал бы «1» там, где
  разошлись три листа из пяти, и разница ушла бы в тишину.
* **Отброшенный путь не идёт в батч ``updated``.** Иначе виджет получал бы
  уведомление об изменении, которого не было, и перечитывал значение, которое
  уже показывает.
* **Поток у сторожа один, и это проверяемо.** ``write_seq`` читает поллер
  (``_tick``, QTimer), пишет его read-model (``on_state_delta``) — оба в main
  thread Qt. Лока нет намеренно; тест фиксирует ПОСЫЛКУ (обе дороги идут одним
  потоком), потому что именно посылка, а не сам лок, сломается первой, если
  влив когда-нибудь переедет в исполнителя.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from multiprocess_framework.modules.frontend_module.state.telemetry_poller import (
    TelemetryPoller,
)
from multiprocess_framework.modules.frontend_module.state.telemetry_view_model import (
    TelemetryViewModel,
)

PATH = "processes.proc_a.state.probe_level"


def _delta(path: str, value: Any, deleted: bool = False) -> dict:
    return {"data_type": "state_delta", "path": path, "value": value, "deleted": deleted}


def _levels_response(levels: dict) -> dict:
    return {"success": True, "result": {"levels": levels}}


class DeferredSubmit:
    """Исполнитель-«держатель»: работа не стартует, пока её не отпустят.

    Нужен, чтобы РАЗВЕСТИ во времени отправку запроса и приход ответа — без
    этого разведения ни один тест сторожа порядка ничего не судит.
    """

    def __init__(self) -> None:
        self.pending: list[tuple] = []

    def __call__(self, fn, on_result) -> None:
        self.pending.append((fn, on_result))

    def release_all(self) -> None:
        items, self.pending = self.pending, []
        for fn, on_result in items:
            on_result(fn())


# --------------------------------------------------------------------------- #
# Счётчик расхождения: пути, а не ответы
# --------------------------------------------------------------------------- #
class TestTheDivergenceCounterCountsPaths:
    def test_one_response_losing_three_of_five_paths_counts_three(self, qtbot) -> None:
        vm = TelemetryViewModel()
        seq = vm.write_seq
        stale = [f"processes.cam.state.m{i}" for i in range(3)]
        fresh = [f"processes.cam.state.ok{i}" for i in range(2)]
        for path in stale:
            vm.on_state_delta(_delta(path, None))

        values = {path: 1.0 for path in stale + fresh}
        vm.ingest_poll_snapshot(values, requested_at_seq=seq)

        assert vm.poll_values_dropped_stale == 3, (
            f"счётчик считает ОТВЕТЫ, а не ПУТИ: отброшено 3 из 5, счётчик показывает {vm.poll_values_dropped_stale}"
        )
        for path in fresh:
            assert vm.get(path) == pytest.approx(1.0), f"свежий путь {path} не влился"

    def test_a_fully_fresh_response_leaves_the_counter_at_zero(self, qtbot) -> None:
        """Обратная сторона: обычная работа счётчик не капает.

        Без этого утверждения счётчик, растущий на КАЖДОМ ответе, выглядел бы
        исправным — и «сторож режет всё» было бы неотличимо от «всё сходится».
        """
        vm = TelemetryViewModel()
        for _ in range(5):
            seq = vm.write_seq
            vm.ingest_poll_snapshot({PATH: 1.0}, requested_at_seq=seq)
        assert vm.poll_values_dropped_stale == 0, (
            f"счётчик расхождения растёт на исправной работе: {vm.poll_values_dropped_stale}"
        )

    def test_an_empty_response_touches_nothing(self, qtbot) -> None:
        vm = TelemetryViewModel()
        vm.ingest_poll_snapshot({}, requested_at_seq=vm.write_seq)
        assert vm.poll_values_dropped_stale == 0
        assert vm.write_seq == 0


# --------------------------------------------------------------------------- #
# Батч `updated` — только применённые пути
# --------------------------------------------------------------------------- #
class TestDroppedPathsDoNotReachTheWidgets:
    def test_a_fully_stale_response_emits_no_batch(self, qtbot) -> None:
        vm = TelemetryViewModel()
        seq = vm.write_seq
        vm.on_state_delta(_delta(PATH, None))
        qtbot.wait(30)  # дать уйти батчу самого push'а

        batches: list[list] = []
        vm.updated.connect(batches.append)
        vm.ingest_poll_snapshot({PATH: 42.0}, requested_at_seq=seq)
        qtbot.wait(50)

        assert batches == [], (
            f"отброшенный путь уехал в батч обновления виджетов: {batches!r} — виджет пойдёт "
            "перечитывать значение, которое уже показывает"
        )

    def test_a_partially_stale_response_emits_only_the_applied_paths(self, qtbot) -> None:
        vm = TelemetryViewModel()
        seq = vm.write_seq
        vm.on_state_delta(_delta(PATH, None))
        qtbot.wait(30)

        batches: list[list] = []
        vm.updated.connect(batches.append)
        vm.ingest_poll_snapshot({PATH: 42.0, "processes.proc_a.state.fps": 7.0}, requested_at_seq=seq)
        qtbot.wait(50)

        assert len(batches) == 1, f"ожидали ровно один батч, получили {batches!r}"
        assert [p for p, _v in batches[0]] == ["processes.proc_a.state.fps"], batches[0]


# --------------------------------------------------------------------------- #
# Проводка поллера: где живёт номер отправки
# --------------------------------------------------------------------------- #
class TestThePollerCarriesTheSendTimeSeq:
    def test_a_push_during_the_flight_makes_the_response_stale(self, qtbot) -> None:
        """Боевой сценарий целиком: push прилетает, ПОКА ответ опроса летит.

        Это тот самый замер ревью (оборот 7.5–10 с): ``t2 push -> None``,
        ``t3 poll -> 12.5``. Здесь оборот сжат до «отпустили держатель», но
        порядок событий тот же.
        """
        submit = DeferredSubmit()
        vm = TelemetryViewModel()
        poller = TelemetryPoller(
            poll_fn=lambda name: _levels_response({"state.probe_level": 12.5}),
            submit=submit,
            view_model=vm,
            interval_sec=0.02,
            targets=("proc_a",),
        )
        try:
            poller.set_active(True)
            assert poller.polls_started >= 1, "предпосылка: запрос отправлен"

            vm.on_state_delta(_delta(PATH, None))  # плагин остановлен, пока ответ летел
            submit.release_all()

            assert vm.get(PATH) is None, (
                f"ответ опроса, вылетевший ДО снятия уровня, воскресил мёртвое число: {vm.get(PATH)!r}"
            )
            assert vm.poll_values_dropped_stale == 1, vm.poll_values_dropped_stale
        finally:
            poller.stop()

    def test_without_a_push_in_flight_the_response_is_applied(self, qtbot) -> None:
        """Контроль к предыдущему: сторож не глушит нормальный опрос.

        Без него «сторож работает» было бы неотличимо от «сторож режет всё».
        """
        submit = DeferredSubmit()
        vm = TelemetryViewModel()
        poller = TelemetryPoller(
            poll_fn=lambda name: _levels_response({"state.probe_level": 12.5}),
            submit=submit,
            view_model=vm,
            interval_sec=0.02,
            targets=("proc_a",),
        )
        try:
            poller.set_active(True)
            submit.release_all()
            assert vm.get(PATH) == pytest.approx(12.5), f"обычный ответ опроса не доехал: {vm.get(PATH)!r}"
            assert vm.poll_values_dropped_stale == 0
        finally:
            poller.stop()

    def test_a_push_BEFORE_the_request_does_not_make_it_stale(self, qtbot) -> None:
        """Номер снимается при ОТПРАВКЕ: всё, что было раньше, ответу не мешает.

        Сними поллер номер в момент ОТВЕТА — этот тест остался бы зелёным, а
        предыдущий «push в полёте» стал бы красным. Пара нужна целиком.
        """
        submit = DeferredSubmit()
        vm = TelemetryViewModel()
        vm.on_state_delta(_delta(PATH, None))  # push ДО отправки запроса
        poller = TelemetryPoller(
            poll_fn=lambda name: _levels_response({"state.probe_level": 12.5}),
            submit=submit,
            view_model=vm,
            interval_sec=0.02,
            targets=("proc_a",),
        )
        try:
            poller.set_active(True)
            submit.release_all()
            assert vm.get(PATH) == pytest.approx(12.5), (
                "опрос, отправленный ПОСЛЕ push'а, обязан победить — иначе поллер снимает "
                f"номер не в момент отправки; получили {vm.get(PATH)!r}"
            )
        finally:
            poller.stop()

    def test_the_flight_record_keeps_both_the_stamp_and_the_seq(self, qtbot) -> None:
        """Запись о полёте несёт ПАРУ; TTL по-прежнему считает по штампу времени.

        Форма записи изменилась — значит выселение по дедлайну обязано быть
        перепроверено прямо здесь, а не «наверное, не сломалось».
        """
        submit = DeferredSubmit()
        vm = TelemetryViewModel()
        poller = TelemetryPoller(
            poll_fn=lambda name: _levels_response({"state.probe_level": 1.0}),
            submit=submit,
            view_model=vm,
            interval_sec=0.02,
            targets=("proc_a",),
            flight_ttl_sec=0.05,
        )
        try:
            poller.set_active(True)
            record = poller._in_flight.get("proc_a")
            assert record is not None and len(record) == 2, f"запись о полёте: {record!r}"
            sent_at, seq = record
            assert isinstance(sent_at, float) and isinstance(seq, int), record
            assert seq == 0, f"номер снят не в момент отправки: {seq}"

            # TTL обязан по-прежнему выселять по ПЕРВОМУ элементу пары.
            deadline = time.monotonic() + 3.0
            while poller.polls_expired == 0 and time.monotonic() < deadline:
                qtbot.wait(20)
            assert poller.polls_expired >= 1, "выселение по дедлайну сломалось вместе со сменой формы записи о полёте"
        finally:
            poller.stop()

    def test_a_response_to_an_evicted_flight_is_judged_conservatively(self, qtbot) -> None:
        """Запись выселена → номер отправки потерян → судим по худшему.

        Такой ответ старше TTL по построению. Применять его «как свежий» значило
        бы пропускать мимо сторожа ровно самые старые ответы — то есть чинить
        механизм так, чтобы он не работал в своём главном случае.
        """
        submit = DeferredSubmit()
        vm = TelemetryViewModel()
        poller = TelemetryPoller(
            poll_fn=lambda name: _levels_response({"state.probe_level": 12.5, "state.fps": 3.0}),
            submit=submit,
            view_model=vm,
            interval_sec=0.02,
            targets=("proc_a",),
            flight_ttl_sec=0.05,
        )
        try:
            poller.set_active(True)
            deadline = time.monotonic() + 3.0
            while poller.polls_expired == 0 and time.monotonic() < deadline:
                qtbot.wait(20)
            assert poller.polls_expired >= 1, "предпосылка: запись о полёте выселена"

            vm.on_state_delta(_delta(PATH, None))  # push по ОДНОМУ из путей ответа
            submit.release_all()

            assert vm.get(PATH) is None, f"ответ выселенного полёта воскресил снятое значение: {vm.get(PATH)!r}"
            assert vm.get("processes.proc_a.state.fps") == pytest.approx(3.0), (
                "путь, которого push не касался вовсе, обязан влиться даже из выселенного ответа"
            )
        finally:
            poller.stop()


# --------------------------------------------------------------------------- #
# Поток: почему лока нет
# --------------------------------------------------------------------------- #
def test_both_sides_of_the_guard_run_in_the_owner_thread(qtbot) -> None:
    """ПОСЫЛКА «лок не нужен» проверяется, а не декларируется.

    ``write_seq`` читает поллер в ``_tick`` (QTimer владельца), пишет read-model
    в ``on_state_delta`` (слот, вызываемый мостом). Обе дороги — поток владельца
    поллера. Тест фиксирует именно это: если влив или тик когда-нибудь переедут
    в исполнителя, посылка «лока не нужно» перестанет держаться, и красным
    станет ЭТО утверждение, а не гонка в проде через полгода.
    """
    seen: dict[str, int] = {}
    owner_thread = threading.get_ident()

    class _WatchingViewModel(TelemetryViewModel):
        @property
        def write_seq(self) -> int:  # type: ignore[override]
            seen["read"] = threading.get_ident()
            return super().write_seq

        def ingest_poll_snapshot(self, values, *, requested_at_seq: int) -> None:  # type: ignore[override]
            seen["ingest"] = threading.get_ident()
            super().ingest_poll_snapshot(values, requested_at_seq=requested_at_seq)

    submit = DeferredSubmit()
    vm = _WatchingViewModel()
    poller = TelemetryPoller(
        poll_fn=lambda name: _levels_response({"state.probe_level": 1.0}),
        submit=submit,
        view_model=vm,
        interval_sec=0.02,
        targets=("proc_a",),
    )
    try:
        poller.set_active(True)
        submit.release_all()
        assert seen.get("read") == owner_thread, (
            f"write_seq прочитан из чужого потока: {seen.get('read')} против {owner_thread} — "
            "посылка «лок не нужен» больше не держится"
        )
        assert seen.get("ingest") == owner_thread, (
            f"влив опроса выполнен из чужого потока: {seen.get('ingest')} против {owner_thread}"
        )
    finally:
        poller.stop()


def test_the_view_model_write_seq_is_a_delegate_not_a_copy(qtbot) -> None:
    """Второй счётчик рядом с ядром разошёлся бы с ним молча."""
    vm = TelemetryViewModel()
    vm.on_state_delta(_delta(PATH, 1.0))
    assert vm.write_seq == vm._model.write_seq, (
        f"view-model завела свою копию счётчика: {vm.write_seq} против {vm._model.write_seq}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
