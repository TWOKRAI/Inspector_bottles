# -*- coding: utf-8 -*-
"""T3 gui-frame-path: приёмка тракта кадров НАСТОЯЩИМИ объектами под перегрузкой.

Purpose: настоящие ``DataReceiverBridge``, ``LatestMailbox`` (``bridge.frame_mailbox``),
``FramePump`` (``process._frame_pump``) и ``ImagePanelWidget`` под потоком кадров:
память ограничена числом дисплеев, последний кадр доходит до экрана, Qt-таймер жив,
state-дельта не тонет в кадрах, кадр, пришедший до насоса, показан.

Тесты написаны вслепую (до кода) по контракту из брифа T3; ожидаемые значения здесь
литералы, не вычислены из кода под тестом. Кадр кодирует свой номер в пикселе
``[0, 0]`` (канал 0 — младший байт, канал 1 — старший), поэтому номер читается с экрана
(``image_panel.grab_frame``). Ключ насоса == имя sender == id дисплея (так ключ не
зависит от того, чем его назовёт реализация: sender или id дисплея).

Машинная безопасность: ВСЕ заливки идут только через ``_Flood`` — единственный
помощник-продюсер; в нём потолок private bytes процесса 500 МБ (опрос каждые 10 мс,
база — после показа >= 1 кадра в каждом слоте, ``GetProcessMemoryInfo`` через ``ctypes``;
psutil запрещён правилами проекта). Продюсеры — демон-потоки с join по дедлайну.
Класс файла для ``machine_gate.sh`` — ``medium``.

Запуск (из корня worktree, PYTHONPATH=корень, PYTHONUTF8=1, Qt offscreen):
    bash ../../../scripts/machine_gate.sh medium inspector-bottles-K \
        ../../../.venv/Scripts/python.exe -m pytest -q --tb=short -p no:cacheprovider \
        multiprocess_prototype/frontend/tests/test_frame_overload_real_objects.py
"""

from __future__ import annotations

import ctypes
import gc
import math
import os
import sys
import threading
import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402

__all__: list[str] = []

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="потолок памяти считается через GetProcessMemoryInfo (Windows); без него заливка небезопасна",
)

# ---------------------------------------------------------------------------
# Литералы приёмки (из брифа T3, не из кода)
# ---------------------------------------------------------------------------

_H, _W = 1080, 1440  # кадр 1440x1080x3 -> 4 665 600 байт
_SENDERS = ("cam0", "cam1", "cam2", "cam3")  # sender == id дисплея == ключ насоса
_FPS_LIMIT = 20.0  # предел четырёх дисплеев во ВСЕХ перегрузочных тестах (берётся из рецепта)
_FLOOD_RATE = 400  # кадр/с на КАЖДОГО sender
_FLOOD_FRAMES = 2000  # 5 с * 400
_MAX_BYTES_HELD = 18_662_400  # 4 ключа * 4 665 600
_GROWTH_BOUND = 100 * 1024 * 1024  # приёмка: рост private не больше 100 МБ
_CEILING = 500 * 1024 * 1024  # аварийный потолок продюсеров: рост private больше 500 МБ
_POLL_S = 0.01  # опрос памяти 100 Гц (требование: не реже 20 Гц, то есть каждые 50 мс и чаще)
_STATE_BOUND_S = 1.0  # дельта состояния доставлена за 1 с (гипотеза, окончательная — по стенду)
_LAST_FRAME_BOUND_S = 1.0  # последний кадр на экране не позднее 1 с после остановки продюсеров
_TICK_INTERVAL_MS = 100  # «Qt-таймер» теста
# Порог по замеру (лид, 2026-11-24): пустой цикл Qt с QTimer 100 мс даёт 8,41-9,02 тика/с (10 прогонов, медиана 8,98);
# заливка из потоков внутри тестового процесса даёт 5,31-9,10 (10 прогонов; GIL и копирование кадров отставляют
# продюсеров, elapsed до 10 с); заливка из отдельных процессов — 8,80-9,00. Состояние с очередью кадров в Qt даёт
# около 1 тика/с (замер cto), поэтому порог 4 отделяет голодание цикла от нормы в четыре раза и не краснеет от GIL.
_MIN_TICKS_PER_S = 4.0

