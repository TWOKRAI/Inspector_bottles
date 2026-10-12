"""Таблицы стражей жизненного цикла и общие помощники (G2, G6, G10).

Только stdlib. Таблицы — литералы: их правят руками и видят в диффе. Содержимое
PUBLISHERS и ALLOWLIST скопировано один в один из
``plans/2026-10-03_lifecycle-owner-scope/tasks/0.5a.{publishers,allowlist}.tsv``
(замер лида 2026-10-11 на 4381fe9d4); ничего не выведено и не добавлено.
Правлено в 1.1: четыре записи стопа детей PM удалены, причины «FROZEN Ф1» переписаны.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    guard: str
    rule: str
    path: str
    line: int
    message: str


@dataclass(frozen=True)
class Publisher:
    path: str
    qualname: str
    status: str  # migrated | pending:<фаза> | exempt:<причина>


@dataclass(frozen=True)
class AllowEntry:
    count: int
    reason: str


# ---------------------------------------------------------------------------
# Общий перечень файлов
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]

# Каталог с таким именем на любом уровне пути — не производственный код.
NON_PRODUCTION_DIRS = frozenset({"tests", "testing", "scripts", ".claude", "docs", "plans", "workspace", "examples"})
# Корневые префиксы, не производственные (каталоги tools/ внутри модулей — производственные).
NON_PRODUCTION_ROOT_PREFIXES = ("backend_ctl/probes/", "robot/", "tools/")
_SKIPPED_WALK_DIRS = frozenset({".venv", "__pycache__", "node_modules"})


def _git_listed(root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    return [p for p in proc.stdout.decode("utf-8").split("\0") if p]


def _walked(root: Path) -> list[str]:
    result = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if _SKIPPED_WALK_DIRS.intersection(rel.parts):
            continue
        result.append(rel.as_posix())
    return sorted(result)


def list_py_files(root: Path) -> list[str]:
    """Относительные пути (с ``/``) всех .py. ``.git`` в worktree — файл, поэтому ``exists()``."""
    if (root / ".git").exists():
        names = _git_listed(root)
    else:
        names = _walked(root)
    return [n for n in names if (root / n).is_file()]


def is_production(rel: str) -> bool:
    if rel.startswith(NON_PRODUCTION_ROOT_PREFIXES):
        return False
    parts = rel.split("/")
    if NON_PRODUCTION_DIRS.intersection(parts[:-1]):
        return False
    name = parts[-1]
    return not (name.startswith("test_") or name == "conftest.py")


def production_files(root: Path) -> Iterator[tuple[str, str]]:
    """(относительный путь, текст) каждого производственного .py."""
    for rel in list_py_files(root):
        if is_production(rel):
            yield rel, (root / rel).read_text(encoding="utf-8-sig", errors="replace")


# ---------------------------------------------------------------------------
# G10: потолок обёрток совместимости
# ---------------------------------------------------------------------------

# путь -> разрешённое число маркеров ``lifecycle-shim:``; сумма значений <= 1 всегда.
SHIMS: dict[str, int] = {"Plugins/io/otel_export/plugin.py": 1}

# ---------------------------------------------------------------------------
# G2: издатели (путь, Класс.метод, статус) — migrated 1, pending:* 41, exempt:* 10
# ---------------------------------------------------------------------------

PUBLISHERS: list[Publisher] = [
    Publisher("backend_ctl/events.py", "EventHub.subscribe", "pending:Ф3"),
    Publisher("backend_ctl/events.py", "_EventChannelMixin.subscribe", "pending:Ф3"),
    Publisher("backend_ctl/interfaces.py", "IEventSource.subscribe", "pending:Ф3"),
    Publisher("multiprocess_framework/modules/actions_module/bus.py", "ActionBus.register_handler", "pending:Ф3"),
    Publisher(
        "multiprocess_framework/modules/actions_module/bus.py", "ActionBus.add_post_execute_callback", "pending:Ф3"
    ),
    Publisher("multiprocess_framework/modules/actions_module/bus.py", "ActionBus.add_change_callback", "pending:Ф3"),
    Publisher(
        "multiprocess_framework/modules/channel_routing_module/core/channel_routing_manager.py",
        "ChannelRoutingManager.add_tap",
        "pending:Ф3",
    ),
    Publisher("multiprocess_framework/modules/config_module/core/config.py", "Config.subscribe", "pending:Ф3"),
    Publisher("multiprocess_framework/modules/config_module/interfaces.py", "IConfig.subscribe", "pending:Ф3"),
    Publisher(
        "multiprocess_framework/modules/dispatch_module/core/base_dispatcher.py",
        "BaseDispatcher.register_handler",
        "exempt:таблица обработчиков диспетчера, жизнь равна процессу, в DESIGN §2.6 не названа (решение лида)",
    ),
    Publisher(
        "multiprocess_framework/modules/dispatch_module/core/dispatcher.py",
        "Dispatcher.register_handler",
        "exempt:таблица обработчиков диспетчера, жизнь равна процессу, в DESIGN §2.6 не названа (решение лида)",
    ),
    Publisher(
        "multiprocess_framework/modules/dispatch_module/interfaces.py",
        "IDispatcher.register_handler",
        "exempt:таблица обработчиков диспетчера, жизнь равна процессу, в DESIGN §2.6 не названа (решение лида)",
    ),
    Publisher(
        "multiprocess_framework/modules/dispatch_module/strategies/base_strategy.py",
        "BaseStrategy.register_handler",
        "exempt:таблица обработчиков диспетчера, жизнь равна процессу, в DESIGN §2.6 не названа (решение лида)",
    ),
    Publisher(
        "multiprocess_framework/modules/dispatch_module/strategies/chain_match.py",
        "ChainMatchStrategy.register_handler",
        "exempt:таблица обработчиков диспетчера, жизнь равна процессу, в DESIGN §2.6 не названа (решение лида)",
    ),
    Publisher(
        "multiprocess_framework/modules/dispatch_module/strategies/exact_match.py",
        "ExactMatchStrategy.register_handler",
        "exempt:таблица обработчиков диспетчера, жизнь равна процессу, в DESIGN §2.6 не названа (решение лида)",
    ),
    Publisher(
        "multiprocess_framework/modules/dispatch_module/strategies/fallback_match.py",
        "FallbackMatchStrategy.register_handler",
        "exempt:таблица обработчиков диспетчера, жизнь равна процессу, в DESIGN §2.6 не названа (решение лида)",
    ),
    Publisher(
        "multiprocess_framework/modules/dispatch_module/strategies/pattern_match.py",
        "PatternMatchStrategy.register_handler",
        "exempt:таблица обработчиков диспетчера, жизнь равна процессу, в DESIGN §2.6 не названа (решение лида)",
    ),
    Publisher(
        "multiprocess_framework/modules/display_module/interfaces.py",
        "IDisplayChannel.subscribe",
        "exempt:каталог входов дисплея по consumer_id, удалённый реестр (DESIGN §2.6)",
    ),
    Publisher("multiprocess_framework/modules/event_module/event_bus.py", "EventBus.subscribe", "pending:Ф3"),
    Publisher("multiprocess_framework/modules/event_module/interfaces.py", "EventBusProtocol.subscribe", "pending:Ф3"),
    Publisher(
        "multiprocess_framework/modules/frontend_module/bridge/remote_frame_source.py",
        "RemoteFrameSource.subscribe",
        "pending:мегаплан-GUI",
    ),
    Publisher(
        "multiprocess_framework/modules/frontend_module/bridge/remote_state_proxy.py",
        "_ClientRouter.register_message_handler",
        "pending:мегаплан-GUI",
    ),
    Publisher(
        "multiprocess_framework/modules/frontend_module/bridge/remote_state_proxy.py",
        "RemoteStateProxy.subscribe",
        "pending:мегаплан-GUI",
    ),
    Publisher(
        "multiprocess_framework/modules/frontend_module/components/base/infrastructure/register_adapter.py",
        "RegisterAdapter.subscribe",
        "pending:мегаплан-GUI",
    ),
    Publisher(
        "multiprocess_framework/modules/frontend_module/components/base/interfaces.py",
        "IRegisterPort.subscribe",
        "pending:мегаплан-GUI",
    ),
    Publisher(
        "multiprocess_framework/modules/frontend_module/components/base/traits/sync_trait.py",
        "SyncTrait.subscribe",
        "pending:мегаплан-GUI",
    ),
    Publisher(
        "multiprocess_framework/modules/frontend_module/core/registers_bridge.py",
        "FrontendRegistersBridge.subscribe",
        "pending:мегаплан-GUI",
    ),
    Publisher(
        "multiprocess_framework/modules/frontend_module/qt_event_bridge.py",
        "QtEventBus.subscribe",
        "pending:мегаплан-GUI",
    ),
    Publisher(
        "multiprocess_framework/modules/frontend_module/widgets/entity_editor/base_editor_model.py",
        "BaseEditorModel.add_change_callback",
        "pending:мегаплан-GUI",
    ),
    Publisher(
        "multiprocess_framework/modules/frontend_module/widgets/tabs/tab_layout_protocol.py",
        "UndoRedoController.add_change_callback",
        "pending:мегаплан-GUI",
    ),
    Publisher(
        "multiprocess_framework/modules/process_module/plugins/interfaces.py",
        "IPluginRouter.register_message_handler",
        "pending:Ф3",
    ),
    Publisher(
        "multiprocess_framework/modules/registers_module/core/manager.py", "RegistersManager.subscribe", "pending:Ф3"
    ),
    Publisher(
        "multiprocess_framework/modules/registers_module/interfaces.py", "IRegistersManager.subscribe", "pending:Ф3"
    ),
    Publisher(
        "multiprocess_framework/modules/router_module/adapters/router_adapter.py",
        "RouterAdapter.add_callback",
        "pending:Ф3",
    ),
    Publisher(
        "multiprocess_framework/modules/router_module/channels/socket_client.py",
        "SocketClient.add_push_listener",
        "pending:Ф3",
    ),
    Publisher(
        "multiprocess_framework/modules/router_module/core/_receiver.py", "AsyncReceiver.add_callback", "pending:Ф3"
    ),
    Publisher(
        "multiprocess_framework/modules/router_module/core/router_manager.py",
        "RouterManager.register_message_handler",
        "pending:Ф3",
    ),
    Publisher(
        "multiprocess_framework/modules/router_module/interfaces.py",
        "IRouterManager.register_message_handler",
        "pending:Ф3",
    ),
    Publisher(
        "multiprocess_framework/modules/shared_resources_module/events/core/manager.py",
        "EventManager.subscribe",
        "pending:Ф3",
    ),
    Publisher(
        "multiprocess_framework/modules/shared_resources_module/events/interfaces.py",
        "IEventManager.subscribe",
        "pending:Ф3",
    ),
    Publisher(
        "multiprocess_framework/modules/state_store_module/core/subscription_manager.py",
        "SubscriptionManager.subscribe",
        "exempt:удалённый реестр по sub_id подписчика (DESIGN §2.6)",
    ),
    Publisher(
        "multiprocess_framework/modules/state_store_module/interfaces.py",
        "IRouter.register_message_handler",
        "pending:Ф3",
    ),
    Publisher("multiprocess_framework/modules/state_store_module/interfaces.py", "IStateProxy.subscribe", "pending:Ф3"),
    Publisher(
        "multiprocess_framework/modules/state_store_module/proxy/state_proxy.py", "StateProxy.subscribe", "pending:Ф3"
    ),
    Publisher(
        "multiprocess_prototype/adapters/dispatch/command_dispatcher.py",
        "CommandDispatcherOrchestrator.add_change_callback",
        "pending:мегаплан-GUI",
    ),
    Publisher(
        "multiprocess_prototype/adapters/stores/config_store.py", "ConfigStoreFromManager.subscribe", "pending:Ф3"
    ),
    Publisher(
        "multiprocess_prototype/backend/state/adapters/camera_state_adapter.py",
        "CameraStateAdapter.add_callback",
        "pending:Ф3",
    ),
    Publisher(
        "multiprocess_prototype/domain/protocols/command_dispatcher.py",
        "CommandDispatcher.add_change_callback",
        "pending:мегаплан-GUI",
    ),
    Publisher("multiprocess_prototype/domain/protocols/config_store.py", "ConfigStore.subscribe", "pending:Ф3"),
    Publisher(
        "multiprocess_prototype/domain/topology_session.py",
        "TopologySession.add_change_callback",
        "pending:мегаплан-GUI",
    ),
    Publisher(
        "multiprocess_prototype/frontend/widgets/displays/preview_window.py",
        "PreviewWindow.subscribe",
        "pending:мегаплан-GUI",
    ),
    Publisher("multiprocess_framework/modules/event_module/subscribers.py", "Subscribers.add", "migrated"),
]

# ---------------------------------------------------------------------------
# G6: храповик — (правило, путь) -> разрешённое число нарушений и причина.
# Запись только УМЕНЬШАЕТСЯ; новая запись — решение владельца, не правка кода.
# ---------------------------------------------------------------------------

ALLOWLIST: dict[tuple[str, str], AllowEntry] = {
    ("R1", "Plugins/runtime/chain_executor/plugin.py"): AllowEntry(1, "FROZEN Ф4 (ждёт потребителя)"),
    ("R1", "Plugins/runtime/worker_pool/plugin.py"): AllowEntry(2, "FROZEN Ф4 (ждёт потребителя)"),
    ("R1", "Plugins/sim/mjpeg_sink/plugin.py"): AllowEntry(1, "FROZEN Ф4 (ждёт потребителя)"),
    ("R1", "Plugins/sim/pult_web/plugin.py"): AllowEntry(1, "FROZEN Ф4 (ждёт потребителя)"),
    ("R1", "Plugins/sim/robot_host/plugin.py"): AllowEntry(1, "FROZEN Ф4 (ждёт потребителя)"),
    ("R1", "Services/auth/audit_writer.py"): AllowEntry(1, "FROZEN Ф4 (ждёт потребителя)"),
    ("R1", "Services/code_reader/core/sdk_reader.py"): AllowEntry(1, "FROZEN Ф4 (ждёт потребителя)"),
    ("R1", "Services/code_reader/core/sink.py"): AllowEntry(2, "FROZEN Ф4 (ждёт потребителя)"),
    ("R1", "Services/code_reader/tools/id3000_tcp_sink.py"): AllowEntry(1, "FROZEN Ф4 (ждёт потребителя)"),
    ("R1", "Services/code_reader/tools/reader_sim.py"): AllowEntry(1, "FROZEN Ф4 (ждёт потребителя)"),
    ("R1", "Services/phone_gateway/gateway.py"): AllowEntry(1, "FROZEN Ф4 (ждёт потребителя)"),
    ("R1", "Services/robot_comm/server/sim_robot.py"): AllowEntry(2, "FROZEN Ф4 (ждёт потребителя)"),
    ("R1", "Services/sql/action_log/log_writer.py"): AllowEntry(1, "FROZEN Ф4 (ждёт потребителя)"),
    ("R2", "Services/robot_comm/gui/sim_view.py"): AllowEntry(1, "мегаплан GUI"),
    ("R2", "multiprocess_framework/modules/frontend_module/bridge/command_sender.py"): AllowEntry(1, "мегаплан GUI"),
    ("R2", "multiprocess_framework/modules/frontend_module/bridge/wire_monitor.py"): AllowEntry(1, "мегаплан GUI"),
    ("R2", "multiprocess_framework/modules/frontend_module/components/base/traits/debounce_trait.py"): AllowEntry(
        1, "мегаплан GUI"
    ),
    ("R2", "multiprocess_prototype/frontend/app.py"): AllowEntry(2, "мегаплан GUI"),
    ("R2", "multiprocess_prototype/frontend/widgets/tabs/pipeline/layout_controller.py"): AllowEntry(1, "мегаплан GUI"),
    ("R2", "multiprocess_prototype/frontend/widgets/tabs/services/robot/controller.py"): AllowEntry(1, "мегаплан GUI"),
    ("R2", "multiprocess_prototype/frontend/widgets/tabs/services/vfd/controller.py"): AllowEntry(1, "мегаплан GUI"),
    ("R3", "Plugins/sim/mjpeg_sink/plugin.py"): AllowEntry(1, "FROZEN Ф4 (ждёт потребителя)"),
    ("R3", "Plugins/sim/pult_web/plugin.py"): AllowEntry(1, "FROZEN Ф4 (ждёт потребителя)"),
    ("R3", "Services/auth/audit_writer.py"): AllowEntry(1, "FROZEN Ф4 (ждёт потребителя)"),
    ("R3", "Services/code_reader/tools/reader_sim.py"): AllowEntry(1, "FROZEN Ф4 (ждёт потребителя)"),
    ("R3", "Services/phone_gateway/gateway.py"): AllowEntry(1, "FROZEN Ф4 (ждёт потребителя)"),
    ("R3", "Services/robot_comm/server/sim_robot.py"): AllowEntry(1, "FROZEN Ф4 (ждёт потребителя)"),
    ("R3", "backend_ctl/recorder.py"): AllowEntry(1, "FROZEN Ф4 (ждёт потребителя)"),
    ("R3", "multiprocess_framework/modules/channel_routing_module/buffers/async_sender_buffer.py"): AllowEntry(
        1, "Ф4: join(N) и terminate вне стопа детей PM → stop_budget"
    ),
    ("R3", "multiprocess_framework/modules/config_module/tools/watcher.py"): AllowEntry(
        2, "Ф4: join(N) и terminate вне стопа детей PM → stop_budget"
    ),
    ("R3", "multiprocess_framework/modules/console_module/core/console_manager.py"): AllowEntry(
        1, "Ф4: join(N) и terminate вне стопа детей PM → stop_budget"
    ),
    ("R3", "multiprocess_framework/modules/logger_module/core/logger_core.py"): AllowEntry(
        1, "Ф4: join(N) и terminate вне стопа детей PM → stop_budget"
    ),
    ("R3", "multiprocess_framework/modules/process_manager_module/launcher/spawner.py"): AllowEntry(
        1, "остаётся после 1.1: цепочка стопа самого PM / цикл Ctrl+C / добой по PID — вне группы детей (О4)"
    ),
    ("R3", "multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py"): AllowEntry(
        1, "остаётся после 1.1: цепочка стопа самого PM / цикл Ctrl+C / добой по PID — вне группы детей (О4)"
    ),
    ("R3", "multiprocess_framework/modules/router_module/channels/queue_channel.py"): AllowEntry(
        1, "Ф4: join(N) и terminate вне стопа детей PM → stop_budget"
    ),
    ("R3", "multiprocess_framework/modules/router_module/channels/socket_channel.py"): AllowEntry(
        1, "Ф4: join(N) и terminate вне стопа детей PM → stop_budget"
    ),
    ("R3", "multiprocess_framework/modules/router_module/channels/socket_client.py"): AllowEntry(
        1, "Ф4: join(N) и terminate вне стопа детей PM → stop_budget"
    ),
    ("R3", "multiprocess_framework/modules/statistics_module/core/aggregation_window.py"): AllowEntry(
        1, "Ф4: join(N) и terminate вне стопа детей PM → stop_budget"
    ),
    ("R4", "Services/hikvision_camera/plugin/plugin.py"): AllowEntry(2, "FROZEN Ф4 (ждёт потребителя)"),
    ("R4", "backend_ctl/harness.py"): AllowEntry(3, "дерево процессов ОС (ProcessTreeGuard, П4 stop-ownership)"),
    ("R4", "multiprocess_framework/modules/console_module/platforms/unix.py"): AllowEntry(
        1, "Ф4: join(N) и terminate вне стопа детей PM → stop_budget"
    ),
    ("R4", "multiprocess_framework/modules/console_module/platforms/windows.py"): AllowEntry(
        1, "Ф4: join(N) и terminate вне стопа детей PM → stop_budget"
    ),
    ("R4", "multiprocess_framework/modules/frontend_module/application/thread_manager.py"): AllowEntry(
        1, "мегаплан GUI"
    ),
    ("R4", "multiprocess_framework/modules/process_manager_module/launcher/pid_registry.py"): AllowEntry(
        1, "остаётся после 1.1: цепочка стопа самого PM / цикл Ctrl+C / добой по PID — вне группы детей (О4)"
    ),
    ("R4", "multiprocess_framework/modules/process_manager_module/launcher/process_tree_guard.py"): AllowEntry(
        3, "дерево процессов ОС (ProcessTreeGuard, П4 stop-ownership)"
    ),
    ("R4", "multiprocess_framework/modules/process_manager_module/launcher/spawner.py"): AllowEntry(
        2, "остаётся после 1.1: цепочка стопа самого PM / цикл Ctrl+C / добой по PID — вне группы детей (О4)"
    ),
    ("R4", "multiprocess_prototype/frontend/widgets/tabs/services/neural/ml_train_section.py"): AllowEntry(
        1, "мегаплан GUI"
    ),
    ("R6", "multiprocess_framework/modules/frontend_module/core/window_registry.py"): AllowEntry(1, "мегаплан GUI"),
    ("R6", "multiprocess_framework/modules/frontend_module/tabs/lazy_tab.py"): AllowEntry(1, "мегаплан GUI"),
    ("R6", "multiprocess_framework/modules/frontend_module/widgets/chrome/side_panels/collapsible.py"): AllowEntry(
        1, "мегаплан GUI"
    ),
    ("R6", "multiprocess_framework/modules/frontend_module/widgets/keyboard/keyboard.py"): AllowEntry(
        1, "мегаплан GUI"
    ),
    ("R6", "multiprocess_framework/modules/frontend_module/widgets/tabs/base_list_nav_tab.py"): AllowEntry(
        1, "мегаплан GUI"
    ),
    ("R6", "multiprocess_framework/modules/frontend_module/widgets/tabs/tab_layouts/diff_scroll_layout.py"): AllowEntry(
        1, "мегаплан GUI"
    ),
    ("R6", "multiprocess_framework/modules/frontend_module/widgets/tabs/tab_layouts/standard_layout.py"): AllowEntry(
        2, "мегаплан GUI"
    ),
    ("R6", "multiprocess_prototype/frontend/widgets/chrome/error_banner.py"): AllowEntry(1, "мегаплан GUI"),
    ("R6", "multiprocess_prototype/frontend/widgets/image_panel/widget.py"): AllowEntry(1, "мегаплан GUI"),
    ("R6", "multiprocess_prototype/frontend/widgets/primitives/sectioned_form.py"): AllowEntry(1, "мегаплан GUI"),
    ("R6", "multiprocess_prototype/frontend/widgets/primitives/side_nav_layout.py"): AllowEntry(1, "мегаплан GUI"),
    ("R6", "multiprocess_prototype/frontend/widgets/tabs/displays/tab.py"): AllowEntry(1, "мегаплан GUI"),
    ("R6", "multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/exec_info_section.py"): AllowEntry(
        1, "мегаплан GUI"
    ),
    ("R6", "multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/params_form_section.py"): AllowEntry(
        1, "мегаплан GUI"
    ),
    ("R6", "multiprocess_prototype/frontend/widgets/tabs/processes/tab.py"): AllowEntry(1, "мегаплан GUI"),
    ("R6", "multiprocess_prototype/frontend/widgets/tabs/recipes/tab.py"): AllowEntry(1, "мегаплан GUI"),
    ("R6", "multiprocess_prototype/frontend/widgets/tabs/services/control_panel/widget.py"): AllowEntry(
        1, "мегаплан GUI"
    ),
    ("R6", "multiprocess_prototype/frontend/widgets/tabs/services/devices_common/master_detail.py"): AllowEntry(
        2, "мегаплан GUI"
    ),
    ("R6", "multiprocess_prototype/frontend/widgets/tabs/services/neural/dataset_gen_section.py"): AllowEntry(
        1, "мегаплан GUI"
    ),
    ("R6", "multiprocess_prototype/frontend/windows/main_window.py"): AllowEntry(1, "мегаплан GUI"),
}
