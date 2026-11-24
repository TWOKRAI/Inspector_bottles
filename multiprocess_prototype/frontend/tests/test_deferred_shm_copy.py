# -*- coding: utf-8 -*-
"""T5 gui-frame-path: приёмка отложенной копии кадра из SHM в gui (слепые тесты, до кода).

Purpose: настоящие ``FrameShmMiddleware`` (писатель и читатель gui), ``DataReceiverBridge``,
``LatestMailbox`` (``bridge.frame_mailbox``), ``FramePump`` и ``ImagePanelWidget``: сообщение с
ссылками на SHM копируется в gui только тогда, когда насос берёт его на показ (в потоке Qt);
сообщение без ссылок проходит как раньше; нечитаемая ссылка роняет сообщение целиком и
считается в ``bridge.restore_dropped``; ящик не держит байты кадров.

Контракт (из брифа T5, не из кода): ``DataReceiverBridge.set_frame_restorer(fn)``,
``DataReceiverBridge.restore_for_show(msg) -> dict | None``, свойство ``restore_dropped``,
``is_frame_message(msg)`` истинна и для ``msg["data"]["_shm_refs"]`` с ключом ``"frame"``.
Номер кадра лежит в пикселе ``[0, 0]`` (байты 0 и 1). «Экран» в этих тестах — сырой кадр
``_last_frames`` (``panel.grab_frame``), а не pixmap. Ожидаемые значения здесь литералы.

Запуск (из корня worktree, PYTHONPATH=корень, PYTHONUTF8=1, Qt offscreen):
    bash scripts/machine_gate.sh light inspector-bottles-K \
        ../../../.venv/Scripts/python.exe -m pytest -q --tb=short -p no:cacheprovider \
        multiprocess_prototype/frontend/tests/test_deferred_shm_copy.py
"""

from __future__ import annotations

import gc
import os
import pickle
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

# ---------------------------------------------------------------------------
# Литералы приёмки (из брифа T5, не из кода)
# ---------------------------------------------------------------------------

_H, _W = 1080, 1440  # кадр 1440x1080x3 uint8
_FRAME_BYTES = 4_665_600  # 1440 * 1080 * 3
_SENDERS = ("cam0", "cam1", "cam2", "cam3")  # sender == id дисплея == ключ насоса
_FPS_LIMIT = 25.0  # предел дисплея из рецепта
_RING_BIG = 8  # глубина кольца писателя в тесте счёта копий и пачки
_RING_SMALL = 3  # глубина кольца там, где нужна устаревшая ссылка
_MESSAGES = 400  # сообщений в тесте счёта копий
_INTERVAL_S = 0.0025  # шаг продюсера 2,5 мс
_BATCH = (36, 36, 35, 35)  # сообщений по четырём sender в пачке (всего 142)
_BATCH_BYTES = 18_662_400  # 4 копии по 4 665 600 байт
_SHOW_BOUND_S = 1.0  # кадр на экране не позднее 1 с

_TEMPLATE = np.zeros((_H, _W, 3), dtype=np.uint8)
_TEMPLATE_2D = np.zeros((_H, _W), dtype=np.uint8)


@pytest.fixture(autouse=True)
def _clean_shm_flags(monkeypatch):
    """Ни одна переменная FW_SHM_* окружения не влияет на тест."""
    for name in [k for k in os.environ if k.startswith("FW_SHM_")]:
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Кадры, сообщения со ссылками и чтение номера с экрана
# ---------------------------------------------------------------------------


def _frame(n: int) -> np.ndarray:
    """Новый кадр 1440x1080x3 с номером n в пикселе [0, 0] (байт 0 — младший, байт 1 — старший)."""
    f = _TEMPLATE.copy()
    f[0, 0, 0] = n & 0xFF
    f[0, 0, 1] = (n >> 8) & 0xFF
    return f


def _plane(n: int) -> np.ndarray:
    """Новый uint8-массив 1080x1440 с номером n в байтах 0 и 1."""
    p = _TEMPLATE_2D.copy()
    p[0, 0] = n & 0xFF
    p[0, 1] = (n >> 8) & 0xFF
    return p


def _frame_no(frame: Any) -> int | None:
    """Номер кадра из байтов 0 и 1 или None, если кадра нет."""
    if frame is None:
        return None
    flat = np.asarray(frame).reshape(-1)
    return int(flat[0]) + 256 * int(flat[1])