_TEMPLATE = np.zeros((_H, _W, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# private bytes процесса (ctypes, без psutil)
# ---------------------------------------------------------------------------

if sys.platform == "win32":
    from ctypes import wintypes

    class _ProcessMemoryCountersEx(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    _K32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _K32.GetCurrentProcess.restype = wintypes.HANDLE
    _K32.K32GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ProcessMemoryCountersEx),
        wintypes.DWORD,
    ]
    _K32.K32GetProcessMemoryInfo.restype = wintypes.BOOL


def _private_bytes() -> int:
    """Private bytes текущего процесса (PrivateUsage)."""
    counters = _ProcessMemoryCountersEx()
    counters.cb = ctypes.sizeof(counters)
    ok = _K32.K32GetProcessMemoryInfo(_K32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    if not ok:
        raise OSError(f"GetProcessMemoryInfo не удалась: winerror={ctypes.get_last_error()}")
    return int(counters.PrivateUsage)


# ---------------------------------------------------------------------------
# Кадры и чтение номера с экрана
# ---------------------------------------------------------------------------


def _frame(n: int) -> np.ndarray:
    """Новый кадр 1440x1080x3 с номером n в пикселе [0, 0] (байт 0 — младший, байт 1 — старший)."""
    f = _TEMPLATE.copy()
    f[0, 0, 0] = n & 0xFF
    f[0, 0, 1] = (n >> 8) & 0xFF
    return f


def _frame_no(frame: Any) -> int | None:
    """Номер кадра из пикселя [0, 0] или None, если кадра нет."""
    if frame is None:
        return None
    return int(frame[0, 0, 0]) + 256 * int(frame[0, 0, 1])


def _msg(sender: str, n: int, capture_ns: int | None = None) -> dict:
    """Сообщение кадра: sender, frame, data{capture_ns, capture_ts}."""
    cap = 1_000_000_000 + n * 1_000_000 if capture_ns is None else capture_ns
    return {"sender": sender, "frame": _frame(n), "data": {"capture_ns": cap, "capture_ts": cap / 1e9}}


def _screen_no(panel: Any, slot: str) -> int | None:
    """Номер последнего кадра, дошедшего до экрана слота."""
    return _frame_no(panel.grab_frame(slot))


# ---------------------------------------------------------------------------
# Цикл событий Qt в главном потоке
# ---------------------------------------------------------------------------


def _spin_until(cond: Callable[[], bool], timeout_s: float) -> bool:
    """Крутить цикл событий Qt, пока cond() не станет True или не истечёт timeout_s."""
    loop = QEventLoop()
    deadline = time.perf_counter() + timeout_s
    state = {"ok": False}
    poll = QTimer()
    poll.setInterval(10)

    def _check() -> None:
        if cond():
            state["ok"] = True
            loop.quit()
        elif time.perf_counter() >= deadline:
            loop.quit()

    poll.timeout.connect(_check)
    poll.start()
    _check()
    if not state["ok"] and time.perf_counter() < deadline:
        loop.exec()
    poll.stop()
    return state["ok"]


# ---------------------------------------------------------------------------
# Стенд из настоящих объектов
# ---------------------------------------------------------------------------


def _recipe(fps_limit: float = _FPS_LIMIT) -> dict:
    """Рецепт: четыре дисплея (id == sender) с fps_limit и привязки sender -> display."""
    return {
        "displays": [
            {"id": s, "name": s, "enabled": True, "position": {"x": i * 10, "y": 0}, "fps_limit": fps_limit}
            for i, s in enumerate(_SENDERS)
        ],
        "blueprint": {"displays": [{"node_id": f"{s}.draw.frame", "display_id": s} for s in _SENDERS]},
    }


class _RecipeManager:
    """Двойник recipe_manager: get_active() -> slug, read_recipe(slug) -> рецепт."""

    def __init__(self, recipe: dict) -> None:
        self._recipe = recipe

    def get_active(self) -> str:
        return "t3_recipe"

    def read_recipe(self, slug: str) -> dict:
        assert slug == "t3_recipe"
        return self._recipe


class _Wiring:
    """Настоящие мост + панель; насос появляется после wire() (настоящая _setup_bridge_callbacks)."""

    def __init__(self, qtbot: Any, bridge: Any | None = None) -> None:
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge
        from multiprocess_prototype.frontend.widgets.image_panel.widget import ImagePanelWidget

        self.bridge = bridge if bridge is not None else DataReceiverBridge()
        self.panel = ImagePanelWidget(slots=[{"id": s, "label": s} for s in _SENDERS])
        qtbot.addWidget(self.panel)
        self.window = MagicMock(name="window_mock")
        self.process = SimpleNamespace(_bridge=self.bridge, _log_info=MagicMock(), _log_warning=MagicMock())

    def wire(self, fps_limit: float = _FPS_LIMIT) -> None:
        """Настоящая _setup_bridge_callbacks: предел берётся из рецепта через build_panel_displays."""
        from multiprocess_prototype.frontend.app import _setup_bridge_callbacks

        _setup_bridge_callbacks(
            self.process, self.panel, self.window, recipe_manager=_RecipeManager(_recipe(fps_limit))
        )

    def shown(self, key: str) -> int:
        """Счётчик shown насоса по ключу (а не число вызовов display_frame)."""
        return int(self.process._frame_pump.stats().get(key, {}).get("shown", 0))

    def close(self) -> None:
        pump = getattr(self.process, "_frame_pump", None)
        if pump is not None:
            pump.stop()
        QCoreApplication.removePostedEvents(None)


@pytest.fixture()
def make_wiring(qtbot):
    made: list[_Wiring] = []

    def _make(bridge: Any | None = None) -> _Wiring:
        w = _Wiring(qtbot, bridge)
        made.append(w)
        return w

    yield _make
    for w in made:
        w.close()
    gc.collect()


# ---------------------------------------------------------------------------
# Единственный помощник-продюсер с потолком памяти
# ---------------------------------------------------------------------------


class _Flood:
    """Продюсеры кадров (демон-потоки) + сторож private bytes с потолком.

    plan: {sender: (rate_hz, count)} — кадры 1..count, шаг 1/rate_hz от общего старта.
    Перед заливкой каждый из четырёх слотов получает кадр 0 и показывает его (база памяти
    берётся ПОСЛЕ этого). Сторож опрашивает private bytes каждые 10 мс; рост больше
    ``ceiling_bytes`` (по умолчанию 500 МБ) ставит ``abort`` — продюсеры выходят.
    """

    def __init__(
        self,
        bridge: Any,
        panel: Any,
        plan: dict[str, tuple[float, int]],
        *,
        ceiling_bytes: int = _CEILING,
    ) -> None:
        self.bridge = bridge
        self.panel = panel
        self.plan = plan
        self.ceiling_bytes = ceiling_bytes
        self.sent: dict[str, int] = {s: 0 for s in plan}
        self.finished_at: dict[str, float] = {}
        self.abort = threading.Event()
        self.aborted = False
        self.base_private = 0
        self.peak_growth = 0
        self.polls = 0
        self.t_start = 0.0
        self.t_end = 0.0
        self.put_delta: int | None = None
        self._watch_done = threading.Event()
        self._threads: list[threading.Thread] = []
        self._watcher: threading.Thread | None = None

    # -- потоки --------------------------------------------------------------

    def _produce(self, sender: str, rate: float, count: int, t0: float) -> None:
        try:
            for n in range(1, count + 1):
                if self.abort.is_set():
                    break
                due = t0 + n / rate
                while True:
                    rest = due - time.perf_counter()
                    if rest <= 0:
                        break
                    time.sleep(rest - 0.002 if rest > 0.003 else 0)
                if self.abort.is_set():
                    break
                self.bridge.dispatch(_msg(sender, n))
                self.sent[sender] = n
        finally:
            self.finished_at[sender] = time.perf_counter()

    def _watch(self) -> None:
        while not self._watch_done.is_set():
            growth = _private_bytes() - self.base_private
            self.polls += 1
            if growth > self.peak_growth:
                self.peak_growth = growth
            if growth > self.ceiling_bytes:
                self.aborted = True
                self.abort.set()
            self._watch_done.wait(_POLL_S)

    def _all_finished(self) -> bool:
        return len(self.finished_at) == len(self.plan)

    # -- прогон --------------------------------------------------------------

    def run(
        self,
        *,
        on_start: Callable[[], None] | None = None,
        on_done: Callable[[], None] | None = None,
        hard_timeout_s: float = 30.0,
    ) -> None:
        """Прогрев, заливка, ожидание конца в цикле событий Qt (главный поток крутит Qt)."""
        mailbox = getattr(self.bridge, "frame_mailbox", None)
        try:
            for s in _SENDERS:
                self.bridge.dispatch(_msg(s, 0))
            warmed = _spin_until(lambda: all(self.panel.grab_frame(s) is not None for s in _SENDERS), 10.0)
            assert warmed, "прогрев: не каждый слот показал >= 1 кадра за 10 с (база памяти не взята)"
            gc.collect()
            self.base_private = _private_bytes()
            put_before = mailbox.stats()["put"] if mailbox is not None else None

            self._watcher = threading.Thread(target=self._watch, name="flood-watch", daemon=True)
            self._watcher.start()
            if on_start is not None:
                on_start()
            self.t_start = time.perf_counter()
            for s, (rate, count) in self.plan.items():
                th = threading.Thread(
                    target=self._produce, args=(s, rate, count, self.t_start), name=f"flood-{s}", daemon=True
                )
                th.start()
                self._threads.append(th)

            _spin_until(self._all_finished, hard_timeout_s)
            if not self._all_finished():
                self.abort.set()  # зависание продюсеров (dispatch не возвращается): остановить
            if on_done is not None:
                on_done()
            self.t_end = max(self.finished_at.values(), default=time.perf_counter())
        finally:
            if not self._all_finished():
                self.abort.set()
            for th in self._threads:
                th.join(2.0)
            self._watch_done.set()
            if self._watcher is not None:
                self._watcher.join(2.0)
        if mailbox is not None and put_before is not None:
            self.put_delta = mailbox.stats()["put"] - put_before

    @property
    def elapsed(self) -> float:
        return self.t_end - self.t_start


@pytest.fixture()
def make_flood():
    """Фабрика заливок: все продюсеры в файле создаются только здесь (потолок памяти внутри)."""
    made: list[_Flood] = []

    def _make(bridge: Any, panel: Any, plan: dict[str, tuple[float, int]], *, ceiling_bytes: int = _CEILING) -> _Flood:
        fl = _Flood(bridge, panel, plan, ceiling_bytes=ceiling_bytes)
        made.append(fl)
        return fl

    yield _make
    for fl in made:
        fl.abort.set()
        fl._watch_done.set()
        for th in fl._threads:
            th.join(2.0)
        if fl._watcher is not None:
            fl._watcher.join(2.0)


def _flood_plan_all() -> dict[str, tuple[float, int]]:
    """Перегрузка: 400 кадр/с на КАЖДОГО из четырёх sender, 5 с, номера 1..2000."""
    return {s: (float(_FLOOD_RATE), _FLOOD_FRAMES) for s in _SENDERS}


def _assert_flood_reached(flood: _Flood, *, ratio: float = 1.0) -> None:
    """Предусловие: заливка достигнута (put каждого sender == 2000; для памяти >= 90%)."""
    assert not flood.aborted, (
        f"заливка прервана потолком памяти: рост private {flood.peak_growth / 2**20:.0f} МБ "
        f"> {flood.ceiling_bytes / 2**20:.0f} МБ; отправлено {flood.sent}"
    )
    for s, (_rate, count) in flood.plan.items():
        need = math.ceil(count * ratio)
        assert flood.sent[s] >= need, f"предусловие: sender {s} отправил {flood.sent[s]} < {need}"
    assert flood.put_delta is not None, "контракт: у моста нет frame_mailbox (LatestMailbox)"
    need_total = math.ceil(sum(count for _r, count in flood.plan.values()) * ratio)
    assert flood.put_delta >= need_total, f"предусловие: put ящика {flood.put_delta} < {need_total}"


# ---------------------------------------------------------------------------
# Самопроверка помощника: потолок действительно останавливает продюсеров
# ---------------------------------------------------------------------------


def test_flood_helper_aborts_producers_on_ceiling(make_flood, qtbot) -> None:
    """Сторож прерывает продюсеров, когда рост private превысил потолок (проверка самого помощника).

    Потолок занижен до 100 МБ, мост-двойник удерживает кадры (память растёт по построению);
    настоящие 500 МБ в этом тесте не достигаются.
    """
    retained: list[dict] = []

    class _RetainingBridge:
        def dispatch(self, msg: dict) -> None:
            retained.append(msg)

    class _Panel:
        def grab_frame(self, slot: str) -> object:
            return object()

    flood = make_flood(_RetainingBridge(), _Panel(), _flood_plan_all(), ceiling_bytes=100 * 1024 * 1024)
    flood.run()

    assert flood.aborted is True
    assert sum(flood.sent.values()) < 4 * _FLOOD_FRAMES
    assert flood.polls >= 2
    # перелёт между опросами ограничен: между опросами продюсеры дают не больше ~150 МБ
    assert flood.peak_growth < 100 * 1024 * 1024 + 400 * 1024 * 1024
    retained.clear()


# ---------------------------------------------------------------------------
# Перегрузочные тесты (REDS)
# ---------------------------------------------------------------------------


def test_overload_memory_stays_bounded(make_wiring, make_flood) -> None:
    """4 sender x 400 кадр/с, 5 с: max_bytes_held <= 18 662 400, рост private <= 100 МБ."""
    w = make_wiring()
    w.wire()
    flood = make_flood(w.bridge, w.panel, _flood_plan_all())

    flood.run()

    _assert_flood_reached(flood, ratio=0.9)
    held = w.bridge.frame_mailbox.stats()["max_bytes_held"]
    assert held <= _MAX_BYTES_HELD, f"max_bytes_held={held} > {_MAX_BYTES_HELD}"
    assert flood.peak_growth <= _GROWTH_BOUND, (
        f"пик роста private {flood.peak_growth / 2**20:.1f} МБ > {_GROWTH_BOUND / 2**20:.0f} МБ"
    )


def test_overload_last_frame_reaches_screen(make_wiring, make_flood) -> None:
    """После остановки продюсеров на каждом слоте последний принятый кадр — 2000, не позднее чем через 1 с."""
    w = make_wiring()
    w.wire()
    flood = make_flood(w.bridge, w.panel, _flood_plan_all())

    flood.run()

    _assert_flood_reached(flood)
    deadline_from_stop = flood.t_end + _LAST_FRAME_BOUND_S
    _spin_until(
        lambda: all(_screen_no(w.panel, s) == _FLOOD_FRAMES for s in _SENDERS),
        max(deadline_from_stop - time.perf_counter(), 0.0),
    )
    last = {s: _screen_no(w.panel, s) for s in _SENDERS}
    late = time.perf_counter() - flood.t_end
    assert last == {s: 2000 for s in _SENDERS}, f"последние кадры на экране: {last} ({late:.2f} с после остановки)"


def test_qt_timer_ticks_under_overload(make_wiring, make_flood) -> None:
    """Qt-таймер 100 мс под заливкой: не менее 4 тиков в секунду в среднем за весь 5-секундный прогон."""
    w = make_wiring()
    w.wire()
    flood = make_flood(w.bridge, w.panel, _flood_plan_all())
    ticks: list[float] = []
    timer = QTimer()
    timer.setInterval(_TICK_INTERVAL_MS)
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))

    flood.run(on_start=timer.start, on_done=timer.stop)
    timer.stop()

    _assert_flood_reached(flood)
    in_run = [t for t in ticks if flood.t_start <= t <= flood.t_end]
    rate = len(in_run) / flood.elapsed
    assert rate >= _MIN_TICKS_PER_S, f"{len(in_run)} тиков за {flood.elapsed:.2f} с = {rate:.1f}/с < 4/с"


