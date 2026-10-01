# -*- coding: utf-8 -*-
"""Task 4.1 (transport-single-policy) — приёмка «claim check по размеру под ЛЮБЫМ ключом»,
часть про ПРИЁМ В ПАЙПЛАЙНЕ (C3) и ЗАЙМЫ при loan-протоколе (C5).

Независимый тест-автор (tester), от контракта C1-C8 плана, БЕЗ чтения реализации.
Парный файл: ``router_module/tests/test_claim_check_any_key.py`` (C1, C2, C4, C6, C7, C8).

C3 — приём в пайплайне. Потребитель = ОТДЕЛЬНЫЙ ОС-процесс (multiprocessing spawn) со своим
``MemoryManager`` и НАСТОЯЩИМ ``DataReceiver.run_loop`` (тот же ``restore_frame`` + тот же
``_build_item``, что в проде). Массивы возвращаются родителю как bytes + shape + dtype.

C5 — займы. Loan-протокол ВКЛ теми же флагами, что в ``test_g5d_loan.py`` (+ zero-copy
потребитель, как в проде, чтобы у него вообще появлялись тикеты). «Потребитель закончил»
ведётся ПРОДОВЫМ путём, ничего не выдумано:
  тикеты — ``PipelineExecutor._collect_view_tickets`` / ``_accumulate_releases`` /
  ``_flush_releases`` (pipeline_executor.py:265-330) ->
  доставка владельцу — ``GenericProcess._handle_shm_release`` (generic_process.py:340-358) ->
  ``release_slots``; вытеснение — ``RouterManager._on_frame_evicted`` -> тот же handler
  (``evicted=True``); мёртвый читатель — ``GenericProcess._handle_shm_reclaim`` -> ``reclaim_reader``.
Что займов не осталось, видно по публичным следствиям, формат билета не пинится:
кольца, полные до отпуска (следующий send = None, ``frame_loan_exhausted`` растёт), после
отпуска снова принимают ровно столько же; счётчики ``frame_slots_released`` /
``frame_loans_released_on_evict`` / ``frame_slots_reclaimed`` равны ЧИСЛУ ССЫЛОК (по одной на
каждый крупный ключ каждого сообщения: «каждая ссылка — отдельный заём»).

ВАЖНО для реализующего. Тест предполагает, что «штатная обработка потребителем» = тикеты
из ``PipelineExecutor._collect_view_tickets`` для КАЖДОЙ ссылки item'а (не только ``frame``)
и они доходят до ``release_slots`` владельца. Если ссылки не-``frame`` ключей отпускаются
иначе (копия + немедленный release, другой конвейер) — нужно выставить эквивалентную
поверхность и переписать ЭТОТ шаг теста, а не пинить внутренний формат.
"""

from __future__ import annotations

import gc
import multiprocessing
import os
import pickle
import queue
import threading
import time
import traceback
from typing import Any, Callable

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.generic.data_receiver import DataReceiver
from multiprocess_framework.modules.process_module.generic.generic_process import GenericProcess
from multiprocess_framework.modules.process_module.generic.pipeline_executor import PipelineExecutor
from multiprocess_framework.modules.router_module.core.router_manager import RouterManager
from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import (
    FrameShmMiddleware,
)
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import (
    MemoryManager,
)

# --- литералы контракта -------------------------------------------------------------
BY_REF_MIN_NBYTES = 8192  # nbytes >= 8192 -> ссылкой
MSG_MAX_PICKLE_BYTES = 16384  # всё data-сообщение после send-middleware

DEADLINE_S = 30.0  # потолок на любой сценарий в этом процессе
CHILD_RESULT_TIMEOUT_S = 45.0  # потолок на ответ дочернего процесса

# Формы ключей: у каждого nbytes >= 8192, формы и dtype разные (ADR-SRM-017: (H,W), (H,W,1), (H,W,3)).
SHAPES: dict[str, tuple[tuple[int, ...], str]] = {
    "frame": ((48, 64, 3), "uint8"),  # 9216 Б
    "foo": ((100, 100), "uint8"),  # 10000 Б
    "mask": ((100, 120), "uint16"),  # 24000 Б
    "depth": ((64, 80, 1), "float32"),  # 20480 Б
}


# --- общие помощники ----------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clean_shm_flags(monkeypatch):
    """Флаги SHM берутся ТОЛЬКО из теста: env разработчика не должен менять поведение."""
    for name in [k for k in os.environ if k.startswith("FW_SHM_")]:
        monkeypatch.delenv(name, raising=False)


