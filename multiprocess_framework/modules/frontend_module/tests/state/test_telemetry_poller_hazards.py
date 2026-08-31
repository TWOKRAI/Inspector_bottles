# -*- coding: utf-8 -*-
"""Авторские hazard-тесты TelemetryPoller — опасности САМОГО механизма (Task 3.3).

Дополняют независимые приёмочные тесты (``test_telemetry_poller_acceptance.py``,
писались без чтения реализации), а не заменяют их. Здесь — то, что видно только
изнутри устройства: поллер тикает по таймеру, а отвечает асинхронно, поэтому у
него есть окно между «запрос ушёл» и «ответ пришёл», и в этом окне мир меняется.

Что именно может сломаться в ЭТОМ механизме:

* тик наступает, пока предыдущий ответ ещё летит (медленный backend) — очередь
  запросов к одному процессу растёт молча, IPC умножается;
* цель снимается за время полёта — чужие числа въезжают в снимок процесса,
  который уже не показан;
* владелец разрушается за время полёта — callback приходит в мёртвый C++-объект;
* влив опроса накрывает поддерево, где рядом лежат push-ключи ДРУГИХ
  публикаторов (долг K-8) — их можно затереть или обнулить, ничего не заметив;
* вырожденный ответ (``levels`` пустой / ``None`` / без поля) трактуется как
  «данные», и в снимок едет мусор;
* у воркера нет ``cycles`` (долг K-9) — это норма, а не «завис».

Блокирующих ожиданий здесь нет по устройству: submit-двойник ``DeferredSubmit``
складывает работу и НЕ исполняет её, пока тест сам не разрешит. Единственный
тест с настоящим фоновым потоком гонит его daemon'ом и join'ит с дедлайном —
висящий тест хуже отсутствующего.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from multiprocess_framework.modules.frontend_module.state import (
    TelemetryPoller,
    TelemetryViewModel,
)

# Восемь ПЛОСКИХ ключей ``processes.<p>.state.<имя>``, которых влив опроса
# трогать не должен (долг K-8, ADR-PM-035). Шесть из них — ``status``, ``pid``,
# ``error``, ``uptime``, ``paused``, ``frozen`` — пишут другие публикаторы push'ем,
# и опрос их не приносит вовсе.
#
# ``frame_count`` и ``drops`` стоят здесь ПО ДРУГОЙ ПРИЧИНЕ, и после Ф1 «порта
# наблюдений» причина стала сильнее прежней: опрос их ПРИНОСИТ, но по ДРУГОМУ
# адресу — ``state.plugins.<писатель>.<имя>``. Плоский адрес для них — чужой, и
# набор сторожит ровно это: вложенное значение не имеет права протечь на плоский
# путь. Прежний комментарий («их пишут другие публикаторы push'ем») был верен до
# задачи 3.5 и врал после неё.
_PUSH_ONLY_KEYS: dict[str, Any] = {
    "status": "running",
    "pid": 4242,
    "frame_count": 100500,
    "error": "",
    "uptime": 3600.0,
    "drops": 7,
    "paused": False,
    "frozen": False,
}


class DeferredSubmit:
    """submit-двойник: КОПИТ работу, исполняет только по команде теста.

    Моделирует медленный backend без единого sleep: между submit и доставкой
    результата проходит ровно столько тиков, сколько тест захочет.
    """

    def __init__(self) -> None:
        self.pending: list[tuple[Any, Any]] = []
        self.submit_calls = 0

    def __call__(self, fn, on_result) -> None:
        self.submit_calls += 1
        self.pending.append((fn, on_result))

    def release_all(self) -> int:
        """Исполнить всю накопленную работу (в текущем потоке) и вернуть счёт."""
        batch, self.pending = self.pending, []
        for fn, on_result in batch:
            on_result(fn())
        return len(batch)


class ImmediateSubmit:
    """submit-двойник: исполняет работу синхронно (ответ «мгновенный»)."""

    def __init__(self) -> None:
        self.submit_calls = 0

    def __call__(self, fn, on_result) -> None:
        self.submit_calls += 1
        on_result(fn())


def _levels_response(levels: Any, *, snapshot_ts: float = 0.0) -> dict:
    """Боевой конверт ответа: router.request оборачивает результат команды.

    Форма взята с реального пути (``RouterManager.reply_to_request`` кладёт
    ``{"success", "result": <ответ команды>}``, а команда ``introspect.telemetry``
    внутри несёт ``levels``/``snapshot_ts``), а не придумана.
    """
    return {
        "success": True,
        "result": {"success": True, "process": "proc_a", "snapshot_ts": snapshot_ts, "levels": levels},
    }


def _seed_push_keys(vm: TelemetryViewModel, process: str) -> None:
    """Заполнить read-model ключами, которые в проде приходят push'ем."""
    for key, value in _PUSH_ONLY_KEYS.items():
        vm.on_state_delta({"data_type": "state_delta", "path": f"processes.{process}.state.{key}", "value": value})


