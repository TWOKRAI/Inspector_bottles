# -*- coding: utf-8 -*-
"""Task 4.1 (transport-single-policy) — приёмка «claim check по размеру под ЛЮБЫМ ключом».

Независимый тест-автор (tester), от контракта C1-C8 плана, БЕЗ чтения реализации.
Router-уровень: реальные ``MemoryManager`` + ``FrameShmMiddleware``, собранные так же, как
``GenericProcess`` (owner, slot="output_frames", coll=глубина, num_consumers).

  * сторона отправки  = ``strip_data_frame_on_send(msg)`` на ``{"type": "data", "data": {...}}``;
  * сторона copy-out  = ОТДЕЛЬНЫЙ ``FrameShmMiddleware`` со своим ``MemoryManager`` и
    ``zero_copy=False`` (как ``multiprocess_prototype/frontend/process.py``), вызов ``on_receive``;
  * между ними провод = ``pickle`` туда-обратно (как очередь процесса).

C1 сужен 4.1-fix (ревью 4.1): ссылкой едет только голый ЧИСЛОВОЙ ndarray нативного порядка байт,
``ndim`` 2–3; строки, object, void, ``datetime64``/``timedelta64``, big-endian, подклассы,
1D и 4D+ — inline (авторский тест в ``test_claim_check_rings_hazards.py``).
Все массивы этого файла — числовые 2D/3D, формулировки ниже читать с этой оговоркой.

Пороги — литералы: ``nbytes >= 8192`` едет ссылкой, ``8191`` — inline; всё data-сообщение
после send-middleware ``len(pickle.dumps(msg)) <= 16384``. Имена ссылочных полей
(``shm_name``, ``_shm_refs`` ...) НЕ пинятся — проверяются только размер, отсутствие
крупного ndarray внутри сообщения и побайтное равенство после приёма (форма И dtype).

Рядом с каждым RED стоит CONTROL на ключе ``frame``, зелёный уже сегодня: он доказывает,
что стенд исправен, а красный падает именно из-за отсутствующей фичи.

Не покрыто здесь (в другом файле): C3 (приём в пайплайне, отдельный ОС-процесс) и C5 (займы).
"""

from __future__ import annotations

import os
import pickle
import threading
from typing import Any, Callable

import numpy as np
import pytest

from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import (
    FrameShmMiddleware,
)
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import (
    MemoryManager,
)

# --- литералы контракта -------------------------------------------------------------
BY_REF_MIN_NBYTES = 8192  # nbytes >= 8192 -> ссылкой
MSG_MAX_PICKLE_BYTES = 16384  # всё data-сообщение после send-middleware

DEADLINE_S = 30.0  # потолок на любой сценарий: зависший тест хуже отсутствующего


# --- стенд --------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clean_shm_flags(monkeypatch):
    """Флаги SHM берутся ТОЛЬКО из теста: env разработчика не должен менять поведение."""
    for name in [k for k in os.environ if k.startswith("FW_SHM_")]:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def make_owner():
    """Фабрика владельца (как GenericProcess:207-213). Финализатор освобождает SHM даже
    если тест упал — иначе на Windows сегменты текут до конца сессии."""
    made: list[tuple[FrameShmMiddleware, MemoryManager]] = []

    def _make(*, coll: int = 4, num_consumers: int = 1) -> FrameShmMiddleware:
        mm = MemoryManager()
        mw = FrameShmMiddleware(
            memory_manager=mm, owner="own", slot="output_frames", coll=coll, num_consumers=num_consumers
        )
        made.append((mw, mm))
        return mw

    yield _make
    for mw, mm in made:
        for fin in (mw.close_handle_cache, mw.release_owned_memory, mm.close_all):
            try:
                fin()
            except Exception:  # noqa: BLE001 — финализатор не должен маскировать причину падения теста
                pass


@pytest.fixture
def make_consumer():
    """Отдельный copy-out потребитель со СВОИМ MemoryManager (как GUI: zero_copy=False)."""
    made: list[tuple[FrameShmMiddleware, MemoryManager]] = []

    def _make(name: str = "gui") -> FrameShmMiddleware:
        mm = MemoryManager()
        mw = FrameShmMiddleware(mm, owner=name, slot="output_frames", zero_copy=False)
        made.append((mw, mm))
        return mw

    yield _make
    for mw, mm in made:
        for fin in (mw.close_handle_cache, mm.close_all):
            try:
                fin()
            except Exception:  # noqa: BLE001
                pass


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