def _bounded(fn: Callable[[], Any], seconds: float = DEADLINE_S) -> Any:
    """Выполнить ``fn`` в daemon-потоке с дедлайном; зависание = FAIL, а не висящий прогон."""
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в основной поток
            box["error"] = exc

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        pytest.fail(f"сценарий завис (> {seconds} с) — блокирующий вызов")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _arr(key: str, seed: int = 0, shape: tuple[int, ...] | None = None) -> np.ndarray:
    """Детерминированное «случайное» содержимое: побайтное сравнение ловит перепутанные ключи."""
    base_shape, dtype = SHAPES[key]
    rng = np.random.default_rng(seed)
    shp = shape or base_shape
    if np.dtype(dtype).kind == "f":
        return rng.random(shp).astype(dtype)
    return rng.integers(0, 250, size=shp).astype(dtype)


def _big_arrays(obj: Any, path: str = "msg") -> list[tuple[str, int]]:
    """Все ndarray с nbytes >= порога внутри сообщения на ЛЮБОЙ глубине (dict/list/tuple/set)."""
    found: list[tuple[str, int]] = []
    if isinstance(obj, np.ndarray):
        if obj.nbytes >= BY_REF_MIN_NBYTES:
            found.append((path, int(obj.nbytes)))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            found += _big_arrays(v, f"{path}[{k!r}]")
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for i, v in enumerate(obj):
            found += _big_arrays(v, f"{path}[{i}]")
    return found


def _assert_small_wire(out: dict) -> None:
    big = _big_arrays(out)
    assert big == [], f"в сообщении остались крупные ndarray (едут inline): {big}"
    size = len(pickle.dumps(out))
    assert size <= MSG_MAX_PICKLE_BYTES, f"len(pickle.dumps(msg)) = {size} > {MSG_MAX_PICKLE_BYTES}"


def _send(mw: FrameShmMiddleware, item: dict, target: str = "t") -> dict | None:
    return mw.strip_data_frame_on_send({"target": target, "type": "data", "channel": "data", "data": item})


def _wire(msg: dict) -> dict:
    return pickle.loads(pickle.dumps(msg))  # провод очереди: получатель видит независимую копию


@pytest.fixture
def made_mws():
    """Реестр middleware/MemoryManager для гарантированной уборки SHM (Windows: сегменты текут)."""
    made: list[tuple[FrameShmMiddleware, MemoryManager, bool]] = []
    yield made
    gc.collect()  # view-массивы должны умереть до close, иначе BufferError на закрытии mmap
    for mw, mm, owned in made:
        fins = [mw.close_handle_cache] + ([mw.release_owned_memory] if owned else []) + [mm.close_all]
        for fin in fins:
            try:
                fin()
            except Exception:  # noqa: BLE001 — финализатор не должен маскировать причину падения теста
                pass


def _owner(made_mws, name: str = "own", *, coll: int = 4, num_consumers: int = 1) -> FrameShmMiddleware:
    """Владелец, собранный как в GenericProcess:207-213."""
    mm = MemoryManager()
    mw = FrameShmMiddleware(memory_manager=mm, owner=name, slot="output_frames", coll=coll, num_consumers=num_consumers)
    made_mws.append((mw, mm, True))
    return mw


# ============================ C3: приём в пайплайне (другой ОС-процесс) ============================
def _child_pipeline_receive(wires: list[bytes], out_q) -> None:
    """Дочерний процесс-потребитель. Верхнего уровня — spawn пиклит цель по dotted-пути.

    НАСТОЯЩИЙ ``DataReceiver.run_loop`` (тот же restore_frame + _build_item, что в проде)
    поверх собственного ``MemoryManager``. Результат: по каждому item — массивы как
    (bytes, shape, dtype) и имена/типы остальных полей.
    """
    try:
        mm = MemoryManager()
        mw = FrameShmMiddleware(mm, owner="consumer", slot="unused")
        pending = list(wires)
        items: list[dict] = []

        def receive_fn(timeout: float = 0.05, channel_types=None, return_messages: bool = True):
            if pending:
                return pickle.loads(pending.pop(0))
            time.sleep(min(float(timeout), 0.05))
            return None

        class _Collector:
            def on_item(self, item: dict) -> None:
                items.append(item)

            def check_timeouts(self) -> None:
                return None

        recv = DataReceiver(
            receive_fn=receive_fn,
            shm_middleware=mw,
            item_collector=_Collector(),
            chain_queue=queue.Queue(),
            node_name="consumer",
        )
        stop, pause = threading.Event(), threading.Event()
        worker = threading.Thread(target=recv.run_loop, args=(stop, pause), daemon=True)
        worker.start()
        deadline = time.monotonic() + 25.0
        while len(items) < len(wires) and time.monotonic() < deadline:
            time.sleep(0.02)
        stop.set()
        worker.join(5.0)

        result = []
        for item in items:
            arrays = {
                k: (v.tobytes(), tuple(v.shape), str(v.dtype)) for k, v in item.items() if isinstance(v, np.ndarray)
            }
            others = {k: type(v).__name__ for k, v in item.items() if not isinstance(v, np.ndarray)}
            result.append({"arrays": arrays, "others": others})
        out_q.put(("ok", result))
    except BaseException:  # noqa: BLE001 — любую ошибку ребёнка вернуть родителю текстом
        out_q.put(("error", traceback.format_exc()))