def _screen_no(panel: Any, slot: str) -> int | None:
    """Номер последнего кадра, дошедшего до экрана слота (сырой кадр, не pixmap)."""
    return _frame_no(panel.grab_frame(slot))


def _inline_msg(sender: str, n: int) -> dict:
    """Сообщение кадра без ссылок: sender, frame, data{capture_ns, capture_ts}."""
    cap = 1_000_000_000 + n * 1_000_000
    return {"sender": sender, "frame": _frame(n), "data": {"capture_ns": cap, "capture_ts": cap / 1e9}}


def _wire_of(writer: Any, sender: str, item: dict) -> dict:
    """Ссылочное сообщение: strip писателя, круг через pickle, плюс верхний ``sender``."""
    out = writer.strip_data_frame_on_send({"target": "gui", "type": "data", "channel": "data", "data": item})
    assert out is not None
    msg = pickle.loads(pickle.dumps(out))
    msg["sender"] = sender
    return msg


def _ref_msg(writer: Any, sender: str, n: int) -> dict:
    """Ссылочное сообщение кадра n (frame уходит ссылкой, в item ещё метки захвата)."""
    cap = 1_000_000_000 + n * 1_000_000
    return _wire_of(writer, sender, {"frame": _frame(n), "capture_ns": cap, "capture_ts": cap / 1e9})


def _write_only(writer: Any, n: int) -> None:
    """Записать кадр n в кольцо писателя без отправки (ссылки на старые кадры стареют)."""
    out = writer.strip_data_frame_on_send(
        {"target": "gui", "type": "data", "channel": "data", "data": {"frame": _frame(n)}}
    )
    assert out is not None


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
# Настоящий SHM: писатели и читатель gui
# ---------------------------------------------------------------------------


@pytest.fixture()
def shm():
    """Фабрика настоящих ``FrameShmMiddleware``; финализаторы как в test_frame_ref_atomic_item."""
    from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import FrameShmMiddleware
    from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager

    made: list[tuple[Any, Any]] = []

    def _make(owner: str, coll: int = _RING_BIG) -> Any:
        mm = MemoryManager()
        mw = FrameShmMiddleware(mm, owner=owner, slot="output_frames", coll=coll)
        made.append((mw, mm))
        return mw

    yield _make
    gc.collect()
    for mw, mm in reversed(made):
        for fin in (mw.close_handle_cache, mw.release_owned_memory, mm.close_all):
            try:
                fin()
            except Exception:  # noqa: BLE001 — финализатор не маскирует причину падения
                pass


def _set_restorer(bridge: Any, reader: Any) -> None:
    """Как в gui: мосту отдаётся ``reader.on_receive`` (новый API — падение внутри теста)."""
    bridge.set_frame_restorer(reader.on_receive)


# ---------------------------------------------------------------------------
# Стенд из настоящих объектов (как _Wiring в test_frame_overload_real_objects)
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
        return "t5_recipe"

    def read_recipe(self, slug: str) -> dict:
        assert slug == "t5_recipe"
        return self._recipe


class _Wiring:
    """Настоящие мост + панель; насос появляется после wire() (настоящая _setup_bridge_callbacks)."""

    def __init__(self, qtbot: Any) -> None:
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge
        from multiprocess_prototype.frontend.frame_intake import FrameIntake
        from multiprocess_prototype.frontend.widgets.image_panel.widget import ImagePanelWidget

        self.bridge = DataReceiverBridge()
        self.panel = ImagePanelWidget(slots=[{"id": s, "label": s} for s in _SENDERS])
        qtbot.addWidget(self.panel)
        self.window = MagicMock(name="window_mock")
        self.process = SimpleNamespace(
            _bridge=self.bridge,
            _frame_intake=FrameIntake(MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock()),
            _log_info=MagicMock(),
            _log_warning=MagicMock(),
        )

    def wire(self, fps_limit: float = _FPS_LIMIT) -> None:
        """Настоящая _setup_bridge_callbacks: предел берётся из рецепта."""
        from multiprocess_prototype.frontend.app import _setup_bridge_callbacks

        _setup_bridge_callbacks(
            self.process, self.panel, self.window, recipe_manager=_RecipeManager(_recipe(fps_limit))
        )

    def shown(self, slot: str) -> int:
        """Счётчик показанных кадров слота в процессе (``_shown_by_slot``)."""
        return int(getattr(self.process, "_shown_by_slot", {}).get(slot, 0))

    def close(self) -> None:
        pump = getattr(self.process, "_frame_pump", None)
        if pump is not None:
            pump.stop()
        QCoreApplication.removePostedEvents(None)