def test_slow_sender_shown_while_fast_floods(make_wiring, make_flood) -> None:
    """1 кадр/с рядом с 300 кадр/с: показано не менее 4 за 5 с."""
    w = make_wiring()
    w.wire()
    plan = {"cam0": (300.0, 1500), "cam1": (1.0, 5)}
    flood = make_flood(w.bridge, w.panel, plan)
    before: dict[str, int] = {}

    flood.run(on_start=lambda: before.update(shown=w.shown("cam1")))
    shown = w.shown("cam1") - before["shown"]

    assert not flood.aborted, f"заливка прервана потолком памяти: {flood.sent}"
    assert flood.sent == {"cam0": 1500, "cam1": 5}, f"предусловие: отправлено {flood.sent}"
    assert shown >= 4, f"медленный sender: показано {shown} из 5 за 5 с (нужно >= 4)"


def test_no_aliasing_22hz_source_limit_20(make_wiring, make_flood) -> None:
    """Источник 22 Гц, предел 20 из рецепта, 3 с: показано от 45 до 63 (не 33)."""
    w = make_wiring()
    w.wire()
    flood = make_flood(w.bridge, w.panel, {"cam0": (22.0, 66)})
    before: dict[str, int] = {}
    after: dict[str, int] = {}

    flood.run(
        on_start=lambda: before.update(shown=w.shown("cam0")), on_done=lambda: after.update(shown=w.shown("cam0"))
    )
    shown = after["shown"] - before["shown"]

    assert flood.sent == {"cam0": 66}, f"предусловие: отправлено {flood.sent}"
    assert 45 <= shown <= 63, f"показано {shown} за 3 с (нужно 45..63, не 33)"