def _wait_until(qtbot, predicate, deadline_sec: float = 3.0, step_ms: int = 20) -> None:
    """Крутить event loop до predicate или до жёсткого дедлайна (не висит)."""
    deadline = time.monotonic() + deadline_sec
    while not predicate() and time.monotonic() < deadline:
        qtbot.wait(step_ms)


# --------------------------------------------------------------------------- #
#  H1 — наложение тиков                                                        #
# --------------------------------------------------------------------------- #


def test_tick_during_flight_does_not_queue_a_second_poll_for_same_target(qtbot) -> None:
    """Медленный ответ: тики продолжают идти, но второй запрос той же цели не уходит.

    Держит: страховку от размножения IPC. Опрос отдаёт УРОВЕНЬ — второй
    одновременный запрос к тому же процессу не добавит ни одного нового числа,
    зато при backend'е медленнее ``interval_sec`` очередь запросов росла бы
    линейно по времени и осталась бы невидимой (счётчик ``polls_started``
    рос бы, а ответы — нет).
    """
    submit = DeferredSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(
        poll_fn=lambda name: _levels_response({"state.fps": 1.0}),
        submit=submit,
        view_model=vm,
        interval_sec=0.02,
        targets=("proc_a",),
    )
    poller.set_active(True)

    # Много тиков подряд — ответ не отдаём ни на один.
    qtbot.wait(300)

    assert poller.polls_started == 1, (
        f"за ~15 тиков при незавершённом ответе ушло {poller.polls_started} запросов — наложение тиков размножает IPC"
    )
    assert len(submit.pending) == 1
    assert poller.polls_completed == 0

    # Ответ пришёл — следующий тик снова имеет право опрашивать.
    submit.release_all()
    assert poller.polls_completed == 1
    _wait_until(qtbot, lambda: poller.polls_started >= 2)
    poller.stop()
    assert poller.polls_started >= 2, "после завершения полёта опрос не возобновился"


def test_in_flight_guard_is_per_target_not_global(qtbot) -> None:
    """Полёт к одной цели не затыкает опрос остальных.

    Держит: границу страховки из предыдущего теста. Сделай её глобальной (один
    флаг «идёт опрос») — и один зависший процесс заморозил бы числа всех
    остальных; симптом («вся вкладка встала») увёл бы поиск не туда.
    """
    submit = DeferredSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(
        poll_fn=lambda name: _levels_response({"state.fps": 1.0}),
        submit=submit,
        view_model=vm,
        interval_sec=0.02,
        targets=("proc_a", "proc_b"),
    )
    poller.set_active(True)
    qtbot.wait(200)
    poller.stop()

    assert poller.polls_started == 2, (
        f"ожидали по одному незавершённому опросу на каждую из двух целей, получили {poller.polls_started}"
    )
    assert len(submit.pending) == 2


# --------------------------------------------------------------------------- #
#  H2 — цель снята за время полёта                                             #
# --------------------------------------------------------------------------- #


def test_result_for_target_removed_mid_flight_is_not_ingested(qtbot) -> None:
    """Ответ по снятой цели не вливается в read-model.

    Держит: чистоту снимка при переключении nav. Запрос к ``proc_a`` уже летит,
    пользователь переключается на ``proc_b``; если ответ всё-таки вольётся,
    виджет покажет числа процесса, который сейчас не показан, — и это будет
    выглядеть не как баг, а как «странные показания».
    """
    submit = DeferredSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(
        poll_fn=lambda name: _levels_response({"state.fps": 99.9}),
        submit=submit,
        view_model=vm,
        interval_sec=5.0,  # тик далеко: в тесте работает только первый опрос
        targets=("proc_a",),
    )
    poller.set_active(True)
    assert len(submit.pending) == 1, "немедленный первый опрос не ушёл"

    poller.set_targets(["proc_b"])  # цель снята, пока ответ летит
    submit.release_all()
    poller.stop()

    assert vm.get("processes.proc_a.state.fps") is None, (
        f"ответ снятой цели влился в снимок: fps={vm.get('processes.proc_a.state.fps')}"
    )
    assert poller.polls_completed == 1, "ответ должен считаться пришедшим, даже если отброшен"


# --------------------------------------------------------------------------- #
#  H3 — владелец разрушается за время полёта                                   #
# --------------------------------------------------------------------------- #


def test_late_result_after_stop_does_not_write_and_does_not_raise(qtbot) -> None:
    """stop() в полёте: поздний ответ не пишет в снимок и не поднимает исключение.

    Держит: тишину после закрытия вкладки. stop() зовётся при разрушении
    владельца, но работа уже у исполнителя — отменить её нечем, ответ придёт.
    Если он всё-таки запишется, «закрытая вкладка = ноль трафика» станет
    неправдой ровно на один тик.
    """
    submit = DeferredSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(
        poll_fn=lambda name: _levels_response({"state.fps": 42.0}),
        submit=submit,
        view_model=vm,
        interval_sec=5.0,
        targets=("proc_a",),
    )
    poller.set_active(True)
    assert len(submit.pending) == 1

    poller.stop()
    submit.release_all()  # не должно бросить

    assert vm.get("processes.proc_a.state.fps") is None, "поздний ответ записался после stop()"


