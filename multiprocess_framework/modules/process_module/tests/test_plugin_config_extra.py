"""Тесты Task 7.0 — PluginConfig extra="allow" + from_plugins() memory proxy.

Проверяем:
1. PluginConfig принимает extra-поля (YAML-поля регистра) без ошибок
2. Extra-поля доступны через __pydantic_extra__
3. model_dump() включает extra-поля
4. from_plugins() корректно вычисляет memory через register_bindings
5. Обратная совместимость: плагины без register_bindings работают как раньше
"""

from __future__ import annotations

from typing import Annotated, Any, ClassVar


from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
)
from multiprocess_framework.modules.process_module.generic.generic_process_config import (
    GenericProcessConfig,
    PluginConfig,
)


# ──────────────────────────────────────────────────────────────
# Фикстуры: тестовые register и config классы
# ──────────────────────────────────────────────────────────────


class _TestRegister(SchemaBase):
    """Тестовый register с memory property."""

    camera_id: Annotated[int, FieldMeta("ID камеры")] = 0
    width: Annotated[int, FieldMeta("Ширина", unit="px")] = 640
    height: Annotated[int, FieldMeta("Высота", unit="px")] = 480
    threshold: Annotated[int, FieldMeta("Порог", min=0, max=255)] = 128

    @property
    def memory(self) -> dict[str, Any] | None:
        return {
            f"output_{self.camera_id}": (self.height, self.width, 1),
        }


class _TestPluginConfigWithBindings(PluginConfig):
    """Config с register_bindings — V3_MY_PURE паттерн."""

    plugin_class: str = "test.TestPlugin"
    plugin_name: str = "test_plugin"
    category: str = "processing"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [_TestRegister]


class _TestPluginConfigLegacy(PluginConfig):
    """Legacy config — memory через собственное свойство (без register)."""

    plugin_class: str = "test.LegacyPlugin"
    plugin_name: str = "legacy"
    category: str = "processing"
    resolution: int = 640

    @property
    def memory(self) -> dict[str, Any] | None:
        return {"frame_legacy": (480, self.resolution, 3)}


class _TestRegisterNoMemory(SchemaBase):
    """Register без memory property."""

    gain: Annotated[int, FieldMeta("Gain", min=0, max=100)] = 50


class _TestPluginConfigBindingNoMemory(PluginConfig):
    """Config с register_bindings, но register без memory."""

    plugin_class: str = "test.NoMemPlugin"
    plugin_name: str = "no_mem"
    category: str = "output"
    register_bindings: ClassVar[list[type[SchemaBase]]] = [_TestRegisterNoMemory]


class _TestPluginConfigNoBindings(PluginConfig):
    """Config без register_bindings и без memory — минимальный плагин."""

    plugin_class: str = "test.MinimalPlugin"
    plugin_name: str = "minimal"
    category: str = "lifecycle"


# ──────────────────────────────────────────────────────────────
# 1. Extra-поля в PluginConfig
# ──────────────────────────────────────────────────────────────


class TestPluginConfigExtra:
    """PluginConfig extra='allow' — YAML-поля не теряются."""

    def test_extra_fields_accepted(self):
        """Extra-поля принимаются без ValidationError."""
        cfg = _TestPluginConfigWithBindings(
            camera_id=2,
            width=1920,
            height=1080,
            threshold=200,
        )
        assert cfg.plugin_name == "test_plugin"
        # Extra-поля доступны через __pydantic_extra__
        extras = cfg.__pydantic_extra__
        assert extras["camera_id"] == 2
        assert extras["width"] == 1920
        assert extras["height"] == 1080
        assert extras["threshold"] == 200

    def test_extra_fields_in_model_dump(self):
        """model_dump() включает extra-поля."""
        cfg = _TestPluginConfigWithBindings(camera_id=5, threshold=100)
        d = cfg.model_dump()
        assert d["camera_id"] == 5
        assert d["threshold"] == 100
        assert d["plugin_name"] == "test_plugin"

    def test_base_plugin_config_accepts_extra(self):
        """Даже базовый PluginConfig принимает extra-поля."""
        cfg = PluginConfig(plugin_name="base", unknown_field=42)
        assert cfg.__pydantic_extra__["unknown_field"] == 42

    def test_legacy_config_no_extra_fields(self):
        """Legacy config с declared полями — они не в extra."""
        cfg = _TestPluginConfigLegacy(resolution=1280)
        # resolution — declared field, не extra
        assert cfg.resolution == 1280
        assert "resolution" not in (cfg.__pydantic_extra__ or {})