def _arr(shape: tuple[int, ...], dtype: str = "uint8", seed: int = 0) -> np.ndarray:
    """Детерминированный массив со «случайным» содержимым: побайтное сравнение ловит
    перепутанные ключи и сдвиги, чего заливка одним числом не поймает."""
    rng = np.random.default_rng(seed)
    if np.dtype(dtype).kind == "f":
        return rng.random(shape).astype(dtype)
    return rng.integers(0, 250, size=shape).astype(dtype)


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


def _send(mw: FrameShmMiddleware, item: dict) -> dict:
    """Отправка как в PipelineExecutor._send_results: msg с item в ``data``."""
    out = mw.strip_data_frame_on_send({"target": "t", "type": "data", "channel": "data", "data": item})
    assert out is not None, "send-middleware отбросил сообщение (drop-на-источнике)"
    return out


def _wire(msg: dict) -> dict:
    """Провод очереди: pickle туда-обратно (получатель видит независимую копию)."""
    return pickle.loads(pickle.dumps(msg))


def _restored(rcv_msg: dict, key: str) -> np.ndarray:
    """Где лежит восстановленный массив после on_receive: ``frame`` — по-прежнему в
    ``msg["frame"]`` (путь GUI не регрессирует), остальные ключи — в ``msg["data"][key]`` (C4)."""
    return rcv_msg["frame"] if key == "frame" else rcv_msg["data"][key]


def _assert_same(got: Any, want: np.ndarray, label: str) -> None:
    assert isinstance(got, np.ndarray), f"{label}: получен {type(got).__name__}, а не ndarray"
    assert got.shape == want.shape, f"{label}: форма {got.shape} != {want.shape}"
    assert got.dtype == want.dtype, f"{label}: dtype {got.dtype} != {want.dtype}"
    assert got.tobytes() == want.tobytes(), f"{label}: содержимое не совпало побайтно"


def _assert_small_wire(out: dict) -> None:
    """Суть C1 в двух утверждениях: размер и отсутствие крупного ndarray внутри."""
    big = _big_arrays(out)
    assert big == [], f"в сообщении остались крупные ndarray (едут inline): {big}"
    size = len(pickle.dumps(out))
    assert size <= MSG_MAX_PICKLE_BYTES, f"len(pickle.dumps(msg)) = {size} > {MSG_MAX_PICKLE_BYTES}"


# ===================================== C1: отправка =====================================
def test_c1_control_frame_goes_by_reference_message_small(make_owner):
    """CONTROL (зелёный сегодня): ключ ``frame`` крупнее порога -> сообщение мелкое."""
    mw = make_owner()
    out = _bounded(lambda: _send(mw, {"frame": _arr((100, 100, 3), seed=1), "n": 1}))
    _assert_small_wire(out)


def test_c1_foo_goes_by_reference_message_small(make_owner):
    """C1: ndarray 30000 Б под произвольным ключом ``foo`` (не ``frame``) уходит ссылкой."""
    mw = make_owner()
    out = _bounded(lambda: _send(mw, {"foo": _arr((100, 100, 3), seed=2), "n": 1}))
    _assert_small_wire(out)


def test_c1_two_large_keys_message_small(make_owner):
    """C1: ``frame`` (921600 Б) + ``rendered_frame`` (921600 Б) + ``mask`` (307200 Б) в одном
    data-сообщении -> всё сообщение <= 16384 Б, ни одного крупного ndarray внутри."""

    def scenario() -> dict:
        mw = make_owner()
        return _send(
            mw,
            {
                "frame": _arr((480, 640, 3), seed=3),
                "rendered_frame": _arr((480, 640, 3), seed=4),
                "mask": _arr((480, 640), seed=5),
                "n": 1,
            },
        )

    _assert_small_wire(_bounded(scenario))


# ===================================== C2: мелочь ======================================
def test_c2_boundary_8191_inline_8192_by_reference(make_owner):
    """C2: граница по обе стороны. 8192 Б под ``foo`` -> ссылкой; 8191 Б под ``bar`` -> inline
    и не меняется. (8191 простое, поэтому форма ``(1, 8191)`` — единственная 2-мерная.)"""
    mw = make_owner()
    at_limit = _arr((64, 128), seed=6)  # ровно 8192 Б
    below = _arr((1, 8191), seed=7)  # ровно 8191 Б
    assert at_limit.nbytes == 8192 and below.nbytes == 8191  # литералы порога, не производные

    out = _bounded(lambda: _send(mw, {"foo": at_limit, "bar": below}))

    big = _big_arrays(out)
    assert big == [], f"массив ровно 8192 Б остался inline (порог >= 8192): {big}"
    inline = out["data"].get("bar")
    assert isinstance(inline, np.ndarray), "массив 8191 Б обязан ехать inline под своим ключом"
    _assert_same(inline, below, "bar (8191 Б)")


