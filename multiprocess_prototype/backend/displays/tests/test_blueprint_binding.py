"""test_blueprint_binding.py -- Unit-тесты bind_displays_to_blueprint и cleanup_display_from_blueprint.

Покрытие:
- bind записывает display_<id> в blueprint
- format → channels маппинг (параметризованный)
- cleanup удаляет ключ
- cleanup несуществующего → без изменений
- оригинальный bp dict не мутируется
- пустой registry → blueprint эквивалентен исходному

Refs: plans/prototype-skeleton-2026-05/phase-4-displays-tab.md Task 4.8
"""

from __future__ import annotations

import copy

import pytest

from multiprocess_framework.modules.display_module import DisplayEntry, DisplayRegistry
from multiprocess_prototype.backend.displays.blueprint_binding import (
    bind_displays_to_blueprint,
    cleanup_display_from_blueprint,
)


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _make_entry(
    display_id: str = "main",
    fmt: str = "BGR",
    width: int = 640,
    height: int = 480,
    ring_buffer_blocks: int = 3,
) -> DisplayEntry:
    """Создать DisplayEntry-заглушку."""
    return DisplayEntry(
        id=display_id,
        name=f"Дисплей {display_id}",
        width=width,
        height=height,
        format=fmt,
        fps_limit=30.0,
        ring_buffer_blocks=ring_buffer_blocks,
    )


def _empty_blueprint() -> dict:
    """Пустой blueprint для тестов."""
    return {}


def _blueprint_with_ui_process() -> dict:
    """Blueprint с готовой секцией ui_process.memory."""
    return {
        "processes": {
            "ui_process": {
                "memory": {},
            }
        }
    }


@pytest.fixture(autouse=True)
def _clean_registry():
    """Очищает singleton DisplayRegistry перед/после каждого теста."""
    DisplayRegistry().clear()
    yield
    DisplayRegistry().clear()


# ---------------------------------------------------------------------------
# Тест 1: bind записывает display_<id1> и display_<id2>
# ---------------------------------------------------------------------------


def test_bind_writes_memory():
    """registry с 2 дисплеями + пустой blueprint → оба display_<id> в memory."""
    registry = DisplayRegistry()
    registry.register(_make_entry("cam0", width=640, height=480, ring_buffer_blocks=3))
    registry.register(_make_entry("debug", width=320, height=240, ring_buffer_blocks=2))

    result = bind_displays_to_blueprint(registry, _empty_blueprint())

    memory = result["processes"]["ui_process"]["memory"]

    assert "display_cam0" in memory
    assert "display_debug" in memory

    cam0_shm = memory["display_cam0"]
    assert cam0_shm["blocks"] == 3
    assert cam0_shm["frame_shape"] == [480, 640, 3]  # [height, width, channels]

    debug_shm = memory["display_debug"]
    assert debug_shm["blocks"] == 2
    assert debug_shm["frame_shape"] == [240, 320, 3]


# ---------------------------------------------------------------------------
# Тест 2: формат → каналы (параметризованный)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fmt, expected_channels",
    [
        ("BGR", 3),
        ("RGB", 3),
        ("GRAY", 1),
        ("RGBA", 4),
    ],
)
def test_bind_format_to_channels(fmt: str, expected_channels: int):
    """Формат пикселей → правильное количество каналов в frame_shape."""
    registry = DisplayRegistry()
    registry.register(_make_entry("test_display", fmt=fmt, width=100, height=50))

    result = bind_displays_to_blueprint(registry, _empty_blueprint())

    memory = result["processes"]["ui_process"]["memory"]
    shm = memory["display_test_display"]
    # frame_shape = [height, width, channels]
    assert shm["frame_shape"][2] == expected_channels


# ---------------------------------------------------------------------------
# Тест 3: cleanup удаляет ключ, другие сохранены
# ---------------------------------------------------------------------------


def test_cleanup_removes_entry():
    """cleanup_display_from_blueprint('main', bp) → ключ 'display_main' исчез, другие сохранены."""
    bp = {
        "processes": {
            "ui_process": {
                "memory": {
                    "display_main": {"blocks": 3, "frame_shape": [720, 1280, 3]},
                    "display_debug": {"blocks": 2, "frame_shape": [480, 640, 3]},
                }
            }
        }
    }

    result = cleanup_display_from_blueprint("main", bp)

    memory = result["processes"]["ui_process"]["memory"]
    assert "display_main" not in memory
    assert "display_debug" in memory


# ---------------------------------------------------------------------------
# Тест 4: cleanup несуществующего → blueprint эквивалентен (deepcopy равны)
# ---------------------------------------------------------------------------


def test_cleanup_nonexistent_no_change():
    """cleanup несуществующего id → blueprint эквивалентен исходному."""
    bp = {
        "processes": {
            "ui_process": {
                "memory": {
                    "display_debug": {"blocks": 2, "frame_shape": [480, 640, 3]},
                }
            }
        }
    }

    original_copy = copy.deepcopy(bp)
    result = cleanup_display_from_blueprint("nonexistent", bp)

    assert result == original_copy


# ---------------------------------------------------------------------------
# Тест 5: оригинальный bp dict не мутируется
# ---------------------------------------------------------------------------


def test_args_not_mutated():
    """bind_displays_to_blueprint не мутирует оригинальный blueprint dict."""
    registry = DisplayRegistry()
    registry.register(_make_entry("main"))

    original_bp = _blueprint_with_ui_process()
    original_copy = copy.deepcopy(original_bp)

    bind_displays_to_blueprint(registry, original_bp)

    assert original_bp == original_copy, "Оригинальный blueprint был мутирован"


# ---------------------------------------------------------------------------
# Тест 5b: cleanup тоже не мутирует оригинал
# ---------------------------------------------------------------------------


def test_cleanup_args_not_mutated():
    """cleanup_display_from_blueprint не мутирует оригинальный blueprint dict."""
    bp = {
        "processes": {
            "ui_process": {
                "memory": {
                    "display_main": {"blocks": 3, "frame_shape": [720, 1280, 3]},
                }
            }
        }
    }
    original_copy = copy.deepcopy(bp)
    cleanup_display_from_blueprint("main", bp)

    assert bp == original_copy, "Оригинальный blueprint был мутирован"


# ---------------------------------------------------------------------------
# Тест 6: пустой registry → blueprint эквивалентен исходному
# ---------------------------------------------------------------------------


def test_empty_registry_no_change():
    """Пустой registry → bind_displays_to_blueprint возвращает эквивалент."""
    registry = DisplayRegistry()  # пуст
    original_bp = _blueprint_with_ui_process()
    original_copy = copy.deepcopy(original_bp)

    result = bind_displays_to_blueprint(registry, original_bp)

    assert result == original_copy
