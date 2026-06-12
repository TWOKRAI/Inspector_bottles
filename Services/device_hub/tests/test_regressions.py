"""Регрессионные тесты ревью Fable — Services/device_hub.

Покрывает:
  н3: draw → исполнение → очередь пуста → mode возвращается в cvt
  н4: merge-upsert корректно защищает name/enabled при recipe-origin
  конкурентность: RLock на _entries/_drivers не ломает CRUD
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from Services.robot_comm.server.sim_core import RobotSimCore
from Services.robot_comm.testing.fake_transport import FakeRobotTransport

from Services.device_hub.drivers.robot_driver import RobotDriver
from Services.device_hub.manager import DeviceManager
from Services.device_hub.registry.entry import DeviceEntry
from Services.device_hub.registry.store import RegistryStore
from Services.device_hub.tests.conftest import FakeClock


# ================================================================== #
# н3: mode возвращается в cvt после draw
# ================================================================== #


class TestDrawModeReturnToCvt:
    """н3: после опустошения draw-очереди mode возвращается в cvt."""

    @pytest.fixture
    def robot_entry(self) -> DeviceEntry:
        return DeviceEntry(
            id="robot_main",
            name="Робот Delta",
            kind="robot",
            transport={"type": "tcp", "host": "127.0.0.1", "port": 502, "unit_id": 2},
            params={"word_order": "little", "feed_poll_s": 0.01, "telemetry_interval_s": 0.1},
        )

    @pytest.fixture
    def driver(self, robot_entry) -> RobotDriver:
        core = RobotSimCore()
        transport = FakeRobotTransport(core)
        clock = FakeClock()
        d = RobotDriver(
            robot_entry,
            protocol=None,
            transport=transport,
            clock=clock.clock,
            sleep=clock.sleep,
        )
        d.connect()
        return d

    def test_draw_circle_then_mode_returns_cvt(self, driver) -> None:
        """draw_circle → исполнение → очередь пуста → mode == cvt."""
        assert driver.mode == "cvt"

        # Поставить задание рисования
        result = driver.call("draw_circle", {"cx": 100, "cy": 100, "r": 50})
        assert result["status"] == "ok"

        # Исполнить через tick
        stop = threading.Event()
        driver.tick(stop)

        # После исполнения: draw_queue пуста, _draw_busy False
        assert driver._draw_queue.empty()
        assert not driver._draw_busy

        # Следующий tick возвращает mode в cvt
        driver.tick(stop)
        assert driver.mode == "cvt", "mode должен вернуться в cvt после завершения draw"

    def test_vfd_driver_not_stale_after_draw_done(self, driver) -> None:
        """VfdDriver видит mode=cvt после завершения draw → poll возобновляется."""
        # Рисуем
        driver.call("draw_circle", {"cx": 0, "cy": 0, "r": 10})
        stop = threading.Event()
        driver.tick(stop)  # исполняет draw
        driver.tick(stop)  # возвращает mode в cvt

        # Проверяем что mode == cvt — VfdDriver._is_carrier_in_draw вернёт False
        assert driver.mode == "cvt"


# ================================================================== #
# н4: merge-upsert защищает name/enabled
# ================================================================== #


class TestUpsertMergeProtection:
    """н4: при recipe-upsert ручные name/enabled не затираются."""

    @pytest.fixture
    def mgr(self, tmp_path: Path) -> DeviceManager:
        store = RegistryStore(tmp_path / "devices.yaml")
        m = DeviceManager(store)
        m.initialize()
        return m

    def test_name_preserved_when_not_in_recipe(self, mgr: DeviceManager) -> None:
        """Ручное переименование → рецепт без name → имя сохранилось."""
        # Ручной upsert с именем
        mgr.upsert({"id": "r1", "name": "Ручное имя", "kind": "robot"})
        assert mgr.get("r1").name == "Ручное имя"

        # Recipe upsert БЕЗ name (только transport обновляется)
        mgr.upsert(
            {"id": "r1", "kind": "robot", "transport": {"type": "tcp", "host": "10.0.0.1"}},
            origin="recipe:demo",
        )
        entry = mgr.get("r1")
        # Имя должно сохраниться
        assert entry.name == "Ручное имя"
        # Transport обновился
        assert entry.transport["host"] == "10.0.0.1"

    def test_name_overwritten_when_in_recipe(self, mgr: DeviceManager) -> None:
        """Рецепт ЯВНО задаёт name → имя обновляется."""
        mgr.upsert({"id": "r1", "name": "Старое", "kind": "robot"})
        mgr.upsert(
            {"id": "r1", "name": "Из рецепта", "kind": "robot"},
            origin="recipe:demo",
        )
        assert mgr.get("r1").name == "Из рецепта"

    def test_enabled_preserved_when_not_in_recipe(self, mgr: DeviceManager) -> None:
        """enabled=False вручную → рецепт без enabled → остаётся False."""
        mgr.upsert({"id": "r1", "name": "R", "kind": "robot", "enabled": False})
        assert mgr.get("r1").enabled is False

        # Recipe upsert БЕЗ enabled
        mgr.upsert({"id": "r1", "kind": "robot"}, origin="recipe:demo")
        assert mgr.get("r1").enabled is False

    def test_enabled_overwritten_when_in_recipe(self, mgr: DeviceManager) -> None:
        """Рецепт ЯВНО задаёт enabled → обновляется."""
        mgr.upsert({"id": "r1", "name": "R", "kind": "robot", "enabled": False})
        mgr.upsert(
            {"id": "r1", "kind": "robot", "enabled": True},
            origin="recipe:demo",
        )
        assert mgr.get("r1").enabled is True


# ================================================================== #
# Конкурентность: RLock не ломает базовый CRUD
# ================================================================== #


class TestConcurrencyRLock:
    """RLock на _entries/_drivers не вызывает дедлок в однопоточном CRUD."""

    @pytest.fixture
    def mgr(self, tmp_path: Path) -> DeviceManager:
        store = RegistryStore(tmp_path / "devices.yaml")
        m = DeviceManager(store)
        m.initialize()
        return m

    def test_upsert_remove_under_lock(self, mgr: DeviceManager) -> None:
        """upsert + remove в одном потоке не дедлочит (RLock реентрантен)."""
        mgr.upsert({"id": "d1", "name": "D", "kind": "robot"})
        assert len(mgr.list_devices()) == 1
        mgr.remove("d1")
        assert len(mgr.list_devices()) == 0

    def test_concurrent_upserts(self, mgr: DeviceManager) -> None:
        """Параллельные upsert из двух потоков не роняют менеджер."""
        errors: list[Exception] = []

        def upsert_batch(prefix: str) -> None:
            try:
                for i in range(20):
                    mgr.upsert({"id": f"{prefix}_{i}", "name": f"D{i}", "kind": "robot"})
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=upsert_batch, args=("a",))
        t2 = threading.Thread(target=upsert_batch, args=("b",))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert not errors, f"Ошибки при параллельных upsert: {errors}"
        assert len(mgr.list_devices()) == 40
