# -*- coding: utf-8 -*-
"""RED-приёмка ``RemoteFrameSource`` / ``ShmFrameReader(track=...)`` (Task 1.3, gui-service).

Слепой независимый tester. Видел ТОЛЬКО: контракт ``remote_frame_source.py``
(докстринги/сигнатуры, тела — ``NotImplementedError``), докстринг ``track`` у
``ShmFrameReader.__init__``, ``socket_client.py``/``socket_channel.py`` (публичная
поверхность) и существующий тест ``router_module/tests/test_socket_client.py`` как
образец харнесса «реальный ``RouterManager`` + реальный ``SocketChannel(port=0)``».
НЕ видел ``_impl/`` (если уже есть), не видел диз-документ ``docs/reviews/2026-09-24_gui-1.3-design.md``
дальше секций DESIGN/REDS, переданных дословно в задании.

Большинство тестов ниже падают СЕЙЧАС в одной и той же точке —
``RemoteFrameSource(...)`` бросает ``NotImplementedError`` в конструкторе. Это
ожидаемо для стадии INTERFACE: тело теста после конструктора — спецификация для
GREEN, а не то, что сейчас реально исполняется. R2 — исключение: он бьёт по уже
существующему коду (``ShmFrameReader``), не по стабу, поэтому падает
``AssertionError``, а не ``NotImplementedError`` (см. докстринг ``track`` —
``self._track`` сохраняется, но нигде не используется).
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import uuid
from multiprocessing import shared_memory
from queue import Queue
from types import SimpleNamespace
from typing import Any, Callable, Dict, List
from unittest.mock import Mock

import numpy as np
import pytest

from multiprocess_framework.modules.frontend_module.bridge.remote_frame_source import (
    RemoteFrameSource,
    RemoteFrameSourceError,
)
from multiprocess_framework.modules.router_module.adapters.socket_bridge_adapter import SocketBridgeAdapter
from multiprocess_framework.modules.router_module.channels.queue_channel import QueueChannel
from multiprocess_framework.modules.router_module.channels.socket_channel import SocketChannel
from multiprocess_framework.modules.router_module.channels.socket_client import SocketClient
from multiprocess_framework.modules.router_module.core.router_manager import RouterManager
from multiprocess_framework.modules.shared_resources_module.memory.format.buffer import (
    calculate_buffer_size,
    pack_images,
)
from multiprocess_framework.modules.shared_resources_module.memory.reader.shm_frame_reader import (
    ShmFrameReader,
)

# --------------------------------------------------------------------------- харнесс хоста
# Дословно по образцу router_module/tests/test_socket_client.py::_make_command_host —
# не изобретённый мной API, существующий паттерн этого кодабейза.


class _Host:
    def __init__(self, router: RouterManager, sock_ch: SocketChannel) -> None:
        self.router = router
        self._sock_ch = sock_ch

    @property
    def host(self) -> str:
        return "127.0.0.1"

    @property
    def port(self) -> int:
        return self._sock_ch.port

    def push(self, msg: Dict[str, Any]) -> None:
        self._sock_ch.send(msg)

    def close(self) -> None:
        try:
            self.router.shutdown()
        finally:
            self._sock_ch.close()


def _make_command_host(commands: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]) -> _Host:
    loop_q: Queue = Queue()
    router = RouterManager(manager_name="host")
    router.register_channel(QueueChannel("self", loop_q))

    def _get_command_info(name: str):
        return {"key": name, "metadata": {}} if name in commands else None

    def _handle_command(msg: Dict[str, Any]) -> Dict[str, Any]:
        handler = commands.get(msg.get("command"))
        if handler is None:
            return {"status": "error", "reason": "no handler"}
        return handler(msg)

    cm = Mock()
    cm.get_command_info = Mock(side_effect=_get_command_info)
    cm.handle_command = Mock(side_effect=_handle_command)
    router.process = SimpleNamespace(command_manager=cm)

    to_self = RouterManager._make_channel_handler("self")
    for key in list(commands) + ["command.response"]:
        router.register_channel_handler(key, to_self)

    router.initialize()
    router.start_listening(poll_interval=0.01)

    adapter = SocketBridgeAdapter(router, "backend_ctl")
    sock_ch = SocketChannel("backend_ctl", host="127.0.0.1", port=0, on_inbound=adapter.on_inbound)
    assert sock_ch.start() is True
    router.register_channel(sock_ch)

    return _Host(router, sock_ch)


def _call_with_deadline(fn: Callable[[], Any], timeout: float = 5.0) -> Any:
    """Любой блокирующий вызов — в daemon-потоке с join-дедлайном (проектное правило)."""
    box: Dict[str, Any] = {}

    def _run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["exc"] = exc

    t = threading.Thread(target=_run, daemon=True, name="t13-caller")
    t.start()
    t.join(timeout)
    assert not t.is_alive(), f"вызов не завершился за {timeout}с — зависание вместо ошибки"
    if "exc" in box:
        raise box["exc"]
    return box.get("result")


def _wait(predicate: Callable[[], bool], timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# --------------------------------------------------------------------------- SHM-хелперы


def _shm_name(tag: str) -> str:
    # POSIX-имя ≤ 31 символа на macOS.
    return f"t13{tag}{uuid.uuid4().hex[:6]}"


def _corner_frame(h: int = 480, w: int = 640, value: int = 7) -> np.ndarray:
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[0, 0] = value
    frame[0, w - 1] = value
    frame[h - 1, 0] = value
    frame[h - 1, w - 1] = value
    return frame


def _write_frame(name: str, frame: np.ndarray, *, seqlock: bool = False):
    size = calculate_buffer_size(1, frame.shape, frame.dtype, seqlock=seqlock)
    shm = shared_memory.SharedMemory(name=name, create=True, size=size)
    pack_images(shm.buf, [frame], frame.shape, frame.dtype, seqlock=seqlock)
    return shm


def _push_descriptor(
    host: _Host, address: str, sender: str, name: str, bseq: int, *, seqlock: bool = False, idx=None
) -> None:
    descriptor = {"sender": sender, "name": name, "idx": idx, "seqlock": seqlock, "bseq": bseq, "ts": time.time()}
    host.push(
        {
            "type": "event",
            "targets": [address],
            "queue_type": "observability",
            "command": "frames.frame",
            "sender": "gui",
            "data": descriptor,
        }
    )


# --------------------------------------------------------------------------- R1


def test_r1_bitwise_identical_frame_and_matching_bseq() -> None:
    """R1: реальный SHM-слот 480x640x3 uint8 с метками углов → on_frame получает
    побитово равный uint8-массив с тем же bseq (Post ``subscribe``: «СОБСТВЕННАЯ
    копия ... побитово равная содержимому слота на момент копии»)."""
    frame = _corner_frame()
    name = _shm_name("r1")
    shm = _write_frame(name, frame)
    host = _make_command_host(
        {"frames.subscribe": lambda msg: {"success": True, "seqlock": False, "owner_incarnation": False}}
    )
    source = None
    try:
        client = SocketClient(host.host, host.port, sender="pult")
        client.connect()
        received: List[Any] = []
        source = RemoteFrameSource(client, dispatch=lambda fn: fn())
        resp = _call_with_deadline(
            lambda: source.subscribe(None, lambda sender, arr, bseq: received.append((sender, arr, bseq))),
            timeout=5.0,
        )
        assert resp == {"success": True, "seqlock": False, "owner_incarnation": False}

        _push_descriptor(host, client.subscriber_address, "camA", name, bseq=1)

        assert _wait(lambda: len(received) == 1, timeout=3.0), "on_frame не вызван за 3с"
        sender, arr, bseq = received[0]
        assert sender == "camA"
        assert bseq == 1
        assert arr.dtype == np.uint8
        assert arr.shape == frame.shape
        assert np.array_equal(arr, frame)
        assert arr is not frame  # собственная копия, не view в SHM
    finally:
        if source is not None:
            source.close()
        shm.close()
        try:
            shm.unlink()
        except FileNotFoundError:
            pass
        host.close()


# --------------------------------------------------------------------------- R2


_R2_SCRIPT = (
    "import sys\n"
    "from multiprocessing import shared_memory\n"
    "from multiprocess_framework.modules.shared_resources_module.memory.reader.shm_frame_reader import ShmFrameReader\n"
    "name = sys.argv[1]\n"
    "track = sys.argv[2] == '1'\n"
    "reader = ShmFrameReader(cache_enabled=False, zero_copy=False, cap=1, track=track)\n"
    "reader.read_frame(name)\n"
)


def _external_read(name: str, *, track: bool) -> None:
    """Читает сегмент ``name`` в НАСТОЯЩЕМ внешнем процессе (``python -c``, не fork/spawn
    внутри дерева — внутри дерева хазард не воспроизводится, дети делят tracker родителя)."""
    subprocess.run([sys.executable, "-c", _R2_SCRIPT, name, "1" if track else "0"], check=True, timeout=10)


def _segment_alive(name: str) -> bool:
    try:
        shm = shared_memory.SharedMemory(name=name, create=False)
    except FileNotFoundError:
        return False
    shm.close()
    return True


def test_r2_external_reader_with_track_false_keeps_backend_segment_alive() -> None:
    """R2 (RED): подпроцесс читает через ``ShmFrameReader(track=False)`` и выходит →
    сегмент бэкенда в родителе по-прежнему открывается по имени. Сейчас RED: ``track``
    сохраняется в ``self._track``, но ``resource_tracker.unregister`` нигде не зовётся —
    поведение при track=False пока идентично track=True (см. докстринг ``track``)."""
    frame = _corner_frame()
    name = _shm_name("r2a")
    shm = _write_frame(name, frame)
    try:
        _external_read(name, track=False)
        assert _segment_alive(name), (
            "внешний читатель с track=False удалил живой сегмент бэкенда — "
            "resource_tracker.unregister ещё не реализован"
        )
    finally:
        if _segment_alive(name):
            shm.close()
            shm.unlink()
        else:
            shm.close()


def test_r2_control_external_reader_with_track_true_still_deletes_segment() -> None:
    """R2 (контроль, ожидаемо GREEN уже сейчас): track=True — прежнее поведение,
    хазард воспроизводится и ДО, и ПОСЛЕ фикса (внутри задачи не меняется)."""
    frame = _corner_frame()
    name = _shm_name("r2b")
    shm = _write_frame(name, frame)
    try:
        _external_read(name, track=True)
        assert not _segment_alive(name), "track=True должен по-прежнему терять сегмент — это и есть хазард"
    finally:
        if _segment_alive(name):
            shm.close()
            shm.unlink()
        else:
            shm.close()


# --------------------------------------------------------------------------- R3


def test_r3_missing_segment_counts_and_next_valid_still_delivered() -> None:
    """R3: дескриптор с несуществующим name → без исключения, stats["missing"] == 1,
    следующий валидный доставлен (``missing``: «не исключение наружу — счётчик и строка
    лога, следующий дескриптор обрабатывается»)."""
    frame = _corner_frame()
    valid_name = _shm_name("r3")
    shm = _write_frame(valid_name, frame)
    host = _make_command_host(
        {"frames.subscribe": lambda msg: {"success": True, "seqlock": False, "owner_incarnation": False}}
    )
    source = None
    try:
        client = SocketClient(host.host, host.port, sender="pult")
        client.connect()
        received: List[Any] = []
        source = RemoteFrameSource(client, dispatch=lambda fn: fn())
        _call_with_deadline(lambda: source.subscribe(None, lambda s, a, b: received.append((s, a, b))), timeout=5.0)

        _push_descriptor(host, client.subscriber_address, "camA", "t13-does-not-exist-xyz", bseq=1)
        assert _wait(lambda: source.stats["missing"] == 1, timeout=3.0), "missing не досчитан за 3с"
        assert received == [], "колбэк не должен звать для отсутствующего сегмента"

        _push_descriptor(host, client.subscriber_address, "camA", valid_name, bseq=2)
        assert _wait(lambda: len(received) == 1, timeout=3.0), "следующий валидный дескриптор не доставлен"
        assert received[0][2] == 2
    finally:
        if source is not None:
            source.close()
        shm.close()
        try:
            shm.unlink()
        except FileNotFoundError:
            pass
        host.close()


# --------------------------------------------------------------------------- R4


def test_r4_duplicate_descriptor_delivered_once() -> None:
    """R4: один и тот же дескриптор дважды → on_frame зовётся один раз, stats["dup"] == 1
    (``dup``: «bseq равен bseq последнего доставленного кадра того же sender»)."""
    frame = _corner_frame()
    name = _shm_name("r4")
    shm = _write_frame(name, frame)
    host = _make_command_host(
        {"frames.subscribe": lambda msg: {"success": True, "seqlock": False, "owner_incarnation": False}}
    )
    source = None
    try:
        client = SocketClient(host.host, host.port, sender="pult")
        client.connect()
        received: List[Any] = []
        source = RemoteFrameSource(client, dispatch=lambda fn: fn())
        _call_with_deadline(lambda: source.subscribe(None, lambda s, a, b: received.append((s, a, b))), timeout=5.0)

        _push_descriptor(host, client.subscriber_address, "camA", name, bseq=5)
        assert _wait(lambda: len(received) == 1, timeout=3.0)

        _push_descriptor(host, client.subscriber_address, "camA", name, bseq=5)
        # Дедуп — не сразу видимый снаружи побочный эффект: даём окно, затем сверяем,
        # что второй раз колбэк НЕ прибавился, ждать больше нечего (latest-wins, один слот).
        time.sleep(0.3)
        assert len(received) == 1, "дубликат bseq вызвал on_frame повторно"
        assert source.stats["dup"] == 1
    finally:
        if source is not None:
            source.close()
        shm.close()
        try:
            shm.unlink()
        except FileNotFoundError:
            pass
        host.close()


# --------------------------------------------------------------------------- R5


def _writer_thread(shm_name: str, stop: threading.Event, *, seqlock: bool) -> threading.Thread:
    def _run() -> None:
        shm = shared_memory.SharedMemory(name=shm_name, create=False)
        try:
            n = 0
            while not stop.is_set():
                frame = _corner_frame(value=(n % 250) + 1)
                pack_images(shm.buf, [frame], frame.shape, frame.dtype, seqlock=seqlock)
                n += 1
                time.sleep(0.001)
        finally:
            shm.close()

    t = threading.Thread(target=_run, daemon=True, name="t13-r5-writer")
    t.start()
    return t


def _corner_values_match(frame: np.ndarray) -> bool:
    v = int(frame[0, 0, 0])
    return int(frame[0, -1, 0]) == v and int(frame[-1, 0, 0]) == v and int(frame[-1, -1, 0]) == v


def test_r5_seqlock_zero_corner_mismatches_under_concurrent_writer() -> None:
    """R5 (seqlock=True): писатель непрерывно перезаписывает слот → у ВСЕХ доставленных
    кадров 0 расхождений углов (seqlock ловит torn-чтение и возвращает None → не
    засчитывается delivered). torn печатается, не проверяется числом (порога нет)."""
    name = _shm_name("r5")
    seed = _corner_frame()
    shm = _write_frame(name, seed, seqlock=True)
    host = _make_command_host(
        {"frames.subscribe": lambda msg: {"success": True, "seqlock": True, "owner_incarnation": False}}
    )
    stop = threading.Event()
    writer = _writer_thread(name, stop, seqlock=True)
    source = None
    try:
        client = SocketClient(host.host, host.port, sender="pult")
        client.connect()
        received: List[np.ndarray] = []
        source = RemoteFrameSource(client, dispatch=lambda fn: fn())
        _call_with_deadline(lambda: source.subscribe(None, lambda s, a, b: received.append(a)), timeout=5.0)

        for bseq in range(1, 60):
            _push_descriptor(host, client.subscriber_address, "camA", name, bseq=bseq, seqlock=True)
            time.sleep(0.005)
        _wait(lambda: len(received) >= 1, timeout=3.0)

        mismatches = sum(1 for f in received if not _corner_values_match(f))
        print(
            f"R5 seqlock=True: доставлено={len(received)} torn={source.stats.get('torn')} "
            f"расхождения_углов={mismatches}"
        )
        assert mismatches == 0, f"{mismatches} доставленных кадров с расходящимися углами при seqlock=True"
    finally:
        stop.set()
        writer.join(timeout=2.0)
        if source is not None:
            source.close()
        shm.close()
        try:
            shm.unlink()
        except FileNotFoundError:
            pass
        host.close()


def test_r5_without_seqlock_measures_mismatches_no_assert() -> None:
    """R5 (без seqlock): то же самое, но torn-детекции нет по построению (docstring
    задачи: «Torn-кадры детектируются только при FW_SHM_SEQLOCK=1»). Печатаем число
    расхождений на ~50 кадров, БЕЗ assert — это измерение, не приёмка."""
    name = _shm_name("r5b")
    seed = _corner_frame()
    shm = _write_frame(name, seed, seqlock=False)
    host = _make_command_host(
        {"frames.subscribe": lambda msg: {"success": True, "seqlock": False, "owner_incarnation": False}}
    )
    stop = threading.Event()
    writer = _writer_thread(name, stop, seqlock=False)
    source = None
    try:
        client = SocketClient(host.host, host.port, sender="pult")
        client.connect()
        received: List[np.ndarray] = []
        source = RemoteFrameSource(client, dispatch=lambda fn: fn())
        _call_with_deadline(lambda: source.subscribe(None, lambda s, a, b: received.append(a)), timeout=5.0)

        for bseq in range(1, 60):
            _push_descriptor(host, client.subscriber_address, "camA", name, bseq=bseq, seqlock=False)
            time.sleep(0.005)
        _wait(lambda: len(received) >= 1, timeout=3.0)

        mismatches = sum(1 for f in received if not _corner_values_match(f))
        print(f"R5 seqlock=False: доставлено={len(received)} расхождения_углов={mismatches} (без порога)")
    finally:
        stop.set()
        writer.join(timeout=2.0)
        if source is not None:
            source.close()
        shm.close()
        try:
            shm.unlink()
        except FileNotFoundError:
            pass
        host.close()


# --------------------------------------------------------------------------- R6


def test_r6_slow_callback_does_not_slow_producer_superseded_grows() -> None:
    """R6: on_frame спит 200мс, дескрипторы продолжают приходить → продюсер (пушер)
    не тормозит, stats["superseded"] растёт (латест-wins почтовый ящик), инвариант
    счётчиков держится. Продюсер и ожидания — в daemon-потоке с join-дедлайном."""
    name = _shm_name("r6")
    frame = _corner_frame()
    shm = _write_frame(name, frame)
    host = _make_command_host(
        {"frames.subscribe": lambda msg: {"success": True, "seqlock": False, "owner_incarnation": False}}
    )
    source = None
    try:
        client = SocketClient(host.host, host.port, sender="pult")
        client.connect()

        def _slow_on_frame(sender: str, arr: np.ndarray, bseq: int) -> None:
            time.sleep(0.2)

        source = RemoteFrameSource(client, dispatch=lambda fn: fn())
        _call_with_deadline(lambda: source.subscribe(None, _slow_on_frame), timeout=5.0)

        def _pusher() -> None:
            for bseq in range(1, 21):
                _push_descriptor(host, client.subscriber_address, "camA", name, bseq=bseq)
                time.sleep(0.02)

        t0 = time.monotonic()
        pusher = threading.Thread(target=_pusher, daemon=True, name="t13-r6-pusher")
        pusher.start()
        pusher.join(timeout=5.0)
        assert not pusher.is_alive(), "продюсер завис вместо равномерной отправки 20 дескрипторов"
        elapsed = time.monotonic() - t0
        assert elapsed < 1.0, f"продюсер притормозил медленным колбэком: {elapsed:.3f}с на 20 пушей (0.2с/кадр колбэк)"

        assert _wait(lambda: source.stats["superseded"] > 0, timeout=3.0), (
            "superseded не растёт — почтовый ящик не latest-wins, продюсер должен был обогнать копирование"
        )
        stats = source.stats
        accounted = (
            stats["delivered"] + stats["dup"] + stats["torn"] + stats["missing"] + stats["errors"] + stats["superseded"]
        )
        in_flight = stats["received"] - accounted
        assert 0 <= in_flight <= 2, f"инвариант stats нарушен (in_flight={in_flight} вне [0,2]): {stats}"
    finally:
        if source is not None:
            source.close()
        shm.close()
        try:
            shm.unlink()
        except FileNotFoundError:
            pass
        host.close()


# --------------------------------------------------------------------------- R7


def test_r7_loan_protocol_refusal_raises_naming_the_flag() -> None:
    """R7: хост отказывает в подписке с reason, называющим FW_SHM_LOAN_PROTOCOL →
    subscribe бросает RemoteFrameSourceError, текст содержит подстроку "FW_SHM_LOAN_PROTOCOL";
    ни одного кадра не доставлено."""
    host = _make_command_host(
        {
            "frames.subscribe": lambda msg: {
                "success": False,
                "reason": "слот занят под FW_SHM_LOAN_PROTOCOL",
            }
        }
    )
    source = None
    try:
        client = SocketClient(host.host, host.port, sender="pult")
        client.connect()
        received: List[Any] = []
        source = RemoteFrameSource(client, dispatch=lambda fn: fn())
        with pytest.raises(RemoteFrameSourceError) as exc_info:
            _call_with_deadline(lambda: source.subscribe(None, lambda s, a, b: received.append((s, a, b))), timeout=5.0)
        assert "FW_SHM_LOAN_PROTOCOL" in str(exc_info.value)
        assert received == []
    finally:
        if source is not None:
            source.close()
        host.close()


# --------------------------------------------------------------------------- R8


def test_r8_on_reconnected_resubscribes_with_new_subscriber_address() -> None:
    """R8: после client.close()+client.connect() (новый session) и on_reconnected() —
    хост получает НОВЫЙ frames.subscribe с НОВЫМ subscriber_address (не старым)."""
    subscribe_calls: List[Any] = []

    def _handle_subscribe(msg: Dict[str, Any]) -> Dict[str, Any]:
        subscribe_calls.append(msg.get("data", {}).get("subscriber"))
        return {"success": True, "seqlock": False, "owner_incarnation": False}

    host = _make_command_host({"frames.subscribe": _handle_subscribe})
    source = None
    try:
        client = SocketClient(host.host, host.port, sender="pult")
        client.connect()
        source = RemoteFrameSource(client, dispatch=lambda fn: fn())
        _call_with_deadline(lambda: source.subscribe(None, lambda s, a, b: None), timeout=5.0)
        first_address = client.subscriber_address
        assert subscribe_calls == [first_address]

        client.close()
        client.connect()
        second_address = client.subscriber_address
        assert second_address != first_address

        _call_with_deadline(lambda: source.on_reconnected(), timeout=5.0)

        assert subscribe_calls[-1] == second_address, "on_reconnected не переподписал(ся) НОВЫМ адресом"
        assert first_address not in subscribe_calls[1:], "старый адрес не должен уходить повторно после реконнекта"
    finally:
        if source is not None:
            source.close()
        host.close()
