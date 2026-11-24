# -*- coding: utf-8 -*-
"""T5 gui-frame-path: тесты гонок отложенной копии кадра из SHM (файл developer-а).

Purpose: копия ссылок SHM делается ТОЛЬКО в Qt-потоке (восстановитель не зовётся из потока приёма),
а два писателя с одним ключом ящика против ``take`` Qt-потока не ломают счёт: ``taken`` ящика ==
показано + ``restore_dropped``, байты чтения == размер кадра x показано, ошибок насоса нет.

Настоящие ``FrameShmMiddleware`` (писатели и читатель gui), ``DataReceiverBridge``, ``FramePump``
(через настоящую ``_setup_bridge_callbacks``) и ``ImagePanelWidget``. Ожидаемые значения здесь
литералы из брифа T5. Каждый вызов, который может зависнуть, — daemon-поток с join-дедлайном.

Запуск (из корня worktree, PYTHONPATH=корень, PYTHONUTF8=1, Qt offscreen):
    bash scripts/machine_gate.sh light inspector-bottles-K \
        ../../../.venv/Scripts/python.exe -m pytest -q --tb=short -p no:cacheprovider \
        multiprocess_prototype/frontend/tests/test_deferred_copy_hazards.py
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
# Литералы (из брифа T5, не из кода)
# ---------------------------------------------------------------------------

_H, _W = 1080, 1440  # кадр 1440x1080x3 uint8
_FRAME_BYTES = 4_665_600
_RING = 8  # кольцо писателя
_SENDER = "cam"  # общий sender обоих писателей -> один ключ ящика и насоса
_FPS_LIMIT = 25.0
_FRAME_MESSAGES = 20  # тест А: сообщений со ссылкой кадра
_WRITER_MESSAGES = 150  # тест Б: сообщений на писателя
_WRITER_PAUSE_S = 0.004  # пауза писателя между сообщениями
_PUMP_RUN_S = 1.5  # тест Б: насос работает не меньше
_JOIN_S = 20.0  # дедлайн join потоков-продюсеров
_MASK_MARK = 77  # метка в массиве mask теста А
_RING_SMALL = 3  # кольцо, которое три записи подряд оборачивают (ссылка устаревает)

_TEMPLATE = np.zeros((_H, _W, 3), dtype=np.uint8)
_MASK_TEMPLATE = np.zeros((_H, _W), dtype=np.uint8)


@pytest.fixture(autouse=True)
def _clean_shm_flags(monkeypatch):
    """Ни одна переменная FW_SHM_* окружения не влияет на тест."""
    for name in [k for k in os.environ if k.startswith("FW_SHM_")]:
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Общие помощники
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


def _ref_wire_msg(writer: Any, data: dict) -> dict:
    """Ссылочное сообщение: strip писателя, круг через pickle (свои данные теста), верхний ``sender``."""
    out = writer.strip_data_frame_on_send({"target": "gui", "type": "data", "channel": "data", "data": data})
    assert out is not None
    msg = pickle.loads(pickle.dumps(out))
    msg["sender"] = _SENDER
    return msg


def _recipe() -> dict:
    """Рецепт: один дисплей ``cam`` и привязка sender ``cam`` -> дисплей ``cam``."""
    return {
        "displays": [
            {"id": _SENDER, "name": _SENDER, "enabled": True, "position": {"x": 0, "y": 0}, "fps_limit": _FPS_LIMIT}
        ],
        "blueprint": {"displays": [{"node_id": f"{_SENDER}.draw.frame", "display_id": _SENDER}]},
    }


class _RecipeManager:
    """Двойник recipe_manager: get_active() -> slug, read_recipe(slug) -> рецепт."""

    def get_active(self) -> str:
        return "t5_hazards"

    def read_recipe(self, slug: str) -> dict:
        assert slug == "t5_hazards"
        return _recipe()


class _Wiring:
    """Настоящие мост + панель; насос появляется после wire() (настоящая _setup_bridge_callbacks)."""

    def __init__(self, qtbot: Any) -> None:
        from multiprocess_prototype.frontend.bridge import DataReceiverBridge
        from multiprocess_prototype.frontend.frame_intake import FrameIntake
        from multiprocess_prototype.frontend.widgets.image_panel.widget import ImagePanelWidget

        self.bridge = DataReceiverBridge()
        self.panel = ImagePanelWidget(slots=[{"id": _SENDER, "label": _SENDER}])
        qtbot.addWidget(self.panel)
        self.window = MagicMock(name="window_mock")
        self.process = SimpleNamespace(
            _bridge=self.bridge,
            _frame_intake=FrameIntake(MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock()),
            _log_info=MagicMock(),
            _log_warning=MagicMock(),
        )

    def wire(self) -> None:
        from multiprocess_prototype.frontend.app import _setup_bridge_callbacks

        _setup_bridge_callbacks(self.process, self.panel, self.window, recipe_manager=_RecipeManager())

    def shown_total(self) -> int:
        return sum(int(v) for v in getattr(self.process, "_shown_by_slot", {}).values())

    def close(self) -> None:
        pump = getattr(self.process, "_frame_pump", None)
        if pump is not None:
            pump.stop()
        QCoreApplication.removePostedEvents(None)


@pytest.fixture()
def shm():
    """Фабрика настоящих ``FrameShmMiddleware`` (по одному ``MemoryManager`` на каждый)."""
    from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import FrameShmMiddleware
    from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager

    made: list[tuple[Any, Any]] = []

    def _make(owner: str, coll: int = _RING) -> Any:
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


def test_restore_runs_only_in_qt_thread(make_wiring, shm) -> None:
    """Восстановитель зовётся только из Qt-потока; не-кадровое сообщение со ссылкой ``mask`` получает массив.

    Обёртка над ``reader.on_receive`` пишет ``threading.get_ident()``; 20 сообщений со ссылкой кадра и
    одно не-кадровое со ссылкой ``mask`` шлются в ``dispatch`` из daemon-потока (поток приёма).
    """
    writer, reader = shm("cam_a"), shm("gui")
    w = make_wiring()
    qt_ident = threading.get_ident()
    idents: list[int] = []

    def _recording_restorer(msg: dict) -> dict | None:
        idents.append(threading.get_ident())
        return reader.on_receive(msg)

    w.bridge.set_frame_restorer(_recording_restorer)
    got: list[Any] = []
    w.bridge.set_command_callback(lambda m: got.append(m))
    w.wire()

    mask = _MASK_TEMPLATE.copy()
    mask[0, 0] = _MASK_MARK
    mask[-1, -1] = _MASK_MARK + 1

    def _produce() -> None:
        frame = _TEMPLATE.copy()
        for n in range(_FRAME_MESSAGES):
            frame[0, 0, 0] = n
            w.bridge.dispatch(_ref_wire_msg(writer, {"frame": frame}))
            time.sleep(0.005)
        w.bridge.dispatch(_ref_wire_msg(writer, {"mask": mask}))  # не-кадровое: уйдёт веткой command

    producer = threading.Thread(target=_produce, name="t5-receive-thread", daemon=True)
    producer.start()
    delivered = _spin_until(lambda: len(got) >= 1 and w.shown_total() >= 1, 10.0)
    producer.join(_JOIN_S)

    assert not producer.is_alive(), "поток приёма не завершился"
    assert delivered, f"не доставлено: command={len(got)}, показано={w.shown_total()}"
    assert len(idents) >= 2, f"восстановитель позван {len(idents)} раз: нужен хотя бы кадр и mask"
    assert set(idents) == {qt_ident}, f"восстановитель вызван из потоков {set(idents)}, Qt-поток {qt_ident}"
    out_mask = got[0]["data"]["mask"]
    assert isinstance(out_mask, np.ndarray)
    assert np.array_equal(out_mask, mask)


def test_counts_consistent_under_concurrent_dispatch(make_wiring, shm) -> None:
    """Два писателя (``cam_a``, ``cam_b``), один ключ ящика: счёт показанных копий сходится.

    ``taken`` ящика == сумма ``_shown_by_slot`` + ``restore_dropped``; ``bytes_read`` читателя ==
    4665600 x показано; ошибок насоса 0. Один ``FrameShmMiddleware`` на два потока не используется
    (кольцо single-writer): у каждого писателя свой экземпляр и свой ``MemoryManager``.

    Что охраняет на деле: счёт показанных без потерь (``bytes_read`` == кадр x показано). Тождество
    с ``restore_dropped`` здесь выполняется тривиально: ``restore_dropped`` == 0 в 4 из 4 запусков,
    кольцо 8 слотов при паузе писателя не успевает перезаписать ссылку. Ветку потерь этот тест не
    исполняет; её покрывает ``test_stale_ref_after_shown_frame_is_not_a_pump_error``.
    """
    writers = [shm("cam_a"), shm("cam_b")]
    reader = shm("gui")
    w = make_wiring()
    w.bridge.set_frame_restorer(reader.on_receive)
    w.wire()
    mailbox = w.bridge.frame_mailbox

    def _produce(writer: Any) -> None:
        frame = _TEMPLATE.copy()
        for n in range(_WRITER_MESSAGES):
            frame[0, 0, 0] = n & 0xFF
            w.bridge.dispatch(_ref_wire_msg(writer, {"frame": frame}))
            time.sleep(_WRITER_PAUSE_S)  # без паузы писатели занимают GIL, и насос берёт 2-3 кадра

    t0 = time.perf_counter()
    producers = [
        threading.Thread(target=_produce, args=(wr,), name=f"t5-writer-{i}", daemon=True)
        for i, wr in enumerate(writers)
    ]
    for p in producers:
        p.start()
    # насос работает не меньше _PUMP_RUN_S, продюсеры к концу завершены (дедлайн join в конце)
    _spin_until(lambda: all(not p.is_alive() for p in producers) and time.perf_counter() - t0 >= _PUMP_RUN_S, _JOIN_S)
    for p in producers:
        p.join(2.0)
    assert all(not p.is_alive() for p in producers), "писатель не завершился"
    _spin_until(lambda: mailbox.stats()["pending"] == 0, 2.0)  # слив: насос взял последнее
    w.process._frame_pump.stop()

    stats = mailbox.stats()
    shown = w.shown_total()
    errors = sum(int(v["errors"]) for v in w.process._frame_pump.stats().values())
    assert stats["put"] == 2 * _WRITER_MESSAGES
    assert stats["pending"] == 0
    assert shown >= 1, "насос ничего не показал"
    assert stats["taken"] == shown + w.bridge.restore_dropped, (
        f"taken={stats['taken']} != показано {shown} + restore_dropped {w.bridge.restore_dropped}"
    )
    assert reader.bytes_read == _FRAME_BYTES * shown, f"bytes_read={reader.bytes_read}, показано {shown}"
    assert errors == 0, f"ошибок насоса {errors}"


def _write_only(writer: Any, n: int) -> None:
    """Записать кадр n в кольцо писателя без отправки: ранее выданные ссылки на этот слот стареют."""
    frame = _TEMPLATE.copy()
    frame[0, 0, 0] = n
    out = writer.strip_data_frame_on_send(
        {"target": "gui", "type": "data", "channel": "data", "data": {"frame": frame}}
    )
    assert out is not None


def test_stale_ref_after_shown_frame_is_not_a_pump_error(make_wiring, shm) -> None:
    """Ссылка устарела ПОСЛЕ показанного кадра: слот держит прежний, sink насоса не бросает.

    Кадр 1 показан. Ссылка кадра 2 отправлена, затем три записи оборачивают кольцо из 3 слотов и
    перезаписывают слот кадра 2. Диспетчер и записи идут в Qt-потоке без цикла событий между ними,
    поэтому насос берёт именно устаревшую ссылку. Охраняет ``if restored is None: return`` в sink
    насоса (app.py): без него ``_on_frame_received(None)`` бросает, и тик считается ошибкой.
    ``shown`` насоса считает тик со stale (2), ``_shown_by_slot`` его не считает (1).
    """
    writer, reader = shm("cam_a", _RING_SMALL), shm("gui", _RING_SMALL)
    w = make_wiring()
    w.bridge.set_frame_restorer(reader.on_receive)
    w.wire()

    def _screen_mark() -> int | None:
        frame = w.panel.grab_frame(_SENDER)
        return None if frame is None else int(np.asarray(frame).reshape(-1)[0])

    first = _TEMPLATE.copy()
    first[0, 0, 0] = 1
    w.bridge.dispatch(_ref_wire_msg(writer, {"frame": first}))
    assert _spin_until(lambda: _screen_mark() == 1, 2.0), "кадр 1 не показан"

    second = _TEMPLATE.copy()
    second[0, 0, 0] = 2
    w.bridge.dispatch(_ref_wire_msg(writer, {"frame": second}))
    for n in (3, 4, 5):
        _write_only(writer, n)  # слот кадра 2 перезаписан: ссылка устарела
    assert _spin_until(lambda: w.bridge.restore_dropped >= 1, 2.0), "устаревшая ссылка не посчитана потерей"

    stats = w.process._frame_pump.stats()[_SENDER]
    assert _screen_mark() == 1, "слот не держит прежний кадр"
    assert int(stats["errors"]) == 0, f"sink бросил на stale-кадре: errors={stats['errors']}"
    assert int(stats["shown"]) == 2, f"shown насоса {stats['shown']}"
    assert w.process._shown_by_slot[_SENDER] == 1


# ---------------------------------------------------------------------------
# Проводка GuiProcess и границы restore_for_show / is_frame_message
# ---------------------------------------------------------------------------


def _make_gui_process(memory_manager: Any) -> Any:
    """``GuiProcess`` с двойниками по образцу test_gui_process.py; ``memory_manager`` None — без памяти."""
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
    process.router_manager = MagicMock()
    process.memory_manager = memory_manager
    return process


def _close_gui_process(process: Any) -> None:
    reader_obj = getattr(process, "_recv_frame_mw", None)
    for fin in (
        getattr(reader_obj, "close_handle_cache", None),
        getattr(reader_obj, "release_owned_memory", None),
        getattr(process.memory_manager, "close_all", None),
    ):
        if fin is not None:
            try:
                fin()
            except Exception:  # noqa: BLE001 — финализатор не маскирует причину падения
                pass


def test_gui_process_sets_restorer_that_copies(qtbot, shm) -> None:
    """``GuiProcess._init_application_threads`` отдаёт мосту восстановитель-КОПИЮ: массив свой и записываемый."""
    from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager

    writer = shm("cam_a")
    process = _make_gui_process(MemoryManager())
    try:
        process._init_application_threads()
        frame = _TEMPLATE.copy()
        frame[0, 0, 0] = 9
        frame[5, 7, 2] = 123
        out = process._bridge.restore_for_show(_ref_wire_msg(writer, {"frame": frame}))

        assert out is not None, "восстановитель не отдан мосту: ссылка не восстановлена"
        assert np.array_equal(out["frame"], frame)
        # view на слот кольца read-only; копия, которую держит presenter, записываема
        assert out["frame"].flags.writeable, "кадр — view на слот кольца, а не копия"
        assert process._bridge.restore_dropped == 0
    finally:
        _close_gui_process(process)


def test_gui_process_without_memory_has_no_restorer(qtbot) -> None:
    """Без ``memory_manager`` читателя нет: мост создан, ссылка считается потерей, процесс не падает."""
    process = _make_gui_process(None)
    try:
        process._init_application_threads()

        assert process._recv_frame_mw is None
        out = process._bridge.restore_for_show({"sender": _SENDER, "data": {"_shm_refs": {"frame": {"name": "x"}}}})
        assert out is None
        assert process._bridge.restore_dropped == 1
    finally:
        _close_gui_process(process)


def test_restorer_exception_is_pump_error_not_swallowed(make_wiring) -> None:
    """Исключение восстановителя не перехватывается мостом: его считает насос в ``errors``; следующий кадр показан."""
    w = make_wiring()
    state = {"raise": True}
    shown_frame = np.zeros((8, 8, 3), dtype=np.uint8)

    def _restorer(msg: dict) -> dict | None:
        if state["raise"]:
            raise RuntimeError("t5 hazard: restorer failed")
        return {"sender": _SENDER, "frame": shown_frame, "data": {}}

    w.bridge.set_frame_restorer(_restorer)
    w.wire()
    ref_msg = {"sender": _SENDER, "data": {"_shm_refs": {"frame": {"name": "x"}}}}
    w.bridge.dispatch(ref_msg)
    pump = w.process._frame_pump
    assert _spin_until(lambda: int(pump.stats()[_SENDER]["errors"]) >= 1, 2.0), "насос не посчитал исключение"
    assert w.bridge.restore_dropped == 0, "исключение посчитано как потеря копии"
    assert w.shown_total() == 0

    state["raise"] = False
    w.bridge.dispatch(dict(ref_msg))
    assert _spin_until(lambda: w.shown_total() == 1, 2.0), "насос не пережил исключение восстановителя"


def test_malformed_refs_are_not_frames_and_pass_untouched(make_wiring) -> None:
    """Кривые ``data``/``_shm_refs`` не кадр; без непустых ссылок ``restore_for_show`` отдаёт тот же объект."""
    from multiprocess_prototype.frontend.bridge_impl import is_frame_message

    w = make_wiring()
    calls: list[dict] = []
    w.bridge.set_frame_restorer(lambda m: calls.append(m) or m)
    cases = [
        {"data": None},
        {"data": [1, 2]},
        {"data": {}},
        {"data": {"_shm_refs": None}},
        {"data": {"_shm_refs": {}}},
        {"data": {"_shm_refs": "frame"}},  # строка: "frame" in "frame" было бы True
        {"data": {"_shm_refs": ["frame"]}},
        {"data": {"_shm_refs": {"mask": {"name": "x"}}}},
    ]
    for msg in cases:
        assert not is_frame_message(msg), f"принято за кадр: {msg}"
    for msg in cases[:5]:  # data не dict / нет непустых ссылок; остальные ссылки имеют и уйдут восстановителю
        assert w.bridge.restore_for_show(msg) is msg, f"сообщение изменено: {msg}"
    assert calls == [], f"восстановитель позван для сообщений без ссылок: {calls}"
    assert w.bridge.restore_dropped == 0


@pytest.mark.parametrize(
    ("data_type", "set_cb"),
    [("status", "set_state_callback"), ("observability_record", "set_observability_callback")],
)
def test_state_and_observability_refs_restored_or_dropped_in_qt(make_wiring, data_type: str, set_cb: str) -> None:
    """Не-кадровые виды ``state``/``observability`` со ссылками: колбэк получает массив, потеря — без колбэка."""
    w = make_wiring()
    plane = _MASK_TEMPLATE.copy()
    plane[0, 0] = _MASK_MARK
    idents: list[int] = []

    def _restorer(msg: dict) -> dict | None:
        idents.append(threading.get_ident())
        if msg["data"].get("lost"):
            return None
        msg["data"]["mask"] = plane
        return msg

    w.bridge.set_frame_restorer(_restorer)
    got: list[dict] = []
    getattr(w.bridge, set_cb)(got.append)

    ref = {"name": "x"}
    w.bridge.dispatch({"data_type": data_type, "data": {"lost": True, "_shm_refs": {"mask": ref}}})
    w.bridge.dispatch({"data_type": data_type, "data": {"_shm_refs": {"mask": ref}}})
    assert _spin_until(lambda: len(got) >= 1 and w.bridge.qt_pending == 0, 2.0), "колбэк не вызван"

    assert len(got) == 1, f"колбэк получил {len(got)} сообщений, потерянное не должно дойти"
    assert np.array_equal(got[0]["data"]["mask"], plane)
    assert w.bridge.restore_dropped == 1
    assert set(idents) == {threading.get_ident()}


def test_failed_restore_does_not_show_inline_frame_of_same_message(make_wiring) -> None:
    """Сообщение с inline ``frame`` и потерянной ссылкой ``mask``: потеря целиком, кадр на экран не попадает."""
    w = make_wiring()
    w.bridge.set_frame_restorer(lambda _msg: None)
    w.wire()
    inline = np.zeros((8, 8, 3), dtype=np.uint8)
    w.bridge.dispatch({"sender": _SENDER, "frame": inline, "data": {"_shm_refs": {"mask": {"name": "x"}}}})

    assert _spin_until(lambda: w.bridge.restore_dropped == 1, 2.0), "насос не взял сообщение"
    assert w.panel.grab_frame(_SENDER) is None, "inline-кадр потерянного сообщения показан"
    assert w.shown_total() == 0


def test_inline_message_without_restorer_passes_and_is_not_counted() -> None:
    """Мост без восстановителя: сообщение без ссылок идёт как есть (тот же объект), потерей не считается."""
    from multiprocess_prototype.frontend.bridge import DataReceiverBridge

    bridge = DataReceiverBridge()
    msg = {"sender": _SENDER, "frame": np.zeros((2, 2, 3), dtype=np.uint8), "data": {"capture_ns": 1}}

    assert bridge.restore_for_show(msg) is msg
    assert bridge.restore_dropped == 0