def _receive_in_other_process(wires: list[dict]) -> list[dict]:
    """Отдать провод-сообщения ребёнку (spawn) и забрать items. Дедлайн на всё."""
    ctx = multiprocessing.get_context("spawn")
    out_q = ctx.Queue()
    proc = ctx.Process(target=_child_pipeline_receive, args=([pickle.dumps(w) for w in wires], out_q), daemon=True)
    proc.start()
    try:
        try:
            status, payload = out_q.get(timeout=CHILD_RESULT_TIMEOUT_S)
        except queue.Empty:
            pytest.fail(f"дочерний процесс не ответил за {CHILD_RESULT_TIMEOUT_S} с (завис или упал до ответа)")
    finally:
        proc.join(10.0)
        if proc.is_alive():
            proc.terminate()
            proc.join(5.0)
    if status != "ok":
        pytest.fail(f"дочерний процесс упал:\n{payload}")
    return payload


def _assert_child_item_has(item_result: dict, key: str, want: np.ndarray, label: str) -> None:
    assert key in item_result["arrays"], (
        f"{label}: в item потребителя нет ndarray под ключом {key!r}; "
        f"массивы: {sorted(item_result['arrays'])}, прочие поля: {item_result['others']}"
    )
    raw, shape, dtype = item_result["arrays"][key]
    assert shape == tuple(want.shape), f"{label}: форма {shape} != {tuple(want.shape)}"
    assert dtype == str(want.dtype), f"{label}: dtype {dtype} != {want.dtype}"
    assert raw == want.tobytes(), f"{label}: содержимое не совпало побайтно"


def test_c3_control_frame_cross_process_shapes_preserved(made_mws):
    """CONTROL (зелёный сегодня): ``frame`` формы (H,W,3), (H,W,1), (H,W) доезжает до item'а
    потребителя в ДРУГОМ ОС-процессе побайтно, форма и dtype сохранены (ADR-SRM-017)."""
    owner = _owner(made_mws, coll=4)
    frames = [_arr("frame", seed=50, shape=s) for s in ((48, 64, 3), (48, 64, 1), (48, 64))]
    # Порядок «большой первым»: меньшие формы ложатся в уже выделенный слот без realloc.

    def scenario() -> list[dict]:
        wires = []
        for f in frames:
            out = _send(owner, {"frame": f})
            assert out is not None
            wires.append(_wire(out))
        return wires

    wires = _bounded(scenario)
    got = _receive_in_other_process(wires)
    assert len(got) == 3, f"потребитель получил {len(got)} item'ов из 3"
    for item_result, want in zip(got, frames):
        _assert_child_item_has(item_result, "frame", want, f"frame {tuple(want.shape)}")


def test_c3_cross_process_two_keys_restored_byte_equal(made_mws):
    """C3: item с ТРЕМЯ крупными ключами разных формы и dtype — ``frame`` (H,W,3) uint8,
    ``mask`` (H,W) uint16, ``depth`` (H,W,1) float32 — после приёма в другом ОС-процессе:
    ``item[key]`` равен исходному побайтно, форма и dtype сохранены, для КАЖДОГО ключа."""
    owner = _owner(made_mws, coll=4)
    arrays = {"frame": _arr("frame", seed=60), "mask": _arr("mask", seed=61), "depth": _arr("depth", seed=62)}
    assert all(a.nbytes >= BY_REF_MIN_NBYTES for a in arrays.values())  # страховка самого стенда

    def scenario() -> dict:
        out = _send(owner, dict(arrays))
        assert out is not None
        _assert_small_wire(out)  # предусловие: на проводе ссылки, а не массивы
        return _wire(out)

    wire = _bounded(scenario)
    got = _receive_in_other_process([wire])
    assert len(got) == 1, f"потребитель получил {len(got)} item'ов из 1"
    for key, want in arrays.items():
        _assert_child_item_has(got[0], key, want, f"ключ {key!r}")


