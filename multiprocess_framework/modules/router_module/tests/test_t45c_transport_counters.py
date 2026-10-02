# -*- coding: utf-8 -*-
"""Task 4.5c (transport-single-policy) — приёмка счётчиков кадрового транспорта: байты SHM,
сбои восстановления, описание колец. Независимый тест-автор (tester), от контракта Task 4.5c
(DESIGN лида), БЕЗ чтения реализации 4.5c (её к моменту написания нет — тесты заведомо RED).

Контракт, который здесь пинится (литералы, не производные от кода):
  * ``FrameShmMiddleware.bytes_written`` — int, растёт на ``array.nbytes`` КАЖДОГО массива, успешно
    записанного в слот СВОЕГО кольца (любой ключ, включая ``frame``; generic-путь отправки и
    wire-путь ``on_send`` одинаково); точен при конкурентных писателях (замок);
  * ``FrameShmMiddleware.bytes_read`` — int, растёт на ``array.nbytes`` каждого массива, успешно
    прочитанного по ссылке; stale/torn/битая ссылка не добавляет ничего;
  * ``FrameShmMiddleware.ring_info()`` — по записи на каждое созданное кольцо:
    ``{"key", "name", "depth"}``; глубина по умолчанию 3 (флаги выключены);
  * ``RouterManager.get_shm_stats()`` получает ``shm_bytes_written`` / ``shm_bytes_read`` /
    ``frame_restore_failures``; ``RouterManager.get_ring_info()`` = конкатенация ``ring_info()``;
  * ``build_router_shm_telemetry(router)`` получает ``bytes_written`` / ``bytes_read`` /
    ``restore_failures``;
  * команда ``introspect.router_stats`` кладёт в результат ``rings`` (= ``router.get_ring_info()``).

Стенд: реальные ``MemoryManager`` + ``FrameShmMiddleware`` (писатель ``A`` с кольцом ``coll=3``,
читатель ``B`` — отдельный middleware со своим ``MemoryManager``; между ними провод = ``pickle``
туда-обратно), реальный ``RouterManager`` (middleware кладётся в ``_frame_middlewares`` — так делают
соседние тесты узкой статистики). Флаги ``FW_SHM_*`` чистятся автоиспользуемой фикстурой.

Ожидаемые размеры (литералы): кадр 480x640x3 uint8 = 921_600 Б; маска 480x640 uint8 = 307_200 Б.
"""

from __future__ import annotations

import gc
import os
import pickle
import threading
from typing import Any, Callable

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    build_router_shm_telemetry,
)
from multiprocess_framework.modules.router_module.core.router_manager import RouterManager
from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import (
    FrameShmMiddleware,
)
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import (
    MemoryManager,
)

# --- литералы контракта -------------------------------------------------------------
FRAME_SHAPE = (480, 640, 3)  # 921_600 Б
FRAME_BYTES = 921_600
MASK_SHAPE = (480, 640)  # 307_200 Б
MASK_BYTES = 307_200
RING_DEPTH = 3
DEADLINE_S = 60.0  # потолок на сценарий: зависший тест хуже отсутствующего


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

    def make(self, owner: str, *, coll: int = RING_DEPTH) -> FrameShmMiddleware:
        mm = MemoryManager()
        mw = FrameShmMiddleware(mm, owner=owner, slot="output_frames", coll=coll)
        self._made.append((mw, mm))
        return mw

    def close(self) -> None:
        gc.collect()
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
    """``fn`` в daemon-потоке с дедлайном; зависание = FAIL, а не висящий прогон."""
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


def _frame(seed: int, shape: tuple[int, ...] = FRAME_SHAPE) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 250, size=shape).astype(np.uint8)


def _send(mw: FrameShmMiddleware, item: dict) -> dict:
    """Отправка как в PipelineExecutor._send_results: сообщение с item в ``data``."""
    out = mw.strip_data_frame_on_send({"target": "t", "type": "data", "channel": "data", "data": item})
    assert out is not None, "send-middleware отбросил сообщение (drop-на-источнике)"
    return out


def _wire(msg: dict) -> dict:
    """Провод очереди: pickle туда-обратно (получатель видит независимую копию)."""
    return pickle.loads(pickle.dumps(msg))


def _router_with(*mws: FrameShmMiddleware) -> RouterManager:
    r = RouterManager(manager_name="t45c_router")
    for mw in mws:
        r._frame_middlewares.append(mw)
    return r


# ===================================== bytes_written =====================================
@pytest.mark.parametrize("path", ["generic", "wire_on_send"])
def test_t45c_bytes_written_counts_frame_nbytes_per_message(rig, path):
    """5 сообщений по одному кадру 480x640x3 uint8 -> ``bytes_written`` == 4_608_000 (5 x 921_600)
    на ОБОИХ путях записи: generic (``strip_data_frame_on_send``) и wire (``on_send`` с top-level
    ``frame``). Красный revert: считать только generic-путь -> wire-параметр остаётся 0."""
    writer = rig.make("A")

    def scenario() -> int:
        for seed in range(5):
            if path == "generic":
                _send(writer, {"frame": _frame(seed)})
            else:
                out = writer.on_send({"frame": _frame(seed)})
                assert out is not None and "_shm_refs" in out["data"], "стенд: кадр не ушёл ссылкой в SHM"
        return writer.bytes_written

    assert _bounded(scenario) == 4_608_000


