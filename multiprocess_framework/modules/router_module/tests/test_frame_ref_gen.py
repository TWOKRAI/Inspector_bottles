# -*- coding: utf-8 -*-
"""Task 4.4 (transport-single-policy) — приёмка «ссылка на SHM указывает на КАДР (поколение
записи), а не на ячейку кольца». Независимый тест-автор (tester), от контракта Task 4.4
(DESIGN + A1-A8), БЕЗ чтения реализации после 83a9092f.

Контракт, который здесь пинится (литералы, не производные от кода):
  * каждый крупный массив, включая ``frame``, едет как ``data["_shm_refs"][key]`` с ключами РОВНО
    ``{"owner", "slot", "idx", "gen", "name"}``; ``gen`` — чётное поколение ЭТОЙ записи; ``owner`` —
    отправитель; плоских полей и меты view на проводе нет (A5);
  * читатель сверяет поколение слота с ``ref["gen"]``: расхождение ДО чтения -> ключ ``None`` и
    ``frame_stale_drops`` +1 (A1, A7); изменилось ВО ВРЕМЯ копии -> ``None`` и ``frame_torn_reads``
    +1 (A2); view, переживший цепочку, сверяется с ``ref["gen"]`` (A3);
  * дверь отправки: перезапись входного слота между чтением view и записью в своё кольцо -> сообщение
    не уходит ни к одной цели, ``frame_stale_drops`` +1 один раз на item (A4);
  * ``FW_SHM_SEQLOCK`` исчезает из реестра, слот всегда несёт поколение (A8).

Стенд: реальные ``MemoryManager`` + ``FrameShmMiddleware`` (сторона отправки — писатель ``A`` с
кольцом ``coll=3``, round-robin: ячейка ``idx`` переписывается ровно через 3 следующих записи в тот же
ключ), читатель — ОТДЕЛЬНЫЙ middleware другого владельца со своим ``MemoryManager``, между ними провод =
``pickle`` туда-обратно. Флаги ``FW_SHM_*`` чистятся автоиспользуемой фикстурой: режим view включается
только аргументами конструктора (``owner_incarnation``/``cache_shm_handles``/``zero_copy``).

Где лежит восстановленный массив (``msg["frame"]`` или ``msg["data"]["frame"]``) контракт не задаёт —
``_pick`` смотрит в оба места; для остальных ключей — ``msg["data"][key]``. ``None``/отсутствие = «нет».

Рядом с каждым RED стоит CONTROL без перезаписи (зелёный и сегодня, и после), он доказывает, что стенд
исправен, а красный падает из-за отсутствующей фичи.
"""

from __future__ import annotations

import gc
import multiprocessing.shared_memory as shared_memory_mod
import os
import pickle
import queue
import threading
from typing import Any, Callable

import numpy as np
import pytest

from multiprocess_framework.modules.config_module.feature_flags import resolve
from multiprocess_framework.modules.process_module.generic.data_receiver import DataReceiver
from multiprocess_framework.modules.process_module.generic.pipeline_executor import PipelineExecutor
from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import (
    FrameShmMiddleware,
)
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import (
    MemoryManager,
)
from multiprocess_framework.modules.shared_resources_module.memory.format import read_generation

# --- литералы контракта -------------------------------------------------------------
REF_KEYS = {"owner", "slot", "idx", "gen", "name"}  # ровно пять полей ссылки
FORBIDDEN_WIRE_KEYS = (  # A5: ни одного из них нигде в исходящем сообщении
    "shm_name",
    "shm_index",
    "shm_actual_name",
    "shm_owner",
    "shm_seqlock",
    "_frame_is_view",
    "_shm_view_name",
    "_shm_view_generation",
    "_shm_generation",
)
RING_DEPTH = 3  # coll писателя: ячейка переписывается через 3 записи в тот же ключ

DEADLINE_S = 30.0  # потолок на любой сценарий: зависший тест хуже отсутствующего

# У каждого массива nbytes >= 8192 (порог claim check) -> всегда ссылкой.
SHAPES: dict[str, tuple[tuple[int, ...], str]] = {
    "frame": ((48, 64, 3), "uint8"),  # 9216 Б
    "foo": ((100, 100), "uint8"),  # 10000 Б
}