@pytest.fixture()
def make_wiring(qtbot, shm):
    """Фабрика стендов; зависит от ``shm``, чтобы насос останавливался раньше закрытия SHM."""
    made: list[_Wiring] = []

    def _make() -> _Wiring:
        w = _Wiring(qtbot)
        made.append(w)
        return w

    yield _make
    for w in made:
        w.close()
    gc.collect()


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


def test_only_shown_frames_are_copied(make_wiring, shm) -> None:
    """Один sender, 400 ссылочных сообщений по 2,5 мс, кольцо 8, предел 25 к/с: копий не больше показанного.

    ``copies = bytes_read / 4665600`` целое; ``put`` 400; ``copies <= 25 * elapsed_s + 2``;
    ``copies >= 10`` (защита от голодания потока Qt под GIL, не проверка устаревания);
    ``_shown_by_slot`` равен ``copies``.
    """
    writer, reader = shm("cam0", _RING_BIG), shm("gui", _RING_BIG)
    w = make_wiring()
    _set_restorer(w.bridge, reader)
    w.wire()
    mailbox = w.bridge.frame_mailbox
    sent: dict[str, int] = {"n": 0}

    def _produce(t0: float) -> None:
        for n in range(1, _MESSAGES + 1):
            due = t0 + n * _INTERVAL_S
            while True:
                rest = due - time.perf_counter()
                if rest <= 0:
                    break
                time.sleep(rest - 0.002 if rest > 0.003 else 0)
            w.bridge.dispatch(_ref_msg(writer, "cam0", n))
            sent["n"] = n

    t0 = time.perf_counter()
    producer = threading.Thread(target=_produce, args=(t0,), name="t5-producer", daemon=True)
    producer.start()
    finished = _spin_until(lambda: not producer.is_alive(), 30.0)
    producer.join(2.0)
    assert finished and sent["n"] == _MESSAGES, f"предусловие: продюсер отправил {sent['n']} из {_MESSAGES}"
    _spin_until(lambda: mailbox.stats()["pending"] == 0, 2.0)  # дренаж: насос взял последнее
    elapsed_s = time.perf_counter() - t0
    w.process._frame_pump.stop()

    stats = mailbox.stats()
    bytes_read = reader.bytes_read
    copies = bytes_read // _FRAME_BYTES
    print(f"copies={copies} elapsed_s={elapsed_s:.3f}")
    assert bytes_read % _FRAME_BYTES == 0, f"bytes_read={bytes_read} не кратно размеру кадра {_FRAME_BYTES}"
    assert stats["put"] == _MESSAGES
    assert copies <= 25 * elapsed_s + 2, f"копий {copies} за {elapsed_s:.2f} с: больше показанного предела"
    assert copies >= 10, f"копий {copies} < 10: поток Qt не получил времени"
    assert w.shown("cam0") == copies, f"показано {w.shown('cam0')}, скопировано {copies}"


def test_ref_without_restorer_is_counted_not_shown(make_wiring, shm) -> None:
    """Ссылочное сообщение кадра 3 без восстановителя: ``restore_for_show`` даёт None, drop посчитан, слот пуст."""
    writer = shm("cam0", _RING_SMALL)
    # часть А: прямой вызов на голом мосту
    from multiprocess_prototype.frontend.bridge import DataReceiverBridge

    bare = DataReceiverBridge()
    result = bare.restore_for_show(_ref_msg(writer, "cam0", 3))
    assert result is None
    assert bare.restore_dropped == 1

    # часть Б: через настоящую _setup_bridge_callbacks слот остаётся пустым
    w = make_wiring()
    w.wire()
    w.bridge.dispatch(_ref_msg(writer, "cam0", 3))
    dropped = _spin_until(lambda: w.bridge.restore_dropped >= 1, _SHOW_BOUND_S)

    assert dropped, "насос не взял сообщение за 1 с"
    assert w.bridge.restore_dropped == 1
    assert w.panel.grab_frame("cam0") is None
    assert w.shown("cam0") == 0