def test_t45c_bytes_written_counts_every_large_key_not_only_frame(rig):
    """К кадру добавлен второй крупный ключ ``mask`` 480x640 uint8 (307_200 Б): ``bytes_written``
    == 5 x (921_600 + 307_200) = 6_144_000. Красный revert: считать только ключ ``frame`` -> 4_608_000."""
    writer = rig.make("A")

    def scenario() -> int:
        for seed in range(5):
            out = _send(writer, {"frame": _frame(seed), "mask": _frame(seed + 50, MASK_SHAPE)})
            assert set(out["data"]["_shm_refs"]) == {"frame", "mask"}, "стенд: оба ключа обязаны уйти ссылками"
        return writer.bytes_written

    assert _bounded(scenario) == 5 * (FRAME_BYTES + MASK_BYTES)


def test_t45c_bytes_written_is_exact_under_two_concurrent_writers(rig):
    """Два потока по 200 кадров 640x480x3 через ОДИН middleware -> ``bytes_written`` ==
    400 x 921_600 = 368_640_000 ровно (замок: потерянный ``+=`` даст меньше). Потоки daemon,
    join с дедлайном."""
    writer = rig.make("A")
    shape = (640, 480, 3)  # тоже 921_600 Б
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def worker(base: int) -> None:
        try:
            barrier.wait(timeout=10)
            for i in range(200):
                _send(writer, {"frame": _frame(base + i, shape)})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(b,), daemon=True) for b in (0, 1000)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(DEADLINE_S)
    assert not any(t.is_alive() for t in threads), "писатели зависли (> дедлайна)"
    assert not errors, f"писатель упал: {errors[0]!r}"
    assert writer.bytes_written == 400 * FRAME_BYTES


# ===================================== bytes_read =====================================
def test_t45c_bytes_read_counts_fresh_refs(rig):
    """Читатель восстанавливает 5 свежих ссылок на кадр 480x640x3 -> ``bytes_read`` == 4_608_000.
    Каждая ссылка читается сразу после записи (кольцо глубиной 3 не успевает обернуться)."""
    writer, reader = rig.make("A"), rig.make("B")

    def scenario() -> int:
        for seed in range(5):
            msg = reader.on_receive(_wire(_send(writer, {"frame": _frame(seed)})))
            assert msg.get("frame") is not None or msg["data"].get("frame") is not None, "стенд: кадр не восстановлен"
        return reader.bytes_read

    assert _bounded(scenario) == 4_608_000


def test_t45c_bytes_read_stale_ref_adds_nothing(rig):
    """Свежая ссылка (921_600) + ссылка, ячейку которой переписали до чтения (кольцо обернулось,
    ``frame_stale_drops`` == 1): ``bytes_read`` остаётся 921_600 — дропнутое чтение байтов не даёт."""
    writer, reader = rig.make("A"), rig.make("B")

    def scenario() -> None:
        fresh = reader.on_receive(_wire(_send(writer, {"frame": _frame(1)})))
        assert (fresh.get("frame") is not None) or (fresh["data"].get("frame") is not None), "стенд: fresh не прочитан"
        stale_wire = _wire(_send(writer, {"frame": _frame(2)}))
        for seed in range(RING_DEPTH):  # обернуть кольцо: ячейка stale_wire перезаписана
            _send(writer, {"frame": _frame(100 + seed)})
        reader.on_receive(stale_wire)

    _bounded(scenario)
    assert reader.frame_stale_drops == 1, "стенд: ссылка не оказалась stale (обёртка кольца не сработала)"
    assert reader.bytes_read == FRAME_BYTES


# ===================================== frame_restore_failures / stats / telemetry =====================================
def test_t45c_broken_ref_shows_up_in_router_shm_stats(rig):
    """Битая ссылка (``name=None``) -> ``frame_restore_failures`` читателя == 1, и
    ``RouterManager.get_shm_stats()["frame_restore_failures"]`` == 1. Ссылка с ЧУЖИМ, но well-formed
    именем сегмента здесь не годится: на 89336393 она считается отвязанным сегментом
    (``frame_stale_drops``, 4.4c), а не сбоем восстановления — проверено прогоном."""
    reader = rig.make("B")
    router = _router_with(reader)
    broken = {"owner": "A", "slot": "output_frames", "idx": 0, "gen": 2, "name": None}

    _bounded(lambda: reader.restore_frame({"data": {"_shm_refs": {"frame": broken}}}))

    stats = router.get_shm_stats()
    assert "frame_restore_failures" in stats, f"ключа нет в узкой статистике: {sorted(stats)}"
    assert stats["frame_restore_failures"] == 1


