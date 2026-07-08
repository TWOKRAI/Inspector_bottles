"""Гоночный тест snapshot-API DeviceManager (Ф3.4 M-race-1).

Воспроизводит исходную гонку: reader-поток читает реестр (snapshot_registry /
list_devices / connected_ids / device_count) ПАРАЛЛЕЛЬНО с writer-потоком,
делающим upsert/remove ×N. До фикса чтения шли без лока и обход
``_entries.values()`` при параллельном ``pop``/``[]=`` давал
``RuntimeError: dictionary changed size during iteration``.

Acceptance: за весь прогон — ни одного RuntimeError (и любого другого
исключения) в reader/writer-потоках.

По образцу ``Services/device_hub/tests/test_regressions.py`` (TestConcurrencyRLock).
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from Services.device_hub.manager import DeviceManager
from Services.device_hub.registry.store import RegistryStore

#: Число итераций writer'а и число оборотов reader'а.
_N = 300


class _FakeDrv:
    """Минимальный драйвер для гонки по _drivers (is_connected — флаг)."""

    def __init__(self, connected: bool = True) -> None:
        self.is_connected = connected


class TestSnapshotRace:
    """reader (snapshot) ∥ writer (upsert/remove) — 0 RuntimeError."""

    @pytest.fixture
    def mgr(self, tmp_path: Path) -> DeviceManager:
        m = DeviceManager(RegistryStore(tmp_path / "devices.yaml"))
        m.initialize()
        return m

    def test_reader_writer_no_runtime_error(self, mgr: DeviceManager) -> None:
        """Параллельные чтения snapshot-API не ломаются при мутации реестра."""
        errors: list[BaseException] = []
        done = threading.Event()

        def writer() -> None:
            try:
                for i in range(_N):
                    mgr.upsert({"id": f"d{i}", "name": f"D{i}", "kind": "robot"})
                    # Мутация _drivers под локом — как реальный lifecycle
                    with mgr._registry_lock:
                        mgr._drivers[f"d{i}"] = _FakeDrv()
                    if i >= 5:
                        old = f"d{i - 5}"
                        try:
                            mgr.remove(old)
                        except Exception:
                            pass  # remove гонок-безопасен; отсутствие записи не ошибка
            except BaseException as exc:  # pragma: no cover — сигнал гонки
                errors.append(exc)
            finally:
                done.set()

        def reader() -> None:
            try:
                while not done.is_set():
                    mgr.snapshot_registry()
                    mgr.list_devices()
                    mgr.connected_ids()
                    mgr.device_count()
                    mgr.connected_count()
            except BaseException as exc:  # pragma: no cover — сигнал гонки
                errors.append(exc)

        readers = [threading.Thread(target=reader) for _ in range(3)]
        w = threading.Thread(target=writer)
        for r in readers:
            r.start()
        w.start()
        w.join(timeout=10)
        for r in readers:
            r.join(timeout=10)

        assert not errors, f"Гонка reader ∥ writer дала исключения: {errors!r}"
        # Реестр консистентен: живы последние 5 устройств
        assert mgr.device_count() == 5
