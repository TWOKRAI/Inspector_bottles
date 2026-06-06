"""app.py — запуск Qt event loop для GuiProcess."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from multiprocess_framework.modules.process_module.generic import frame_trace
from .auth_context import AuthContext
from .bridge.command_sender import CommandSender
from .windows.main_window import MainWindow
from .widgets.image_panel import ImagePanelWidget
from .tab_factory import TabFactory
from .styles.theme_loader import apply_default_theme

if TYPE_CHECKING:
    from .process import GuiProcess


def _resolve_dev_login_settings() -> tuple[bool, str, str]:
    """Получить (auto_login_enabled, username, password) из env и dev_settings.py.

    Приоритет: env-переменные → multiprocess_prototype/dev_settings.py → дефолты.

    Returns:
        (auto_login_enabled, username, password)
    """
    import os

    enabled_env = os.environ.get("INSPECTOR_AUTH_DEV_AUTO_LOGIN", "").strip().lower()
    password_env = os.environ.get("INSPECTOR_DEV_PASSWORD", "").strip()
    username_env = os.environ.get("INSPECTOR_DEV_USERNAME", "").strip()

    # dev_settings.py — опциональный локальный конфиг (в .gitignore)
    try:
        from multiprocess_prototype import dev_settings  # type: ignore[import-not-found]

        ds_enabled = bool(getattr(dev_settings, "DEV_AUTO_LOGIN", False))
        ds_username = str(getattr(dev_settings, "DEV_USERNAME", "dev"))
        ds_password = str(getattr(dev_settings, "DEV_PASSWORD", ""))
    except ImportError:
        ds_enabled, ds_username, ds_password = False, "dev", ""

    enabled = enabled_env in ("1", "true", "yes") if enabled_env else ds_enabled
    username = username_env or ds_username or "dev"
    password = password_env or ds_password
    return enabled, username, password


def run_gui(process: "GuiProcess") -> None:
    """Создать QApplication и запустить Qt event loop."""
    app = QApplication.instance() or QApplication(sys.argv)

    # qt-mcp probe — активируется только при QT_MCP_PROBE=1.
    # Слушает localhost:9142, видимо MCP-сервером qt-mcp для UI-интроспекции.
    # Прод-поведение не меняется без env-флага.
    import os

    if os.environ.get("QT_MCP_PROBE") == "1":
        try:
            from qt_mcp.probe import install

            install()
            process._log_info("qt-mcp probe installed on localhost:9142", module="startup")
        except ImportError:
            process._log_warning("qt-mcp probe requested but qt_mcp not installed", module="startup")

    # 1. Загрузить главный конфиг (манифест) и применить тему из него
    from multiprocess_prototype.backend.config.manifest import load_manifest
    from multiprocess_prototype.main import PROJECT_ROOT, resolve_manifest_path

    _manifest = load_manifest(resolve_manifest_path())
    apply_default_theme(app, _manifest.styles.active)

    # 2. Сканировать плагины и построить RegistersManager
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
    from multiprocess_framework.modules.registers_module import RegistersManager
    from multiprocess_prototype.backend.config.schemas import load_system_config

    _app_sys_config = load_system_config(_manifest.system)
    _app_plugin_paths = [
        str(PROJECT_ROOT / p) if not Path(p).is_absolute() else p
        for p in (_app_sys_config.discovery.plugin_paths if _app_sys_config.discovery.auto_discover else [])
    ]

    try:
        PluginRegistry.discover(*_app_plugin_paths)
    except Exception as e:
        process._log_warning(f"Не удалось обнаружить плагины: {e}", module="startup")

    # 2a. Создать PluginManager singleton (Phase 2.4)
    from multiprocess_framework.modules.process_module.plugins.manager import PluginManager

    _plugin_manager = PluginManager(
        registry=PluginRegistry,
        paths=_app_plugin_paths,
    )
    _plugin_manager.initialize()

    registers_manager = RegistersManager.from_registry(PluginRegistry)

    # 3. CommandSender для IPC. G.5.3: AppContext-контейнер удалён — зависимости
    # живут локальными переменными run_gui() (живы весь lifetime: app.exec() блокирует),
    # AppServices собирается из них через AppServicesDeps, runtime — через RuntimeDeps.
    command_sender = CommandSender(process)

    # 3-bis. ProcessManagerProxy — IPC-фасад управления живым ProcessManagerProcess
    # (Этап 1 pipeline-live-control). Тонкая обёртка над command_sender: шлёт
    # blueprint.replace / process.start|stop|restart через RouterManager в backend.
    # Прокидывается в табы Pipeline/Recipes через RuntimeDeps (runtime-layer, не
    # AppServices). Закрывает корневой блокер «proxy=None» (launch_active_recipe).
    from .bridge.process_manager_proxy import ProcessManagerProxy

    process_manager_proxy = ProcessManagerProxy(command_sender)

    # 3b-pre. Bootstrap ServiceRegistry + ServiceStateAdapter (Task 3.6 / Phase 3)
    #
    # Порядок критичен (Reviewer zone of concern):
    #   ServiceRegistry + discover() → AppServicesDeps.service_registry
    #   → ServiceStateAdapter.bind(state_proxy) → connect() → sync_domain_to_state()
    #
    # state_proxy создаётся позже (GuiStateBindings в шаге 3b), поэтому
    # здесь только registry + discover; adapter подключается после bindings.
    from multiprocess_framework.modules.service_module import ServiceRegistry, discover

    _service_registry = ServiceRegistry()
    _app_service_paths = [
        str(PROJECT_ROOT / p) if not Path(p).is_absolute() else p
        for p in (_app_sys_config.discovery.service_paths if _app_sys_config.discovery.auto_discover else [])
    ]

    try:
        _discovery_result = discover(*[Path(p) for p in _app_service_paths])
        process._log_info(
            f"service discovery: loaded={_discovery_result.loaded}, failed={_discovery_result.failed}",
            module="startup",
        )
    except Exception as e:
        process._log_warning(f"Не удалось выполнить service discovery: {e}", module="startup")

    # 3b-pre2. Preload DisplayRegistry из YAML до создания AppServices (Task C.1.5).
    #
    # Phase D adapter ожидает заполненный singleton. Без этого блока
    # services.displays.list_displays() вернёт пустой tuple до открытия DisplaysTab.
    # Idempotent: DisplayRegistry — singleton; повторный register() от DisplaysTab
    # будет отловлен через ValueError (дубликат) и проигнорирован.
    from multiprocess_framework.modules.display_module import DisplayRegistry as _DisplayRegistry
    from multiprocess_prototype.backend.config.displays_loader import (
        load_displays_config,
        displays_config_to_registry,
    )

    _displays_yaml_path = PROJECT_ROOT / "multiprocess_prototype" / "backend" / "config" / "displays.yaml"
    _display_registry = _DisplayRegistry()
    if _displays_yaml_path.exists():
        _displays_config = load_displays_config(_displays_yaml_path)
        displays_config_to_registry(_displays_config, _display_registry)
        process._log_info(
            f"display_registry: preloaded {len(_displays_config.displays)} дисплей(ов) из {_displays_yaml_path.name}",
            module="startup",
        )
    else:
        process._log_info(
            f"display_registry: {_displays_yaml_path.name} не найден — singleton инициализирован пустым",
            module="startup",
        )

    # 3a. Загрузить topology для GUI + создать EventBus и TopologyRepositoryStore (G.3).
    # Store владеет topology dict и публикует TopologyReplaced на каждую мутацию.
    # EventBus создаётся рано (QApplication уже есть, app.py:54) — на него подписываются
    # PipelinePresenter (scene reload) и TopologyBridge (cache). build_app_services получает
    # event_bus + topology_store через AppServicesDeps.
    import yaml as _yaml
    from multiprocess_prototype.adapters import TopologyRepositoryStore
    from .qt_event_bus import QtEventBus

    try:
        # Та же сборка, что грузит backend (фундамент ⊕ pipeline из общего манифеста)
        # — GUI-редактор показывает то же, что реально бежит.
        # unwrap_recipe обязателен: manifest.pipeline указывает на РЕЦЕПТ (вложенный
        # blueprint:), а без разворачивания GUI читает processes с верхнего уровня и
        # видит только base (Этап 1 pipeline-live-control: иначе «Перезапустить»
        # применял бы неполный граф и убивал живой pipeline). Зеркалит backend launch.
        from multiprocess_prototype.backend.launch import merge_topologies, unwrap_recipe

        _topology_dict = unwrap_recipe(_yaml.safe_load(_manifest.pipeline.read_text(encoding="utf-8")) or {})
        if _manifest.base:
            _base_dict = unwrap_recipe(_yaml.safe_load(_manifest.base.read_text(encoding="utf-8")) or {})
            _topology_dict = merge_topologies(_base_dict, _topology_dict)
    except Exception as e:
        process._log_warning(f"Не удалось загрузить topology: {e}", module="startup")
        _topology_dict = {}

    event_bus = QtEventBus()
    topology_store = TopologyRepositoryStore(_topology_dict, events=event_bus)

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
    #     (Phase 10B: табы получают bindings через RuntimeDeps.bindings)
    from .state.bindings import GuiStateBindings

    # cache_snapshot: replay закэшированного state при bind() (Task 4.1) —
    # ленивые вкладки сразу получают последний статус/метрики, не дожидаясь
    # следующей дельты (разовые status-дельты проходят до создания вкладки).
    _gui_proxy = getattr(process, "_gui_state_proxy", None)
    bindings = GuiStateBindings(
        process._bridge,
        cache_snapshot=(lambda: _gui_proxy.cache) if _gui_proxy is not None else None,
    )

    # 3c. Phase 12: CommandCatalog + CommandValidator + TopologyBridge
    from .bridge.command_catalog import CommandCatalog
    from .bridge.command_validator import CommandValidator
    from .bridge.topology_bridge import TopologyBridge
    from multiprocess_prototype.registers.connection_map import ConnectionMap

    connection_map = ConnectionMap.from_topology(_topology_dict)
    command_catalog = CommandCatalog.from_registry_and_map(PluginRegistry, connection_map)
    command_validator = CommandValidator(command_catalog, registers_manager)
    topology_bridge = TopologyBridge(
        command_sender=command_sender,
        command_catalog=command_catalog,
        command_validator=command_validator,
        registers_manager=registers_manager,
        topology_holder=topology_store,
    )

    # IPC cache-invalidation bridge подписывается на typed EventBus в блоке 3h.1
    # (ниже, после сборки app_services). Legacy holder.on_changed убран в G.1.2.

    # §11.15: topology_bridge подписывается на state ОТДЕЛЬНЫМ слушателем,
    # а не обёрткой-closure поверх set_state_callback. GuiStateBindings
    # держит первичный set_state_callback (занял его в 3b); здесь добавляем
    # второго подписчика через add_state_listener (multi-subscriber). Порядок
    # сохранён: сначала bindings (_state_cb), затем этот listener.
    def _forward_state_delta_to_topology(msg_dict: dict) -> None:
        if msg_dict.get("data_type") == "state_delta":
            path = msg_dict.get("path", "")
            value = msg_dict.get("value")
            if path:
                topology_bridge.on_state_delta(path, value)

    process._bridge.add_state_listener(_forward_state_delta_to_topology)

    # 3f. ServiceStateAdapter — подключить ПОСЛЕ bindings (proxy-aware step)
    # В GUI-процессе нет StateProxy (он живёт только в ProcessModule-процессах),
    # поэтому adapter создаётся с state_proxy=None → sync_domain_to_state() — no-op.
    # Это штатное поведение: ServiceStateAdapter.bind() будет вызван из
    # ProcessManagerProcess когда/если GUI получит proxy-доступ (Phase 6+).
    try:
        from multiprocess_prototype.backend.state.adapters.service_state_adapter import (
            ServiceStateAdapter,
        )

        _service_adapter = ServiceStateAdapter(
            registry=_service_registry,
            state_proxy=None,  # GUI-процесс не имеет StateProxy
        )
        # Попытка sync: не-op если proxy=None (adapter логирует warning)
        _service_adapter.sync_domain_to_state()
        process._log_info(
            "service_state_adapter: создан (proxy=None, sync no-op в GUI-процессе)",
            module="startup",
        )
    except Exception as e:
        process._log_warning(f"ServiceStateAdapter: не удалось создать: {e}", module="startup")

    # 3g. RecipeManager + RecipeStateAdapter (Task 5.8 wire-up)
    #
    # Порядок: RecipeEngine (framework) → RecipeManager (prototype) →
    #          RecipeStateAdapter → AppServicesDeps.recipe_manager.
    #
    # state_proxy = None в GUI-процессе (аналогично ServiceStateAdapter выше).
    # RecipeStateAdapter.connect() не вызывается без proxy — graceful degradation.
    #
    # RecipeEngine читает/пишет recipes_dir и вызывает migration_fn при load()
    # legacy-файлов (is_v1_recipe → True).
    _recipes_dir = PROJECT_ROOT / "multiprocess_prototype" / "recipes"
    _recipe_manager = None  # G.5.1: инициализируем до try — build_app_services fail-loud при None
    try:
        from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
        from multiprocess_framework.modules.state_store_module.recipes.recipe_engine import RecipeEngine
        from multiprocess_prototype.recipes.manager import RecipeManager
        from multiprocess_prototype.recipes.migrations.format_v1_to_v2 import (
            migrate_v1_to_v2,
            is_v1_recipe,
        )
        from multiprocess_prototype.backend.state.adapters.recipe_adapter import RecipeStateAdapter

        # Отдельный TreeStore для RecipeEngine в GUI-процессе.
        # GUI-процесс не имеет общего StateStoreManager, поэтому создаём
        # изолированный store — используется только для внутреннего snapshot/restore.
        _recipe_store = TreeStore()
        _recipe_engine = RecipeEngine(
            store=_recipe_store,
            recipes_dir=_recipes_dir,
            migration_fn=migrate_v1_to_v2,
            migration_check_fn=is_v1_recipe,
        )
        _recipe_manager = RecipeManager(
            engine=_recipe_engine,
            state_proxy=None,  # GUI-процесс не имеет StateProxy
            logger=None,
        )
        _recipe_adapter = RecipeStateAdapter(
            recipe_manager=_recipe_manager,
            state_proxy=None,  # no-op без proxy
        )
        # sync_domain_to_state — no-op если proxy=None (adapter логирует warning)
        _recipe_adapter.sync_domain_to_state()

        # Restore активного рецепта: манифест (app.yaml → pipeline) указывает на
        # бутовый рецепт — он же «последний активный» (persist пишет pipeline при
        # активации). set_active помечает его в движке, чтобы GUI (Pipeline/Recipes)
        # знал текущий рецепт сразу после старта, без ручной активации. Зовём
        # менеджер напрямую (не через presenter) — не зависит от UI-пути активации.
        try:
            _boot_slug = _manifest.pipeline.stem
            if _recipe_manager.set_active(_boot_slug):
                process._log_info(
                    f"recipe_manager: активный рецепт восстановлен из манифеста: '{_boot_slug}'",
                    module="startup",
                )
            else:
                process._log_warning(
                    f"recipe_manager: рецепт из манифеста не найден: '{_boot_slug}'",
                    module="startup",
                )
        except Exception as e:
            process._log_warning(f"recipe_manager: restore активного рецепта не удался: {e}", module="startup")

        process._log_info(
            f"recipe_manager: создан, recipes_dir={_recipes_dir}, доступно рецептов={len(_recipe_manager.list())}",
            module="startup",
        )
    except Exception as e:
        process._log_warning(f"RecipeManager: не удалось создать: {e}", module="startup")

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

    # Заполняем декларативный каталог permissions (tabs.*, users.*, roles.*).
    # Используется админ-панелью «Роли» и audit-трейлом (PR4).
    from .permissions import register_all_permissions

    register_all_permissions(_auth_manager.permissions)

    _auth_state = AuthState()

    # G.5.3: auth_ctx собирается напрямую из локалов (раньше — ctx.auth property).
    # audit_storage в GUI не инициализируется → audit=None (как было в ctx.auth).
    auth_ctx = AuthContext(manager=_auth_manager, state=_auth_state, audit=None)

    # 3c-bis. Dev-mode автологин.
    # Источники (по приоритету): env-переменные → multiprocess_prototype/dev_settings.py → дефолты.
    # Env используется в prod / CI; dev_settings.py — для локальной разработки
    # (файл в .gitignore, не попадает в репо). См. dev_settings.example.py.
    from multiprocess_framework.modules.frontend_module.managers.access_context import (
        AccessContext,
    )

    _dev_auto_login_enabled, _dev_username, _dev_password = _resolve_dev_login_settings()
    if _dev_auto_login_enabled and _dev_password:
        try:
            _result = _auth_manager.login(_dev_username, _dev_password)
            _auth_state.set_user(_result, AccessContext.from_dict(_result))
            process._log_info(f"auth.auto_login: {_dev_username}", module="startup")
        except Exception as exc:
            process._log_error(f"auth.auto_login.failed: {exc}", module="startup")
    elif _dev_password and not _dev_auto_login_enabled:
        process._log_info(
            "auth.auto_login.disabled: DEV_PASSWORD set, DEV_AUTO_LOGIN=False",
            module="startup",
        )
    elif _dev_auto_login_enabled and not _dev_password:
        process._log_warning(
            "auth.auto_login.no_password: DEV_AUTO_LOGIN=True, но DEV_PASSWORD пустой. "
            "Впиши пароль в multiprocess_prototype/dev_settings.py",
            module="startup",
        )

    # 3c-ter. Fallback: если автологин не дал access_context — показать
    # модальный LoginDialog при старте. Иначе TabFactory скроет все табы
    # (нет permissions) и UI будет пустым, что путает пользователя.
    if not _auth_state.is_authenticated:
        from .widgets.dialogs.login_dialog import LoginDialog

        _login_dlg = LoginDialog(_auth_manager, _auth_state)
        if _login_dlg.exec() != LoginDialog.DialogCode.Accepted:
            process._log_warning(
                "auth.startup_login.cancelled: пользователь закрыл LoginDialog без входа — все табы будут скрыты",
                module="startup",
            )

    # 3d. Создать legacy ActionBus.
    # G.4.4: глобальный undo/redo (Ctrl+Z/Y) переведён на domain CommandDispatcher
    # (см. window.set_undo_controller ниже). Эта legacy-шина БОЛЬШЕ не управляет
    # undo приложения; сохранена как инфраструктура ещё не мигрированных на domain
    # доменов (forms binding-aware write через FormContext, roles ROLE_UPDATE,
    # system-settings field-undo) — их перевод запланирован отдельными задачами
    # (Phase G+; удаление frontend/actions/ — отдельный cleanup, big-bang здесь запрещён).
    # G.5.3: после удаления ctx.extras прямых потребителей у шины нет (потребители
    # отложенных доменов появятся при их миграции) — биндим в `_legacy_action_bus`
    # (живёт весь lifetime: app.exec() блокирует) как retained-but-unbound infra.
    from .actions.bus_factory import create_action_bus

    _legacy_action_bus = create_action_bus(
        registers_manager,
        topology_store,
        topology_bridge=topology_bridge,
        auth_state=_auth_state,
        auth_manager=_auth_manager,
    )

    # 3h. Phase D (Task D.1): AppServices factory — собирает 10 adapter'ов
    # в типизированный DI-контейнер. G.5.1: фабрика принимает explicit
    # AppServicesDeps из локалов run_gui() (не ctx.extras) — coupling factory→AppContext снят.
    # Failure = sys.exit(1) с понятным логом (аналог startup-checks).
    from .app_services_factory import build_app_services, AppServicesDeps

    _services_deps = AppServicesDeps(
        event_bus=event_bus,
        topology_store=topology_store,
        plugin_registry=PluginRegistry,
        display_registry=_display_registry,
        service_registry=_service_registry,
        registers_manager=registers_manager,
        config={},
        recipe_manager=_recipe_manager,
        auth_state=_auth_state,
    )

    try:
        app_services = build_app_services(_services_deps)
    except Exception as exc:
        process._log_error(
            f"AppServices factory failed: {exc}",
            module="startup",
        )
        import traceback

        traceback.print_exc()
        sys.exit(1)

    # 3h.1. G.3: TopologyRepositoryStore сам публикует TopologyReplaced на каждую
    # мутацию (set_topology/save) — отдельный publisher-мост (G.1) больше не нужен.
    # PipelinePresenter подписывается на TopologyReplaced в своём __init__ (scene reload).
    # Здесь — единственная оставшаяся обвязка: TopologyBridge инвалидирует IPC-кэш.
    from multiprocess_prototype.domain.events import TopologyReplaced

    event_bus.subscribe(TopologyReplaced, lambda _e: topology_bridge.on_topology_changed())

    # 3h.2. G.4.3 (Y1) + Этап 2 pipeline-live-control: live field-write listener.
    # При dispatch(SetPluginConfig) или undo/redo field-config orchestrator публикует
    # PluginConfigChanged → listener (а) синхронизирует GUI-side RegistersManager
    # (виджеты) и (б) шлёт register_update IPC в живой процесс-владелец через
    # CommandSender → RouterManager → PluginOrchestrator._on_register_update.
    #
    # Этап 2: адрес плагина = имя регистра (= plugin_name), резолвится из editor-
    # топологии по (process_name, plugin_index). Раньше listener звал только
    # set_value(process_name, ...) — IPC НЕ уходил (единственный sender,
    # FrontendRegistersBridge, в v3 не инстанцируется; send_callback=None). Теперь
    # IPC идёт штатным RouterManager-путём (курс «всё через RouterManager»), а
    # register-адрес плагин-гранулярен (multi-plugin процессы бьют в нужный регистр).
    #
    # ПОРЯДОК ПОДПИСЧИКОВ (reviewer iter1 #3): EventBus вызывает handler'ы в порядке
    # регистрации. TopologyReplaced (save, шаг 4) приходит ПЕРЕД PluginConfigChanged
    # (шаг 6 dispatch / шаг _emit_config_diff undo). Порядок: presenter reload
    # (suppressed при field-edit) + bridge cache reset → затем этот listener. Не
    # переставлять без анализа.
    from multiprocess_prototype.domain.events import PluginConfigChanged
    from .bridge.plugin_register_resolver import resolve_plugin_register

    def _on_plugin_config_changed(event: PluginConfigChanged) -> None:
        """Live field-write: domain → GUI RegistersManager + register_update IPC."""
        import logging as _logging

        _log = _logging.getLogger(__name__)

        # Адрес плагина: register_name = plugin_name по (process, plugin_index).
        # Fallback на process_name — legacy 1:1 (process == plugin == register).
        register = (
            resolve_plugin_register(topology_store.topology, event.process_name, event.plugin_index)
            or event.process_name
        )

        # (а) GUI-side: обновить регистр inspector-виджетов (тот же ключ plugin_name).
        if registers_manager is not None:
            ok = registers_manager.set_value(register, event.field, event.value)
            if not ok:
                _log.warning(
                    "live field-write: GUI rm.set_value не прошёл %s.%s = %s",
                    register,
                    event.field,
                    event.value,
                )

        # (б) IPC в живой процесс через RouterManager (command="register_update").
        # Контракт payload приёмника (_on_register_update): {register, field, value}.
        # Дисптач по key_field="command" (router_manager.receive) → handler жив.
        # Fire-and-forget: процесс может быть не запущен — graceful, лог на DEBUG.
        try:
            command_sender.send_command(
                event.process_name,
                "register_update",
                {"register": register, "field": event.field, "value": event.value},
            )
            process._log_debug(
                f"live field-write IPC → {event.process_name}: {register}.{event.field}={event.value!r}",
                module="live",
            )
        except Exception as exc:  # noqa: BLE001 — IPC fire-and-forget, не валим GUI
            _log.warning(
                "live field-write: IPC register_update в '%s' не отправлен: %s",
                event.process_name,
                exc,
            )

    event_bus.subscribe(PluginConfigChanged, _on_plugin_config_changed)

    # 4. Создать MainWindow
    window = MainWindow()

    # Показать startup ошибки в StatusBar
    if not _report.ok:
        window.statusBar().showMessage(_report.summary(), 10000)

    # 4a. Привязать глобальные undo/redo shortcuts (Ctrl+Z / Ctrl+Y) к domain
    # CommandDispatcher — единая шина undo (G.4.4). app_services.commands
    # удовлетворяет UndoRedoController (undo/redo/can_undo/can_redo/add_change_callback).
    window.set_undo_controller(app_services.commands)

    # 4a1. Кнопка входа в header (зависит от auth_state и auth_manager)
    from .widgets.chrome.login_button import LoginButton

    _login_btn = LoginButton(auth_ctx.state, auth_ctx.manager)
    window.header.set_login_button(_login_btn)

    # 4a2. Phase 12: StatusBar live bindings
    window.connect_bindings(bindings)

    # 4b. Создать и установить ImagePanel
    image_panel = ImagePanelWidget()
    window.set_image_panel(image_panel)

    # 5. Создать TabFactory и заполнить табы (Phase 10: все 7 табов)
    # G.5.2: RuntimeDeps + auth_ctx собираются здесь (composition root) и
    # передаются TabFactory явно — фабрика больше не зависит от AppContext.
    from .widgets.tabs import register_all_tabs
    from .runtime_deps import RuntimeDeps

    def _request_ui_restart() -> None:
        """Узкий callback для InterfaceSection — перезапуск UI без перезапуска процесса."""
        process._restart_ui = True
        app.quit()

    _runtime = RuntimeDeps(
        command_sender=command_sender,
        topology_bridge=topology_bridge,
        bindings=bindings,
        plugin_manager=_plugin_manager,
        registers_manager=registers_manager,
        auth_ctx=auth_ctx,
        process_manager_proxy=process_manager_proxy,
        request_ui_restart=_request_ui_restart,
    )

    tab_factory = TabFactory(
        app_services,
        auth_ctx=auth_ctx,
        runtime=_runtime,
        custom_factories=register_all_tabs(),
    )
    tab_factory.create_tabs(window.tab_widget)

    # 5a. Подключить dirty-индикатор Settings → StatusBar
    from .widgets.tabs.settings.tab import SettingsTab

    for i in range(window.tab_widget.count()):
        w = window.tab_widget.widget(i)
        if isinstance(w, SettingsTab):
            w.dirty_changed.connect(window.set_dirty_indicator)
            break

    # 5b. PR3: подключить tree-propagator AccessContext — любой виджет
    # с `_trait`/`_apply_access`/`presenter.set_access_context` под
    # MainWindow автоматически реагирует на login/logout/смену роли.
    from .widgets.access import propagate_access_context_to_tree

    propagate_access_context_to_tree(window, auth_ctx.state)

    # 6. Подключить bridge callbacks
    _setup_bridge_callbacks(process, image_panel, window)

    # 7. Запустить таймеры (fps, safety)
    _setup_timers(app, process, window)

    # 8. Сохранить ссылку на окно в process
    process._window = window

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
            # Сквозная задержка: source штампует data.capture_ts = time.time() при
            # захвате; здесь, на выходе всей цепочки, считаем now - capture_ts.
            # time.time() (wall) — кросс-процессно сравнимо на одной машине.
            data = msg_dict.get("data")
            cts = data.get("capture_ts") if isinstance(data, dict) else None
            if isinstance(cts, (int, float)):
                window.record_chain_latency((time.time() - cts) * 1000.0)

            # frame-trace: финальный transport-спан (painter→gui) + дамп полного
            # таймлайна каждый 30-й кадр (под флагом INSPECTOR_FRAME_TRACE).
            if frame_trace.enabled() and isinstance(data, dict):
                frame_trace.record_transport(data, "gui")
                # Накопить пер-сегментные времена → таблица «участок · мс»
                # («Все процессы»). Публикуется усреднённо раз в секунду.
                window.record_trace_spans(data.get("trace"))
                # Сводка ветвей fan-in (нелинейный пайплайн): храним последний
                # снимок trace_branches — публикуется раз в секунду.
                window.record_trace_branches(data.get("trace_branches"))
                if _frame_trace_cnt % 30 == 1:
                    process._log_info(f"[FRAME-TRACE] {data.get('trace')}", module="gui")

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
        # Сквозной FPS цепочки → health-панель «Все процессы». count = кадров/с,
        # дошедших до дисплея через ВСЕ процессы (выходная пропускная способность
        # пайплайна). Инъекция локальной state-дельты в bridge (тот же канал, что
        # телеметрия): через дерево нельзя — GUI не получает свои дельты (exclude_self).
        try:
            process._bridge.dispatch({"data_type": "state_delta", "path": "system.chain_fps", "value": float(count)})
            # Сквозная задержка цепочки (среднее за секунду, мс): capture→display.
            latency = window.reset_chain_latency()
            if latency is not None:
                process._bridge.dispatch(
                    {"data_type": "state_delta", "path": "system.chain_latency_ms", "value": latency}
                )
            # Пер-сегментная разбивка кадра (среднее за секунду) → таблица в
            # «Все процессы». Не пусто только при INSPECTOR_FRAME_TRACE=1.
            segments = window.reset_trace_segments()
            if segments is not None:
                process._bridge.dispatch(
                    {"data_type": "state_delta", "path": "system.trace_segments", "value": segments}
                )
            # Сводка ветвей fan-in (последний снимок за период) → блок ветвей в
            # «Все процессы». Не пусто только при INSPECTOR_FRAME_TRACE=1 +
            # нелинейный пайплайн (stitcher кладёт trace_branches).
            branches = window.reset_trace_branches()
            if branches is not None:
                process._bridge.dispatch(
                    {"data_type": "state_delta", "path": "system.trace_branches", "value": branches}
                )
        except Exception:  # noqa: BLE001 — телеметрия не критична
            pass

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

    # При выходе из Qt — сигнализируем процессу (кроме перезапуска UI)
    app.aboutToQuit.connect(
        lambda: setattr(process, "_stop_requested", True) if not getattr(process, "_restart_ui", False) else None
    )

    # Сохранить ссылки на таймеры чтобы GC не убил их
    window._fps_timer = fps_timer
    window._safety_timer = safety_timer