# ================================= C5: займы при loan-протоколе ==================================
class _Stub:
    """Минимальный ``self`` для handler'ов GenericProcess (они трогают лишь имя и лог ошибок)."""

    name = "own"

    def __init__(self) -> None:
        self.errors: list[str] = []

    def _log_error(self, msg: str) -> None:
        self.errors.append(msg)


class _FakeQR:
    """Ловит send_to_queue RouterManager'а (как в test_live2_evict_release.py)."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict]] = []

    def send_to_queue(self, process, qtype, msg, timeout: float = 0.0, on_evict=None):
        self.sent.append((process, qtype, msg))
        return True

    def get_queue(self, process, qtype):
        return None


@pytest.fixture
def loan_env(monkeypatch):
    """Loan-протокол ВКЛ + всё, что нужно ему и zero-copy потребителю (как test_g5b/g5d)."""
    for name in (
        "FW_SHM_LOAN_PROTOCOL",
        "FW_SHM_SEQLOCK",
        "FW_SHM_OWNER_INCARNATION",
        "FW_SHM_HANDLE_CACHE",
        "FW_SHM_ZERO_COPY",
    ):
        monkeypatch.setenv(name, "1")


def _fill_rings(owner: FrameShmMiddleware, keys: tuple[str, ...]) -> list[dict]:
    """Два сообщения (по одному на слот кольца глубиной 2) с крупными ``keys``; читатель их
    пока не видел. Возвращает провод-копии. Предусловие: каждый ключ реально уехал ссылкой."""
    wires = []
    for i in range(2):
        out = _send(owner, {k: _arr(k, seed=70 + 10 * i + j) for j, k in enumerate(keys)})
        assert out is not None, "send отброшен на заполнении колец (исчерпание раньше времени)"
        _assert_small_wire(out)  # займ под ключ берётся только если ключ ушёл ссылкой
        wires.append(_wire(out))
    return wires


def _assert_full_then_reusable_after(
    owner: FrameShmMiddleware, keys: tuple[str, ...], release: Callable[[], None]
) -> None:
    """Кольца полны (третий send = None, исчерпание громкое), потом ``release()``, потом кольца
    принимают ещё два сообщения без единого нового исчерпания и без inline-откатов."""
    assert _send(owner, {k: _arr(k, seed=1) for k in keys}) is None, "кольца должны быть полны до отпуска займов"
    assert owner.frame_loan_exhausted >= 1
    exhausted_before = owner.frame_loan_exhausted

    release()

    for i in range(2):
        out = _send(owner, {k: _arr(k, seed=80 + i) for k in keys})
        assert out is not None, "после отпуска всех займов кольцо всё ещё исчерпано: часть займов утекла"
        _assert_small_wire(out)
    assert owner.frame_loan_exhausted == exhausted_before, "после отпуска появились новые исчерпания"


def _deliver_to_owner(owner: FrameShmMiddleware, stub: _Stub, sent: list[tuple[str, Any]]) -> None:
    """Продовая доставка release-почты владельцу: event_dispatcher -> _handle_shm_release."""
    for target, msg in sent:
        if target == "own" and msg.get("type") == "shm_release":
            GenericProcess._handle_shm_release(stub, msg, owner)


def _consumer_done(made_mws, owner: FrameShmMiddleware, wires: list[dict], stub: _Stub) -> None:
    """Потребитель-пайплайн дочитал все сообщения: restore (zero-copy) -> item как у DataReceiver ->
    тикеты как у PipelineExecutor -> флаш release-пачек -> доставка владельцу."""
    mm = MemoryManager()
    cons = FrameShmMiddleware(mm, owner="cons", slot="unused", num_consumers=0)
    made_mws.append((cons, mm, False))
    assert cons.loan_protocol_enabled is True

    sent: list[tuple[str, Any]] = []
    executor = PipelineExecutor(
        plugins=[], chain_targets=["x"], shm_middleware=cons, send_fn=lambda t, m: sent.append((t, m)), node_name="cons"
    )
    receiver = DataReceiver(
        receive_fn=lambda **_: None,
        shm_middleware=cons,
        item_collector=None,
        chain_queue=queue.Queue(),
        node_name="cons",
    )
    for wire in wires:
        restored = cons.restore_frame(wire)
        item = receiver._build_item(restored)
        tickets = executor._collect_view_tickets([item])
        executor._accumulate_releases(tickets)
        del restored, item, tickets  # view-массивы: «дочитал» = отпустил ссылки
    gc.collect()
    executor._flush_releases()
    _deliver_to_owner(owner, stub, sent)


def _c5_consumer_done(monkeypatch, made_mws, keys: tuple[str, ...]) -> None:
    owner = _owner(made_mws, coll=2, num_consumers=1)
    stub = _Stub()

    def scenario() -> None:
        wires = _fill_rings(owner, keys)
        _assert_full_then_reusable_after(owner, keys, lambda: _consumer_done(made_mws, owner, wires, stub))

    _bounded(scenario)
    assert stub.errors == [], f"handler release получил ошибку: {stub.errors}"
    refs = 2 * len(keys)  # два сообщения x по ссылке на каждый крупный ключ
    assert owner.frame_slots_released == refs, (
        f"отпущено займов {owner.frame_slots_released}, ожидалось {refs} (по одному на каждую ссылку)"
    )


def _c5_evict(made_mws, keys: tuple[str, ...]) -> None:
    owner = _owner(made_mws, coll=2, num_consumers=1)
    stub = _Stub()
    qr = _FakeQR()
    router = RouterManager(manager_name="seg", queue_registry=qr)

    def evict_both(wires: list[dict]) -> None:
        for wire in wires:  # оба сообщения вытеснены из полной очереди до прочтения
            router._on_frame_evicted(wire, reader_process="lines")
        _deliver_to_owner(owner, stub, [(t, m) for (t, _qt, m) in qr.sent])

    def scenario() -> None:
        wires = _fill_rings(owner, keys)
        _assert_full_then_reusable_after(owner, keys, lambda: evict_both(wires))

    _bounded(scenario)
    assert stub.errors == [], f"handler release получил ошибку: {stub.errors}"
    refs = 2 * len(keys)
    assert owner.frame_loans_released_on_evict == refs, (
        f"отпущено при вытеснении {owner.frame_loans_released_on_evict}, ожидалось {refs}"
    )


def _c5_reclaim(made_mws, keys: tuple[str, ...]) -> None:
    owner = _owner(made_mws, coll=2, num_consumers=1)
    stub = _Stub()

    def reclaim() -> None:
        # Supervisor по confirmed-death читателя шлёт {data:{dead_reader}} -> handler -> reclaim_reader.
        GenericProcess._handle_shm_reclaim(stub, {"type": "shm_reclaim", "data": {"dead_reader": "c0"}}, owner)

    def scenario() -> None:
        _fill_rings(owner, keys)  # читатель c0 «взял» всё и умер, не отпустив ничего
        _assert_full_then_reusable_after(owner, keys, reclaim)

    _bounded(scenario)
    assert stub.errors == [], f"handler reclaim получил ошибку: {stub.errors}"
    refs = 2 * len(keys)
    assert owner.frame_slots_reclaimed == refs, (
        f"снято займов мёртвого читателя {owner.frame_slots_reclaimed}, ожидалось {refs}"
    )


def test_c5_control_frame_loans_returned_after_consumer(loan_env, monkeypatch, made_mws):
    """CONTROL (зелёный сегодня): продовый путь потребителя на ключе ``frame`` возвращает все займы."""
    _c5_consumer_done(monkeypatch, made_mws, ("frame",))


def test_c5_loans_all_keys_returned_after_consumer(loan_env, monkeypatch, made_mws):
    """C5: сообщения с ``frame`` и ``foo`` — после штатной обработки потребителем займов у
    владельца 0 по ВСЕМ кольцам: кольца снова принимают, отпущено 4 займа (по ссылке)."""
    _c5_consumer_done(monkeypatch, made_mws, ("frame", "foo"))


def test_c5_control_frame_evict_releases_refs(loan_env, made_mws):
    """CONTROL (зелёный сегодня): вытеснение сообщения с ``frame`` отпускает его ссылку."""
    _c5_evict(made_mws, ("frame",))


def test_c5_evict_releases_all_refs(loan_env, made_mws):
    """C5: вытеснение сообщения из очереди отпускает ВСЕ его ссылки (``frame`` и ``foo``)."""
    _c5_evict(made_mws, ("frame", "foo"))


def test_c5_control_frame_reclaim_dead_reader(loan_env, made_mws):
    """CONTROL (зелёный сегодня): reclaim мёртвого читателя снимает займ ``frame``."""
    _c5_reclaim(made_mws, ("frame",))


def test_c5_reclaim_dead_reader_all_keys(loan_env, made_mws):
    """C5: reclaim мёртвого читателя снимает займы ВСЕХ ключей (``frame`` и ``foo``)."""
    _c5_reclaim(made_mws, ("frame", "foo"))
