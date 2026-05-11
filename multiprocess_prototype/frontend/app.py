"""app.py — запуск Qt event loop для GuiProcess."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .app_context import build_app_context
from .windows.main_window import MainWindow
from .widgets.image_panel import ImagePanelWidget
from .tab_factory import TabFactory
from .styles.theme_loader import apply_default_theme

if TYPE_CHECKING:
    from .process import GuiProcess

# Vocabulary плагинов на уровне проекта: Plugins/ (перенесено в Phase 5)
_PLUGINS_DIR = Path(__file__).resolve().parents[2] / "Plugins"


def run_gui(process: "GuiProcess") -> None:
    """Создать QApplication и запустить Qt event loop."""
    app = QApplication.instance() or QApplication(sys.argv)

    # 1. Применить тему
    apply_default_theme(app)

    # 2. Сканировать плагины и построить RegistersManagerV2
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
    from multiprocess_prototype.registers.manager import RegistersManagerV2

    try:
        PluginRegistry.discover(str(_PLUGINS_DIR))
    except Exception as e:
        process._log_warning(f"Не удалось обнаружить плагины: {e}", module="startup")

    registers_manager = RegistersManagerV2.from_registry(PluginRegistry)

    # 3. Создать AppContext
    ctx = build_app_context(
        process,
        plugin_registry=PluginRegistry,
        registers_manager=registers_manager,
    )

    # 3a. Загрузить topology для GUI и создать TopologyHolder
    import yaml as _yaml
    from multiprocess_prototype.main import DEFAULT_BLUEPRINT
    from .topology_holder import TopologyHolder

    try:
        _topology_dict = _yaml.safe_load(DEFAULT_BLUEPRINT.read_text(encoding="utf-8"))
    except Exception as e:
        process._log_warning(f"Не удалось загрузить topology: {e}", module="startup")
        _topology_dict = {}

    topology_holder = TopologyHolder(_topology_dict)
    ctx.extras["topology_holder"] = topology_holder
    ctx.extras["topology"] = _topology_dict  # обратная совместимость

    # 3a.1. Startup validation
    from .startup_checks import StartupChecker

    _checker = StartupChecker()
    _report = _checker.check_all(_topology_dict, registry=PluginRegistry)

    if _report.warnings:
        for w in _report.warnings:
            process._log_warning(w, module="startup")
    if _report.errors:
        for e in _report.errors:
            process._log_error(e, module="startup")
        process._track_error(
            RuntimeError(f"Startup: {len(_report.errors)} ошибок валидации"),
            context={"errors": _report.errors},
        )
        process._record_metric("startup.errors", len(_report.errors))

    # 3b. Создать GuiStateBindings — занимает слот bridge.set_state_callback
    #     (Phase 10B: табы обращаются через ctx.bindings().bind(...))
    from .state.bindings import GuiStateBindings
    bindings = GuiStateBindings(process._bridge)
    ctx.extras["bindings"] = bindings

    # 3c. Phase 12: CommandCatalog + CommandValidator + TopologyBridge
    from .bridge.command_catalog import CommandCatalog
    from .bridge.command_validator import CommandValidator
    from .bridge.topology_bridge import TopologyBridge
    from multiprocess_prototype.registers.connection_map import ConnectionMap

    connection_map = ConnectionMap.from_topology(_topology_dict)
    command_catalog = CommandCatalog.from_registry_and_map(PluginRegistry, connection_map)
    command_validator = CommandValidator(command_catalog, registers_manager)
    topology_bridge = TopologyBridge(
        command_sender=ctx.command_sender,
        command_catalog=command_catalog,
        command_validator=command_validator,
        registers_manager=registers_manager,
        topology_holder=topology_holder,
    )

    ctx.extras["command_catalog"] = command_catalog
    ctx.extras["topology_bridge"] = topology_bridge

    # Подписка: topology_holder.on_changed → bridge.on_topology_changed
    topology_holder.on_changed(topology_bridge.on_topology_changed)

    # Phase 12: мультиплексор state_callback → bindings + topology_bridge
    # GuiStateBindings уже занял set_state_callback. Теперь ставим обёртку,
    # которая вызывает и bindings, и bridge.on_state_delta.
    _original_state_cb = bindings._on_state_msg

    def _state_multiplexer(msg_dict: dict) -> None:
        _original_state_cb(msg_dict)
        if msg_dict.get("data_type") == "state_delta":
            path = msg_dict.get("path", "")
            value = msg_dict.get("value")
            if path:
                topology_bridge.on_state_delta(path, value)

    process._bridge.set_state_callback(_state_multiplexer)

    # 3e. Auth: инициализация AuthManager + AuthState (PR2 auth-rbac)
    import os
    from Services.auth import AuthManager, AuthConfig, YamlUserStorage
    from multiprocess_prototype.frontend.state.auth_state import AuthState

    _users_path = os.environ.get(
        "INSPECTOR_AUTH_USERS_PATH",
        str(Path.home() / ".inspector_bottles" / "auth" / "users.yaml"),
    )
    _auth_config = AuthConfig(users_path=_users_path)
    _storage = YamlUserStorage(_users_path)

    if not _storage.exists():
        # Bootstrap не запускался — показать блокирующий диалог и выйти
        from multiprocess_prototype.frontend.widgets.dialogs import StartupBlockingDialog

        _dlg = StartupBlockingDialog(
            "Хранилище пользователей не найдено.\n\n"
            "Запустите перед запуском приложения:\n"
            "    python -m Services.auth.bootstrap"
        )
        _dlg.exec()
        sys.exit(1)

    _auth_manager = AuthManager(_auth_config)
    try:
        _auth_manager.initialize()
    except Exception as exc:  # включая StorageCorrupted
        process._log_error(f"auth.init.failed: {exc}", module="startup")
        from multiprocess_prototype.frontend.widgets.dialogs import StartupBlockingDialog
        _dlg = StartupBlockingDialog(f"Ошибка инициализации Auth:\n\n{exc}")
        _dlg.exec()
        sys.exit(1)
    ctx.extras["auth_manager"] = _auth_manager

    _auth_state = AuthState()
    ctx.extras["auth_state"] = _auth_state

    # 3d. Создать ActionBus (Phase 11: undo/redo + Phase 12: bridge integration)
    from .actions.bus_factory import create_action_bus

    action_bus = create_action_bus(
        registers_manager,
        topology_holder,
        topology_bridge=topology_bridge,
        auth_state=_auth_state,
    )
    ctx.extras["action_bus"] = action_bus

    # 4. Создать MainWindow
    window = MainWindow()

    # Показать startup ошибки в StatusBar
    if not _report.ok:
        window.statusBar().showMessage(_report.summary(), 10000)

    # 4a. Привязать ActionBus shortcuts (Ctrl+Z / Ctrl+Y)
    window.set_action_bus(action_bus)

    # 4a1. Кнопка входа в header (зависит от auth_state и auth_manager)
    if ctx.auth_state() is not None and ctx.auth_manager() is not None:
        from .widgets.chrome.login_button import LoginButton
        _login_btn = LoginButton(ctx.auth_state(), ctx.auth_manager())
        window.header.set_login_button(_login_btn)

    # 4a2. Phase 12: StatusBar live bindings
    window.connect_bindings(bindings)

    # 4b. Создать и установить ImagePanel
    image_panel = ImagePanelWidget()
    window.set_image_panel(image_panel)

    # 5. Создать TabFactory и заполнить табы (Phase 10: все 7 табов)
    from .widgets.tabs import register_all_tabs
    tab_factory = TabFactory(ctx, custom_factories=register_all_tabs())
    tab_factory.create_tabs(window.tab_widget)

    # 6. Подключить bridge callbacks
    _setup_bridge_callbacks(process, image_panel, window)

    # 7. Запустить таймеры (fps, safety)
    _setup_timers(app, process, window)

    # 8. Сохранить ссылки в process
    process._window = window
    process._app_context = ctx

    window.show()
    app.exec()


def _setup_bridge_callbacks(
    process: "GuiProcess",
    image_panel: ImagePanelWidget,
    window: MainWindow,
) -> None:
    """Подключить bridge signals к виджетам."""
    _frame_trace_cnt = 0

    def _on_frame_received(msg_dict: dict) -> None:
        nonlocal _frame_trace_cnt
        _frame_trace_cnt += 1

        frame = msg_dict.get("frame")

        if _frame_trace_cnt % 30 == 1:
            process._log_info(
                f"[TRACE] _on_frame_received #{_frame_trace_cnt}: "
                f"has_frame={frame is not None}, "
                f"frame_shape={frame.shape if frame is not None and hasattr(frame, 'shape') else None}, "
                f"data_type={msg_dict.get('data_type', '?')}, "
                f"keys={list(msg_dict.keys())[:10]}",
                module="gui",
            )

        if frame is not None:
            image_panel.display_frame("main", frame)
            window.increment_frame_count()

    process._bridge.set_frame_callback(_on_frame_received)
    # State callback занят GuiStateBindings (создан в run_gui, Phase 10A)


def _setup_timers(
    app: QApplication,
    process: "GuiProcess",
    window: MainWindow,
) -> None:
    """FPS таймер + safety таймер."""
    # FPS таймер: раз в секунду
    fps_timer = QTimer()
    fps_timer.setInterval(1000)

    def _update_fps() -> None:
        count = window.reset_frame_count()
        window.update_status(fps=float(count))

    fps_timer.timeout.connect(_update_fps)
    fps_timer.start()

    # Safety таймер: проверяем флаг остановки
    safety_timer = QTimer()
    safety_timer.setInterval(1000)

    def _check_stop() -> None:
        if process.should_stop():
            app.quit()

    safety_timer.timeout.connect(_check_stop)
    safety_timer.start()

    # При выходе из Qt — сигнализируем процессу
    app.aboutToQuit.connect(lambda: setattr(process, '_stop_requested', True))

    # Сохранить ссылки на таймеры чтобы GC не убил их
    window._fps_timer = fps_timer
    window._safety_timer = safety_timer