def test_frame_before_callback_shown_after(make_wiring) -> None:
    """Кадр, пришедший в dispatch до создания насоса и первого set_keys, показан первым тиком."""
    w = make_wiring()
    w.bridge.dispatch(_msg("cam0", 7))
    assert w.panel.grab_frame("cam0") is None, "предусловие: до насоса кадр не на экране"

    w.wire()
    _spin_until(lambda: _screen_no(w.panel, "cam0") == 7, 0.5)

    assert _screen_no(w.panel, "cam0") == 7
    assert w.shown("cam0") == 1


def test_state_delta_delivered_under_frame_flood(make_wiring, make_flood) -> None:
    """Дельта состояния доставлена за 1 с при потоке 400 кадр/с на каждого из 4 sender."""
    w = make_wiring()
    w.wire()
    flood = make_flood(w.bridge, w.panel, _flood_plan_all())
    probe: dict[str, float] = {}

    def _on_state(msg: dict) -> None:
        if msg.get("path") == "flood.probe":
            probe.setdefault("t_recv", time.perf_counter())

    w.bridge.state_updated.connect(_on_state)

    def _send_probe() -> None:
        time.sleep(1.0)  # заливка уже идёт
        probe["t_sent"] = time.perf_counter()
        w.bridge.dispatch({"data_type": "state_delta", "path": "flood.probe", "value": 42})

    sender = threading.Thread(target=_send_probe, name="probe-sender", daemon=True)
    flood.run(on_start=sender.start)
    sender.join(2.0)
    _spin_until(lambda: "t_recv" in probe, 5.0)  # дельта, не дошедшая в заливке, доходит позже — это уже провал

    _assert_flood_reached(flood)
    assert "t_sent" in probe, "дельта не отправлена"
    assert "t_recv" in probe, "дельта не доставлена за заливку и 5 с после неё"
    latency = probe["t_recv"] - probe["t_sent"]
    assert latency <= _STATE_BOUND_S, f"дельта доставлена за {latency:.2f} с > {_STATE_BOUND_S} с"