# ──────────────────────────────────────────────────────────────
# 2. from_plugins() — memory proxy через register_bindings
# ──────────────────────────────────────────────────────────────


class TestFromPluginsMemoryProxy:
    """from_plugins() корректно проксирует memory из register."""

    def test_memory_from_register_defaults(self):
        """Register без overrides → memory с defaults."""
        cfg = _TestPluginConfigWithBindings()
        gpc = GenericProcessConfig.from_plugins("proc1", [cfg])
        mem = gpc.memory
        assert mem is not None
        # _TestRegister defaults: camera_id=0, height=480, width=640
        assert "output_0" in mem
        assert mem["output_0"] == (480, 640, 1)

    def test_memory_from_register_yaml_overrides(self):
        """YAML overrides (extra-поля) → memory с кастомными значениями."""
        cfg = _TestPluginConfigWithBindings(
            camera_id=3,
            width=1920,
            height=1080,
        )
        gpc = GenericProcessConfig.from_plugins("proc2", [cfg])
        mem = gpc.memory
        assert mem is not None
        assert "output_3" in mem
        assert mem["output_3"] == (1080, 1920, 1)

    def test_memory_legacy_config_still_works(self):
        """Legacy config (без register_bindings) — memory как раньше."""
        cfg = _TestPluginConfigLegacy(resolution=1280)
        gpc = GenericProcessConfig.from_plugins("proc3", [cfg])
        mem = gpc.memory
        assert mem is not None
        assert "frame_legacy" in mem
        assert mem["frame_legacy"] == (480, 1280, 3)

    def test_memory_mixed_plugins(self):
        """Несколько плагинов: один с register, другой legacy."""
        cfg_reg = _TestPluginConfigWithBindings(camera_id=1, width=800, height=600)
        cfg_legacy = _TestPluginConfigLegacy(resolution=320)
        gpc = GenericProcessConfig.from_plugins("proc4", [cfg_reg, cfg_legacy])
        mem = gpc.memory
        assert mem is not None
        assert "output_1" in mem
        assert mem["output_1"] == (600, 800, 1)
        assert "frame_legacy" in mem
        assert mem["frame_legacy"] == (480, 320, 3)

    def test_memory_none_when_no_plugins_have_memory(self):
        """Плагин без memory → memory = None."""
        cfg = _TestPluginConfigNoBindings()
        gpc = GenericProcessConfig.from_plugins("proc5", [cfg])
        assert gpc.memory is None

    def test_memory_register_no_memory_property(self):
        """Register без memory property → memory = None."""
        cfg = _TestPluginConfigBindingNoMemory(gain=75)
        gpc = GenericProcessConfig.from_plugins("proc6", [cfg])
        assert gpc.memory is None


# ──────────────────────────────────────────────────────────────
# 3. Обратная совместимость
# ──────────────────────────────────────────────────────────────


class TestBackwardCompatibility:
    """Существующие плагины без изменений продолжают работать."""

    def test_plugin_config_without_extra(self):
        """PluginConfig без extra-полей — работает как раньше."""
        cfg = PluginConfig(plugin_class="x.Y", plugin_name="y", category="source")
        assert cfg.plugin_class == "x.Y"
        assert cfg.memory is None
        assert not cfg.__pydantic_extra__

    def test_register_bindings_default_empty(self):
        """Base PluginConfig.register_bindings = [] по умолчанию."""
        assert PluginConfig.register_bindings == []

    def test_model_dump_roundtrip(self):
        """model_dump → PluginConfig(**dict) — roundtrip работает."""
        original = _TestPluginConfigWithBindings(camera_id=7, threshold=42)
        d = original.model_dump()
        restored = _TestPluginConfigWithBindings(**d)
        assert restored.__pydantic_extra__["camera_id"] == 7
        assert restored.__pydantic_extra__["threshold"] == 42

    def test_from_plugins_plugins_dicts_include_extra(self):
        """from_plugins() сериализует extra-поля в plugins list[dict]."""
        cfg = _TestPluginConfigWithBindings(camera_id=2, width=1024)
        gpc = GenericProcessConfig.from_plugins("proc", [cfg])
        assert len(gpc.plugins) == 1
        plugin_dict = gpc.plugins[0]
        assert plugin_dict["camera_id"] == 2
        assert plugin_dict["width"] == 1024
        assert plugin_dict["plugin_name"] == "test_plugin"