def test_t45c_shm_stats_and_telemetry_carry_the_new_counters(rig):
    """Писатель: 2 кадра (1_843_200 Б); читатель: 1 кадр (921_600 Б) + 1 битая ссылка. Роутер держит
    обоих: ``get_shm_stats()`` даёт суммы по ключам ``shm_bytes_written`` / ``shm_bytes_read`` /
    ``frame_restore_failures``, а ``build_router_shm_telemetry`` — те же числа под именами
    ``bytes_written`` / ``bytes_read`` / ``restore_failures``."""
    writer, reader = rig.make("A"), rig.make("B")
    router = _router_with(writer, reader)
    broken = {"owner": "A", "slot": "output_frames", "idx": 0, "gen": 2, "name": None}

    def scenario() -> None:
        reader.on_receive(_wire(_send(writer, {"frame": _frame(1)})))
        _send(writer, {"frame": _frame(2)})
        reader.restore_frame({"data": {"_shm_refs": {"frame": broken}}})

    _bounded(scenario)

    stats = router.get_shm_stats()
    for key in ("shm_bytes_written", "shm_bytes_read", "frame_restore_failures"):
        assert key in stats, f"ключа {key} нет в get_shm_stats(): {sorted(stats)}"
    assert stats["shm_bytes_written"] == 2 * FRAME_BYTES
    assert stats["shm_bytes_read"] == FRAME_BYTES
    assert stats["frame_restore_failures"] == 1

    telemetry = build_router_shm_telemetry(router)
    for key in ("bytes_written", "bytes_read", "restore_failures"):
        assert key in telemetry, f"ключа {key} нет в телеметрии: {sorted(telemetry)}"
    assert telemetry["bytes_written"] == 2 * FRAME_BYTES
    assert telemetry["bytes_read"] == FRAME_BYTES
    assert telemetry["restore_failures"] == 1


# ===================================== ring_info =====================================
def test_t45c_ring_info_describes_every_created_ring_and_router_concatenates(rig):
    """После записи ``frame`` и ``mask`` у писателя ``A`` ``ring_info()`` — ровно две записи
    ``{"key","name","depth"}``: ключи {"frame","mask"}, глубина 3, имена различны. У второго писателя
    ``B`` (только ``frame``) — одна запись. ``RouterManager.get_ring_info()`` == конкатенация
    ``A.ring_info() + B.ring_info()`` (три записи)."""
    a, b = rig.make("A"), rig.make("B")
    router = _router_with(a, b)

    def scenario() -> None:
        _send(a, {"frame": _frame(1), "mask": _frame(2, MASK_SHAPE)})
        _send(b, {"frame": _frame(3)})

    _bounded(scenario)

    info_a = a.ring_info()
    assert len(info_a) == 2, f"ожидались два кольца (frame, mask), получено: {info_a}"
    assert {e["key"] for e in info_a} == {"frame", "mask"}
    for entry in info_a:
        assert set(entry) == {"key", "name", "depth"}, entry
        assert entry["depth"] == RING_DEPTH, entry
        assert isinstance(entry["name"], str) and entry["name"], entry
    assert len({e["name"] for e in info_a}) == 2, f"имена колец совпали: {info_a}"

    info_b = b.ring_info()
    assert [e["key"] for e in info_b] == ["frame"]

    combined = router.get_ring_info()
    assert len(combined) == 3
    assert combined == info_a + info_b


# ===================================== introspect.router_stats =====================================
class _FakeCommandManager:
    def __init__(self) -> None:
        self.handlers: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler

    def dispatch(self, command: str, data: dict | None = None) -> dict:
        return self.handlers[command](data or {})


class _FakeServices:
    """Минимальные сервисы процесса для ``BuiltinCommands._register_introspect_commands`` (по образцу
    ``process_module/tests/test_introspect_commands.py``), но с НАСТОЯЩИМ ``RouterManager``."""

    def __init__(self, router) -> None:
        self.command_manager = _FakeCommandManager()
        self.router_manager = router
        self.worker_manager = None
        self._orchestrator = None
        self.queues = None
        self.shared_resources = None
        self.name = "preprocessor"
        self._current_process_status = "running"

    def _log_info(self, *a, **k) -> None: ...
    def _log_debug(self, *a, **k) -> None: ...
    def _log_warning(self, *a, **k) -> None: ...


def test_t45c_introspect_router_stats_reports_rings(rig):
    """Команда ``introspect.router_stats`` у процесса с настоящим роутером, чей писатель уже создал
    кольцо ``frame``, отдаёт в результате ``rings`` == ``router.get_ring_info()``: одна запись
    ``{"key": "frame", "depth": 3, ...}``. Существующие ключи (``success``, ``router_stats``) на месте."""
    writer = rig.make("A")
    router = _router_with(writer)
    _bounded(lambda: _send(writer, {"frame": _frame(1)}))

    svc = _FakeServices(router)
    BuiltinCommands(svc)._register_introspect_commands()
    result = svc.command_manager.dispatch("introspect.router_stats")

    assert result["success"] is True
    assert "router_stats" in result
    assert "rings" in result, f"в результате нет rings; ключи: {sorted(result)}"
    assert len(result["rings"]) == 1
    assert result["rings"][0]["key"] == "frame"
    assert result["rings"][0]["depth"] == RING_DEPTH
    assert result["rings"] == router.get_ring_info()