# ---------------------------------------------------------------------------
# Охранные тесты (GUARDS)
# ---------------------------------------------------------------------------


def test_state_delta_delivery_unchanged(make_wiring) -> None:
    """Охранный: state-дельта без перегрузки доходит до state_updated как раньше (с рабочего потока)."""
    w = make_wiring()
    received: list[dict] = []
    w.bridge.state_updated.connect(received.append)

    sender = threading.Thread(
        target=lambda: w.bridge.dispatch({"data_type": "state_delta", "path": "a.b", "value": 3}),
        name="state-sender",
        daemon=True,
    )
    sender.start()
    delivered = _spin_until(lambda: len(received) >= 1, 2.0)
    sender.join(2.0)

    assert delivered, "state-дельта не доставлена за 2 с"
    assert len(received) == 1
    assert received[0]["data_type"] == "state_delta"
    assert received[0]["path"] == "a.b"
    assert received[0]["value"] == 3


def test_frame_with_older_capture_ns_is_shown(make_wiring) -> None:
    """Охранный: кадр с capture_ns 2_000_000_000, затем кадр с capture_ns 1_000_000_000 — второй показан."""
    w = make_wiring()
    w.wire()
    w.bridge.dispatch(_msg("cam0", 1, capture_ns=2_000_000_000))
    assert _spin_until(lambda: _screen_no(w.panel, "cam0") == 1, 1.0), "первый кадр не показан"

    w.bridge.dispatch(_msg("cam0", 2, capture_ns=1_000_000_000))
    _spin_until(lambda: _screen_no(w.panel, "cam0") == 2, 1.0)

    assert _screen_no(w.panel, "cam0") == 2, "кадр со старым capture_ns отброшен"
    assert w.shown("cam0") == 2