def test_late_result_into_destroyed_view_model_is_swallowed(qtbot) -> None:
    """Приёмник разрушен за время полёта — влив не роняет callback.

    Держит: живучесть на закрытии окна. Read-model — QObject; его C++-часть
    может уйти раньше, чем прилетит ответ, и обращение к ней поднимает
    RuntimeError уже ВНУТРИ чужого callback'а (в main thread), где его никто
    не ждёт. Проверяем воспроизведением, а не рассуждением: явно удаляем
    C++-объект через sip/shiboken-делит и отпускаем ответ.
    """
    from PySide6.QtCore import QObject

    submit = DeferredSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(
        poll_fn=lambda name: _levels_response({"state.fps": 42.0}),
        submit=submit,
        view_model=vm,
        interval_sec=5.0,
        targets=("proc_a",),
    )
    poller.set_active(True)
    assert len(submit.pending) == 1

    # Разрушаем C++-часть приёмника, оставляя Python-обёртку живой — ровно то
    # состояние, в котором оказывается VM после deleteLater() владельца.
    QObject.deleteLater(vm)
    qtbot.wait(50)
    try:
        vm.objectName()
    except RuntimeError:
        pass  # C++-объект действительно ушёл — сценарий воспроизведён
    else:
        pytest.skip("Qt не удалил C++-объект VM — сценарий на этой сборке не воспроизводится")

    submit.release_all()  # не должно бросить наружу
    poller.stop()


# --------------------------------------------------------------------------- #
#  H4 — влив опроса не затирает push-ключи (долг K-8)                          #
# --------------------------------------------------------------------------- #


def test_poll_ingest_preserves_push_only_keys(qtbot) -> None:
    """Восемь push-ключей переживают влив снимка без изменений (K-8).

    Держит: самый вероятный дефект задачи. ``levels`` — это то, что собирает
    телеметрийный тик, а НЕ весь ``processes.<name>.state``: рядом в дереве
    лежат ``status``/``pid``/``frame_count``/``error``/``uptime``/``drops``/
    ``paused``/``frozen`` от других публикаторов. Любая реализация влива,
    работающая «поддеревом» (заменить ``processes.<name>``, очистить перед
    записью, слить с удалением отсутствующих) сотрёт их — и вкладка покажет
    прочерки в статусе живого процесса, хотя опрос «работает».
    """
    vm = TelemetryViewModel()
    _seed_push_keys(vm, "proc_a")

    submit = ImmediateSubmit()
    poller = TelemetryPoller(
        poll_fn=lambda name: _levels_response({"state": {"fps": 21.3, "latency_ms": 4.1}}),
        submit=submit,
        view_model=vm,
        interval_sec=0.02,
        targets=("proc_a",),
    )
    poller.set_active(True)
    _wait_until(qtbot, lambda: poller.polls_completed >= 3)
    poller.stop()

    assert poller.polls_completed >= 3, "не набралось трёх вливов"
    for key, expected in _PUSH_ONLY_KEYS.items():
        actual = vm.get(f"processes.proc_a.state.{key}")
        assert actual == expected, (
            f"push-ключ state.{key} испорчен вливом опроса: было {expected!r}, стало {actual!r} "
            "(долг K-8: опрос эти ключи не приносит и трогать их не должен)"
        )
    # И при этом опрошенное действительно доехало.
    assert vm.get("processes.proc_a.state.fps") == pytest.approx(21.3)


def test_poll_ingest_does_not_touch_other_processes(qtbot) -> None:
    """Влив по ``proc_a`` не задевает поддерево ``proc_b``.

    Держит: границу префикса. Пути строятся конкатенацией, и ошибка на один
    разделитель (``processes.proc_a`` + ``state.fps`` без точки, или префикс
    без имени процесса) свалила бы числа всех процессов в одну кучу — на
    одном процессе в тесте это невидимо.
    """
    vm = TelemetryViewModel()
    vm.on_state_delta({"data_type": "state_delta", "path": "processes.proc_b.state.fps", "value": 5.0})

    submit = ImmediateSubmit()
    poller = TelemetryPoller(
        poll_fn=lambda name: _levels_response({"state.fps": 21.3}),
        submit=submit,
        view_model=vm,
        interval_sec=0.02,
        targets=("proc_a",),
    )
    poller.set_active(True)
    _wait_until(qtbot, lambda: poller.polls_completed >= 1)
    poller.stop()

    assert vm.get("processes.proc_b.state.fps") == pytest.approx(5.0), "влив по proc_a задел proc_b"
    assert vm.get("processes.proc_a.state.fps") == pytest.approx(21.3)