# --- стенд --------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clean_shm_flags(monkeypatch):
    """Флаги SHM берутся ТОЛЬКО из теста: env разработчика не должен менять поведение."""
    for name in [k for k in os.environ if k.startswith("FW_SHM_")]:
        monkeypatch.delenv(name, raising=False)


class _Rig:
    """Фабрика middleware со снятием SHM в конце — даже если тест упал (Windows держит сегмент,
    пока открыт любой handle)."""

    def __init__(self) -> None:
        self._made: list[tuple[FrameShmMiddleware, MemoryManager]] = []

    def make(
        self,
        owner: str,
        *,
        coll: int = RING_DEPTH,
        view: bool = False,
        mm: MemoryManager | None = None,
        slot: str = "output_frames",
    ) -> FrameShmMiddleware:
        mm = mm or MemoryManager()
        extra = dict(owner_incarnation=True, cache_shm_handles=True, zero_copy=True) if view else {"zero_copy": False}
        mw = FrameShmMiddleware(mm, owner=owner, slot=slot, coll=coll, **extra)
        self._made.append((mw, mm))
        return mw

    def close(self) -> None:
        gc.collect()  # отпустить view-массивы, иначе close() handle падает BufferError
        for mw, mm in reversed(self._made):
            for fin in (mw.close_handle_cache, mw.release_owned_memory, mm.close_all):
                try:
                    fin()
                except Exception:  # noqa: BLE001 — финализатор не должен маскировать причину падения теста
                    pass
        self._made.clear()


@pytest.fixture
def rig():
    r = _Rig()
    yield r
    r.close()


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


def _arr(key: str, seed: int) -> np.ndarray:
    """Детерминированное «случайное» содержимое: побайтное сравнение ловит чужие кадры."""
    shape, dtype = SHAPES[key]
    return np.random.default_rng(seed).integers(0, 250, size=shape).astype(dtype)


def _send(mw: FrameShmMiddleware, item: dict) -> dict:
    """Отправка как в PipelineExecutor._send_results: msg с item в ``data``."""
    out = mw.strip_data_frame_on_send({"target": "t", "type": "data", "channel": "data", "data": item})
    assert out is not None, "send-middleware отбросил сообщение (drop-на-источнике)"
    return out


def _wire(msg: dict) -> dict:
    """Провод очереди: pickle туда-обратно (получатель видит независимую копию)."""
    return pickle.loads(pickle.dumps(msg))


def _pick(msg: dict, key: str) -> Any:
    """Восстановленный массив ``key`` после restore_frame/on_receive (см. докстринг модуля)."""
    if key == "frame" and msg.get("frame") is not None:
        return msg["frame"]
    data = msg.get("data")
    return data.get(key) if isinstance(data, dict) else None


def _overwrite(writer: FrameShmMiddleware, key: str, first_seed: int = 100) -> list[np.ndarray]:
    """Прогнать кольцо ключа целиком (RING_DEPTH записей) -> ячейка первой записи перезаписана.
    Возвращает записанные массивы («чужие» кадры), чтобы тест мог сказать, что именно вернул читатель."""
    foreign = []
    for s in range(RING_DEPTH):
        arr = _arr(key, first_seed + s)
        _send(writer, {key: arr})
        foreign.append(arr)
    return foreign


def _same(got: Any, want: np.ndarray) -> bool:
    return isinstance(got, np.ndarray) and got.shape == want.shape and got.tobytes() == want.tobytes()


def _refs(out: dict) -> dict:
    data = out.get("data")
    refs = data.get("_shm_refs") if isinstance(data, dict) else None
    assert isinstance(refs, dict) and refs, (
        f"в исходящем data-сообщении нет _shm_refs; ключи data: {sorted(data or {})}"
    )
    return refs


