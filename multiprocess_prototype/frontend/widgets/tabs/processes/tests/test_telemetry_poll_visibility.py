# -*- coding: utf-8 -*-
"""Проводка «видимость вкладки → опрос уровней» (Task 3.3).

Механизм поллера проверен в его собственных тестах (framework:
``tests/state/test_telemetry_poller_{acceptance,hazards}.py``). Здесь — ШОВ:
вкладка обязана двигать выключатель, а не владеть опросом.

Что именно может сломаться в ЭТОМ шве:

* поллер прокинут в ``create()``, но выключатель не подключён — опрос либо не
  включится никогда, либо не выключится никогда (второе тише и дороже);
* скрытие через переключение таба и скрытие вместе с окном идут РАЗНЫМИ путями
  Qt; закрыть надо оба, иначе «закрытое окно = ноль трафика» неверно;
* состав целей взят один раз при сборке — переключение nav оставляет опрос
  на прежнем процессе (виден один, опрашивается другой);
* вкладка зовёт ``stop()`` вместо ``set_active(False)`` — опрос умирает на
  первом же уходе с вкладки, и вернувшийся пользователь видит замершие числа
  без единой ошибки в логе.

Поллер здесь — двойник со счётчиками: настоящий IPC в юнит-тесте не нужен,
а нужен факт «кто и когда дёрнул выключатель».
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout

from multiprocess_prototype.frontend.widgets.tabs.processes.data import ALL_PROCESSES_KEY
from multiprocess_prototype.frontend.widgets.tabs.processes.tab import ProcessesTab

from ._helpers import make_processes_runtime, make_processes_services


class FakePoller:
    """Двойник TelemetryPoller: запоминает движения выключателя и состав целей."""

    def __init__(self) -> None:
        self.active_calls: list[bool] = []
        self.targets: tuple[str, ...] = ()
        self.target_calls: list[tuple[str, ...]] = []
        self.stop_calls = 0

    def set_active(self, active: bool) -> None:
        self.active_calls.append(bool(active))

    def set_targets(self, names) -> None:
        self.targets = tuple(names)
        self.target_calls.append(self.targets)

    def stop(self) -> None:
        self.stop_calls += 1

    @property
    def is_active(self) -> bool:
        return bool(self.active_calls) and self.active_calls[-1]


def _make_tab(qtbot, poller: FakePoller) -> ProcessesTab:
    tab = ProcessesTab.create(
        make_processes_services(),
        make_processes_runtime(telemetry_poller=poller),
    )
    qtbot.addWidget(tab)
    return tab


def test_hidden_tab_never_activates_the_poll(qtbot) -> None:
    """Сборка вкладки без показа не включает опрос ни разу.

    Держит: «скрытая молчит» в самом дешёвом случае — вкладка создана
    (lazy-панели построены, nav заполнен), но пользователь её не открывал.
    """
    poller = FakePoller()
    _make_tab(qtbot, poller)

    assert True not in poller.active_calls, f"опрос включился на построении невидимой вкладки: {poller.active_calls}"


def test_show_activates_and_hide_deactivates(qtbot) -> None:
    """Показ включает опрос, скрытие — выключает (счёт движений, не факт)."""
    poller = FakePoller()
    tab = _make_tab(qtbot, poller)

    tab.show()
    qtbot.waitExposed(tab)
    assert poller.is_active, f"показанная вкладка не включила опрос: {poller.active_calls}"

    tab.hide()
    assert not poller.is_active, f"скрытая вкладка не выключила опрос: {poller.active_calls}"


def test_hiding_the_parent_window_also_silences_the_poll(qtbot) -> None:
    """Скрытие окна-родителя гасит опрос вкладки.

    Держит: «закрытое окно = ноль трафика». Проверено ЗАПУСКОМ, а не
    рассуждением о том, доходит ли QHideEvent до дочернего виджета: если бы
    не доходил, опрос продолжал бы ходить в backend за спиной закрытого окна.
    """
    poller = FakePoller()
    window = QWidget()
    qtbot.addWidget(window)
    layout = QVBoxLayout(window)
    tab = ProcessesTab.create(
        make_processes_services(),
        make_processes_runtime(telemetry_poller=poller),
    )
    layout.addWidget(tab)

    window.show()
    qtbot.waitExposed(window)
    assert poller.is_active, "вкладка в показанном окне не включила опрос"

    window.hide()
    assert not poller.is_active, f"опрос продолжился после скрытия окна: {poller.active_calls}"


def test_tab_never_calls_stop(qtbot) -> None:
    """Вкладка не зовёт stop() — он терминален и принадлежит владельцу.

    Держит: возврат на вкладку. Скрытие обратимо (пользователь переключил таб),
    а stop() — нет: опрос умер бы на первом уходе, и вернувшийся пользователь
    смотрел бы на замершие числа без ошибки в логе. Терминальную остановку
    делает composition root на aboutToQuit.
    """
    poller = FakePoller()
    tab = _make_tab(qtbot, poller)
    tab.show()
    qtbot.waitExposed(tab)
    tab.hide()
    tab.deleteLater()
    qtbot.wait(50)

    assert poller.stop_calls == 0, "вкладка вызвала терминальный stop()"


def test_targets_follow_the_visible_scope(qtbot) -> None:
    """Состав целей = состав ПОКАЗАННОГО: все процессы vs один выбранный."""
    poller = FakePoller()
    tab = _make_tab(qtbot, poller)
    tab.show()
    qtbot.waitExposed(tab)

    # Вид «Все процессы» — показаны карточки всех трёх.
    assert set(poller.targets) == {"camera_0", "processor", "renderer"}, (
        f"в виде «Все процессы» цели опроса: {poller.targets}"
    )

    tab.select_item("processor")
    assert poller.targets == ("processor",), (
        f"подвкладка процесса должна опрашивать только его, а цели: {poller.targets}"
    )

    tab.select_item(ALL_PROCESSES_KEY)
    assert set(poller.targets) == {"camera_0", "processor", "renderer"}, (
        f"возврат в «Все процессы» не восстановил состав целей: {poller.targets}"
    )


def test_real_poller_with_request_runner_polls_off_main_thread(qtbot) -> None:
    """Боевая связка (TelemetryPoller + RequestRunner) не ходит в IPC из main thread.

    Держит: инвариант ADR-136 на ТОЙ ЖЕ паре объектов, что собирает app.py —
    двойники здесь не годятся. ``test_tab_open_invariant`` строит RuntimeDeps
    без поллера и этот путь не проходит вовсе, поэтому проверка живёт тут.
    Единственное, что подменено, — сам блокирующий запрос (вместо
    ``command_sender.request_command`` записывающая заглушка): проверяется
    ПОТОК исполнения, а не наличие backend'а.
    """
    import threading
    import time

    from multiprocess_framework.modules.frontend_module.state import (
        TelemetryPoller,
        TelemetryViewModel,
    )
    from multiprocess_prototype.frontend.bridge.request_runner import RequestRunner

    main_thread_id = threading.get_ident()
    seen: list[int] = []

    def poll_fn(name: str) -> dict:
        seen.append(threading.get_ident())
        return {"success": True, "result": {"snapshot_ts": 0.0, "levels": {"state.fps": 7.5}}}

    vm = TelemetryViewModel()
    runner = RequestRunner()
    poller = TelemetryPoller(poll_fn=poll_fn, submit=runner.submit, view_model=vm, interval_sec=0.05)
    tab = ProcessesTab.create(
        make_processes_services(),
        make_processes_runtime(telemetry=vm, telemetry_poller=poller),
    )
    qtbot.addWidget(tab)

    tab.show()
    qtbot.waitExposed(tab)

    deadline = time.monotonic() + 5.0
    while vm.get("processes.camera_0.state.fps") is None and time.monotonic() < deadline:
        qtbot.wait(20)
    tab.hide()
    poller.stop()

    assert seen, "опрос не состоялся за 5с — связка не собралась"
    assert main_thread_id not in seen, f"запрос ушёл из main thread: {seen}"
    assert vm.get("processes.camera_0.state.fps") == 7.5, (
        "результат опроса не доехал до read-model через боевой RequestRunner"
    )


def test_dedicated_pool_isolates_hung_polls_from_other_gui_requests(qtbot) -> None:
    """Зависшие опросы в СВОЁМ пуле не задерживают обычные запросы GUI.

    Держит: находку ревью F2. Опрос ходит к N процессам с таймаутом 3с; на
    общем ``QThreadPool.globalInstance()`` неотвечающие цели занимают слоты,
    через которые идут действия пользователя — измерено ревью: 2 зависшие цели
    на пуле из 2 потоков задержали обычный запрос на 3.02 с.

    Проверяется НАБЛЮДАЕМОЕ (время обслуживания постороннего запроса), а не имя
    вызванного конструктора: подмена пула на эквивалентный не должна ронять
    тест, а возврат на общий пул — должна.

    Число зависших задач берётся ОТ ПУЛА (``maxThreadCount + 2``), а не
    константой: на 16-ядерной машине общий пул держит 16 потоков, и двух
    зависших задач не хватило бы, чтобы его засорить — тест был бы вакуумен
    ровно там, где должен ловить регрессию (проверено: `maxThreadCount`
    globalInstance здесь = 16).
    """
    import threading
    import time

    from PySide6.QtCore import QThreadPool

    from multiprocess_prototype.frontend.bridge.request_runner import RequestRunner

    release = threading.Event()
    poll_pool = QThreadPool()
    poll_pool.setMaxThreadCount(2)
    poll_runner = RequestRunner(pool=poll_pool)

    other_runner = RequestRunner()  # обычные действия GUI — общий пул
    other_done: list[float] = []

    # Сколько задач нужно, чтобы засорить ТОТ пул, которым реально пользуется
    # опрос (а не тот, который мы ему подсунули в этом тесте).
    hung = max(poll_pool.maxThreadCount(), QThreadPool.globalInstance().maxThreadCount()) + 2

    try:
        for _ in range(hung):
            poll_runner.submit(lambda: (release.wait(timeout=10.0), {"success": True})[1])

        qtbot.wait(100)  # дать пулу разобрать задачи
        started = time.monotonic()
        other_runner.submit(lambda: {"success": True}, lambda _r: other_done.append(time.monotonic() - started))

        deadline = time.monotonic() + 3.0
        while not other_done and time.monotonic() < deadline:
            qtbot.wait(10)
    finally:
        release.set()
        poll_pool.waitForDone(10000)
        QThreadPool.globalInstance().waitForDone(10000)

    assert other_done, "обычный запрос GUI не обслужен за 3с — пул опроса его блокирует"
    assert other_done[0] < 1.0, f"обычный запрос ждал {other_done[0]:.2f}с — опрос делит пул с действиями GUI"


def test_missing_poller_is_a_no_op(qtbot) -> None:
    """RuntimeDeps без поллера → вкладка живёт как до 3.3, без падений.

    Держит: graceful-путь оболочки без backend'а (и всех существующих тестов,
    которые строят RuntimeDeps без нового поля).
    """
    tab = ProcessesTab.create(make_processes_services(), make_processes_runtime())
    qtbot.addWidget(tab)
    tab.show()
    qtbot.waitExposed(tab)
    tab.select_item("processor")
    tab.hide()