# --------------------------------------------------------------------------- #
#  H5 — вырожденные ответы                                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "levels, case",
    [
        ({}, "пустой dict — сенсоры есть, показаний нет"),
        (None, "None — сенсоров нет (процесс без ProcessHeartbeat)"),
        ({"state": {}}, "вложенный пустой раздел"),
        ("не-dict", "мусор вместо снимка"),
    ],
)
def test_degenerate_levels_write_nothing_and_keep_polling(qtbot, levels, case) -> None:
    """Вырожденный ``levels`` не пишет ничего, не стирает push-ключи и не рвёт тики.

    Держит: различение «нет показаний» и «нет процесса». ``levels=None`` —
    легальный ответ команды (сборщик уровней так и отвечает у процесса без
    heartbeat'а, ADR-PM-035), и при этом ``snapshot_ts`` в ответе свежий.
    Реализация, читающая ``levels`` без проверки типа, на ``None`` бросит
    внутри callback'а и остановит опрос ВСЕХ целей.
    """
    vm = TelemetryViewModel()
    _seed_push_keys(vm, "proc_a")

    submit = ImmediateSubmit()
    poller = TelemetryPoller(
        poll_fn=lambda name: _levels_response(levels, snapshot_ts=1755300000.0),
        submit=submit,
        view_model=vm,
        interval_sec=0.02,
        targets=("proc_a",),
    )
    poller.set_active(True)
    _wait_until(qtbot, lambda: poller.polls_completed >= 3)
    poller.stop()

    assert poller.polls_completed >= 3, f"опрос заглох на случае «{case}»"
    for key, expected in _PUSH_ONLY_KEYS.items():
        assert vm.get(f"processes.proc_a.state.{key}") == expected, f"случай «{case}» испортил push-ключ state.{key}"
    assert vm.get("processes.proc_a.state.fps") is None, f"случай «{case}» записал мусор"


def test_alien_snapshot_ts_does_not_gate_the_ingest(qtbot) -> None:
    """Чужой/убывающий ``snapshot_ts`` не отбрасывает числа.

    Держит: явное решение НЕ строить упорядочивание на этом поле. Штамп —
    возраст ОТВЕТА, а не чисел (ADR-PM-035), и часы источника чужие: перевод
    системных часов назад делает его убывающим. Реализация, отбрасывающая
    ответ «старее предыдущего», в этот момент замерла бы навсегда, а причина
    (перевод часов на другой машине) не нашлась бы никогда.
    """
    vm = TelemetryViewModel()
    submit = ImmediateSubmit()
    stamps = iter([1_900_000_000.0, 1.0, 0.0, -5.0])

    def poll_fn(name: str) -> dict:
        return _levels_response({"state.fps": 21.3}, snapshot_ts=next(stamps, -100.0))

    poller = TelemetryPoller(poll_fn=poll_fn, submit=submit, view_model=vm, interval_sec=0.02, targets=("proc_a",))
    poller.set_active(True)
    _wait_until(qtbot, lambda: poller.polls_completed >= 4)
    poller.stop()

    assert poller.polls_completed >= 4
    assert vm.get("processes.proc_a.state.fps") == pytest.approx(21.3), (
        "убывающий snapshot_ts заблокировал влив — поллер не должен судить о свежести по штампу"
    )
    assert vm.get("processes.proc_a.snapshot_ts") is None, (
        "snapshot_ts просочился в read-model как метрика — это поле конверта, не уровень"
    )


# --------------------------------------------------------------------------- #
#  H6 — боевая (вложенная) форма снимка и отсутствие cycles (долг K-9)         #
# --------------------------------------------------------------------------- #


def test_real_nested_levels_shape_lands_on_push_paths(qtbot) -> None:
    """Вложенный снимок раскладывается ровно в те пути, куда пишет push.

    Держит: главное обещание задачи — «виджет не узнает, push это был или
    опрос». Сборщик отдаёт ВЛОЖЕННЫЙ dict (``{"workers": {...}, "state":
    {"shm": {...}}}``), а виджеты забиндены на плоские пути
    ``processes.<p>.workers.<w>.status`` и ``processes.<p>.state.shm.*``.
    Разложи на уровень мельче/крупнее — числа приедут по путям, на которые
    никто не подписан, и вкладка останется с прочерками при «успешном» опросе.

    Здесь же граница долга K-9: у ``w_idle`` нет ``cycles`` (воркер без
    CycleMetricsRecorder) — отсутствующий ключ просто не пишется.
    """
    vm = TelemetryViewModel()
    submit = ImmediateSubmit()
    nested = {
        "workers": {
            "w_loop": {"status": "running", "effective_hz": 21.2, "cycle_duration_ms": 47.7, "cycles": 4242},
            "w_idle": {"status": "running"},  # K-9: нет CycleMetricsRecorder — нет cycles
        },
        "state": {"fps": 21.2, "latency_ms": 4.1, "shm": {"boundary_crossings": 2257, "reused": 0}},
    }
    poller = TelemetryPoller(
        poll_fn=lambda name: _levels_response(nested),
        submit=submit,
        view_model=vm,
        interval_sec=0.02,
        targets=("camera_0",),
    )
    poller.set_active(True)
    _wait_until(qtbot, lambda: poller.polls_completed >= 1)
    poller.stop()

    assert vm.get("processes.camera_0.workers.w_loop.status") == "running"
    assert vm.get("processes.camera_0.workers.w_loop.effective_hz") == pytest.approx(21.2)
    assert vm.get("processes.camera_0.workers.w_loop.cycles") == 4242
    assert vm.get("processes.camera_0.state.fps") == pytest.approx(21.2)
    # Нули включительно: для опроса «0» — показание, а не отсутствие данных.
    assert vm.get("processes.camera_0.state.shm.boundary_crossings") == 2257
    assert vm.get("processes.camera_0.state.shm.reused") == 0
    # K-9: воркер без recorder'а просто не имеет поля — это норма, не «завис».
    assert vm.get("processes.camera_0.workers.w_idle.status") == "running"
    assert vm.get("processes.camera_0.workers.w_idle.cycles") is None
    # И ни одного пути от промежуточных узлов (dict целиком в снимок не едет).
    assert vm.get("processes.camera_0.workers") is None
    assert vm.get("processes.camera_0.state.shm") is None


