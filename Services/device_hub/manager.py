"""DeviceManager — центральный менеджер устройств (Р5 плана device-hub).

CRUD реестра + lifecycle (connect/disconnect) + dispatch (call) + describe.
Наследует BaseManager + ObservableMixin (правило владельца).

Драйверы создаются лениво через register_driver_factory(kind, factory).
Дефолтные фабрики (robot/vfd/hikvision/generic_modbus) регистрируются в __init__.

publish_cb — инъекция конструктора: ``(path, dict) -> None``.
В тестах — фейк; в продакшене — state-публикация.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from multiprocess_framework.modules.base_manager import BaseManager, ObservableMixin

from Services.device_hub.errors import (
    DeviceHubError,
    DeviceNotFoundError,
    RegistryIntegrityError,
)
from Services.device_hub.registry.entry import DeviceEntry
from Services.device_hub.registry.store import RegistryStore


class DeviceManager(BaseManager, ObservableMixin):
    """Менеджер устройств: CRUD + lifecycle + dispatch.

    Args:
        store:      RegistryStore для персистентности.
        publish_cb: Callback публикации ``(path, data_dict) -> None``.
    """

    def __init__(
        self,
        store: RegistryStore,
        publish_cb: Callable[[str, dict], None] | None = None,
    ) -> None:
        BaseManager.__init__(self, manager_name="device_manager")
        ObservableMixin.__init__(self)
        self._store = store
        self._publish = publish_cb or (lambda _p, _d: None)

        # Реестр: id -> DeviceEntry
        self._entries: dict[str, DeviceEntry] = {}

        # Живые драйверы: id -> BaseDeviceDriver
        self._drivers: dict[str, Any] = {}

        # RLock на _entries/_drivers: мутируются из командного потока
        # (upsert/remove) и supervisor (connect→_get_or_create_driver).
        # Короткие критические секции — НЕ держать на время connect-IO!
        self._registry_lock = threading.RLock()

        # Фабрики драйверов: kind -> callable(entry, protocol) -> driver
        self._factories: dict[str, Callable] = {}

        # Регистрация дефолтных фабрик
        self._register_defaults()

    # ------------------------------------------------------------------ #
    # BaseManager
    # ------------------------------------------------------------------ #

    def initialize(self) -> bool:
        """Загрузить реестр из store."""
        entries = self._store.load()
        for e in entries:
            self._entries[e.id] = e
        self.is_initialized = True
        return True

    def shutdown(self) -> bool:
        """Отключить все устройства и сохранить реестр."""
        for dev_id in list(self._drivers):
            try:
                self.disconnect(dev_id)
            except Exception:
                pass
        self._save()
        self.is_initialized = False
        return True

    # ------------------------------------------------------------------ #
    # Фабрики драйверов
    # ------------------------------------------------------------------ #

    def register_driver_factory(self, kind: str, factory: Callable) -> None:
        """Зарегистрировать фабрику драйвера для kind.

        Args:
            kind:    Тип устройства (``robot``, ``vfd``, ...).
            factory: ``(entry, protocol) -> BaseDeviceDriver``.
        """
        self._factories[kind] = factory

    def _register_defaults(self) -> None:
        """Зарегистрировать дефолтные фабрики драйверов."""
        from Services.device_hub.drivers.robot_driver import RobotDriver
        from Services.device_hub.drivers.vfd_driver import VfdDriver
        from Services.device_hub.drivers.hikvision_driver import HikvisionDriver
        from Services.device_hub.drivers.generic_modbus_driver import GenericModbusDriver

        self._factories["robot"] = lambda entry, proto: RobotDriver(entry, proto)
        self._factories["vfd"] = lambda entry, proto: VfdDriver(entry, proto, resolve_device=self._get_driver)
        self._factories["hikvision"] = lambda entry, proto: HikvisionDriver(entry, proto)
        self._factories["generic_modbus"] = lambda entry, proto: GenericModbusDriver(entry, proto)

    # ------------------------------------------------------------------ #
    # CRUD реестра
    # ------------------------------------------------------------------ #

    def list_devices(self) -> list[dict]:
        """Список всех устройств реестра (dict-формат)."""
        return [e.to_dict() for e in self._entries.values()]

    def get(self, dev_id: str) -> DeviceEntry:
        """Получить запись устройства по id.

        Raises:
            DeviceNotFoundError: Устройство не найдено.
        """
        entry = self._entries.get(dev_id)
        if entry is None:
            raise DeviceNotFoundError(f"Устройство {dev_id!r} не найдено")
        return entry

    def upsert(
        self,
        entry_dict: dict,
        origin: str | None = None,
    ) -> DeviceEntry:
        """Создать или обновить устройство (merge-семантика).

        При обновлении: ручные name/enabled НЕ затираются рецептом, если
        рецепт их не задаёт ЯВНО (ключ отсутствует в entry_dict).
        origin проставляется если передан.

        н4 ревью Fable: исправлена мёртвая ветка — старая проверка
        ``key in ("name","enabled") and key not in entry_dict`` невыполнима
        (итерация по entry_dict.items() гарантирует key in entry_dict).
        Теперь: при recipe-origin храним множество _явно_ переданных ключей
        и пропускаем name/enabled, которых НЕТ в исходном dict.

        Args:
            entry_dict: Dict с полями DeviceEntry (обязательно id, kind).
            origin:     Источник (``manual`` / ``recipe:<slug>``).

        Returns:
            Обновлённый DeviceEntry.
        """
        dev_id = entry_dict.get("id", "")
        existing = self._entries.get(dev_id)

        if existing is not None:
            # Merge: новые данные поверх старых, но name/enabled только
            # если ЯВНО заданы в entry_dict (ключ присутствует).
            # Множество ключей entry_dict — источник истины «явно задано».
            explicit_keys = set(entry_dict.keys())
            merged = existing.to_dict()
            for key, value in entry_dict.items():
                if key in ("name", "enabled") and key not in explicit_keys:
                    # Невозможная ветка (safety), но семантика ясна
                    continue  # pragma: no cover
                merged[key] = value
            # Защита: name/enabled НЕ затираются, если рецепт их не указал
            for protected_key in ("name", "enabled"):
                if protected_key not in explicit_keys:
                    merged[protected_key] = getattr(existing, protected_key)
            if origin is not None:
                merged["origin"] = origin
            entry = DeviceEntry.from_dict(merged)
        else:
            if origin is not None:
                entry_dict = {**entry_dict, "origin": origin}
            entry = DeviceEntry.from_dict(entry_dict)

        with self._registry_lock:
            self._entries[entry.id] = entry
        self._save()
        self._publish(f"devices.registry.{entry.id}", entry.to_dict())
        return entry

    def remove(self, dev_id: str) -> None:
        """Удалить устройство из реестра.

        ADR-DH-004: удаление носителя при живых bridge-зависимых ЗАБЛОКИРОВАНО
        (RegistryIntegrityError). Решение: блокировка, НЕ каскад.

        Raises:
            DeviceNotFoundError: Устройство не найдено.
            RegistryIntegrityError: Есть зависимые bridge-устройства.
        """
        with self._registry_lock:
            if dev_id not in self._entries:
                raise DeviceNotFoundError(f"Устройство {dev_id!r} не найдено")

            # Проверка: есть ли bridge-зависимые
            dependents = [
                e.id
                for e in self._entries.values()
                if e.transport.get("type") == "bridge" and e.transport.get("bridge") == dev_id
            ]
            if dependents:
                raise RegistryIntegrityError(
                    f"Нельзя удалить устройство {dev_id!r}: от него зависят "
                    f"bridge-устройства: {dependents}. Удалите зависимые сначала."
                )

        # Отключить драйвер если есть (ВНЕ lock — IO)
        if dev_id in self._drivers:
            try:
                self.disconnect(dev_id)
            except Exception:
                pass

        with self._registry_lock:
            self._entries.pop(dev_id, None)
            self._drivers.pop(dev_id, None)
        self._save()
        self._publish(f"devices.registry.{dev_id}", {})

    # ------------------------------------------------------------------ #
    # Lifecycle: connect / disconnect
    # ------------------------------------------------------------------ #

    def connect(self, dev_id: str) -> bool:
        """Подключить устройство (синхронно — async-обёртку даёт плагин Фазы 2).

        Bridge-устройство: connect требует connected-носителя.

        Raises:
            DeviceNotFoundError: Устройство не найдено.
            DeviceHubError: Носитель bridge не подключён.
        """
        entry = self.get(dev_id)
        driver = self._get_or_create_driver(entry)

        # Bridge: проверить connected-носителя
        if entry.transport.get("type") == "bridge":
            bridge_id = entry.transport.get("bridge", "")
            carrier = self._drivers.get(bridge_id)
            if carrier is None or not carrier.is_connected:
                raise DeviceHubError(
                    f"Устройство {dev_id!r}: носитель {bridge_id!r} не подключён. Подключите носителя сначала."
                )

        ok = driver.connect()
        self._publish(f"devices.state.{dev_id}.conn", {"conn": "connected" if ok else "error"})
        return ok

    def disconnect(self, dev_id: str) -> None:
        """Отключить устройство.

        Disconnect носителя -> зависимые bridge-драйверы переводятся в degraded.

        Raises:
            DeviceNotFoundError: Устройство не найдено.
        """
        if dev_id not in self._entries:
            raise DeviceNotFoundError(f"Устройство {dev_id!r} не найдено")

        driver = self._drivers.get(dev_id)
        if driver is not None:
            driver.disconnect()
            self._publish(f"devices.state.{dev_id}.conn", {"conn": "disconnected"})

        # Cascade degraded для зависимых bridge-устройств
        for e in self._entries.values():
            if e.transport.get("type") == "bridge" and e.transport.get("bridge") == dev_id:
                dep_driver = self._drivers.get(e.id)
                if dep_driver is not None and hasattr(dep_driver, "set_degraded"):
                    dep_driver.set_degraded()
                    self._publish(f"devices.state.{e.id}.conn", {"conn": "disconnected"})

    # ------------------------------------------------------------------ #
    # Dispatch: call
    # ------------------------------------------------------------------ #

    def call(self, dev_id: str, op: str, args: dict | None = None) -> dict:
        """Диспетчер: get driver -> driver.call(op, args).

        Ошибки -> {"status": "error", "message": ...}
        Успех — {"status": "ok", ...} (определяется драйвером).
        """
        args = args or {}
        try:
            self.get(dev_id)  # проверка существования
        except DeviceNotFoundError as exc:
            return {"status": "error", "message": str(exc)}

        driver = self._drivers.get(dev_id)
        if driver is None:
            return {"status": "error", "message": f"Устройство {dev_id!r} не подключено"}
        if not driver.is_connected:
            return {"status": "error", "message": f"Устройство {dev_id!r} не подключено"}

        return driver.call(op, args)

    # ------------------------------------------------------------------ #
    # Describe / protocols / read/write registers
    # ------------------------------------------------------------------ #

    def describe(self, dev_id: str) -> dict:
        """Описание устройства: entry + protocol meta + conn + stats.

        Returns:
            {"entry": ..., "protocol": {name: RegisterMeta.to_dict()},
             "conn": ..., "stats": ...}
        """
        entry = self.get(dev_id)
        driver = self._drivers.get(dev_id)

        result: dict[str, Any] = {
            "entry": entry.to_dict(),
            "protocol": {},
            "conn": "disconnected",
            "stats": {},
        }

        if driver is not None:
            result["conn"] = "connected" if driver.is_connected else "disconnected"
            result["stats"] = driver.stats
            if driver.protocol is not None and hasattr(driver.protocol, "meta"):
                result["protocol"] = {name: meta.to_dict() for name, meta in driver.protocol.meta.items()}

        return result

    def protocols(self, kind: str | None = None) -> dict[str, dict]:
        """Список доступных протоколов: {name: {kind, description}}.

        Использует find_protocols + load_protocol из Services/modbus.
        """
        from Services.modbus import find_protocols, load_protocol

        result: dict[str, dict] = {}
        for name, path in find_protocols(kind).items():
            try:
                proto = load_protocol(path)
                result[name] = {
                    "kind": proto.kind,
                    "description": proto.description,
                }
            except Exception:
                pass  # пропускаем битые протоколы
        return result

    def read_register(self, dev_id: str, name: str) -> dict:
        """Универсальное чтение регистра через RegisterMap.

        Валидация: access не может быть 'w' (write-only).
        """
        driver = self._get_connected_driver(dev_id)
        if driver.protocol is None:
            return {"status": "error", "message": f"Устройство {dev_id!r} без протокола"}

        meta = driver.protocol.meta.get(name)
        if meta is None:
            return {"status": "error", "message": f"Регистр {name!r} не найден в протоколе"}
        if meta.access == "w":
            return {"status": "error", "message": f"Регистр {name!r} доступен только на запись"}

        try:
            transport = getattr(driver, "transport", None) or driver._client
            val = driver.protocol.register_map.read(transport, name)
            return {"status": "ok", "name": name, "value": val}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def write_registers(self, dev_id: str, values: dict) -> dict:
        """Универсальная запись регистров с валидацией access/min/max из meta.

        Args:
            dev_id: ID устройства.
            values: {name: value, ...}
        """
        driver = self._get_connected_driver(dev_id)
        if driver.protocol is None:
            return {"status": "error", "message": f"Устройство {dev_id!r} без протокола"}

        # Валидация
        for name, value in values.items():
            meta = driver.protocol.meta.get(name)
            if meta is None:
                return {"status": "error", "message": f"Регистр {name!r} не найден"}
            if meta.access == "r":
                return {"status": "error", "message": f"Регистр {name!r} доступен только на чтение"}
            if meta.min is not None and float(value) < meta.min:
                return {"status": "error", "message": f"{name}={value} < min={meta.min}"}
            if meta.max is not None and float(value) > meta.max:
                return {"status": "error", "message": f"{name}={value} > max={meta.max}"}

        try:
            transport = getattr(driver, "transport", None) or driver._client
            ops = driver.protocol.register_map.write_ops(values)
            transport.transaction(ops)
            return {"status": "ok", "written": list(values.keys())}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    # ------------------------------------------------------------------ #
    # Служебное
    # ------------------------------------------------------------------ #

    def _get_driver(self, dev_id: str) -> Any:
        """Получить драйвер по id (для resolve_device в VfdDriver и transports)."""
        return self._drivers.get(dev_id)

    def _get_connected_driver(self, dev_id: str) -> Any:
        """Получить подключённый драйвер; raise при ошибке."""
        self.get(dev_id)  # проверка существования (DeviceNotFoundError)
        driver = self._drivers.get(dev_id)
        if driver is None or not driver.is_connected:
            raise DeviceHubError(f"Устройство {dev_id!r} не подключено")
        return driver

    def _get_or_create_driver(self, entry: DeviceEntry) -> Any:
        """Получить или лениво создать драйвер (потокобезопасно)."""
        with self._registry_lock:
            driver = self._drivers.get(entry.id)
            if driver is not None:
                return driver

        factory = self._factories.get(entry.kind)
        if factory is None:
            raise DeviceHubError(
                f"Нет фабрики драйвера для kind={entry.kind!r}. Зарегистрируйте через register_driver_factory()."
            )

        # Загрузить протокол если указан (ВНЕ lock — может быть IO)
        protocol = None
        if entry.protocol:
            protocol = self._load_protocol(entry.protocol)

        driver = factory(entry, protocol)
        with self._registry_lock:
            # Double-check: другой поток мог создать
            existing = self._drivers.get(entry.id)
            if existing is not None:
                return existing
            self._drivers[entry.id] = driver
        return driver

    def _load_protocol(self, name: str) -> Any:
        """Загрузить протокол по имени."""
        from Services.modbus import find_protocols, load_protocol

        all_protos = find_protocols()
        path = all_protos.get(name)
        if path is None:
            return None
        return load_protocol(path)

    def _save(self) -> None:
        """Сохранить реестр в store (под lock — атомарная запись не thread-safe)."""
        with self._registry_lock:
            self._store.save(list(self._entries.values()))