def _walk_keys(obj: Any) -> set[str]:
    """Все строковые ключи всех вложенных dict внутри сообщения (list/tuple обходятся)."""
    found: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.add(k)
            found |= _walk_keys(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            found |= _walk_keys(v)
    return found


# ===================================== A1: stale до чтения =====================================
KEYS = ("frame", "foo")
MODES = ("copy", "view")


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("key", KEYS)
def test_a1_control_not_overwritten_reads_original(rig, key, mode):
    """CONTROL (зелёный сегодня): ячейку не трогали -> читатель возвращает ровно записанные пиксели,
    оба счётчика нулевые."""
    writer, reader = rig.make("A"), rig.make("B", view=(mode == "view"))
    want = _arr(key, 1)

    def scenario() -> dict:
        return reader.restore_frame(_wire(_send(writer, {key: want, "n": 1})))

    got = _pick(_bounded(scenario), key)
    assert _same(got, want), "стенд неисправен: нетронутая ссылка не восстановилась побайтно"
    assert reader.frame_stale_drops == 0 and reader.frame_torn_reads == 0


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("key", KEYS)
def test_a1_overwritten_before_read_returns_none_and_counts_stale(rig, key, mode):
    """A1: между отправкой ссылки и чтением ячейка переписана (кольцо обернулось) -> читатель
    возвращает ``None`` (НЕ пиксели новой записи), ``frame_stale_drops`` == 1, ``frame_torn_reads`` == 0."""
    writer, reader = rig.make("A"), rig.make("B", view=(mode == "view"))

    def scenario() -> tuple[dict, list[np.ndarray]]:
        wire = _wire(_send(writer, {key: _arr(key, 1), "n": 1}))
        foreign = _overwrite(writer, key)  # ссылка уже указывает на чужую запись
        return reader.restore_frame(wire), foreign

    msg, foreign = _bounded(scenario)
    got = _pick(msg, key)
    if got is not None:
        who = "пиксели НОВОЙ записи (чужой кадр)" if any(_same(got, f) for f in foreign) else "какой-то массив"
        pytest.fail(f"читатель вернул {who} вместо None: ячейка была переписана до чтения")
    assert reader.frame_stale_drops == 1, f"frame_stale_drops = {reader.frame_stale_drops}, ожидалось 1"
    assert reader.frame_torn_reads == 0, "stale (перезапись ДО чтения) не должен считаться torn"


# ===================================== A2: torn во время копии =====================================
# Настоящий класс — запоминаем при импорте: подмена ``SharedMemory`` в модуле не должна ссылаться на себя.
_REAL_SHARED_MEMORY = shared_memory_mod.SharedMemory


class _BufProxy:
    """Обёртка над ``SharedMemory.buf``: каждое обращение читателя к буферу (struct.unpack_from,
    np.frombuffer, индексирование) — «точка касания», в которой стенд может вклиниться писателем.
    Протокол буфера у Python-классов — PEP 688 (3.12)."""

    def __init__(self, mv: memoryview, touch: Callable[[], None]) -> None:
        self._mv = mv
        self._touch = touch

    def __buffer__(self, flags: int) -> memoryview:
        self._touch()
        return self._mv

    def __release_buffer__(self, view: memoryview) -> None:
        return None

    def __len__(self) -> int:
        return len(self._mv)

    def __getitem__(self, item: Any) -> Any:
        self._touch()
        return self._mv[item]


class _Injector:
    """Считает касания буфера читателя и на касании номер ``fire_at`` один раз зовёт ``action``."""

    def __init__(self, fire_at: int, action: Callable[[], None]) -> None:
        self.fire_at = fire_at
        self.action = action
        self.touches = 0
        self.fired = False
        self._firing = False

    def touch(self) -> None:
        if self._firing:
            return  # касания самого писателя (если он открывает сегменты) в счёт не идут
        self.touches += 1
        if self.touches == self.fire_at and not self.fired:
            self.fired = True
            self._firing = True
            try:
                self.action()
            finally:
                self._firing = False


def _one_read_with_overwrite_at(fire_at: int, idx: int) -> dict[str, Any]:
    """Один сценарий: писатель пишет ссылку, читатель (копия) читает; на касании буфера номер
    ``fire_at`` писатель прогоняет кольцо (перезапись ячейки ПОСРЕДИ чтения). Возвращает исход."""
    rig = _Rig()
    try:
        writer = rig.make(f"A{idx}_{fire_at}")
        reader = rig.make(f"B{idx}_{fire_at}")
        original = _arr("frame", 1)
        wire = _wire(_send(writer, {"frame": original, "n": 1}))
        inj = _Injector(fire_at, lambda: _overwrite(writer, "frame"))

        class _TearingSharedMemory(_REAL_SHARED_MEMORY):
            @property
            def buf(self):  # type: ignore[override]
                mv = _REAL_SHARED_MEMORY.buf.fget(self)
                return None if mv is None else _BufProxy(mv, inj.touch)

        shared_memory_mod.SharedMemory = _TearingSharedMemory  # type: ignore[misc]
        try:
            msg = reader.restore_frame(wire)
        finally:
            shared_memory_mod.SharedMemory = _REAL_SHARED_MEMORY  # type: ignore[misc]
        got = _pick(msg, "frame")
        return {
            "fired": inj.fired,
            "touches": inj.touches,
            "returned_original": _same(got, original),
            "returned_none": got is None,
            "stale": reader.frame_stale_drops,
            "torn": reader.frame_torn_reads,
        }
    finally:
        rig.close()


def test_a2_overwrite_during_copy_counts_torn():
    """A2: перезапись ячейки ПОСРЕДИ чтения (писатель вклинивается на каждом по счёту касании буфера
    читателя — перебор всех точек чтения) -> ни в одной точке читатель не отдаёт пиксели, отличные от
    записанных; каждый ``None`` посчитан ровно один раз (stale + torn == 1); и хотя бы в одной точке
    (после проверки поколения, до конца копии) перезапись классифицирована как ``frame_torn_reads`` == 1."""

    def sweep() -> list[dict[str, Any]]:
        outcomes: list[dict[str, Any]] = []
        for fire_at in range(1, 60):
            res = _one_read_with_overwrite_at(fire_at, len(outcomes))
            if not res["fired"]:
                break  # читатель касался буфера реже, чем fire_at: точки чтения кончились
            outcomes.append(res)
        return outcomes

    outcomes = _bounded(sweep, seconds=120.0)
    assert len(outcomes) >= 3, (
        f"стенд неисправен: читатель коснулся SharedMemory.buf слишком мало раз ({len(outcomes)} точек) — "
        "перезапись «посреди чтения» не смоделирована"
    )
    for point, res in enumerate(outcomes, start=1):
        if not res["returned_none"]:
            assert res["returned_original"] and res["stale"] == 0 and res["torn"] == 0, (
                f"перезапись на касании {point}: читатель вернул массив, НЕ равный записанному "
                f"(порванный/чужой кадр), stale={res['stale']} torn={res['torn']}"
            )
        else:
            assert res["stale"] + res["torn"] == 1, (
                f"перезапись на касании {point}: None не посчитан ровно один раз "
                f"(stale={res['stale']} torn={res['torn']})"
            )
    assert any(res["torn"] == 1 for res in outcomes), (
        "ни в одной точке чтения перезапись во время копии не посчитана как frame_torn_reads; "
        f"исходы по точкам (stale, torn, none): {[(r['stale'], r['torn'], r['returned_none']) for r in outcomes]}"
    )


# ===================================== A3 / A4: конвейер =====================================
class _Probe:
    """Плагин цепочки: запоминает пиксели, которые видит, и в нужный момент зовёт ``on_process``."""

    name = "probe"
    enabled = True
    inputs: list = []
    outputs: list = []

    def __init__(self, key: str, on_process: Callable[[], None] | None = None) -> None:
        self._key = key
        self._on_process = on_process
        self.seen: list[bytes] = []
        self.done = threading.Event()

    def process(self, items: list[dict]) -> list[dict]:
        for item in items:
            arr = item.get(self._key)
            self.seen.append(arr.tobytes() if isinstance(arr, np.ndarray) else b"")
        if self._on_process is not None:
            self._on_process()
        self.done.set()
        return items


def _run_executor(ex: PipelineExecutor, batch: list[dict], wait_for: threading.Event) -> None:
    """Один батч через настоящий ``PipelineExecutor.run`` в daemon-потоке: ждём, пока плагин отработал,
    останавливаем воркер (он доделывает текущий такт целиком) и join с дедлайном."""
    q: queue.Queue = queue.Queue()
    q.put(batch)
    ex.bind_queue(q)
    stop, pause = threading.Event(), threading.Event()
    worker = threading.Thread(target=ex.run, args=(stop, pause), daemon=True)
    worker.start()
    if not wait_for.wait(15.0):
        stop.set()
        pytest.fail("плагин цепочки не был вызван за 15 с")
    stop.set()
    worker.join(10.0)
    if worker.is_alive():
        pytest.fail("PipelineExecutor не завершил такт за 10 с")


def _receive_as_pipeline(reader: FrameShmMiddleware, wire: dict) -> dict:
    """Приём как в ``DataReceiver.run_loop``: restore_frame -> настоящий ``_build_item``."""
    receiver = DataReceiver(
        receive_fn=lambda **_: None,
        shm_middleware=reader,
        item_collector=None,
        chain_queue=queue.Queue(),
        node_name=reader._owner,
    )
    return receiver._build_item(reader.restore_frame(wire))


@pytest.mark.parametrize("overwrite", [False, True], ids=["control_no_overwrite", "overwritten_during_chain"])
@pytest.mark.parametrize("key", KEYS)
def test_a3_view_overwritten_during_chain_drops_batch(rig, key, overwrite):
    """A3: view прочитан ЦЕЛЫМ, а во время обработки (плагин цепочки) писатель прогоняет кольцо ->
    батч НЕ отправляется, ``frame_stale_drops`` == 1. CONTROL (без перезаписи): батч уходит, счётчик 0.
    Плагин в обоих случаях видит ровно записанные пиксели (перезапись после чтения)."""
    writer, reader = rig.make("A"), rig.make("B", view=True)
    want = _arr(key, 1)
    sent: list[tuple[str, dict]] = []
    probe = _Probe(key, (lambda: _overwrite(writer, key)) if overwrite else None)

    def scenario() -> None:
        item = _receive_as_pipeline(reader, _wire(_send(writer, {key: want, "n": 1})))
        ex = PipelineExecutor(
            plugins=[probe],
            chain_targets=["out"],
            shm_middleware=reader,
            send_fn=lambda target, msg: sent.append((target, msg)),
            node_name="B",
        )
        _run_executor(ex, [item], probe.done)

    _bounded(scenario)
    assert probe.seen == [want.tobytes()], "плагин увидел пиксели, отличные от записанных писателем"
    if overwrite:
        assert sent == [], "батч ушёл дальше, хотя входной view был перезаписан во время обработки"
        assert reader.frame_stale_drops == 1, f"frame_stale_drops = {reader.frame_stale_drops}, ожидалось 1"
    else:
        assert len(sent) == 1, "нетронутый view: батч обязан уйти"
        assert reader.frame_stale_drops == 0


@pytest.mark.parametrize("overwrite", [False, True], ids=["control_no_overwrite", "overwritten_during_send_copy"])
@pytest.mark.parametrize("key", KEYS)
def test_a4_input_overwritten_during_send_copy_drops_all_targets(rig, monkeypatch, key, overwrite):
    """A4: входной view пережил цепочку (проверка executor'а проходит), но писатель переписывает
    входную ячейку РОВНО перед записью в кольцо отправителя (перехват ``MemoryManager.write_images``
    отправителя) -> копия «чужих» пикселей не уходит НИ к одной из двух целей, ``frame_stale_drops`` == 1
    (один раз на item, не на цель). CONTROL: без перезаписи уходят оба сообщения, счётчик 0."""
    writer = rig.make("A")
    mm_b = MemoryManager()
    sender = rig.make("B", view=True, mm=mm_b)
    fired: list[int] = []
    real_write = mm_b.write_images

    def write_images_after_overwrite(*args, **kwargs):
        if overwrite and not fired:
            fired.append(1)
            _overwrite(writer, key)  # писатель перезаписывает входную ячейку прямо перед копией
        return real_write(*args, **kwargs)

    monkeypatch.setattr(mm_b, "write_images", write_images_after_overwrite)

    sent: list[tuple[str, dict]] = []

    def send_like_router(target: str, msg: dict) -> None:
        out = sender.strip_data_frame_on_send(msg)  # send-middleware роутера; None = дроп
        if out is not None:
            sent.append((target, out))

    probe = _Probe(key)

    def scenario() -> None:
        item = _receive_as_pipeline(sender, _wire(_send(writer, {key: _arr(key, 1), "n": 1})))
        ex = PipelineExecutor(
            plugins=[probe],
            chain_targets=["t1", "t2"],
            shm_middleware=sender,
            send_fn=send_like_router,
            node_name="B",
        )
        _run_executor(ex, [item], probe.done)

    _bounded(scenario)
    if overwrite:
        assert fired, "стенд неисправен: перехват write_images отправителя не сработал"
        assert sent == [], f"сообщение ушло к целям {[t for t, _ in sent]} с пикселями перезаписанного входа"
        assert sender.frame_stale_drops == 1, f"frame_stale_drops = {sender.frame_stale_drops}, ожидалось 1"
    else:
        assert [t for t, _ in sent] == ["t1", "t2"], "нетронутый вход: сообщение обязано уйти к обеим целям"
        assert sender.frame_stale_drops == 0


# ===================================== A5: формат на проводе =====================================
def test_a5_outgoing_message_carries_only_five_field_own_refs(rig):
    """A5: в исходящем data-сообщении (frame + foo) нет ни одного ключа старого формата (плоские
    поля ссылки, мета view) на ЛЮБОЙ глубине; ``_shm_refs`` содержит ссылки на ``frame`` и ``foo`` с
    набором ключей РОВНО {owner, slot, idx, gen, name}, ``owner`` = отправитель, массивов в сообщении
    нет."""
    writer = rig.make("A")
    out = _bounded(lambda: _send(writer, {"frame": _arr("frame", 1), "foo": _arr("foo", 2), "n": 1}))

    leaked = sorted(set(FORBIDDEN_WIRE_KEYS) & _walk_keys(out))
    assert leaked == [], f"в исходящем сообщении остались ключи старого формата: {leaked}"
    assert not any(isinstance(v, np.ndarray) for v in out["data"].values()), "массив остался в сообщении"
    refs = _refs(out)
    assert set(refs) == {"frame", "foo"}, f"_shm_refs по ключам {sorted(refs)}, ожидалось ['foo', 'frame']"
    for key, ref in refs.items():
        assert set(ref) == REF_KEYS, f"ссылка {key!r}: ключи {sorted(ref)} != {sorted(REF_KEYS)}"
        assert ref["owner"] == "A", f"ссылка {key!r}: owner {ref['owner']!r}, ожидался отправитель 'A'"


def test_a5_ref_gen_is_even_and_tracks_each_write(rig):
    """A5 (значение ``gen``): у ссылки на ячейку, записанную дважды подряд, ``gen`` чётный и растёт;
    ``idx`` — номер ячейки кольца (0 <= idx < 3), ``name`` — непустая строка."""
    writer = rig.make("A")

    def scenario() -> list[dict]:
        return [_refs(_send(writer, {"frame": _arr("frame", s)}))["frame"] for s in range(RING_DEPTH + 1)]

    refs = _bounded(scenario)
    first, again = refs[0], refs[RING_DEPTH]  # ячейка 0 записана 1-й и (после оборота кольца) 4-й записью
    assert first["idx"] == again["idx"] == 0, f"round-robin: idx {first['idx']} и {again['idx']}, ожидались 0 и 0"
    assert [r["idx"] for r in refs] == [0, 1, 2, 0]
    for ref in refs:
        assert isinstance(ref["gen"], int) and ref["gen"] % 2 == 0, f"gen {ref['gen']!r} не чётное целое"
        assert isinstance(ref["name"], str) and ref["name"], "name — пустая/не строка"
    assert again["gen"] > first["gen"], f"gen не вырос при перезаписи ячейки: {first['gen']} -> {again['gen']}"


def test_a5_on_send_path_uses_same_ref_format(rig):
    """A5 (путь ``on_send``, wire/GUI): top-level ``msg["frame"]`` уходит тем же форматом —
    ``msg["data"]["_shm_refs"]["frame"]`` с пятью полями, ``owner`` = отправитель, без ключей старого
    формата и без массива в сообщении."""
    writer = rig.make("A")
    msg = {"type": "video", "frame": _arr("frame", 1), "data": {"camera_id": 1}}
    out = _bounded(lambda: writer.on_send(msg))

    assert out is not None
    assert sorted(set(FORBIDDEN_WIRE_KEYS) & _walk_keys(out)) == []
    assert out.get("frame") is None, "массив остался в top-level msg['frame']"
    ref = _refs(out)["frame"]
    assert set(ref) == REF_KEYS and ref["owner"] == "A"


# ===================================== A7: copy-out (GUI) =====================================
def test_a7_control_copy_out_restores_frame_and_large_key(rig):
    """CONTROL (зелёный сегодня): ``on_receive`` (copy-out, как GUI) восстанавливает ``frame`` и
    крупный ключ ``foo`` побайтно; счётчики нулевые."""
    writer, gui = rig.make("A"), rig.make("gui")
    frame, foo = _arr("frame", 1), _arr("foo", 2)

    def scenario() -> dict:
        return gui.on_receive(_wire(_send(writer, {"frame": frame, "foo": foo, "n": 7})))

    msg = _bounded(scenario)
    assert _same(_pick(msg, "frame"), frame) and _same(_pick(msg, "foo"), foo)
    assert msg["data"]["n"] == 7
    assert gui.frame_stale_drops == 0 and gui.frame_torn_reads == 0


def test_a7_copy_out_restores_and_counts_stale(rig):
    """A7: обе ссылки (``frame`` и ``foo``) устарели до приёма (кольца обернулись) -> ``on_receive``
    возвращает ``None`` под обоими ключами (никаких пикселей новых записей), ``frame_stale_drops`` == 2
    (по одному на ключ), ``frame_torn_reads`` == 0."""
    writer, gui = rig.make("A"), rig.make("gui")

    def scenario() -> tuple[dict, list[np.ndarray]]:
        wire = _wire(_send(writer, {"frame": _arr("frame", 1), "foo": _arr("foo", 2), "n": 7}))
        foreign = _overwrite(writer, "frame") + _overwrite(writer, "foo", first_seed=200)
        return gui.on_receive(wire), foreign

    msg, foreign = _bounded(scenario)
    for key in KEYS:
        got = _pick(msg, key)
        if got is not None:
            who = "пиксели НОВОЙ записи (чужой кадр)" if any(_same(got, f) for f in foreign) else "какой-то массив"
            pytest.fail(f"copy-out вернул {who} под ключом {key!r} вместо None")
    assert gui.frame_stale_drops == 2, f"frame_stale_drops = {gui.frame_stale_drops}, ожидалось 2 (по одному на ключ)"
    assert gui.frame_torn_reads == 0


# ===================================== A8: seqlock всегда =====================================
def test_a8_seqlock_flag_removed_and_slot_has_generation(rig):
    """A8: флаг ``FW_SHM_SEQLOCK`` исчез из реестра — ``resolve`` бросает ``KeyError`` (опечатка/
    удалённый флаг ловится, а не молча читается как False)."""
    with pytest.raises(KeyError):
        resolve("FW_SHM_SEQLOCK")


def test_a8_slot_without_flag_has_even_generation_that_grows(rig):
    """A8: слот, созданный БЕЗ каких-либо флагов, несёт поколение: открыв сегмент по ``ref["name"]``,
    из заголовка (``read_generation``) читаем чётное число, равное ``ref["gen"]``, а после второй записи
    в ту же ячейку (``coll=1``) — бо́льшее чётное, равное новому ``ref["gen"]``."""
    writer = rig.make("A", coll=1)

    def scenario() -> list[tuple[int, int]]:
        pairs = []
        for seed in (1, 2):
            ref = _refs(_send(writer, {"frame": _arr("frame", seed)}))["frame"]
            seg = shared_memory_mod.SharedMemory(name=ref["name"], create=False)
            try:
                pairs.append((ref["gen"], read_generation(seg.buf)))
            finally:
                seg.close()
        return pairs

    (ref_gen1, slot_gen1), (ref_gen2, slot_gen2) = _bounded(scenario)
    assert ref_gen1 == slot_gen1 and slot_gen1 % 2 == 0, (
        f"gen ссылки {ref_gen1} != поколению слота {slot_gen1} или нечётное"
    )
    assert ref_gen2 == slot_gen2 and slot_gen2 % 2 == 0
    assert slot_gen2 > slot_gen1, f"поколение слота не выросло при второй записи: {slot_gen1} -> {slot_gen2}"
