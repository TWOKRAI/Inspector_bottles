"""DeviceHubPlugin — always-on плагин процесса devices.

Командный контракт (Р7): все именованные команды — однострочные алиасы над
DeviceManager; логика НЕ расползается по плагину.

Контракт исполнения (Б2): device_connect/device_disconnect — асинхронные
(ответ сразу, TCP-connect в supervisor-воркере). Быстрые register-операции
(2–50 мс) допустимы в командном потоке. Блокирующее >100 мс — в воркере.

State-пути (Р8):
    devices.registry.<id>       = {id, name, kind, ...}
    devices.state.<id>.conn     = "disconnected"|"connecting"|"connected"|"error"
    devices.state.<id>.status   = kind-специфика + quality + ts
    devices.state.<id>.stats    = {tx_ok, tx_err, ...}
    devices.state.<id>.last_error = str
"""

from __future__ import annotations

import os
import queue
import threading
import time
from pathlib import Path
from typing import Any

from multiprocess_framework.modules.process_module.plugins import (
    ExecutionMode,
    PluginContext,
    ProcessModulePlugin,
    ThreadConfig,
    register_plugin,
)

from Services.device_hub import DeviceHubError
from Services.device_hub.manager import DeviceManager
from Services.device_hub.registry.store import RegistryStore

from .registers import DeviceHubRegisters

# Корень проекта — для резолва относительных путей
_PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _resolve_registry_path(raw_path: str) -> Path:
    """Резолвить путь к реестру: абсолютный — как есть, относительный — от корня проекта.

    Приоритет: env INSPECTOR_DATA_DIR (если задан) → корень проекта.
    Паттерн аналогичен резолву db_path в telemetry_sink/database плагинах.
    """
    p = Path(raw_path)
    if p.is_absolute():
        return p
    data_dir = os.environ.get("INSPECTOR_DATA_DIR")
    if data_dir:
        # INSPECTOR_DATA_DIR указывает на каталог data/ — но registry_path
        # уже содержит data/ префикс, поэтому отрезаем его если совпадает
        base = Path(data_dir)
        if raw_path.startswith("data/") or raw_path.startswith("data\\"):
            return base.parent / raw_path
        return base / raw_path
    return _PROJECT_ROOT / raw_path