def test_c2_small_values_inline_unchanged(make_owner):
    """CONTROL (зелёный сегодня): мелкие массивы (< 8192 Б) и не-массивы едут inline и не
    меняются. ``frame`` сюда намеренно НЕ входит (см. отчёт: C2 vs существующие тесты)."""
    mw = make_owner()
    small = _arr((10, 10, 3), seed=8)  # 300 Б
    payload = {"s": "text", "i": 7, "f": 1.5, "l": [1, 2, 3], "d": {"a": 1}, "none": None, "small": small}
    out = _bounded(lambda: _send(mw, dict(payload)))
    got = out["data"]
    for key in ("s", "i", "f", "l", "d", "none"):
        assert got[key] == payload[key], f"не-массив {key!r} изменён"
    _assert_same(got["small"], small, "small (300 Б)")


# ================================== C4: приём copy-out =================================
def test_c4_control_frame_restored_by_on_receive(make_owner, make_consumer):
    """CONTROL (зелёный сегодня): путь ``frame`` для GUI — восстановлен в ``msg["frame"]``."""
    owner, gui = make_owner(), make_consumer()
    frame = _arr((48, 64, 3), seed=9)

    def scenario() -> dict:
        out = _send(owner, {"frame": frame, "n": 7})
        _assert_small_wire(out)
        return gui.on_receive(_wire(out))

    got = _bounded(scenario)
    _assert_same(_restored(got, "frame"), frame, "frame")
    assert got["data"]["n"] == 7


def test_c4_on_receive_restores_rendered_frame(make_owner, make_consumer):
    """C4: крупный НЕ-``frame`` ключ ``rendered_frame`` восстановлен в ``msg["data"][key]``
    побайтно; ``frame`` рядом не регрессирует. Предусловие «на проводе ссылка, не массив»
    обязательно: иначе restore проверял бы массив, который никуда не уезжал."""
    owner, gui = make_owner(), make_consumer()
    frame = _arr((48, 64, 3), seed=10)
    rendered = _arr((96, 128, 3), seed=11)

    def scenario() -> dict:
        out = _send(owner, {"frame": frame, "rendered_frame": rendered, "n": 7})
        _assert_small_wire(out)  # массив реально ушёл в SHM, а не остался в конверте
        return gui.on_receive(_wire(out))

    got = _bounded(scenario)
    _assert_same(_restored(got, "rendered_frame"), rendered, "rendered_frame")
    _assert_same(_restored(got, "frame"), frame, "frame")
    assert got["data"]["n"] == 7


# ==================================== C6: fan-out ======================================
def _fanout_scenario(monkeypatch, make_owner, make_consumer, keys: tuple[str, ...]) -> None:
    """Один item (ОДИН dict, как в PipelineExecutor) к двум целям, кольца глубиной 2,
    num_consumers=2, loan ВКЛ. Пишется ли каждый ключ ровно один раз, видно по публичным
    следствиям: если бы второй send писал заново, B (следующий item) упёрся бы в исчерпание
    кольца — ``strip`` вернул бы None, а ``frame_loan_exhausted`` вырос бы."""
    monkeypatch.setenv("FW_SHM_LOAN_PROTOCOL", "1")
    monkeypatch.setenv("FW_SHM_SEQLOCK", "1")
    owner = make_owner(coll=2, num_consumers=2)
    gui1, gui2 = make_consumer("gui1"), make_consumer("gui2")
    shapes = {"frame": (48, 64, 3), "foo": (100, 100)}  # 9216 Б и 10000 Б — оба >= порога
    arrays = {k: _arr(shapes[k], seed=20 + i) for i, k in enumerate(keys)}
    assert all(a.nbytes >= BY_REF_MIN_NBYTES for a in arrays.values())  # страховка самого стенда

    def scenario() -> tuple[dict, dict]:
        item_a = {k: v for k, v in arrays.items()}
        out1 = owner.strip_data_frame_on_send({"target": "t1", "type": "data", "channel": "data", "data": item_a})
        out2 = owner.strip_data_frame_on_send({"target": "t2", "type": "data", "channel": "data", "data": item_a})
        assert out1 is not None and out2 is not None
        _assert_small_wire(out1)
        _assert_small_wire(out2)

        item_b = {k: _arr(v.shape, str(v.dtype), seed=90) for k, v in arrays.items()}
        out_b = owner.strip_data_frame_on_send({"target": "t1", "type": "data", "channel": "data", "data": item_b})
        assert out_b is not None, "второй item упёрся в исчерпание: первый item писался в SHM более одного раза"
        assert owner.frame_loan_exhausted == 0
        return gui1.on_receive(_wire(out1)), gui2.on_receive(_wire(out2))

    got1, got2 = _bounded(scenario)
    for k, want in arrays.items():
        _assert_same(_restored(got1, k), want, f"получатель 1, {k}")
        _assert_same(_restored(got2, k), want, f"получатель 2, {k}")


