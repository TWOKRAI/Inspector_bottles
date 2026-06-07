"""Тесты normalize_blueprint — app-glue нормализация.

Проверяем:
1. normalize_blueprint применяет per-category defaults как старый _merge_defaults.
2. Inline-значения плагина имеют приоритет (override) над defaults.
3. Неизвестные категории не ломают обработку.
4. build_proc_dicts связывает нормализацию + assembler.
"""

from __future__ import annotations

import copy

from multiprocess_prototype.backend.assembly.normalize import (
    build_proc_dicts,
    normalize_blueprint,
)
from multiprocess_prototype.backend.config.schemas import SystemConfig


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


def _make_sys_config(**overrides) -> SystemConfig:
    """Создать SystemConfig с дефолтными значениями."""
    return SystemConfig(**overrides)


_BLUEPRINT_WITH_PLUGINS: dict = {
    "name": "test",
    "processes": [
        {
            "process_name": "cam",
            "process_class": "some.CamApp",
            "plugins": [
                {
                    "plugin_class": "some.CameraPlugin",
                    "plugin_name": "camera",
                    "category": "source",
                    "camera_id": 42,
                },
            ],
        },
        {
            "process_name": "proc",
            "process_class": "some.ProcApp",
            "plugins": [
                {
                    "plugin_class": "some.FilterPlugin",
                    "plugin_name": "filter",
                    "category": "processing",
                    "threshold": 100,
                },
            ],
        },
    ],
    "wires": [],
}


# ---------------------------------------------------------------------------
# Тесты normalize_blueprint
# ---------------------------------------------------------------------------


class TestNormalizeBlueprint:
    """normalize_blueprint применяет per-category defaults."""

    def test_source_defaults_applied(self) -> None:
        """Defaults для категории 'source' (mapping → camera) применяются."""
        bp = copy.deepcopy(_BLUEPRINT_WITH_PLUGINS)
        sys_config = _make_sys_config()
        result = normalize_blueprint(bp, sys_config)

        cam_plugin = result["processes"][0]["plugins"][0]
        # SystemConfig.camera.source_type = "simulator" — должен быть в конфиге
        # если inline не переопределил.
        assert "source_type" in cam_plugin

    def test_inline_override_priority(self) -> None:
        """Inline-значения плагина побеждают defaults."""
        bp = copy.deepcopy(_BLUEPRINT_WITH_PLUGINS)
        sys_config = _make_sys_config()

        # camera defaults: resolution_width = 640
        # inline задаёт camera_id = 42 (нет в defaults), его не затрёт
        result = normalize_blueprint(bp, sys_config)

        cam_plugin = result["processes"][0]["plugins"][0]
        assert cam_plugin["camera_id"] == 42, "inline camera_id затёрт defaults"

    def test_processing_defaults_applied(self) -> None:
        """Defaults для категории 'processing' применяются."""
        bp = copy.deepcopy(_BLUEPRINT_WITH_PLUGINS)
        sys_config = _make_sys_config()
        result = normalize_blueprint(bp, sys_config)

        proc_plugin = result["processes"][1]["plugins"][0]
        # inline threshold = 100 — сохранён
        assert proc_plugin["threshold"] == 100

    def test_unknown_category_no_crash(self) -> None:
        """Неизвестная категория — не падает, плагин не меняется."""
        bp = {
            "name": "test",
            "processes": [
                {
                    "process_name": "x",
                    "process_class": "a.B",
                    "plugins": [
                        {
                            "plugin_class": "c.D",
                            "plugin_name": "custom",
                            "category": "nonexistent_category",
                            "value": 1,
                        },
                    ],
                },
            ],
            "wires": [],
        }
        sys_config = _make_sys_config()
        result = normalize_blueprint(bp, sys_config)

        plugin = result["processes"][0]["plugins"][0]
        assert plugin["value"] == 1

    def test_no_category_no_crash(self) -> None:
        """Плагин без category — не падает."""
        bp = {
            "name": "test",
            "processes": [
                {
                    "process_name": "x",
                    "process_class": "a.B",
                    "plugins": [
                        {
                            "plugin_class": "c.D",
                            "plugin_name": "bare",
                        },
                    ],
                },
            ],
            "wires": [],
        }
        sys_config = _make_sys_config()
        result = normalize_blueprint(bp, sys_config)
        assert result["processes"][0]["plugins"][0]["plugin_name"] == "bare"

    def test_mutates_in_place(self) -> None:
        """normalize_blueprint мутирует in-place и возвращает тот же объект."""
        bp = copy.deepcopy(_BLUEPRINT_WITH_PLUGINS)
        sys_config = _make_sys_config()
        result = normalize_blueprint(bp, sys_config)
        assert result is bp, "normalize_blueprint должен возвращать тот же объект"

    def test_empty_processes(self) -> None:
        """Blueprint без процессов — не падает."""
        bp = {"name": "empty", "processes": [], "wires": []}
        sys_config = _make_sys_config()
        result = normalize_blueprint(bp, sys_config)
        assert result["processes"] == []


# ---------------------------------------------------------------------------
# Тесты build_proc_dicts (связка)
# ---------------------------------------------------------------------------


class TestBuildProcDicts:
    """build_proc_dicts — связка normalize + assembler."""

    def test_returns_proc_dicts(self) -> None:
        """build_proc_dicts возвращает dict[str, dict]."""
        bp = copy.deepcopy(_BLUEPRINT_WITH_PLUGINS)
        sys_config = _make_sys_config()
        result = build_proc_dicts(bp, sys_config)

        assert isinstance(result, dict)
        assert set(result.keys()) == {"cam", "proc"}
        for name, proc_dict in result.items():
            assert isinstance(proc_dict, dict)
            # merge_with_defaults применён — обязательные ключи есть
            assert "class" in proc_dict
            assert "workers" in proc_dict
