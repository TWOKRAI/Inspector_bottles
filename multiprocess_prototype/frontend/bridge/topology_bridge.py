"""TopologyBridge — единый мост GUI ↔ Runtime.

Замыкает цикл:
  GUI field_set → IPC command → target process → plugin
  Plugin state update → state_delta → bridge → RegistersManager sync

Модульный блок конструктора: собирается из CommandCatalog + CommandValidator +
CommandSender. Каждая зависимость через DI, каждая заменяема.

v2 (Phase 12.6): runtime extensions — hot_add/remove, connect/disconnect wire,
apply_topology_diff, get_capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from multiprocess_framework.modules.logger_module import get_logger

from .diff_engine import compute_diff
from .wire_protocol import WireConfig, ShmConfig, validate_wire
from .system_commands import (
    build_hot_add_process,
    build_hot_remove_process,
    build_wire_setup,
    build_wire_teardown,
)
from .wire_monitor import WireStatusMonitor


def _log(msg: str, level: str = "info") -> None:
    """Записать в LoggerManager (если инициализирован), иначе тихо.

    module="trace" — диагностические сообщения уходят в logs/<proc>/trace.log
    (см. LoggerManagerConfig.modules["trace"]) плюс в scope-каналы.
    """
    lm = get_logger()
    if lm is None:
        return
    getattr(lm, level)(msg, module="trace")


# Тонкая прокси-обёртка чтобы прежний `logger.warning(...)` стиль работал
# без массовых правок в файле. Все вызовы делегируются в LoggerManager.
class _LegacyLoggerShim:
    def info(self, msg: str, *args: Any) -> None:
        _log(msg % args if args else msg)

    def warning(self, msg: str, *args: Any) -> None:
        _log(msg % args if args else msg, level="warning")

    def error(self, msg: str, *args: Any) -> None:
        _log(msg % args if args else msg, level="error")

    def debug(self, msg: str, *args: Any) -> None:
        _log(msg % args if args else msg, level="debug")

    def exception(self, msg: str, *args: Any) -> None:
        _log(msg % args if args else msg, level="error")


logger = _LegacyLoggerShim()

# Дефолтный debounce для числовых полей с min/max (slider)
_DEFAULT_SLIDER_DEBOUNCE_MS = 50


# --- Результат применения diff ---


@dataclass
class TopologyApplyResult:
    """Результат apply_topology_diff — какие изменения применены и ошибки."""

    processes_added: list[str] = field(default_factory=list)
    processes_removed: list[str] = field(default_factory=list)
    wires_added: list[str] = field(default_factory=list)
    wires_removed: list[str] = field(default_factory=list)
    configs_updated: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True если ни одной ошибки."""
        return len(self.errors) == 0

    def summary(self) -> str:
        """Краткая сводка результата.

        Формат: '+N процессов, -M процессов, +K wire, ошибок: E'
        """
        parts: list[str] = []
        if self.processes_added:
            parts.append(f"+{len(self.processes_added)} процессов")
        if self.processes_removed:
            parts.append(f"-{len(self.processes_removed)} процессов")
        if self.wires_added:
            parts.append(f"+{len(self.wires_added)} wire")
        if self.wires_removed:
            parts.append(f"-{len(self.wires_removed)} wire")
        if self.configs_updated:
            parts.append(f"~{len(self.configs_updated)} конфигов")
        if self.errors:
            parts.append(f"ошибок: {len(self.errors)}")
        return ", ".join(parts) if parts else "Нет изменений"


# --- Протоколы ---


@runtime_checkable
class IBridgeCommandCatalog(Protocol):
    """Интерфейс CommandCatalog для TopologyBridge."""

    def resolve_field_command(self, plugin_name: str, field_name: str) -> Any | None: ...
    def resolve_action_command(self, plugin_name: str, command_name: str) -> Any | None: ...
    def get_plugin(self, plugin_name: str) -> Any | None: ...


@runtime_checkable
class IBridgeCommandValidator(Protocol):
    """Интерфейс CommandValidator для TopologyBridge."""

    def validate_field_command(self, plugin_name: str, field_name: str, value: Any) -> Any: ...
    def validate_action_command(self, plugin_name: str, command_name: str) -> Any: ...