# --------------------------------------------------------------------------- #
#  H8 — опрос не крадёт окно истории спарклайна (находка ревью F1)             #
# --------------------------------------------------------------------------- #


def test_poll_ingest_does_not_consume_history_ring(qtbot) -> None:
    """N вливов опроса не сдвигают окно истории ни на одну точку.

    Держит: длину окна графика. Кольцо истории — ``deque`` с фиксированным
    ``maxlen`` (окно × ожидаемая частота ОДНОГО писателя, живьём 600 точек).
    Опрос пишет в ТЕ ЖЕ пути, что и push; вливаясь через общий вход, он
    вытеснял бы точки push'а и сокращал окно пропорционально своей частоте —
    «10 минут» на вкладке стали бы 4.8 минуты, и ни один тест на значения
    этого бы не заметил: `get()` продолжал бы отдавать верное число.

    Проверяем не «есть отсечка», а НАБЛЮДАЕМОЕ: список точек истории до и
    после серии вливов совпадает поэлементно.
    """
    vm = TelemetryViewModel(window_sec=10.0, sample_hz=1.0)  # маленькое кольцо: maxlen=10
    path = "processes.proc_a.state.fps"

    # Наполняем кольцо push'ем ДО отказа — теперь любое лишнее вытеснение видно.
    for i in range(10):
        vm.on_state_delta({"data_type": "state_delta", "path": path, "value": float(i)})
    before = vm.history(path)
    assert len(before) == 10, f"кольцо не заполнилось: {len(before)}"

    submit = ImmediateSubmit()
    poller = TelemetryPoller(
        poll_fn=lambda name: _levels_response({"state.fps": 999.0}),
        submit=submit,
        view_model=vm,
        interval_sec=0.02,
        targets=("proc_a",),
    )
    poller.set_active(True)
    _wait_until(qtbot, lambda: poller.polls_completed >= 12)
    poller.stop()

    assert poller.polls_completed >= 12, "не набралось 12 вливов опроса"
    after = vm.history(path)
    assert after == before, (
        f"опрос вытеснил точки истории: было {len(before)} точек {before[:2]}..., "
        f"стало {len(after)} {after[:2]}... — окно спарклайна сокращено молча"
    )
    # При этом СНИМОК опрос обновил — иначе тест проходил бы и для «опрос не работает».
    assert vm.get(path) == pytest.approx(999.0), "опрос не обновил снимок"


# --------------------------------------------------------------------------- #
#  H9 — потерянный callback не запирает цель навсегда (находка ревью F3)       #
# --------------------------------------------------------------------------- #


def test_lost_callback_is_evicted_by_deadline_and_counted(qtbot) -> None:
    """Цель, чей ответ потерян исполнителем, возвращается в опрос по дедлайну.

    Держит: единственную дорогу назад. Доставка результата идёт через ЧУЖОЙ
    исполнитель и не гарантирована: у RequestRunner она делается Qt-сигналом,
    и на разрушенном источнике `emit` поднимает RuntimeError уже после
    успешного запроса — воспроизведено ревью дословно. Без выселения запись
    осталась бы в `_in_flight` навсегда, цель молча перестала бы опрашиваться,
    а единственным следом была бы разность счётчиков, которую никто не читает.
    """
    submit = DeferredSubmit()  # работу принимает и НЕ исполняет — callback «потерян»
    vm = TelemetryViewModel()
    poller = TelemetryPoller(
        poll_fn=lambda name: _levels_response({"state.fps": 1.0}),
        submit=submit,
        view_model=vm,
        interval_sec=0.02,
        targets=("proc_a",),
        flight_ttl_sec=0.15,
    )
    poller.set_active(True)
    qtbot.wait(100)
    assert poller.polls_started == 1, "запись о полёте не удержала повторный запрос"
    assert poller.in_flight == 1

    _wait_until(qtbot, lambda: poller.polls_expired >= 1, deadline_sec=2.0)
    poller.stop()

    assert poller.polls_expired >= 1, "потерянный callback не выселен по дедлайну — цель заперта навсегда"
    assert poller.polls_started >= 2, f"после выселения цель не вернулась в опрос: polls_started={poller.polls_started}"