@register_plugin(
    "device_hub",
    category="hub",
    description="Always-on хаб устройств: реестр, соединения, dispatch команд",
)
class DeviceHubPlugin(ProcessModulePlugin):
    """Always-on хаб устройств: CRUD реестра, lifecycle, dispatch."""

    name = "device_hub"
    category = "hub"
    thread_safe = False

    inputs = []
    outputs = []

    register_class = DeviceHubRegisters

    # ------------------------------------------------------------------ #
    # Таблица команд (Р7): имя_команды -> имя_метода
    # ------------------------------------------------------------------ #
    commands = {
        # Реестр
        "device_list": "cmd_device_list",
        "device_describe": "cmd_device_describe",
        "device_upsert": "cmd_device_upsert",
        "device_upsert_many": "cmd_device_upsert_many",
        "device_sync_set": "cmd_device_sync_set",
        "device_remove": "cmd_device_remove",
        "device_protocols": "cmd_device_protocols",
        # Соединение (асинхронные — Б2)
        "device_connect": "cmd_device_connect",
        "device_disconnect": "cmd_device_disconnect",
        # Универсальные регистры
        "device_read": "cmd_device_read",
        "device_write": "cmd_device_write",
        # Робот (11)
        "robot_enqueue_job": "cmd_robot_enqueue_job",
        "robot_send_test_job": "cmd_robot_send_test_job",
        "robot_abort": "cmd_robot_abort",
        "robot_set_mode": "cmd_robot_set_mode",
        "robot_set_servo": "cmd_robot_set_servo",
        "robot_set_robot_config": "cmd_robot_set_robot_config",
        "robot_get_robot_config": "cmd_robot_get_robot_config",
        "robot_get_telemetry": "cmd_robot_get_telemetry",
        "robot_read_echo": "cmd_robot_read_echo",
        "robot_set_manual_mode": "cmd_robot_set_manual_mode",
        "robot_clear_queue": "cmd_robot_clear_queue",
        # Рисование (8)
        "robot_draw_polyline": "cmd_robot_draw_polyline",
        "robot_draw_circle": "cmd_robot_draw_circle",
        "robot_draw_square": "cmd_robot_draw_square",
        "robot_draw_set_pen": "cmd_robot_draw_set_pen",
        "robot_draw_set_speed": "cmd_robot_draw_set_speed",
        "robot_draw_set_overlap": "cmd_robot_draw_set_overlap",
        "robot_draw_abort": "cmd_robot_draw_abort",
        "robot_draw_progress": "cmd_robot_draw_progress",
        # ПЧ (5)
        "vfd_run": "cmd_vfd_run",
        "vfd_set_freq": "cmd_vfd_set_freq",
        "vfd_stop": "cmd_vfd_stop",
        "vfd_reset_fault": "cmd_vfd_reset_fault",
        "vfd_get_status": "cmd_vfd_get_status",
        # Hikvision (6)
        "hik_enum": "cmd_hik_enum",
        "hik_open": "cmd_hik_open",
        "hik_close": "cmd_hik_close",
        "hik_get_params": "cmd_hik_get_params",
        "hik_set_params": "cmd_hik_set_params",
        "hik_release": "cmd_hik_release",
    }

    @classmethod
    def config_class(cls) -> type | None:
        """Явный config_class -> register_schema() резолвит register_bindings."""
        from .config import DeviceHubPluginConfig

        return DeviceHubPluginConfig

    # ------------------------------------------------------------------ #
    # LIFECYCLE
    # ------------------------------------------------------------------ #

    def configure(self, ctx: PluginContext) -> None:
        """IDLE -> READY: создать DeviceManager, загрузить реестр, публикация."""
        self._ctx = ctx
        self._reg: DeviceHubRegisters = self._init_register(ctx)

        # Резолв пути к реестру (У6)
        resolved = _resolve_registry_path(self._reg.registry_path)
        resolved.parent.mkdir(parents=True, exist_ok=True)

        store = RegistryStore(resolved)
        self._manager = DeviceManager(store=store, publish_cb=self._publish_state)
        self._manager.initialize()

        # Очередь async connect/disconnect (Б2)
        self._conn_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        # Воркеры per-device: {device_id: worker_name}
        self._device_workers: dict[str, str] = {}
        # Lock для device_workers И desired_connected
        # (модифицируется из supervisor и командного потока)
        self._workers_lock = threading.Lock()

        # НР-1/НР-2 ревью Fable: desired-state соединения.
        # Runtime-состояние сессии (НЕ persist в devices.yaml).
        # True = пользователь/рецепт хотят устройство подключённым;
        # False = пользователь явно отключил.
        # Без desired=True supervisor НЕ создаёт воркер и драйвер НЕ реконнектит.
        self._desired_connected: dict[str, bool] = {}

        # Публикация начального реестра
        self._publish_full_registry()
        self._update_counters()

        ctx.log_info(f"DeviceHubPlugin: configured (registry={resolved})")

    def start(self, ctx: PluginContext) -> None:
        """READY -> RUNNING: upsert recipe_devices, auto_connect, supervisor-worker."""
        # Upsert устройств из конфига рецепта (опционально).
        # н6: читаем recipe_origin из конфига плагина, чтобы slug не терялся
        # (origin="recipe" не позволяет отличить один рецепт от другого).
        recipe_devices = ctx.config.get("recipe_devices", [])
        recipe_origin: str = ctx.config.get("recipe_origin", "recipe")
        recipe_ids: set[str] = set()
        for dev_dict in recipe_devices:
            if isinstance(dev_dict, dict) and "id" in dev_dict:
                self._manager.upsert(dev_dict, origin=recipe_origin)
                recipe_ids.add(dev_dict["id"])

        # Обновить счётчики после recipe upsert
        self._publish_full_registry()
        self._update_counters()

        # Auto-connect: устройства с auto_connect=True ИЛИ из рецепта (Р11/н1:
        # запись в devices: подразумевает auto_connect — иначе pipeline молча
        # дропает job'ы до ручного «Подключить»).
        # НР-1: выставляем desired_connected=True, чтобы supervisor знал намерение.
        for entry in self._manager._entries.values():
            if entry.enabled and (entry.auto_connect or entry.id in recipe_ids):
                self._desired_connected[entry.id] = True
                self._conn_queue.put(("connect", entry.id))

        # Supervisor-worker (LOOP)
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(
            "device_supervisor",
            self._supervisor_loop,
            cfg,
            auto_start=True,
        )
        ctx.log_info(f"DeviceHubPlugin: started ({len(self._manager._entries)} устройств)")

    def shutdown(self, ctx: PluginContext) -> None:
        """* -> STOPPED: отключить всех, сохранить реестр."""
        # Остановить и удалить per-device воркеры (remove_worker освобождает имена)
        with self._workers_lock:
            for dev_id, wname in list(self._device_workers.items()):
                try:
                    if ctx.worker_manager is not None:
                        remove_fn = getattr(ctx.worker_manager, "remove_worker", None)
                        if remove_fn:
                            remove_fn(wname)
                except Exception:
                    pass
            self._device_workers.clear()

        # Disconnect всех + сохранить
        self._manager.shutdown()
        ctx.log_info("DeviceHubPlugin: shutdown")

    # ------------------------------------------------------------------ #
    # SUPERVISOR WORKER (Б2)
    # ------------------------------------------------------------------ #

    def _supervisor_loop(self, stop_event: threading.Event, pause_event: threading.Event) -> None:
        """Фоновый цикл: разбор очереди connect/disconnect + tick connected-драйверов."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            time.sleep(self._reg.supervisor_interval_s)

            # 1. Разобрать очередь connect/disconnect
            self._process_conn_queue()

            # 2. Для connected-драйверов без воркера — создать per-device воркер
            self._ensure_device_workers()

    def _process_conn_queue(self) -> None:
        """Обработать все ожидающие connect/disconnect запросы."""
        while True:
            try:
                op, dev_id = self._conn_queue.get_nowait()
            except queue.Empty:
                break
            try:
                if op == "connect":
                    self._publish_state(f"devices.state.{dev_id}.conn", {"conn": "connecting"})
                    ok = self._manager.connect(dev_id)
                    conn = "connected" if ok else "error"
                    self._publish_state(f"devices.state.{dev_id}.conn", {"conn": conn})
                    # НР-1/НР-2: проставляем desired на драйвере (для reconnect в tick)
                    driver = self._manager._drivers.get(dev_id)
                    if driver is not None:
                        driver.desired_connected = True
                elif op == "disconnect":
                    self._publish_state(f"devices.state.{dev_id}.conn", {"conn": "disconnecting"})
                    # НР-1: desired=False на драйвере ДО disconnect (tick не реконнектит)
                    driver = self._manager._drivers.get(dev_id)
                    if driver is not None:
                        driver.desired_connected = False
                    self._manager.disconnect(dev_id)
                    self._publish_state(f"devices.state.{dev_id}.conn", {"conn": "disconnected"})
                    # Остановить per-device воркер
                    self._stop_device_worker(dev_id)
            except Exception as exc:
                self._publish_state(f"devices.state.{dev_id}.conn", {"conn": "error"})
                self._publish_state(f"devices.state.{dev_id}.last_error", str(exc))
                self._reg.last_error = str(exc)
                if self._ctx:
                    self._ctx.log_error(f"DeviceHubPlugin: {op} {dev_id} ошибка: {exc}")
            self._update_counters()

    def _ensure_device_workers(self) -> None:
        """Привести факт к desired: воркер есть <=> desired_connected=True.

        НР-1/НР-2 ревью Fable: воркер создаётся ТОЛЬКО для desired=True.
        При desired=False воркер останавливается (если был).
        Драйвер в _drivers может оставаться для быстрого повторного connect.

        НР-3: проверка desired + _drivers + запись _device_workers — под
        общим _workers_lock, чтобы remove не мог создать окно.

        НР-4: create_worker может вернуть False — записываем в _device_workers
        ТОЛЬКО при True; при False — лог, retry на следующей итерации.
        """
        with self._workers_lock:
            # Остановить воркеры для desired=False (факт > desired)
            for dev_id in list(self._device_workers):
                if not self._desired_connected.get(dev_id, False):
                    wname = self._device_workers.pop(dev_id, None)
                    if wname and self._ctx and self._ctx.worker_manager:
                        remove_fn = getattr(self._ctx.worker_manager, "remove_worker", None)
                        if remove_fn:
                            try:
                                remove_fn(wname)
                            except Exception:
                                pass

            # Создать воркеры для desired=True без существующего воркера
            for dev_id in list(self._desired_connected):
                if not self._desired_connected.get(dev_id, False):
                    continue
                if dev_id in self._device_workers:
                    continue
                # НР-3: драйвер должен существовать (не удалён remove)
                driver = self._manager._drivers.get(dev_id)
                if driver is None:
                    continue

                wname = f"dev_{dev_id}"

                def make_tick_fn(did: str, drv: Any) -> Any:
                    """Замыкание для per-device tick."""

                    def tick_loop(stop_evt: threading.Event, pause_evt: threading.Event) -> None:
                        interval = getattr(drv.entry, "params", {}).get("poll_interval_s", 0.5)
                        if isinstance(interval, str):
                            interval = float(interval)
                        tick_n = 0
                        while not stop_evt.is_set():
                            if pause_evt.is_set():
                                time.sleep(0.1)
                                continue
                            try:
                                tick_n += 1
                                snapshot = drv.tick(stop_evt)
                                if snapshot is not None:
                                    self._publish_state(f"devices.state.{did}.status", snapshot)
                                    self._publish_state(f"devices.state.{did}.stats", drv.stats)
                                # conn каждый тик: иначе одноразовая дельта при connect
                                # дедуплицируется StateStore, и поздние подписчики (список,
                                # страница добавления) видят stale «disconnected». ts меняется
                                # → дельта проходит. quality снапшота отражает живость чтений.
                                if getattr(drv, "is_connected", False):
                                    conn = "error" if (snapshot or {}).get("quality") == "bad" else "connected"
                                else:
                                    conn = "disconnected"
                                self._publish_state(f"devices.state.{did}.conn", {"conn": conn, "ts": tick_n})
                                # io_peek для панели «Вход/Выход» (если драйвер
                                # накапливает wire-обмен — robot/generic_modbus).
                                io = getattr(drv, "last_io", None)
                                if io and (io.get("input") or io.get("output")):
                                    self._publish_state(
                                        f"devices.state.{did}.io_peek",
                                        {"method": "modbus", **io},
                                    )
                            except Exception as exc:
                                self._publish_state(f"devices.state.{did}.last_error", str(exc))
                            time.sleep(interval)

                    return tick_loop

                try:
                    cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
                    ok = self._ctx.worker_manager.create_worker(
                        wname,
                        make_tick_fn(dev_id, driver),
                        cfg,
                        auto_start=True,
                    )
                    # НР-4: записываем ТОЛЬКО при ok=True
                    if ok:
                        self._device_workers[dev_id] = wname
                    elif self._ctx:
                        self._ctx.log_error(
                            f"DeviceHubPlugin: create_worker {wname} вернул False "
                            f"(имя занято?), retry на следующей итерации"
                        )
                except Exception as exc:
                    if self._ctx:
                        self._ctx.log_error(f"DeviceHubPlugin: не удалось создать воркер {wname}: {exc}")

    def _stop_device_worker(self, dev_id: str) -> None:
        """Остановить и ПОЛНОСТЬЮ удалить per-device воркер из WorkerManager.

        Б-1 ревью Fable: stop_worker оставляет имя в реестре WorkerManager,
        поэтому повторный create_worker вернёт False. remove_worker
        останавливает поток И удаляет запись — имя освобождается для
        повторного connect.
        """
        with self._workers_lock:
            wname = self._device_workers.pop(dev_id, None)
        if wname and self._ctx and self._ctx.worker_manager:
            remove_fn = getattr(self._ctx.worker_manager, "remove_worker", None)
            if remove_fn:
                try:
                    remove_fn(wname)
                except Exception:
                    pass

    # ------------------------------------------------------------------ #
    # State-публикация
    # ------------------------------------------------------------------ #

    def _publish_state(self, path: str, data: Any) -> None:
        """Публикация в state-дерево через state_proxy.merge (потокобезопасен)."""
        if self._ctx and self._ctx.state_proxy is not None:
            self._ctx.state_proxy.merge(path, data)

    def _publish_full_registry(self) -> None:
        """Опубликовать весь реестр в state-дерево."""
        for entry in self._manager._entries.values():
            self._publish_state(f"devices.registry.{entry.id}", entry.to_dict())

    def _update_counters(self) -> None:
        """Обновить счётчики в register."""
        self._reg.devices_total = len(self._manager._entries)
        connected = sum(1 for d in self._manager._drivers.values() if d.is_connected)
        self._reg.devices_connected = connected

    # ------------------------------------------------------------------ #
    # SAFE CALL — обёртка ошибок в dict-ответ
    # ------------------------------------------------------------------ #

    def _safe_call(self, fn: Any, *args: Any, **kwargs: Any) -> dict:
        """Выполнить функцию, завернув ошибки в {"status": "error", "message": ...}."""
        try:
            result = fn(*args, **kwargs)
            self._reg.commands_ok += 1
            if isinstance(result, dict):
                if "status" not in result:
                    result["status"] = "ok"
                return result
            return {"status": "ok"}
        except Exception as exc:
            self._reg.commands_err += 1
            self._reg.last_error = str(exc)
            return {"status": "error", "message": str(exc)}

    def _kind_call(self, data: dict, expected_kind: str, op: str) -> dict:
        """Команда для конкретного kind: валидация kind + dispatch."""
        dev_id = data.get("device_id", "")
        if not dev_id:
            return {"status": "error", "message": "device_id обязателен"}
        # Валидация kind
        try:
            entry = self._manager.get(dev_id)
        except DeviceHubError as exc:
            return {"status": "error", "message": str(exc)}
        if entry.kind != expected_kind:
            return {
                "status": "error",
                "message": f"Устройство {dev_id!r} имеет kind={entry.kind!r}, ожидается {expected_kind!r}",
            }
        args = {k: v for k, v in data.items() if k != "device_id"}
        return self._safe_call(self._manager.call, dev_id, op, args)

    # ------------------------------------------------------------------ #
    # КОМАНДЫ — Реестр
    # ------------------------------------------------------------------ #

    def cmd_device_list(self, data: dict) -> dict:
        """Список всех устройств реестра."""
        return self._safe_call(lambda: {"devices": self._manager.list_devices()})

    def cmd_device_describe(self, data: dict) -> dict:
        """Описание устройства: entry + protocol meta + conn + stats."""
        dev_id = data.get("device_id", "")
        return self._safe_call(self._manager.describe, dev_id)

    def cmd_device_upsert(self, data: dict) -> dict:
        """Создать/обновить устройство."""
        origin = data.pop("origin", None)
        result = self._safe_call(self._manager.upsert, data, origin)
        # Публикуем реестр после успешного upsert — аналогично cmd_device_upsert_many.
        # Без этого комбо DeviceComboController не получит push-дельту devices.registry.*
        # и GUI отобразит устройство только после явного pull/refresh.
        if result.get("status") == "ok":
            self._publish_full_registry()
        self._update_counters()
        return result

    def cmd_device_upsert_many(self, data: dict) -> dict:
        """Массовый upsert устройств.

        Args (в data):
            devices: list[dict] — записи DeviceEntry для upsert.
            origin:  str | None — источник (``recipe:<slug>``).
            connect: bool — если True, auto-connect все upserted-устройства (Р11).
        """
        devices = data.get("devices", [])
        origin = data.get("origin")
        do_connect = bool(data.get("connect", False))
        results = []
        upserted_ids: list[str] = []
        for dev_dict in devices:
            if isinstance(dev_dict, dict):
                r = self._safe_call(self._manager.upsert, dev_dict, origin)
                results.append(r)
                if r.get("status") == "ok" and "id" in dev_dict:
                    upserted_ids.append(dev_dict["id"])
        self._publish_full_registry()
        self._update_counters()
        # Р11: auto-connect все upserted-устройства (async через supervisor)
        if do_connect:
            with self._workers_lock:
                for dev_id in upserted_ids:
                    self._desired_connected[dev_id] = True
            for dev_id in upserted_ids:
                self._conn_queue.put(("connect", dev_id))
        return {"status": "ok", "results": results, "count": len(results)}

    def cmd_device_sync_set(self, data: dict) -> dict:
        """Полная синхронизация recipe-устройств реестра с переданным набором.

        Идемпотентная замена набора recipe-устройств (план device-tree-recipe,
        Фаза B): рецепт — источник истины, hub — runtime-отражение. Вызывается
        при активации рецепта (вместо ``device_upsert_many``).

        Семантика:
          1. upsert всех из ``devices`` с ``origin`` (обычно ``recipe:<slug>``);
          2. **remove** recipe-устройств (origin начинается с ``recipe:``), которых
             НЕТ в новом списке — через полный путь cmd_device_remove (disconnect +
             стоп воркера + публикация). Manual-устройства (origin != recipe:*) НЕ
             трогаются;
          3. auto-connect всех upserted (если ``connect`` True, по умолчанию True).

        Bridge-зависимые recipe-устройства удаляются первыми (иначе manager.remove
        бросит RegistryIntegrityError на устройстве-носителе).

        Args (в data):
            devices: list[dict] — целевой набор recipe-устройств.
            origin:  str — источник (``recipe:<slug>``).
            connect: bool — auto-connect upserted (по умолчанию True).
        """
        devices = data.get("devices", [])
        origin = data.get("origin")
        do_connect = bool(data.get("connect", True))

        # 1. upsert целевого набора
        new_ids: set[str] = set()
        results = []
        for dev_dict in devices:
            if isinstance(dev_dict, dict) and "id" in dev_dict:
                r = self._safe_call(self._manager.upsert, dev_dict, origin)
                results.append(r)
                if r.get("status") == "ok":
                    new_ids.add(dev_dict["id"])

        # 2. удалить лишние recipe-устройства (bridge-зависимые — первыми)
        stale = [
            e
            for e in self._manager.list_devices()
            if str(e.get("origin", "")).startswith("recipe:") and e.get("id") not in new_ids
        ]
        stale.sort(key=lambda e: 0 if e.get("transport", {}).get("type") == "bridge" else 1)
        removed_ids: list[str] = []
        for entry in stale:
            dev_id = entry.get("id", "")
            rm = self.cmd_device_remove({"device_id": dev_id})
            if rm.get("status") == "ok":
                removed_ids.append(dev_id)

        self._publish_full_registry()
        self._update_counters()

        # 3. auto-connect upserted (async через supervisor)
        if do_connect:
            with self._workers_lock:
                for dev_id in new_ids:
                    self._desired_connected[dev_id] = True
            for dev_id in new_ids:
                self._conn_queue.put(("connect", dev_id))

        return {
            "status": "ok",
            "upserted": sorted(new_ids),
            "removed": removed_ids,
            "count": len(results),
        }

    def cmd_device_remove(self, data: dict) -> dict:
        """Удалить устройство из реестра.

        н2 ревью Fable: останавливаем per-device воркер ПЕРЕД удалением
        записи, иначе tick_loop замыкание вечно тикает удалённый драйвер,
        а повторное добавление того же id не создаст воркер (имя занято).

        НР-3: desired=False ДО остановки воркера — _ensure_device_workers
        не пересоздаст воркер в окне между remove и stop.
        """
        dev_id = data.get("device_id", "")
        # НР-3: сначала desired=False, потом воркер, потом remove —
        # атомарно по отношению к _ensure_device_workers
        with self._workers_lock:
            self._desired_connected.pop(dev_id, None)
        self._stop_device_worker(dev_id)
        result = self._safe_call(self._manager.remove, dev_id)
        # Очистить state удалённого устройства и обновить реестр в StateStore.
        # _publish_full_registry после remove не публикует удалённую запись →
        # DeltaDispatcher удаляет/замещает устаревший узел devices.registry.<id>,
        # что приводит к исчезновению устройства из комбо в GUI.
        if result.get("status") == "ok":
            self._publish_state(f"devices.state.{dev_id}", {})
            self._publish_full_registry()
        self._update_counters()
        return result

    def cmd_device_protocols(self, data: dict) -> dict:
        """Список доступных протоколов (опц. фильтр по kind)."""
        kind = data.get("kind")
        return self._safe_call(lambda: {"protocols": self._manager.protocols(kind)})

    # ------------------------------------------------------------------ #
    # КОМАНДЫ — Соединение (асинхронные, Б2)
    # ------------------------------------------------------------------ #

    def cmd_device_connect(self, data: dict) -> dict:
        """Асинхронный connect: ответ сразу, TCP в supervisor-воркере."""
        dev_id = data.get("device_id", "")
        if not dev_id:
            return {"status": "error", "message": "device_id обязателен"}
        try:
            self._manager.get(dev_id)  # проверка существования
        except DeviceHubError as exc:
            return {"status": "error", "message": str(exc)}
        # НР-1: выставляем desired перед постановкой в очередь
        with self._workers_lock:
            self._desired_connected[dev_id] = True
        self._conn_queue.put(("connect", dev_id))
        return {"status": "ok", "conn": "connecting"}

    def cmd_device_disconnect(self, data: dict) -> dict:
        """Асинхронный disconnect: ответ сразу, реальный disconnect в supervisor."""
        dev_id = data.get("device_id", "")
        if not dev_id:
            return {"status": "error", "message": "device_id обязателен"}
        try:
            self._manager.get(dev_id)
        except DeviceHubError as exc:
            return {"status": "error", "message": str(exc)}
        # НР-1: desired=False — supervisor НЕ пересоздаст воркер
        with self._workers_lock:
            self._desired_connected[dev_id] = False
        self._conn_queue.put(("disconnect", dev_id))
        return {"status": "ok", "conn": "disconnecting"}

    # ------------------------------------------------------------------ #
    # КОМАНДЫ — Универсальные регистры
    # ------------------------------------------------------------------ #

    def cmd_device_read(self, data: dict) -> dict:
        """Чтение регистра: {device_id, name}."""
        dev_id = data.get("device_id", "")
        name = data.get("name", "")
        return self._safe_call(self._manager.read_register, dev_id, name)

    def cmd_device_write(self, data: dict) -> dict:
        """Запись регистров: {device_id, values: {name: value}}."""
        dev_id = data.get("device_id", "")
        values = data.get("values", {})
        return self._safe_call(self._manager.write_registers, dev_id, values)

    # ------------------------------------------------------------------ #
    # КОМАНДЫ — Робот (11)
    # ------------------------------------------------------------------ #

    def cmd_robot_enqueue_job(self, data: dict) -> dict:
        """Поставить CVT-задание: {device_id, x_mm, y_mm, e_capture?}."""
        return self._kind_call(data, "robot", "enqueue_job")

    def cmd_robot_send_test_job(self, data: dict) -> dict:
        """Тестовое CVT-задание: {device_id, x, y}."""
        return self._kind_call(data, "robot", "send_test_job")

    def cmd_robot_abort(self, data: dict) -> dict:
        """Стоп робота: {device_id, mode: 1|2|3}."""
        return self._kind_call(data, "robot", "abort")

    def cmd_robot_set_mode(self, data: dict) -> dict:
        """Режим робота: {device_id, mode: cvt|draw}."""
        return self._kind_call(data, "robot", "set_mode")

    def cmd_robot_set_servo(self, data: dict) -> dict:
        """Серво: {device_id, on: bool}."""
        return self._kind_call(data, "robot", "set_servo")

    def cmd_robot_set_robot_config(self, data: dict) -> dict:
        """Конфиг робота: {device_id, ...fields}."""
        return self._kind_call(data, "robot", "set_robot_config")

    def cmd_robot_get_robot_config(self, data: dict) -> dict:
        """Прочитать конфиг-блок робота."""
        return self._kind_call(data, "robot", "get_robot_config")

    def cmd_robot_get_telemetry(self, data: dict) -> dict:
        """Телеметрия робота."""
        return self._kind_call(data, "robot", "get_telemetry")

    def cmd_robot_read_echo(self, data: dict) -> dict:
        """Эхо последнего задания."""
        return self._kind_call(data, "robot", "read_echo")

    def cmd_robot_set_manual_mode(self, data: dict) -> dict:
        """Ручной режим: {device_id, on: bool}."""
        return self._kind_call(data, "robot", "set_manual_mode")

    def cmd_robot_clear_queue(self, data: dict) -> dict:
        """Очистить очередь заданий."""
        return self._kind_call(data, "robot", "clear_queue")

    # ------------------------------------------------------------------ #
    # КОМАНДЫ — Рисование (8)
    # ------------------------------------------------------------------ #

    def cmd_robot_draw_polyline(self, data: dict) -> dict:
        """Нарисовать полилинию: {device_id, points, ...}."""
        return self._kind_call(data, "robot", "draw_polyline")

    def cmd_robot_draw_circle(self, data: dict) -> dict:
        """Нарисовать окружность: {device_id, cx, cy, r}."""
        return self._kind_call(data, "robot", "draw_circle")

    def cmd_robot_draw_square(self, data: dict) -> dict:
        """Нарисовать квадрат: {device_id, cx, cy, side}."""
        return self._kind_call(data, "robot", "draw_square")

    def cmd_robot_draw_set_pen(self, data: dict) -> dict:
        """Установить перо: {device_id, pen_z}."""
        return self._kind_call(data, "robot", "draw_set_pen")

    def cmd_robot_draw_set_speed(self, data: dict) -> dict:
        """Установить скорость рисования: {device_id, speed}."""
        return self._kind_call(data, "robot", "draw_set_speed")

    def cmd_robot_draw_set_overlap(self, data: dict) -> dict:
        """Установить overlap: {device_id, overlap}."""
        return self._kind_call(data, "robot", "draw_set_overlap")

    def cmd_robot_draw_abort(self, data: dict) -> dict:
        """Прервать рисование: {device_id}."""
        return self._kind_call(data, "robot", "draw_abort")

    def cmd_robot_draw_progress(self, data: dict) -> dict:
        """Прогресс рисования: {device_id}."""
        return self._kind_call(data, "robot", "draw_progress")

    # ------------------------------------------------------------------ #
    # КОМАНДЫ — ПЧ (5)
    # ------------------------------------------------------------------ #

    def cmd_vfd_run(self, data: dict) -> dict:
        """Пуск ПЧ: {device_id, direction?, freq_hz?}."""
        return self._kind_call(data, "vfd", "run")

    def cmd_vfd_set_freq(self, data: dict) -> dict:
        """Установить частоту: {device_id, freq_hz}."""
        return self._kind_call(data, "vfd", "set_freq")

    def cmd_vfd_stop(self, data: dict) -> dict:
        """Стоп ПЧ: {device_id}."""
        return self._kind_call(data, "vfd", "stop")

    def cmd_vfd_reset_fault(self, data: dict) -> dict:
        """Сброс аварии ПЧ: {device_id}."""
        return self._kind_call(data, "vfd", "reset_fault")

    def cmd_vfd_get_status(self, data: dict) -> dict:
        """Статус ПЧ: {device_id}."""
        return self._kind_call(data, "vfd", "get_status")

    # ------------------------------------------------------------------ #
    # КОМАНДЫ — Hikvision (6)
    # ------------------------------------------------------------------ #

    def cmd_hik_enum(self, data: dict) -> dict:
        """Перечислить камеры Hikvision (device-less: не требует device_id).

        Discovery — операция вида (kind), а не экземпляра: перечисляет ВСЕ
        камеры Hikvision на шине, без привязки к конкретной записи реестра.
        Lazy import SDK: если SDK недоступен — ошибка, не crash.
        """
        try:
            from Services.hikvision_camera.core.discovery import enum_devices
        except ImportError:
            return {"status": "error", "message": "SDK Hikvision недоступен"}
        try:
            devices = enum_devices()
            return {
                "status": "ok",
                "devices": [
                    {
                        "serial": getattr(d, "serial", getattr(d, "serial_number", "")),
                        "model": getattr(d, "model_name", ""),
                        "ip": getattr(d, "ip_address", getattr(d, "display_name", "")),
                        "index": getattr(d, "index", i),
                    }
                    for i, d in enumerate(devices)
                ],
            }
        except Exception as exc:
            return {"status": "error", "message": f"Ошибка перечисления камер: {exc}"}

    def cmd_hik_open(self, data: dict) -> dict:
        """Открыть камеру: {device_id}."""
        return self._kind_call(data, "hikvision", "open")

    def cmd_hik_close(self, data: dict) -> dict:
        """Закрыть камеру: {device_id}."""
        return self._kind_call(data, "hikvision", "close")

    def cmd_hik_get_params(self, data: dict) -> dict:
        """Получить параметры камеры: {device_id}."""
        return self._kind_call(data, "hikvision", "get_params")

    def cmd_hik_set_params(self, data: dict) -> dict:
        """Установить параметры камеры: {device_id, ...params}."""
        return self._kind_call(data, "hikvision", "set_params")

    def cmd_hik_release(self, data: dict) -> dict:
        """Освободить камеру: {device_id?}.

        Если device_id не указан — release всех подключённых hikvision-устройств
        (арбитраж: capture-плагин просит освободить handle перед стартом).
        Если у hub нет открытого handle — просто ok.
        """
        dev_id = data.get("device_id", "")
        if dev_id:
            return self._kind_call(data, "hikvision", "release")
        # Без device_id — release всех hikvision-устройств
        released = []
        for entry in list(self._manager._entries.values()):
            if entry.kind != "hikvision":
                continue
            driver = self._manager._drivers.get(entry.id)
            if driver is not None and driver.is_connected:
                try:
                    driver.call("release", {})
                    released.append(entry.id)
                except Exception:
                    pass
        return {"status": "ok", "released": released}