def test_item_meta_reaches_sink(make_wiring, qtbot) -> None:
    """Охранный: capture_ns и capture_ts доходят до sink насоса литерально (настоящие ящик и насос)."""
    from multiprocess_framework.modules.frontend_module.bridge.frame_pump import FramePump
    from multiprocess_framework.modules.process_module.generic.latest_mailbox import LatestMailbox

    w = make_wiring()
    mailbox = w.bridge.frame_mailbox
    assert isinstance(mailbox, LatestMailbox)
    w.bridge.dispatch(
        {
            "sender": "cam0",
            "frame": _frame(5),
            "data": {"capture_ns": 123_456_789_012, "capture_ts": 1_700_000_000.25},
        }
    )
    keys = mailbox.pending_keys()
    assert len(keys) == 1, f"ожидали один ожидающий ключ, есть {keys}"

    got: list[tuple[str, Any]] = []
    pump = FramePump(mailbox=mailbox, sink=lambda key, item: got.append((key, item)))
    try:
        pump.set_keys({keys[0]: 60})
        assert _spin_until(lambda: len(got) >= 1, 1.0), "sink не вызван за 1 с"
    finally:
        pump.stop()

    item = got[0][1]
    meta = item if "capture_ns" in item else item["data"]
    assert meta["capture_ns"] == 123_456_789_012
    assert meta["capture_ts"] == 1_700_000_000.25