def test_stop_clears_flight_records(qtbot) -> None:
    """stop() тоже снимает записи о полётах — наблюдаемое состояние не врёт.

    Держит: честность публичного ``in_flight`` после терминальной остановки.
    Тяжесть низкая (объект мёртв, опрашивать он больше не будет), но счётчик
    остаётся читаемым — оператор и диагностика увидели бы «2 запроса в полёте»
    у давно остановленного поллера. Строка в ``stop()`` есть, значит её должен
    держать тест: иначе следующий рефактор снимет её молча.
    """
    submit = DeferredSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(
        poll_fn=lambda name: _levels_response({"state.fps": 1.0}),
        submit=submit,
        view_model=vm,
        interval_sec=5.0,
        targets=("proc_a", "proc_b"),
        flight_ttl_sec=60.0,
    )
    poller.set_active(True)
    assert poller.in_flight == 2, f"полёты не начались: in_flight={poller.in_flight}"

    poller.stop()
    assert poller.in_flight == 0, (
        f"после stop() поллер сообщает о {poller.in_flight} запросах в полёте — показание пережило объект"
    )


def test_deactivate_clears_flight_records(qtbot) -> None:
    """set_active(False) снимает записи о полётах — показ не ждёт TTL.

    Держит: отзывчивость возврата на вкладку. Записи, оставленные с прошлого
    показа, заставили бы следующий showEvent молчать до истечения дедлайна —
    и это выглядело бы как «вкладка иногда открывается пустой».
    """
    submit = DeferredSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(
        poll_fn=lambda name: _levels_response({"state.fps": 1.0}),
        submit=submit,
        view_model=vm,
        interval_sec=5.0,
        targets=("proc_a",),
        flight_ttl_sec=60.0,
    )
    poller.set_active(True)
    assert poller.in_flight == 1

    poller.set_active(False)
    assert poller.in_flight == 0, "записи о полётах пережили выключение"

    poller.set_active(True)  # немедленный опрос обязан пройти, а не ждать TTL=60с
    assert poller.polls_started == 2, (
        f"повторный показ не опросил цель (ждёт TTL?): polls_started={poller.polls_started}"
    )
    poller.stop()


# --------------------------------------------------------------------------- #
#  H10 — потолок одновременных полётов и круговой обход (находка ревью F2)     #
# --------------------------------------------------------------------------- #


def test_max_in_flight_caps_concurrent_polls(qtbot) -> None:
    """Одновременных запросов не больше потолка, сколько бы ни было целей.

    Держит: чужие потоки. Каждый полёт занимает поток пула исполнителя и
    держит его до своего таймаута; без потолка семь целей разом выгребали бы
    пул, через который идут и обычные действия GUI.
    """
    submit = DeferredSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(
        poll_fn=lambda name: _levels_response({"state.fps": 1.0}),
        submit=submit,
        view_model=vm,
        interval_sec=0.02,
        targets=tuple(f"proc_{i}" for i in range(7)),
        max_in_flight=2,
        flight_ttl_sec=60.0,
    )
    poller.set_active(True)
    qtbot.wait(200)
    poller.stop()

    assert len(submit.pending) == 2, f"потолок 2 пробит: одновременно в полёте {len(submit.pending)} запросов"


def test_tick_rate_has_a_lower_bound(qtbot) -> None:
    """Тик идёт НЕ РЕЖЕ заявленного — нижняя граница темпа.

    Держит: то, чего не держал никто. Приёмочный
    ``test_interval_sec_is_public_and_bounds_poll_count`` ставит потолок сверху
    («не чаще»), и удвоение интервала его только УЛУЧШАЕТ — регрессия «опрос
    замедлился вдвое» проходила бы зелёной. Проверено инъекцией: удвоение
    ``setInterval`` не роняло ни одного теста до появления этого.

    Одна цель и мгновенный ответ выбраны намеренно: так измеряется чистый темп
    таймера, без вмешательства потолка одновременных полётов. Порог 70% —
    запас на джиттер таймера Qt (на Windows сетка ~15.6 мс); двукратная
    регрессия даёт 50% и ловится с большим отрывом.
    """
    interval, window_sec = 0.05, 1.5
    submit = ImmediateSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(
        poll_fn=lambda name: _levels_response({"state.fps": 1.0}),
        submit=submit,
        view_model=vm,
        interval_sec=interval,
        targets=("proc_a",),
    )
    poller.set_active(True)
    qtbot.wait(int(window_sec * 1000))
    poller.stop()

    expected = window_sec / interval
    assert poller.polls_started >= expected * 0.7, (
        f"темп просел: {poller.polls_started} опросов за {window_sec}с при "
        f"interval_sec={interval} (ожидалось ~{int(expected)}, порог {int(expected * 0.7)})"
    )