@runtime_checkable
class IBridgeCommandSender(Protocol):
    """Интерфейс CommandSender для TopologyBridge."""

    def send_field_command(
        self, target_process: str, command: str, args: dict[str, Any], *, debounce_ms: int = 0
    ) -> None: ...

    def send_action_command(self, target_process: str, command: str, args: dict[str, Any] | None = None) -> None: ...

    def send_command(self, target_process: str, command: str, args: dict[str, Any] | None = None) -> None: ...

    def send_system_command(self, command: dict[str, Any]) -> None: ...


@runtime_checkable
class IBridgeRegistersManager(Protocol):
    """Интерфейс RegistersManager для TopologyBridge."""

    def get_fields(self, plugin_name: str) -> list[Any]: ...
    def set_value(self, plugin_name: str, field_name: str, value: Any) -> bool: ...


@runtime_checkable
class IBridgeTopologyHolder(Protocol):
    """Интерфейс TopologyHolder для TopologyBridge."""

    @property
    def topology(self) -> dict[str, Any]: ...


# --- TopologyBridge ---


class TopologyBridge:
    """Единый мост GUI → Runtime и Runtime → GUI.

    Потоки данных:
    1. on_field_set()     — GUI изменил поле → IPC-команда в процесс
    2. on_action_command() — GUI вызвал действие → IPC-команда
    3. on_state_delta()   — Runtime прислал state_delta → обновить RegistersManager
    4. start/stop/restart — lifecycle-команды процессов
    5. on_topology_changed() — topology изменилась → пересобрать каталог

    Все зависимости через конструктор (DI). Каждая заменяема.
    """

    def __init__(
        self,
        command_sender: IBridgeCommandSender,
        command_catalog: IBridgeCommandCatalog,
        command_validator: IBridgeCommandValidator,
        registers_manager: IBridgeRegistersManager,
        topology_holder: IBridgeTopologyHolder,
        wire_monitor: WireStatusMonitor | None = None,
    ) -> None:
        self._sender = command_sender
        self._catalog = command_catalog
        self._validator = command_validator
        self._rm = registers_manager
        self._holder = topology_holder
        self._wire_monitor = wire_monitor
        self._connected = True
        self._applying = False

        # Кэш: plugin_name → set(field_names с min/max → slider → debounce)
        self._slider_fields: dict[str, set[str]] = {}

    # --- GUI → Runtime ---

    def on_field_set(
        self,
        plugin_name: str,
        field_name: str,
        value: Any,
    ) -> bool:
        """Обработать изменение поля в GUI → отправить IPC-команду.

        Returns:
            True если команда отправлена (или не нужна для stateless).
            False если валидация не прошла.
        """
        # Resolve
        resolved = self._catalog.resolve_field_command(plugin_name, field_name)
        _log(f"[trace bridge] on_field_set({plugin_name}.{field_name}={value!r}) → resolved={resolved!r}")
        if resolved is None:
            # Stateless плагин или не в каталоге — IPC не нужен
            _log(f"[trace bridge] {plugin_name} stateless или не в каталоге — IPC пропущен")
            return True

        # Валидация
        result = self._validator.validate_field_command(plugin_name, field_name, value)
        if not result.ok:
            _log(
                f"TopologyBridge: валидация отклонена — {plugin_name}.{field_name} = {value!r}: {result.error}",
                level="warning",
            )
            return False

        # Debounce для slider-полей
        debounce_ms = self._get_debounce(plugin_name, field_name)

        # Fan-out — отправить во все target-процессы (может быть несколько при multi-target)
        _log(
            f"[trace bridge] send_field_command(targets={resolved.process_names}, "
            f"cmd={resolved.command_name}, args={ {field_name: value}!r}, debounce_ms={debounce_ms})"
        )
        for process_name in resolved.process_names:
            self._sender.send_field_command(
                process_name,
                resolved.command_name,
                {field_name: value},
                debounce_ms=debounce_ms,
            )
        return True

    def on_action_command(
        self,
        plugin_name: str,
        command_name: str,
        args: dict[str, Any] | None = None,
    ) -> bool:
        """Отправить action-команду (start/stop и т.п.).

        Returns:
            True если команда отправлена. False если валидация не прошла.
        """
        result = self._validator.validate_action_command(plugin_name, command_name)
        if not result.ok:
            logger.warning(
                "TopologyBridge: action отклонён — %s.%s: %s",
                plugin_name,
                command_name,
                result.error,
            )
            return False

        resolved = self._catalog.resolve_action_command(plugin_name, command_name)
        if resolved is None:
            return False

        self._sender.send_action_command(resolved.process_name, command_name, args)
        return True

    # --- Runtime → GUI ---

    def on_state_delta(self, path: str, value: Any) -> None:
        """Обработать state_delta из runtime → обновить RegistersManager.

        Парсит path формата: processes.{name}.config.{field}
        и обновляет RegistersManager для обратной синхронизации.
        """
        parts = path.split(".")
        # Формат: processes.<process_name>.config.<field_name>
        if len(parts) >= 4 and parts[0] == "processes" and parts[2] == "config":
            plugin_name = parts[1]  # convention: process_name ~ plugin_name
            field_name = ".".join(parts[3:])
            ok = self._rm.set_value(plugin_name, field_name, value)
            if not ok:
                logger.debug(
                    "TopologyBridge: state_delta не применён — %s.%s = %r",
                    plugin_name,
                    field_name,
                    value,
                )
        # Другие path (processes.X.state.fps и т.п.) — не для rm, для bindings

    # --- Lifecycle ---

    def start_process(self, process_name: str) -> bool:
        """Запустить процесс."""
        return self._send_lifecycle("process.start", process_name)

    def stop_process(self, process_name: str) -> bool:
        """Остановить процесс."""
        return self._send_lifecycle("process.stop", process_name)

    def restart_process(self, process_name: str) -> bool:
        """Перезапустить процесс."""
        return self._send_lifecycle("process.restart", process_name)

    def _send_lifecycle(self, command: str, process_name: str) -> bool:
        """Отправить lifecycle-команду после проверки topology."""
        if not self._process_exists(process_name):
            logger.warning("TopologyBridge: процесс '%s' не найден в topology", process_name)
            return False

        self._sender.send_command(process_name, command)
        return True

    def _process_exists(self, process_name: str) -> bool:
        """Проверить существование процесса в topology."""
        for proc in self._holder.topology.get("processes", []):
            if proc.get("process_name") == process_name:
                return True
        return False

    # --- Topology changes ---

    def on_topology_changed(self, new_topology: dict[str, Any]) -> None:
        """Topology изменилась — пересобрать каталог.

        Вызывается через TopologyHolder.on_changed callback.
        """
        # Очистить кэш slider-полей
        self._slider_fields.clear()
        logger.info("TopologyBridge: topology changed, кэш очищен")

    def rebuild_catalog(self, new_catalog: IBridgeCommandCatalog) -> None:
        """Заменить каталог (после пересборки внешним кодом)."""
        self._catalog = new_catalog
        self._slider_fields.clear()

    # --- Debounce helpers ---

    def _get_debounce(self, plugin_name: str, field_name: str) -> int:
        """Определить debounce для поля: slider (числовое с min/max) → 50ms, иначе 0."""
        if plugin_name not in self._slider_fields:
            self._slider_fields[plugin_name] = self._detect_slider_fields(plugin_name)

        if field_name in self._slider_fields[plugin_name]:
            return _DEFAULT_SLIDER_DEBOUNCE_MS
        return 0

    def _detect_slider_fields(self, plugin_name: str) -> set[str]:
        """Определить какие поля являются slider (числовые с min/max)."""
        slider_fields: set[str] = set()
        for fi in self._rm.get_fields(plugin_name):
            if fi.min_value is not None and fi.max_value is not None:
                if fi.field_type in (int, float):
                    slider_fields.add(fi.field_name)
        return slider_fields

    # --- Runtime extensions (Phase 12.6) ---

    def hot_add_process(
        self,
        process_name: str,
        plugin_name: str,
        plugin_config: dict[str, Any] | None = None,
        *,
        auto_start: bool = True,
    ) -> bool:
        """Горячее добавление нового процесса.

        Проверяет что процесс ещё НЕ существует в topology,
        формирует IPC-команду и отправляет в ProcessManager.

        Returns:
            True если команда отправлена, False если процесс уже есть.
        """
        if self._process_exists(process_name):
            logger.warning("TopologyBridge.hot_add: процесс '%s' уже существует", process_name)
            return False

        cmd = build_hot_add_process(process_name, plugin_name, plugin_config, auto_start=auto_start)
        self._sender.send_system_command(cmd)
        return True

    def hot_remove_process(
        self,
        process_name: str,
        *,
        graceful: bool = True,
    ) -> bool:
        """Горячее удаление процесса.

        Каскадно отключает все wire'ы процесса перед удалением.

        Returns:
            True если команда отправлена, False если процесс не найден.
        """
        if not self._process_exists(process_name):
            logger.warning("TopologyBridge.hot_remove: процесс '%s' не найден", process_name)
            return False

        # Каскадное отключение wire'ов процесса
        process_wires = self._find_process_wires(process_name)
        for wire in process_wires:
            wire_key = f"{wire.get('source', '')}|{wire.get('target', '')}"
            self.disconnect_wire(wire_key)

        cmd = build_hot_remove_process(process_name, graceful=graceful)
        self._sender.send_system_command(cmd)
        return True

    def connect_wire(
        self,
        wire_key: str,
        source: str,
        target: str,
        *,
        transport: str = "router",
        shm_config: ShmConfig | None = None,
    ) -> bool:
        """Создать wire (соединение между процессами).

        Создаёт WireConfig, валидирует, формирует IPC-команду
        и уведомляет wire_monitor.

        Returns:
            True если команда отправлена, False если валидация не прошла.
        """
        wire = WireConfig(
            wire_key=wire_key,
            source=source,
            target=target,
            transport=transport,
            shm_config=shm_config or ShmConfig(),
        )

        valid, error = validate_wire(wire)
        if not valid:
            logger.warning(
                "TopologyBridge.connect_wire: валидация провалена — %s: %s",
                wire_key,
                error,
            )
            return False

        cmd = build_wire_setup(wire)
        self._sender.send_system_command(cmd)

        # Уведомить монитор
        if self._wire_monitor is not None:
            self._wire_monitor.on_wire_setup_sent(wire_key)

        return True

    def disconnect_wire(self, wire_key: str) -> bool:
        """Удалить wire по ключу.

        Ищет wire в topology, формирует teardown-команду
        и уведомляет wire_monitor.

        Returns:
            True если команда отправлена, False если wire не найден.
        """
        wire = self._find_wire(wire_key)
        if wire is None:
            logger.warning("TopologyBridge.disconnect_wire: wire '%s' не найден", wire_key)
            return False

        source = wire.get("source", "")
        target = wire.get("target", "")
        source_process = source.split(".")[0]
        target_process = target.split(".")[0]

        cmd = build_wire_teardown(wire_key, source_process, target_process)
        self._sender.send_system_command(cmd)

        # Уведомить монитор
        if self._wire_monitor is not None:
            self._wire_monitor.on_wire_teardown_sent(wire_key)

        return True

    def apply_topology_diff(
        self,
        old_topology: dict[str, Any],
        new_topology: dict[str, Any],
    ) -> TopologyApplyResult:
        """Применить diff между двумя topology.

        ПОРЯДОК КРИТИЧЕН:
        1. Отключить wire'ы удалённых процессов
        2. Отключить wire'ы из removed_wires
        3. Удалить процессы
        4. Добавить процессы
        5. Подключить новые wire'ы
        6. Обновить конфиги изменённых процессов

        Returns:
            TopologyApplyResult с деталями и ошибками.
        """
        if self._applying:
            return TopologyApplyResult(errors=["apply_topology_diff уже выполняется (re-entrant guard)"])

        self._applying = True
        result = TopologyApplyResult()

        try:
            diff = compute_diff(old_topology, new_topology)

            if not diff.has_changes:
                return result

            # 1. Отключить wire'ы удалённых процессов
            for pdiff in diff.removed_processes:
                try:
                    process_wires = self._find_process_wires(pdiff.process_name)
                    for wire in process_wires:
                        wk = f"{wire.get('source', '')}|{wire.get('target', '')}"
                        self.disconnect_wire(wk)
                except Exception as exc:
                    result.errors.append(f"Ошибка отключения wire'ов процесса '{pdiff.process_name}': {exc}")

            # 2. Отключить wire'ы из removed_wires
            for wdiff in diff.removed_wires:
                try:
                    self.disconnect_wire(wdiff.wire_key)
                    result.wires_removed.append(wdiff.wire_key)
                except Exception as exc:
                    result.errors.append(f"Ошибка отключения wire '{wdiff.wire_key}': {exc}")

            # 3. Удалить процессы
            for pdiff in diff.removed_processes:
                try:
                    # Прямая отправка — wire'ы уже отключены на шаге 1
                    cmd = build_hot_remove_process(pdiff.process_name)
                    self._sender.send_system_command(cmd)
                    result.processes_removed.append(pdiff.process_name)
                except Exception as exc:
                    result.errors.append(f"Ошибка удаления процесса '{pdiff.process_name}': {exc}")

            # 4. Добавить процессы
            for pdiff in diff.added_processes:
                try:
                    new_cfg = pdiff.new_config or {}
                    plugin_name = new_cfg.get("plugin_name", pdiff.process_name)
                    plugin_config = new_cfg.get("plugin_config")
                    cmd = build_hot_add_process(pdiff.process_name, plugin_name, plugin_config)
                    self._sender.send_system_command(cmd)
                    result.processes_added.append(pdiff.process_name)
                except Exception as exc:
                    result.errors.append(f"Ошибка добавления процесса '{pdiff.process_name}': {exc}")

            # 5. Подключить новые wire'ы
            for wdiff in diff.added_wires:
                try:
                    new_cfg = wdiff.new_config or {}
                    source = new_cfg.get("source", "")
                    target = new_cfg.get("target", "")
                    transport = new_cfg.get("transport", "router")
                    self.connect_wire(wdiff.wire_key, source, target, transport=transport)
                    result.wires_added.append(wdiff.wire_key)
                except Exception as exc:
                    result.errors.append(f"Ошибка подключения wire '{wdiff.wire_key}': {exc}")

            # 6. Обновить конфиги изменённых процессов через on_field_set
            for pdiff in diff.modified_processes:
                try:
                    new_cfg = pdiff.new_config or {}
                    plugin_name = new_cfg.get("plugin_name", pdiff.process_name)
                    plugin_config = new_cfg.get("plugin_config", {})
                    if isinstance(plugin_config, dict):
                        for fld_name, value in plugin_config.items():
                            self.on_field_set(plugin_name, fld_name, value)
                    result.configs_updated.append(pdiff.process_name)
                except Exception as exc:
                    result.errors.append(f"Ошибка обновления конфига '{pdiff.process_name}': {exc}")

        finally:
            self._applying = False

        return result

    def get_capabilities(self) -> dict[str, bool]:
        """Вернуть возможности bridge.

        Позволяет GUI узнать какие операции поддерживаются.
        """
        return {
            "field_set": True,
            "hot_add": True,
            "wire": True,
            "diff_apply": True,
        }

    # --- Wire helpers ---

    def _find_process_wires(self, process_name: str) -> list[dict[str, Any]]:
        """Найти wire'ы где source или target начинается с process_name.

        Проверяет что source/target именно начинается с process_name
        и за ним идёт точка (чтобы 'cam' не матчил 'camera_0').
        """
        prefix = f"{process_name}."
        result: list[dict[str, Any]] = []
        for wire in self._holder.topology.get("wires", []):
            source = wire.get("source", "")
            target = wire.get("target", "")
            if source.startswith(prefix) or target.startswith(prefix):
                result.append(wire)
        return result

    def _find_wire(self, wire_key: str) -> dict[str, Any] | None:
        """Найти wire по ключу формата 'source|target'.

        Ключ формируется как f"{source}|{target}" из полей wire.
        """
        for wire in self._holder.topology.get("wires", []):
            source = wire.get("source", "")
            target = wire.get("target", "")
            key = f"{source}|{target}"
            if key == wire_key:
                return wire
        return None

    # --- Properties ---

    @property
    def is_connected(self) -> bool:
        """Есть ли живое IPC-соединение."""
        return self._connected
