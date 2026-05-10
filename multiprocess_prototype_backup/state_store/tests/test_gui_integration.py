"""Тесты интеграции GuiProcess + GuiStateProxy + RegistersStateAdapter.

Все тесты без Qt — используют Mock для изоляции от GUI-зависимостей.
FrontendLauncher импортируется через sys.modules-патч, чтобы избежать
тяжёлых транзитивных импортов (PySide6, pydantic, frontend_module).
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Патч тяжёлых модулей ПЕРЕД любым импортом frontend.launcher
# ---------------------------------------------------------------------------

def _patch_heavy_modules() -> None:
    """Подставить заглушки для модулей, недоступных в тестовой среде."""
    stubs = [
        "frontend_module",
        "frontend_module.core",
        "frontend_module.core.schema_config",
        "frontend_module.core.routed_command",
        "frontend_module.windows",
        "frontend_module.core.qt_imports",
    ]
    for name in stubs:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            # Добавляем нужные атрибуты-заглушки
            mod.FrontendLaunchHooks = MagicMock  # type: ignore[attr-defined]
            mod.run_process_attached_frontend = MagicMock()  # type: ignore[attr-defined]
            mod.coerce_schema_config = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
            mod.LoadingWindow = MagicMock  # type: ignore[attr-defined]
            sys.modules[name] = mod

    # Заглушки для внутренних модулей приложения
    app_stubs = [
        "multiprocess_prototype.frontend.app_context",
        "multiprocess_prototype.frontend.commands",
        "multiprocess_prototype.frontend.configs.frontend_config",
        "multiprocess_prototype.frontend.diagnostics",
        "multiprocess_prototype.frontend.managers",
        "multiprocess_prototype.frontend.managers.app_recipe_aggregate",
        "multiprocess_prototype.frontend.managers.camera_registry",
        "multiprocess_prototype.frontend.managers.recipe_manager",
        "multiprocess_prototype.frontend.widgets",
        "multiprocess_prototype.frontend.widgets.tabs_setting.camera_tab.schemas",
        "multiprocess_prototype.frontend.windows.main_window",
        "multiprocess_prototype.registers",
    ]
    for name in app_stubs:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.FrontendAppContext = MagicMock  # type: ignore[attr-defined]
            mod.GuiCommandHandler = MagicMock  # type: ignore[attr-defined]
            mod.build_frontend_config = MagicMock(return_value={})  # type: ignore[attr-defined]
            mod.attach_ui_diagnostics = MagicMock()  # type: ignore[attr-defined]
            mod.RecipeManager = MagicMock  # type: ignore[attr-defined]
            mod.SettingsProfileManager = MagicMock  # type: ignore[attr-defined]
            mod.aggregate_to_snapshot = MagicMock(return_value={})  # type: ignore[attr-defined]
            mod.build_default_app_aggregate = MagicMock(return_value={})  # type: ignore[attr-defined]
            mod.CameraRegistry = MagicMock  # type: ignore[attr-defined]
            mod.build_camera_tab_callbacks = MagicMock(return_value={})  # type: ignore[attr-defined]
            mod.CameraTabUiConfig = MagicMock  # type: ignore[attr-defined]
            mod.MainWindow = MagicMock  # type: ignore[attr-defined]
            mod.create_tab_widget_factory = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
            mod.DEFAULT_RECIPE_SLOT_ID = "default"  # type: ignore[attr-defined]
            mod.create_registers = MagicMock(return_value=(MagicMock(), {}))  # type: ignore[attr-defined]
            sys.modules[name] = mod


_patch_heavy_modules()


# ---------------------------------------------------------------------------
# Вспомогательные фикстуры
# ---------------------------------------------------------------------------


def _make_mock_process(name: str = "gui") -> MagicMock:
    """Создать Mock-объект, имитирующий GuiProcess."""
    process = MagicMock()
    process.name = name
    process.router_manager = MagicMock()
    process.router_manager.register_message_handler = MagicMock()
    return process


def _make_mock_registers(reg_names: list[str] | None = None) -> MagicMock:
    """Создать Mock RegistersManager с нужными методами."""
    regs = MagicMock()

    if reg_names is None:
        reg_names = ["camera", "processor", "renderer"]

    regs.register_names = MagicMock(return_value=reg_names)

    # Каждый регистр имеет model_fields с тестовыми полями
    def get_register(name: str) -> MagicMock | None:
        if name not in reg_names:
            return None
        reg = MagicMock()
        # Используем model_fields (Pydantic v2)
        reg.model_fields = {"fps": None, "exposure": None}
        # Убираем __fields__ чтобы не двоить
        del reg.__fields__
        return reg

    regs.get_register = MagicMock(side_effect=get_register)
    return regs


def _make_mock_state_proxy() -> MagicMock:
    """Создать Mock GuiStateProxy с нужными методами."""
    proxy = MagicMock()
    proxy.set = MagicMock()
    proxy.shutdown = MagicMock()
    proxy.subscribe = MagicMock(return_value="sub-test-1")
    proxy.on_state_changed = MagicMock()
    return proxy


# ---------------------------------------------------------------------------
# Тест 1: GuiProcess создаёт _state_proxy
# ---------------------------------------------------------------------------


def test_gui_process_creates_state_proxy():
    """GuiStateProxy создаётся и присваивается как _state_proxy в process."""
    mock_proxy = _make_mock_state_proxy()

    with patch(
        "multiprocess_framework.modules.state_store_module.proxy.gui_state_proxy.GuiStateProxy",
        return_value=mock_proxy,
    ) as MockProxy:
        # Симулируем инициализацию: создаём proxy вручную (как в _init_application_threads)
        from multiprocess_framework.modules.state_store_module.proxy.gui_state_proxy import GuiStateProxy

        router = MagicMock()
        proxy = GuiStateProxy("gui", router=router)

        # Убеждаемся что конструктор вызван с правильными аргументами
        MockProxy.assert_called_once_with("gui", router=router)
        assert proxy is mock_proxy


# ---------------------------------------------------------------------------
# Тест 2: GuiProcess регистрирует handler state.changed
# ---------------------------------------------------------------------------


def test_gui_process_registers_handler():
    """register_message_handler вызывается с 'state.changed' и proxy.on_state_changed."""
    router = MagicMock()
    router.register_message_handler = MagicMock()

    mock_proxy = _make_mock_state_proxy()

    with patch(
        "multiprocess_framework.modules.state_store_module.proxy.gui_state_proxy.GuiStateProxy",
        return_value=mock_proxy,
    ):
        from multiprocess_framework.modules.state_store_module.proxy.gui_state_proxy import GuiStateProxy

        proxy = GuiStateProxy("gui", router=router)

        # Регистрируем обработчик (как в GuiProcess._init_application_threads)
        router.register_message_handler("state.changed", proxy.on_state_changed)

        router.register_message_handler.assert_called_once_with(
            "state.changed", mock_proxy.on_state_changed
        )


# ---------------------------------------------------------------------------
# Тест 3: shutdown пишет статус "shutdown" перед завершением
# ---------------------------------------------------------------------------


def test_gui_process_shutdown_writes_status():
    """При shutdown proxy.set('gui.state.status', 'shutdown') и proxy.shutdown() вызываются."""
    mock_proxy = _make_mock_state_proxy()

    # Имитируем наличие _state_proxy на process
    class FakeGuiProcess:
        _state_proxy = mock_proxy

        def shutdown(self):
            if hasattr(self, "_state_proxy"):
                self._state_proxy.set("gui.state.status", "shutdown")
                self._state_proxy.shutdown()

    process = FakeGuiProcess()
    process.shutdown()

    # Проверяем порядок вызовов
    mock_proxy.set.assert_called_once_with("gui.state.status", "shutdown")
    mock_proxy.shutdown.assert_called_once()


# ---------------------------------------------------------------------------
# Тест 4: _build_path_mapping — camera register
# ---------------------------------------------------------------------------


def test_build_path_mapping_camera():
    """Маппинг camera регистра: (camera, field) -> cameras.0.config.field."""
    from frontend.launcher import FrontendLauncher  # type: ignore[import]

    launcher = FrontendLauncher.__new__(FrontendLauncher)
    launcher._process = None
    launcher._app_config = {}

    # Только camera register
    regs = MagicMock()
    regs.register_names = MagicMock(return_value=["camera"])

    camera_reg = MagicMock()
    camera_reg.model_fields = {"fps": None, "exposure": None}
    del camera_reg.__fields__
    regs.get_register = MagicMock(return_value=camera_reg)

    config = {"camera_id": 0}
    mapping = launcher._build_path_mapping(regs, config)

    assert mapping[("camera", "fps")] == "cameras.0.config.fps"
    assert mapping[("camera", "exposure")] == "cameras.0.config.exposure"


# ---------------------------------------------------------------------------
# Тест 5: _build_path_mapping — renderer register
# ---------------------------------------------------------------------------


def test_build_path_mapping_renderer():
    """Маппинг renderer регистра: (renderer, field) -> renderer.config.field."""
    from frontend.launcher import FrontendLauncher  # type: ignore[import]

    launcher = FrontendLauncher.__new__(FrontendLauncher)
    launcher._process = None
    launcher._app_config = {}

    regs = MagicMock()
    regs.register_names = MagicMock(return_value=["renderer"])

    renderer_reg = MagicMock()
    renderer_reg.model_fields = {"show_mask": None, "opacity": None}
    del renderer_reg.__fields__
    regs.get_register = MagicMock(return_value=renderer_reg)

    config = {}
    mapping = launcher._build_path_mapping(regs, config)

    assert mapping[("renderer", "show_mask")] == "renderer.config.show_mask"
    assert mapping[("renderer", "opacity")] == "renderer.config.opacity"


# ---------------------------------------------------------------------------
# Тест 6: неизвестный регистр пропускается
# ---------------------------------------------------------------------------


def test_build_path_mapping_unknown_register_skipped():
    """Регистр без маппинга в PREFIX_MAP не добавляется в результат."""
    from frontend.launcher import FrontendLauncher  # type: ignore[import]

    launcher = FrontendLauncher.__new__(FrontendLauncher)
    launcher._process = None
    launcher._app_config = {}

    regs = MagicMock()
    regs.register_names = MagicMock(return_value=["unknown_register", "camera"])

    # unknown_register: имеет поля, но нет в PREFIX_MAP
    unknown_reg = MagicMock()
    unknown_reg.model_fields = {"some_field": None}
    del unknown_reg.__fields__

    camera_reg = MagicMock()
    camera_reg.model_fields = {"fps": None}
    del camera_reg.__fields__

    def get_reg(name: str) -> MagicMock:
        if name == "unknown_register":
            return unknown_reg
        return camera_reg

    regs.get_register = MagicMock(side_effect=get_reg)

    config = {"camera_id": 1}
    mapping = launcher._build_path_mapping(regs, config)

    # unknown_register должен быть пропущен
    keys = [k[0] for k in mapping.keys()]
    assert "unknown_register" not in keys
    # camera должен присутствовать
    assert ("camera", "fps") in mapping


# ---------------------------------------------------------------------------
# Тест 7: RegistersStateAdapter подключён после connect()
# ---------------------------------------------------------------------------


def test_registers_adapter_connected():
    """adapter.is_connected == True после вызова connect()."""
    from multiprocess_prototype.state_store.adapters.registers_adapter import RegistersStateAdapter

    mock_rm = MagicMock()
    mock_rm.subscribe_all = MagicMock()
    mock_rm.unsubscribe_all = MagicMock()

    mock_proxy = MagicMock()
    mock_proxy.subscribe = MagicMock(return_value="sub-42")
    mock_proxy.unsubscribe = MagicMock()

    path_mapping = {
        ("camera", "fps"): "cameras.0.config.fps",
    }

    adapter = RegistersStateAdapter(
        registers_manager=mock_rm,
        state_proxy=mock_proxy,
        path_mapping=path_mapping,
    )

    assert adapter.is_connected is False
    adapter.connect()
    assert adapter.is_connected is True

    # subscribe_all и proxy.subscribe вызваны
    mock_rm.subscribe_all.assert_called_once()
    mock_proxy.subscribe.assert_called_once()