def test_effective_interval_matches_documented_formula() -> None:
    """``effective_interval_sec`` == ``interval × ceil(N / max_in_flight)``.

    Держит: САМО документированное число, без wall-clock и без джиттера.
    Формула названа в докстроке модуля, в описании аргумента и в ADR-139 §5 —
    значит она обязана быть исполняемой, а не только написанной. Оператор
    читает её как «возраст чисел на карточке», и разойдись реализация с
    документацией, ошибётся именно он.

    Последний случай — боевая раскладка стенда: 6 целей (7 процессов минус
    собственный ``gui``), потолок 2, тик 1 с → 3 с на цель. Замерено живьём:
    6–7 опросов на цель за 20.28 с ≈ 0.30–0.35/с.
    """
    vm = TelemetryViewModel()

    def make(interval: float, n: int, cap: int) -> TelemetryPoller:
        return TelemetryPoller(
            poll_fn=lambda name: _levels_response({}),
            submit=ImmediateSubmit(),
            view_model=vm,
            interval_sec=interval,
            targets=tuple(f"p{i}" for i in range(n)),
            max_in_flight=cap,
        )

    # (interval, N, cap) -> ожидаемый период на цель
    cases = [
        (1.0, 0, 2, 1.0),  # целей нет — период вырождается в тик
        (1.0, 1, 2, 1.0),  # подвкладка одного процесса: потолок не связывает
        (1.0, 2, 2, 1.0),  # ровно по потолку
        (1.0, 3, 2, 2.0),  # ceil(3/2) = 2
        (1.0, 6, 2, 3.0),  # БОЕВАЯ раскладка стенда
        (0.5, 7, 3, 1.5),  # ceil(7/3) = 3
    ]
    for interval, n, cap, expected in cases:
        poller = make(interval, n, cap)
        assert poller.effective_interval_sec == pytest.approx(expected), (
            f"interval={interval} N={n} cap={cap}: ожидался период {expected}с, "
            f"получен {poller.effective_interval_sec}с"
        )
        poller.stop()


def test_effective_interval_follows_target_changes() -> None:
    """Период пересчитывается при смене состава целей, а не застывает.

    Держит: актуальность показания. Пользователь уходит в подвкладку одного
    процесса — период обязан схлопнуться до тика; возвращается в «Все
    процессы» — снова растянуться. Закешированное при старте значение врало бы
    ровно в тот момент, когда на него смотрят.
    """
    poller = TelemetryPoller(
        poll_fn=lambda name: _levels_response({}),
        submit=ImmediateSubmit(),
        view_model=TelemetryViewModel(),
        interval_sec=1.0,
        targets=tuple(f"p{i}" for i in range(6)),
        max_in_flight=2,
    )
    assert poller.effective_interval_sec == pytest.approx(3.0)

    poller.set_targets(["p0"])  # подвкладка одного процесса
    assert poller.effective_interval_sec == pytest.approx(1.0), (
        f"период не схлопнулся при одной цели: {poller.effective_interval_sec}"
    )

    poller.set_targets([f"p{i}" for i in range(6)])
    assert poller.effective_interval_sec == pytest.approx(3.0), (
        f"период не восстановился при возврате к шести целям: {poller.effective_interval_sec}"
    )
    poller.stop()


def test_capped_polling_walks_all_targets_in_turn(qtbot) -> None:
    """При упёртом потолке обход круговой — хвост списка целей не голодает.

    Держит: границу предыдущей страховки. Фиксированный порядок обхода при
    потолке 2 и семи целях означал бы, что цели 3..7 не опрашиваются НИКОГДА,
    а симптом («у части процессов числа не идут») увёл бы искать в бэкенд.
    """
    submit = DeferredSubmit()
    vm = TelemetryViewModel()
    targets = tuple(f"proc_{i}" for i in range(7))
    poller = TelemetryPoller(
        poll_fn=lambda name: _levels_response({"state.fps": 1.0}),
        submit=submit,
        view_model=vm,
        interval_sec=0.02,
        targets=targets,
        max_in_flight=2,
    )
    polled: set[str] = set()

    poller.set_active(True)
    deadline = time.monotonic() + 5.0
    while len(polled) < len(targets) and time.monotonic() < deadline:
        qtbot.wait(20)
        # Отпускаем накопленное — освободившийся слот должен достаться следующим.
        for fn, on_result in list(submit.pending):
            polled.add(fn.args[0] if hasattr(fn, "args") else "?")
        submit.release_all()
    poller.stop()

    assert polled == set(targets), f"опрошены не все цели: не досталось {set(targets) - polled}"


# --------------------------------------------------------------------------- #
#  H11 — исключение собственного процесса (находка ревью F8)                   #
# --------------------------------------------------------------------------- #


