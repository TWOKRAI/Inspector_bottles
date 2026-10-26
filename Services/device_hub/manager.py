"""DeviceManager — центральный менеджер устройств (Р5 плана device-hub).

CRUD реестра + lifecycle (connect/disconnect) + dispatch (call) + describe.
Наследует BaseManager + ObservableMixin (правило владельца).

Драйверы создаются лениво через register_driver_factory(kind, factory).
Дефолтные фабрики (robot/vfd/hikvision/generic_modbus) регистрируются в __init__.

publish_cb — инъекция конструктора: ``(path, dict) -> None``.
В тестах — фейк; в продакшене — state-публикация.
"""

from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from multiprocess_framework.modules.base_manager import BaseManager, ObservableMixin
from multiprocess_framework.modules.base_manager.interfaces import ScopeClosedError
from multiprocess_framework.modules.logger_module import get_std_logger

from Services.device_hub.errors import (
    DeviceHubError,
    DeviceNotFoundError,
    RegisterTransportUnavailable,
    RegistryIntegrityError,
)
from Services.device_hub.registry.entry import DeviceEntry
from Services.device_hub.registry.store import RegistryStore
from Services.device_hub.robot_data_ops import STORE_ERRORS, param_source_for, run_op, store_error_for_operator
from Services.device_hub.spi import DeviceDriver

if TYPE_CHECKING:
    from Services.device_hub.robot_data_ops import RobotDataStore

logger = get_std_logger(__name__)

# Срок рассылки стопа, если request_stop_all() позван без срока (не из плагина), с
_STOP_ALL_DEFAULT_S = 2.5
# Номер потока рассылки стопа: имя ``stop-<id>-<k>`` уникально в области
_STOP_SEQ = itertools.count(1)
_STOP_SEQ_LOCK = threading.Lock()


def _next_stop_k() -> int:
    with _STOP_SEQ_LOCK:
        return next(_STOP_SEQ)