def test_stale_ref_counted_next_frame_shown(make_wiring, shm) -> None:
    """Кольцо 3: ссылка кадра 1 устарела (кадры 2-4 записаны) -> stale 1, drop 1, слот пуст; кадр 5 показан за 1 с."""
    writer, reader = shm("cam0", _RING_SMALL), shm("gui", _RING_SMALL)
    w = make_wiring()
    _set_restorer(w.bridge, reader)
    w.bridge.dispatch(_ref_msg(writer, "cam0", 1))  # до насоса
    for n in (2, 3, 4):
        _write_only(writer, n)  # кольцо обернулось, ссылка кадра 1 устарела

    w.wire()
    dropped = _spin_until(lambda: w.bridge.restore_dropped >= 1, _SHOW_BOUND_S)

    assert dropped, "насос не взял сообщение кадра 1 за 1 с"
    assert reader.frame_stale_drops == 1
    assert w.bridge.restore_dropped == 1
    assert w.panel.grab_frame("cam0") is None

    w.bridge.dispatch(_ref_msg(writer, "cam0", 5))
    _spin_until(lambda: _screen_no(w.panel, "cam0") == 5, _SHOW_BOUND_S)
    assert _screen_no(w.panel, "cam0") == 5, "следующий кадр после отброшенного не показан за 1 с"


def test_inline_frame_still_shown(make_wiring, shm) -> None:
    """Охранный: кадр без ссылок проходит как раньше, читатель его не копирует (``bytes_read`` 0)."""
    reader = shm("gui", _RING_SMALL)
    w = make_wiring()
    _set_restorer(w.bridge, reader)
    w.wire()

    w.bridge.dispatch(_inline_msg("cam0", 7))
    _spin_until(lambda: _screen_no(w.panel, "cam0") == 7, _SHOW_BOUND_S)

    assert _screen_no(w.panel, "cam0") == 7
    assert w.shown("cam0") == 1
    assert reader.bytes_read == 0


def test_batch_of_142_holds_no_frame_bytes(make_wiring, shm) -> None:
    """142 ссылочных сообщения четырёх sender до насоса: ящик держит 4, байтов кадров 0; после wire номера и 4 копии."""
    writers = {s: shm(s, _RING_BIG) for s in _SENDERS}
    reader = shm("gui", _RING_BIG)
    w = make_wiring()
    _set_restorer(w.bridge, reader)
    counts = dict(zip(_SENDERS, _BATCH, strict=True))
    for n in range(1, max(_BATCH) + 1):  # по кругу: как пачка из очереди процесса
        for s in _SENDERS:
            if n <= counts[s]:
                w.bridge.dispatch(_ref_msg(writers[s], s, n))

    stats = w.bridge.frame_mailbox.stats()
    assert stats["put"] == 142
    assert stats["pending"] == 4
    assert stats["superseded"] == 138
    assert stats["max_bytes_held"] == 0
    assert reader.bytes_read == 0

    w.wire()
    _spin_until(lambda: all(w.panel.grab_frame(s) is not None for s in _SENDERS), _SHOW_BOUND_S)

    assert {s: _screen_no(w.panel, s) for s in _SENDERS} == {"cam0": 36, "cam1": 36, "cam2": 35, "cam3": 35}
    assert reader.bytes_read == _BATCH_BYTES


def test_one_unreadable_ref_drops_whole_message(make_wiring, shm) -> None:
    """Ссылки ``frame`` и ``mask`` (uint8 1080x1440), кольцо 3, три записи ``mask``: сообщение отброшено целиком."""
    writer, reader = shm("cam0", _RING_SMALL), shm("gui", _RING_SMALL)
    w = make_wiring()
    _set_restorer(w.bridge, reader)
    w.bridge.dispatch(_wire_of(writer, "cam0", {"frame": _plane(1), "mask": _plane(1)}))
    for n in (2, 3, 4):
        writer.strip_data_frame_on_send(
            {"target": "gui", "type": "data", "channel": "data", "data": {"mask": _plane(n)}}
        )  # кольцо mask обернулось: ссылка mask сообщения 1 устарела

    w.wire()
    dropped = _spin_until(lambda: w.bridge.restore_dropped >= 1, _SHOW_BOUND_S)

    assert dropped, "насос не взял сообщение за 1 с"
    assert w.bridge.restore_dropped == 1
    assert reader.frame_stale_drops == 1
    assert w.panel.grab_frame("cam0") is None, "frame отброшенного сообщения попал на экран"
    assert w.shown("cam0") == 0

    w.bridge.dispatch(_wire_of(writer, "cam0", {"frame": _plane(5), "mask": _plane(5)}))
    _spin_until(lambda: _screen_no(w.panel, "cam0") == 5, _SHOW_BOUND_S)
    assert _screen_no(w.panel, "cam0") == 5, "целое сообщение после отброшенного не показано за 1 с"