def test_excluded_name_is_never_polled(qtbot) -> None:
    """Имя из ``exclude`` не опрашивается, даже если пришло в set_targets.

    Держит: круг ``gui → PM → gui``. GUI входит в топологию, и
    ``get_process_names()`` отдаёт его наравне с остальными — вкладка честно
    просит опрашивать всех показанных. Отсев обязан жить в поллере, иначе его
    придётся помнить каждому вызывающему.
    """
    calls: list[str] = []

    def poll_fn(name: str) -> dict:
        calls.append(name)
        return _levels_response({"state.fps": 1.0})

    submit = ImmediateSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(
        poll_fn=poll_fn,
        submit=submit,
        view_model=vm,
        interval_sec=0.02,
        targets=("gui", "camera_0"),
        exclude=("gui",),
    )
    poller.set_active(True)
    _wait_until(qtbot, lambda: poller.polls_completed >= 3)

    # И через set_targets — тоже (отсев в одном месте, а не в конструкторе).
    poller.set_targets(["gui", "camera_0", "gui"])
    _wait_until(qtbot, lambda: poller.polls_completed >= 6)
    poller.stop()

    assert "camera_0" in calls, "обычная цель не опрошена"
    assert "gui" not in calls, f"исключённый процесс опрошен: {calls}"


# --------------------------------------------------------------------------- #
#  H12 — неудачный опрос отличим от удачного (находка ревью F9)                #
# --------------------------------------------------------------------------- #


def test_failed_polls_are_counted_separately(qtbot) -> None:
    """``success=False`` считается в polls_failed, а не растворяется в completed.

    Держит: отличимость «протухло» от «стабильно». Неудачный опрос ничего не
    пишет, поэтому на экране остаются последние ХОРОШИЕ числа — визуально это
    неотличимо от работающей системы. Счётчик — единственный способ увидеть
    разницу, не читая лог.
    """
    submit = ImmediateSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(
        poll_fn=lambda name: {"success": False, "error": "timeout"},
        submit=submit,
        view_model=vm,
        interval_sec=0.02,
        targets=("proc_a",),
    )
    poller.set_active(True)
    _wait_until(qtbot, lambda: poller.polls_completed >= 3)
    poller.stop()

    assert poller.polls_failed == poller.polls_completed, (
        f"неудачи не посчитаны: failed={poller.polls_failed}, completed={poller.polls_completed}"
    )
    assert poller.polls_failed >= 3


def test_successful_polls_do_not_count_as_failures(qtbot) -> None:
    """Обратная сторона: удачные опросы не капают в polls_failed.

    Держит: счётчик от вырождения в «число ответов». Без этой проверки
    реализация, инкрементящая failed всегда, прошла бы предыдущий тест.
    """
    submit = ImmediateSubmit()
    vm = TelemetryViewModel()
    poller = TelemetryPoller(
        poll_fn=lambda name: _levels_response({"state.fps": 1.0}),
        submit=submit,
        view_model=vm,
        interval_sec=0.02,
        targets=("proc_a",),
    )
    poller.set_active(True)
    _wait_until(qtbot, lambda: poller.polls_completed >= 3)
    poller.stop()

    assert poller.polls_failed == 0, f"удачные опросы посчитаны неудачами: {poller.polls_failed}"


# --------------------------------------------------------------------------- #
#  H7 — poll_fn исполняется вне main thread и не блокирует его                  #
# --------------------------------------------------------------------------- #


def test_slow_poll_fn_does_not_block_main_thread(qtbot) -> None:
    """Медленный poll_fn крутится в фоне; main thread продолжает тикать.

    Держит: инвариант ADR-136 на живом времени, а не на подсчёте вызовов.
    Фоновый поток — daemon, join с дедлайном: если механизм всё-таки зовёт
    poll_fn синхронно, тест обязан УПАСТЬ по ассерту, а не повиснуть вместе
    с ним (висящий тест прячет регрессию за таймаутом).
    """
    main_thread_id = threading.get_ident()
    seen_threads: list[int] = []
    release = threading.Event()
    threads: list[threading.Thread] = []

    def slow_poll_fn(name: str) -> dict:
        seen_threads.append(threading.get_ident())
        release.wait(timeout=2.0)  # «медленный backend» с собственным дедлайном
        return _levels_response({"state.fps": 1.0})

    def submit(fn, on_result) -> None:
        t = threading.Thread(target=lambda: on_result(fn()), daemon=True)
        threads.append(t)
        t.start()

    vm = TelemetryViewModel()
    poller = TelemetryPoller(poll_fn=slow_poll_fn, submit=submit, view_model=vm, interval_sec=0.02, targets=("proc_a",))

    started_at = time.monotonic()
    poller.set_active(True)
    elapsed = time.monotonic() - started_at
    assert elapsed < 1.0, f"set_active(True) блокировал main thread на {elapsed:.2f}с — poll_fn зовётся синхронно"

    _wait_until(qtbot, lambda: bool(seen_threads), deadline_sec=2.0)
    release.set()
    for t in threads:
        t.join(timeout=2.0)
        assert not t.is_alive(), "фоновый poll_fn не завершился за 2с — дедлок"
    poller.stop()

    assert seen_threads, "poll_fn не был вызван"
    assert main_thread_id not in seen_threads, f"poll_fn вызван в main thread: {seen_threads}"