class DeviceManager(BaseManager, ObservableMixin):
    """Менеджер устройств: CRUD + lifecycle + dispatch.

    Args:
        store:      RegistryStore для персистентности, либо ``None`` — реестр чисто
                    in-memory (источник истины — рецепт, план device-tree-recipe
                    Фаза B; полное удаление файлового стора — Фаза E + ADR-DH-007).
        publish_cb: Callback публикации ``(path, data_dict) -> None``.
        spawn:      ``(target, *, name) -> IHandle`` — ``IScope.spawn`` области плагина (T5.3a); получает драйвер
                    робота v2 (его потоки живут в этой области) и рассылка стопа ``request_stop_all``. ``None`` —
                    робот ``delta_v2`` не создаётся (``RuntimeError`` фабрики), драйверы v1 работают как прежде.
        robot_store: Единственное на процесс ``RobotDataStore`` данных робота v2 (T5.3c): им пользуется ``robot_data``;
                    ``None`` — ``robot_data`` отвечает отказом «хранилище данных робота не задано».
    """

    def __init__(
        self,
        store: RegistryStore | None,
        publish_cb: Callable[[str, dict], None] | None = None,
        *,
        spawn: Callable[..., Any] | None = None,
        robot_store: RobotDataStore | None = None,
    ) -> None:
        BaseManager.__init__(self, manager_name="device_manager")
        ObservableMixin.__init__(self)
        self._store = store
        self._publish = publish_cb or (lambda _p, _d: None)
        self._spawn = spawn
        self._robot_store = robot_store
        self._stop_deadline: float | None = None  # срок первого request_stop_all (фаза 1 остановки)

        # Реестр: id -> DeviceEntry
        self._entries: dict[str, DeviceEntry] = {}

        # Живые драйверы: id -> BaseDeviceDriver
        self._drivers: dict[str, DeviceDriver] = {}

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
        """Загрузить реестр из store (store=None — пустой in-memory реестр)."""
        if self._store is not None:
            for e in self._store.load():
                self._check_kind(e.kind)  # неизвестный вид в файле — ValueError при загрузке, как до SPI.c1b
                self._entries[e.id] = e
        self.is_initialized = True
        return True

    def request_stop_all(self, deadline: float | None = None) -> None:
        """Фаза 1 остановки (T5.3a К1, T5.3 круг 2): стоп-запрос всем драйверам с ``request_stop`` ПАРАЛЛЕЛЬНО.

        ``deadline`` — абсолютный срок по ``time.monotonic()`` (None — сейчас + ``_STOP_ALL_DEFAULT_S``); он же уходит
        каждому драйверу. Каждый драйвер — свой поток из ``spawn`` (``stop-<id>-<k>``): молчащий робот не задерживает
        стоп соседа. Ожидание потоков — до общего срока; не вышедший поток виден в отчёте закрытия его записи.
        Драйверы v1 и прочих kind метода ``request_stop`` не имеют — не трогаются. Не бросает. Отказ ``spawn``
        (область закрыта — второй вызов после ``scope.close``; любое исключение) — стоп этому роботу идёт в
        вызывающем потоке (fail-closed), следующие роботы не пропускаются; лишней записи нет — её отсекает защёлка
        драйвера. Исключение одного драйвера логируется.
        Без ``spawn`` (менеджер без области: роботов ``delta_v2`` нет) — вызовы по очереди в этом потоке.
        """
        with self._registry_lock:
            if deadline is None:  # повторный вызов без срока (фаза 4 через _on_shutdown) — срок первого вызова
                deadline = (
                    self._stop_deadline if self._stop_deadline is not None else time.monotonic() + _STOP_ALL_DEFAULT_S
                )
            if self._stop_deadline is None:
                self._stop_deadline = deadline
            drivers = list(self._drivers.items())
        targets: list[tuple[str, Callable[..., object]]] = []
        for dev_id, drv in drivers:
            # Отбор — внутри try на драйвер: флаг stop_aware без метода request_stop (AttributeError) или сбойное
            # свойство одного драйвера пишется в лог, соседи стоп получают
            try:
                if drv.stop_aware:
                    targets.append((dev_id, drv.request_stop))
            except Exception:
                logger.exception(f"device_hub: стоп-запрос {dev_id!r} не прошёл")
        if self._spawn is None:
            for dev_id, request in targets:
                self._stop_one(dev_id, request, deadline)
            return
        handles = []
        inline: list[tuple[str, Callable[..., object]]] = []  # spawn отказал: стоп этим роботам — в этом потоке
        for dev_id, request in targets:
            name = f"stop-{dev_id}-{_next_stop_k()}"
            try:
                handles.append(self._spawn(lambda _ev, d=dev_id, r=request: self._stop_one(d, r, deadline), name=name))
            except Exception as exc:  # ScopeClosedError (второй вызов после scope.close) и любой отказ spawn
                inline.append((dev_id, request))
                if len(inline) == 1:
                    text = f"device_hub: поток стоп-запроса не запущен ({type(exc).__name__}) — стоп идёт в этом потоке"
                    (logger.debug if isinstance(exc, ScopeClosedError) else logger.warning)(text)
        for dev_id, request in inline:  # fail-closed: отказ spawn не лишает робота стопа (защёлка — в драйвере)
            self._stop_one(dev_id, request, deadline)
        for handle in handles:
            try:
                report = handle.close(max(0.0, deadline - time.monotonic()))
            except Exception:
                logger.exception("device_hub: запись потока стоп-запроса не закрыта")
                continue
            if report.survivors:
                logger.warning(f"device_hub: поток стоп-запроса не вышел к сроку: {list(report.survivors)}")

    @staticmethod
    def _stop_one(dev_id: str, request: Callable[..., object], deadline: float) -> None:
        try:
            request(deadline)
        except Exception:
            logger.exception(f"device_hub: стоп-запрос {dev_id!r} не прошёл")

    def _on_shutdown(self) -> bool:
        """Стоп-запрос всем, затем отключить все устройства и сохранить реестр."""
        self.request_stop_all()  # стоп робота уходит до любых ожиданий потоков
        with self._registry_lock:
            driver_ids = list(self._drivers)
        for dev_id in driver_ids:
            try:
                self.disconnect(dev_id)
            except Exception:
                logger.exception(f"device_hub: disconnect {dev_id!r} при остановке не прошёл")
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

    def _check_kind(self, kind: str) -> None:
        """Вид допустим, если для него зарегистрирована фабрика драйвера (один источник истины, SPI.c1b)."""
        if kind not in self._factories:
            raise ValueError(f"DeviceEntry.kind {kind!r} не из {sorted(self._factories)}")

    def _register_defaults(self) -> None:
        """Зарегистрировать дефолтные фабрики драйверов."""
        from Services.device_hub.drivers.robot_driver import RobotDriver
        from Services.device_hub.drivers.vfd_driver import VfdDriver
        from Services.device_hub.drivers.hikvision_driver import HikvisionDriver
        from Services.device_hub.drivers.generic_modbus_driver import GenericModbusDriver

        def _robot_factory(entry: DeviceEntry, proto: Any) -> Any:
            # Робот протокола v2 — свой драйвер (T5.1); импорт ленивый: v1-хаб не тянет клиент v2.
            if entry.protocol == "delta_v2":
                from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2

                if self._spawn is None:  # T5.3 круг 2: потоки робота v2 — только в области плагина
                    raise RuntimeError(f"робот {entry.id!r} (delta_v2): менеджер без spawn не создаёт драйвер v2")
                if self._robot_store is None:
                    return RobotDriverV2(entry, proto, publish=self._publish, spawn=self._spawn)
                # Параметры робота при подключении — из params.yaml (T5.3c c2); плохие данные бросают RobotDataInvalid
                # и др. из фабрики, их перехватывает ``connect``
                param_source = param_source_for(self._robot_store, entry.id, entry.params)
                return RobotDriverV2(
                    entry,
                    proto,
                    publish=self._publish,
                    spawn=self._spawn,
                    param_source=param_source,
                    store=self._robot_store,
                )
            return RobotDriver(entry, proto)

        self._factories["robot"] = _robot_factory
        self._factories["vfd"] = lambda entry, proto: VfdDriver(entry, proto, resolve_device=self._get_driver)
        self._factories["hikvision"] = lambda entry, proto: HikvisionDriver(entry, proto)
        self._factories["generic_modbus"] = lambda entry, proto: GenericModbusDriver(entry, proto)

    # ------------------------------------------------------------------ #
    # CRUD реестра
    # ------------------------------------------------------------------ #

    def list_devices(self) -> list[dict]:
        """Список всех устройств реестра (dict-формат)."""
        return [e.to_dict() for e in self.snapshot_registry()]

    def get(self, dev_id: str) -> DeviceEntry:
        """Получить запись устройства по id.

        Raises:
            DeviceNotFoundError: Устройство не найдено.
        """
        with self._registry_lock:
            entry = self._entries.get(dev_id)
        if entry is None:
            raise DeviceNotFoundError(f"Устройство {dev_id!r} не найдено")
        return entry

    # ------------------------------------------------------------------ #
    # Публичный snapshot-API реестра (M-race-1)
    # ------------------------------------------------------------------ #
    #
    # Единственный потокобезопасный способ читать реестр/драйверы ИЗВНЕ
    # менеджера (плагин, supervisor, per-device tick-воркеры). Прямой обход
    # приваток (`._entries.values()`, `._drivers.get`) из другого потока при
    # параллельном upsert/remove даёт `RuntimeError: dictionary changed size
    # during iteration` либо полу-удалённое состояние. Гейт
    # `Plugins/hub/device_hub/tests/test_no_private_access.py` держит прод-код
    # плагина чистым от прямого доступа к приваткам менеджера.
    #
    # Контракт: методы возвращают КОПИЮ верхнего уровня под локом (shallow) —
    # защищают от мутации словаря, НО НЕ от мутации самого DeviceEntry/драйвера.

    def snapshot_registry(self) -> list[DeviceEntry]:
        """Снимок всех записей реестра под локом (shallow-копия значений)."""
        with self._registry_lock:
            return list(self._entries.values())

    def get_driver(self, dev_id: str) -> DeviceDriver | None:
        """Живой драйвер по id под локом (``None`` если ещё не создан)."""
        with self._registry_lock:
            return self._drivers.get(dev_id)

    def connected_ids(self) -> list[str]:
        """ID подключённых устройств (по ``driver.is_connected``).

        Ссылки на драйверы снимаются под локом; сам ``is_connected`` (чтение
        флага) вычисляется ВНЕ лока — критическая секция максимально короткая.
        """
        with self._registry_lock:
            drivers = list(self._drivers.items())
        return [dev_id for dev_id, drv in drivers if drv.is_connected]

    def device_count(self) -> int:
        """Число записей в реестре (под локом)."""
        with self._registry_lock:
            return len(self._entries)

    def connected_count(self) -> int:
        """Число подключённых устройств (по ``is_connected``)."""
        return len(self.connected_ids())

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
        self._check_kind(entry.kind)

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
        try:
            driver = self._get_or_create_driver(entry)
        except STORE_ERRORS as exc:
            # OSError не у робота v2 -> None: пробрасываем; у робота v2 путь диска и имя файла — в лог, в last_error —
            # константа (robot_data_ops.store_error_for_operator)
            translated = store_error_for_operator(exc, dev_id, entry.protocol, log=logger)
            if translated is None:
                raise
            exc = translated
            # Ошибка данных или конфига оператора (битый params.yaml, плохой robot_params, недопустимый id) с постоянным
            # текстом: оператор видит причину в last_error; health не трогаем, исключение из менеджера не выходит
            self._publish(f"devices.state.{dev_id}.last_error", str(exc))
            self._publish(f"devices.state.{dev_id}.conn", {"conn": "error"})
            return False

        # Bridge: проверить connected-носителя
        if entry.transport.get("type") == "bridge":
            bridge_id = entry.transport.get("bridge", "")
            carrier = self.get_driver(bridge_id)
            if carrier is None or not carrier.is_connected:
                raise DeviceHubError(
                    f"Устройство {dev_id!r}: носитель {bridge_id!r} не подключён. Подключите носителя сначала."
                )

        ok = driver.connect()
        # C-29 (В3): connect, прерванный «Отключить», — не ошибка (`is True`: подмены MagicMock дают истинный объект)
        aborted = not ok and driver.disconnect_pending is True
        conn = "connected" if ok else ("disconnecting" if aborted else "error")
        self._publish(f"devices.state.{dev_id}.conn", {"conn": conn})
        return ok

    def disconnect(self, dev_id: str) -> None:
        """Отключить устройство.

        Disconnect носителя -> зависимые bridge-драйверы переводятся в degraded.

        Raises:
            DeviceNotFoundError: Устройство не найдено.
        """
        with self._registry_lock:
            exists = dev_id in self._entries
        if not exists:
            raise DeviceNotFoundError(f"Устройство {dev_id!r} не найдено")

        driver = self.get_driver(dev_id)
        if driver is not None:
            driver.disconnect()
            self._publish(f"devices.state.{dev_id}.conn", {"conn": "disconnected"})

        # Cascade degraded для зависимых bridge-устройств (итерация по снапшоту —
        # реестр может мутироваться параллельно; сам disconnect-IO вне лока).
        for e in self.snapshot_registry():
            if e.transport.get("type") == "bridge" and e.transport.get("bridge") == dev_id:
                # Сбой одного зависимого не лишает деградации остальных (А20)
                try:
                    dep_driver = self.get_driver(e.id)
                    if dep_driver is not None and dep_driver.set_degraded():
                        self._publish(f"devices.state.{e.id}.conn", {"conn": "disconnected"})
                except Exception:
                    logger.exception(f"device_hub: деградация зависимого {e.id!r} при отключении носителя не прошла")

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

        driver = self.get_driver(dev_id)
        if driver is None or not driver.is_connected:
            # error= дублирует message для CommandManager-лога (он читает reason/error)
            msg = f"Устройство {dev_id!r} не подключено"
            return {"status": "error", "message": msg, "error": msg}

        return driver.call(op, args)

    def robot_data(self, dev_id: str, op: str, args: dict | None = None) -> dict:
        """Офлайн-данные робота v2 (путь О4 мимо ``call``): параметры, точки, СК, программы (T5.3c).

        Pre: устройство в реестре, ``kind == "robot"`` и ``protocol == "delta_v2"``, хранилище задано; связь с
        роботом не нужна. Операции — ``robot_data_ops.OPS``; запись требует ключ ``base_rev``.
        Post: успех -> ``{"status": "ok", ...}``. Ошибка -> ``{"status": "error", "message": <постоянный текст без
        входных значений>}``; ``RevisionConflict`` добавляет ``current_rev``; плохие аргументы — ``TEXT_BAD_ARGS``.
        ``OSError`` хранилища -> постоянный ``TEXT_STORE_ERROR``; полный текст ошибки (путь, имя) — в лог.
        """
        try:
            entry = self.get(dev_id)
        except DeviceNotFoundError as exc:
            return {"status": "error", "message": str(exc)}
        if entry.kind != "robot" or entry.protocol != "delta_v2":
            return {"status": "error", "message": "данные робота — только для протокола delta_v2"}
        if self._robot_store is None:
            return {"status": "error", "message": "хранилище данных робота не задано"}
        return run_op(self._robot_store, dev_id, op, args, entry.params, log=logger)

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
        driver = self.get_driver(dev_id)

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
            transport = self._register_transport(driver)
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
        # Д2 (T5.3c): регистры робота v2 пишут только команды robot_*; отказ не зависит от связи (до проверки драйвера)
        if self.get(dev_id).protocol == "delta_v2":
            return {"status": "error", "message": "запись регистров робота v2 — только командами robot_*"}
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
            transport = self._register_transport(driver)
            ops = driver.protocol.register_map.write_ops(values)
            transport.transaction(ops)
            return {"status": "ok", "written": list(values.keys())}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    # ------------------------------------------------------------------ #
    # Служебное
    # ------------------------------------------------------------------ #

    @staticmethod
    def _register_transport(driver: DeviceDriver) -> Any:
        """Транспорт регистров драйвера (``driver.transport``); нет — ``RegisterTransportUnavailable``."""
        transport = driver.transport
        if transport is None:
            raise RegisterTransportUnavailable(driver.entry.id)
        return transport

    def _get_driver(self, dev_id: str) -> DeviceDriver | None:
        """Получить драйвер по id (для resolve_device в VfdDriver и transports).

        Внутренний алиас публичного :meth:`get_driver` (лукап под локом).
        """
        return self.get_driver(dev_id)

    def _get_connected_driver(self, dev_id: str) -> DeviceDriver:
        """Получить подключённый драйвер; raise при ошибке."""
        self.get(dev_id)  # проверка существования (DeviceNotFoundError)
        driver = self.get_driver(dev_id)
        if driver is None or not driver.is_connected:
            raise DeviceHubError(f"Устройство {dev_id!r} не подключено")
        return driver

    def _get_or_create_driver(self, entry: DeviceEntry) -> DeviceDriver:
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
        """Сохранить реестр в store (под lock — атомарная запись не thread-safe).

        store=None — no-op (in-memory реестр, источник истины — рецепт).
        """
        if self._store is None:
            return
        with self._registry_lock:
            self._store.save(list(self._entries.values()))