def test_ref_message_is_frame_message(shm) -> None:
    """``is_frame_message`` истинна для сообщения с ``data["_shm_refs"]["frame"]`` (и ложна для state-дельты)."""
    from multiprocess_prototype.frontend.bridge_impl import is_frame_message

    writer = shm("cam0", _RING_SMALL)
    msg = _ref_msg(writer, "cam0", 1)
    assert "frame" in msg["data"]["_shm_refs"], "предусловие: frame ушёл ссылкой"

    assert is_frame_message(msg)
    assert not is_frame_message({"data_type": "state_delta", "path": "a.b", "value": 3})


def test_gui_registers_no_receive_middleware(qtbot) -> None:
    """Читатель в ``register_frame_middleware``; его ``on_receive`` не в ``add_receive_middleware``."""
    from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager
    from multiprocess_prototype.frontend.process import GuiProcess

    sr = MagicMock()
    sr.get_process_data.return_value = None
    sr.update_process_state.return_value = None
    sr.get_system_stop_event.return_value = None
    sr.process_state_registry = MagicMock()
    process = GuiProcess(name="gui", shared_resources=sr)
    process._init_configuration = MagicMock()
    process._init_queues = MagicMock()
    process._init_managers = MagicMock()
    process._init_communication = MagicMock()
    process._register_process_state = MagicMock()
    process._init_system_threads = MagicMock()
    process._init_custom_managers = MagicMock()
    process.update_process_state = MagicMock()
    process.worker_manager = MagicMock()
    process.router_manager = MagicMock()  # без router_manager и memory_manager ветка читателя пропускается
    process.memory_manager = MemoryManager()
    try:
        process._init_application_threads()

        reader = process._recv_frame_mw
        register = process.router_manager.register_frame_middleware
        assert register.call_count == 1
        reg_args = (*register.call_args.args, *register.call_args.kwargs.values())
        assert any(a is reader for a in reg_args), f"register_frame_middleware вызван не с читателем: {reg_args}"
        for call in process.router_manager.add_receive_middleware.call_args_list:
            args = (*call.args, *call.kwargs.values())
            assert not any(a == reader.on_receive for a in args), "on_receive читателя добавлен в receive-цепочку"
    finally:
        reader_obj = getattr(process, "_recv_frame_mw", None)
        for fin in (
            getattr(reader_obj, "close_handle_cache", None),
            getattr(reader_obj, "release_owned_memory", None),
            process.memory_manager.close_all,
        ):
            if fin is not None:
                try:
                    fin()
                except Exception:  # noqa: BLE001 — финализатор не маскирует причину падения
                    pass


def test_presenter_keeps_own_copy_after_slot_overwrite(make_wiring, shm) -> None:
    """Кольцо 3: кадр 9 показан по ссылке, три записи поверх -> экран и ``get_last_frame`` всё ещё дают 9."""
    writer, reader = shm("cam0", _RING_SMALL), shm("gui", _RING_SMALL)
    w = make_wiring()
    _set_restorer(w.bridge, reader)
    w.wire()
    w.bridge.dispatch(_ref_msg(writer, "cam0", 9))
    _spin_until(lambda: _screen_no(w.panel, "cam0") == 9, _SHOW_BOUND_S)
    assert _screen_no(w.panel, "cam0") == 9, "предусловие: кадр 9 показан"

    for n in (10, 11, 12):
        _write_only(writer, n)  # слот кадра 9 перезаписан

    assert _screen_no(w.panel, "cam0") == 9
    assert _frame_no(w.panel._presenter.get_last_frame("cam0")) == 9