def test_c6_control_fanout_frame_written_once_both_restore(monkeypatch, make_owner, make_consumer):
    """CONTROL (зелёный сегодня): fan-out одного ``frame`` — пишется один раз, оба восстановили."""
    _fanout_scenario(monkeypatch, make_owner, make_consumer, ("frame",))


def test_c6_fanout_writes_each_key_once_both_restore(monkeypatch, make_owner, make_consumer):
    """C6: fan-out item с ``frame`` и ``foo`` — каждый ключ пишется в SHM один раз,
    оба получателя восстанавливают оба ключа."""
    _fanout_scenario(monkeypatch, make_owner, make_consumer, ("frame", "foo"))


# ============================== C7: независимость ключей ===============================
def _realloc_scenario(make_owner, make_consumer, grow: str, stable: str) -> None:
    """Ключ ``grow`` растёт (grow-only realloc его кольца) между двумя send'ами; сообщение 1
    (до роста) читается ПОСЛЕ отправки сообщения 2. Кольцо ключа ``stable`` пересоздаваться
    не имеет права -> его массив из сообщения 1 обязан восстановиться побайтно."""
    owner, gui = make_owner(coll=4), make_consumer()
    small = {"frame": (48, 64, 3), "foo": (64, 64)}  # 9216 Б и 8192 Б — оба >= порога
    dtypes = {"frame": "uint8", "foo": "uint16"}
    grown = {"frame": (96, 128, 3), "foo": (128, 128)}  # заведомо больше — realloc кольца ``grow``

    stable_1 = _arr(small[stable], dtypes[stable], seed=30)
    stable_2 = _arr(small[stable], dtypes[stable], seed=31)
    grow_2 = _arr(grown[grow], dtypes[grow], seed=32)

    def scenario() -> tuple[dict, dict]:
        m1 = _send(owner, {stable: stable_1, grow: _arr(small[grow], dtypes[grow], seed=33)})
        m2 = _send(owner, {stable: stable_2, grow: grow_2})
        _assert_small_wire(m1)
        _assert_small_wire(m2)
        # m1 читается только теперь, уже после роста ключа ``grow``.
        return gui.on_receive(_wire(m1)), gui.on_receive(_wire(m2))

    got1, got2 = _bounded(scenario)
    _assert_same(_restored(got1, stable), stable_1, f"сообщение 1 ДО роста {grow!r}: ключ {stable!r}")
    _assert_same(_restored(got2, stable), stable_2, f"сообщение 2: ключ {stable!r}")
    _assert_same(_restored(got2, grow), grow_2, f"сообщение 2: выросший ключ {grow!r}")


def test_c7_realloc_of_one_key_keeps_other_key_ring(make_owner, make_consumer):
    """C7 в обе стороны: рост ``foo`` не трогает кольцо ``frame``, рост ``frame`` — кольцо ``foo``."""
    _realloc_scenario(make_owner, make_consumer, grow="foo", stable="frame")
    _realloc_scenario(make_owner, make_consumer, grow="frame", stable="foo")


# ================================= C8: прочие сообщения =================================
def test_c8_non_data_message_with_arrays_untouched(make_owner):
    """C8 (зелёный сегодня): не-data сообщение не трогается — крупные массивы остаются теми же
    объектами, новых полей нет."""
    mw = make_owner()
    foo, frame = _arr((100, 100, 3), seed=40), _arr((100, 100, 3), seed=41)
    msg = {"type": "command", "data": {"foo": foo, "frame": frame, "n": 1}}

    out = _bounded(lambda: mw.strip_data_frame_on_send(msg))

    assert out is not None
    assert set(out) == {"type", "data"}, f"не-data сообщение получило/потеряло поля: {sorted(out)}"
    assert set(out["data"]) == {"foo", "frame", "n"}, f"data изменена: {sorted(out['data'])}"
    assert out["data"]["foo"] is foo and out["data"]["frame"] is frame


def test_c8_messages_without_data_field_untouched(make_owner):
    """C8 (зелёный сегодня): heartbeat / сообщение без ``type`` / ``type='data'`` без поля
    ``data`` проходят как есть и не роняют send-middleware."""
    mw = make_owner()
    cases = [{"type": "heartbeat", "ts": 1.5}, {"payload": 1}, {"type": "data"}]
    for original in cases:
        msg = dict(original)
        out = _bounded(lambda m=msg: mw.strip_data_frame_on_send(m))
        assert out is not None, f"сообщение {original} отброшено"
        assert out == original, f"сообщение {original} изменено: {out}"
