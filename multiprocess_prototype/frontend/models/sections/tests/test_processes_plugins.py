"""Тесты для Plugin CRUD в ProcessesSectionView.

Task 6.2 — проверяет add_plugin, remove_plugin, move_plugin,
update_plugin_config, plugins_for_process.
"""

import pytest

from multiprocess_prototype.frontend.models.system_topology_editor import SystemTopologyEditor
from multiprocess_prototype.frontend.models.sections.processes_section import ProcessesSectionView


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def editor() -> SystemTopologyEditor:
    """Свежий редактор без данных."""
    return SystemTopologyEditor()


@pytest.fixture
def section(editor: SystemTopologyEditor) -> ProcessesSectionView:
    """Section View с добавленным процессом 'cam'."""
    view = editor.processes  # lazy property
    view.add_process("cam", "myapp.processes.CamProcess")
    return view


@pytest.fixture
def plugin_a() -> dict:
    """Корректный dict плагина A."""
    return {"plugin_class": "myapp.plugins.Capture", "plugin_name": "capture", "category": "source"}


@pytest.fixture
def plugin_b() -> dict:
    """Корректный dict плагина B."""
    return {"plugin_class": "myapp.plugins.Filter", "plugin_name": "hsv_filter", "category": "processing"}


# ---------------------------------------------------------------------------
# Тесты plugins_for_process
# ---------------------------------------------------------------------------

def test_plugins_for_process_empty(section: ProcessesSectionView) -> None:
    """Начальный список плагинов пустой."""
    plugins = section.plugins_for_process("cam")
    assert plugins == []


def test_plugins_for_process_nonexistent(section: ProcessesSectionView) -> None:
    """KeyError при несуществующем процессе."""
    with pytest.raises(KeyError, match="ghost"):
        section.plugins_for_process("ghost")


# ---------------------------------------------------------------------------
# Тесты add_plugin
# ---------------------------------------------------------------------------

def test_add_plugin(section: ProcessesSectionView, plugin_a: dict) -> None:
    """add_plugin возвращает индекс 0, плагин добавляется в список."""
    idx = section.add_plugin("cam", plugin_a)
    assert idx == 0

    plugins = section.plugins_for_process("cam")
    assert len(plugins) == 1
    assert plugins[0]["plugin_name"] == "capture"
    assert plugins[0]["category"] == "source"


def test_add_plugin_second(section: ProcessesSectionView, plugin_a: dict, plugin_b: dict) -> None:
    """Второй плагин получает индекс 1."""
    idx_a = section.add_plugin("cam", plugin_a)
    idx_b = section.add_plugin("cam", plugin_b)

    assert idx_a == 0
    assert idx_b == 1
    assert len(section.plugins_for_process("cam")) == 2


def test_add_plugin_duplicate_name(section: ProcessesSectionView, plugin_a: dict) -> None:
    """ValueError при дублирующемся plugin_name."""
    section.add_plugin("cam", plugin_a)

    duplicate = {"plugin_class": "other.Class", "plugin_name": "capture"}
    with pytest.raises(ValueError, match="capture"):
        section.add_plugin("cam", duplicate)


def test_add_plugin_missing_plugin_class(section: ProcessesSectionView) -> None:
    """ValueError если нет ключа plugin_class."""
    with pytest.raises(ValueError, match="plugin_class"):
        section.add_plugin("cam", {"plugin_name": "capture"})


def test_add_plugin_missing_plugin_name(section: ProcessesSectionView) -> None:
    """ValueError если нет ключа plugin_name."""
    with pytest.raises(ValueError, match="plugin_name"):
        section.add_plugin("cam", {"plugin_class": "some.Class"})


def test_add_plugin_nonexistent_process(section: ProcessesSectionView, plugin_a: dict) -> None:
    """KeyError при добавлении плагина в несуществующий процесс."""
    with pytest.raises(KeyError, match="ghost"):
        section.add_plugin("ghost", plugin_a)


# ---------------------------------------------------------------------------
# Тесты remove_plugin
# ---------------------------------------------------------------------------

def test_remove_plugin(section: ProcessesSectionView, plugin_a: dict, plugin_b: dict) -> None:
    """remove_plugin удаляет плагин, возвращает его dict."""
    section.add_plugin("cam", plugin_a)
    section.add_plugin("cam", plugin_b)

    removed = section.remove_plugin("cam", 0)
    assert removed["plugin_name"] == "capture"

    # Остался только plugin_b
    plugins = section.plugins_for_process("cam")
    assert len(plugins) == 1
    assert plugins[0]["plugin_name"] == "hsv_filter"


def test_remove_plugin_bad_index(section: ProcessesSectionView, plugin_a: dict) -> None:
    """IndexError при неверном индексе."""
    section.add_plugin("cam", plugin_a)

    with pytest.raises(IndexError):
        section.remove_plugin("cam", 5)


def test_remove_plugin_negative_index(section: ProcessesSectionView, plugin_a: dict) -> None:
    """IndexError при отрицательном индексе."""
    section.add_plugin("cam", plugin_a)

    with pytest.raises(IndexError):
        section.remove_plugin("cam", -1)


def test_remove_plugin_nonexistent_process(section: ProcessesSectionView) -> None:
    """KeyError при удалении из несуществующего процесса."""
    with pytest.raises(KeyError, match="ghost"):
        section.remove_plugin("ghost", 0)


# ---------------------------------------------------------------------------
# Тесты move_plugin
# ---------------------------------------------------------------------------

def test_move_plugin(section: ProcessesSectionView, plugin_a: dict, plugin_b: dict) -> None:
    """move_plugin изменяет порядок плагинов."""
    section.add_plugin("cam", plugin_a)  # idx=0: capture
    section.add_plugin("cam", plugin_b)  # idx=1: hsv_filter

    section.move_plugin("cam", 0, 1)

    plugins = section.plugins_for_process("cam")
    assert plugins[0]["plugin_name"] == "hsv_filter"
    assert plugins[1]["plugin_name"] == "capture"


def test_move_plugin_noop(
    section: ProcessesSectionView,
    plugin_a: dict,
    plugin_b: dict,
) -> None:
    """move_plugin с from==to — no-op, подписчики не уведомляются."""
    section.add_plugin("cam", plugin_a)
    section.add_plugin("cam", plugin_b)

    call_count = 0

    def on_change() -> None:
        nonlocal call_count
        call_count += 1

    section._editor.subscribe("SECTION_PROCESSES", on_change)
    # Сбрасываем счётчик после подписки (subscribe не триггерит callback)
    call_count = 0

    section.move_plugin("cam", 1, 1)
    assert call_count == 0, "no-op не должен вызывать notification"


def test_move_plugin_bad_index(section: ProcessesSectionView, plugin_a: dict, plugin_b: dict) -> None:
    """IndexError при неверном индексе при перемещении."""
    section.add_plugin("cam", plugin_a)
    section.add_plugin("cam", plugin_b)

    with pytest.raises(IndexError):
        section.move_plugin("cam", 0, 5)

    with pytest.raises(IndexError):
        section.move_plugin("cam", 99, 0)


def test_move_plugin_nonexistent_process(section: ProcessesSectionView) -> None:
    """KeyError при перемещении в несуществующем процессе."""
    with pytest.raises(KeyError, match="ghost"):
        section.move_plugin("ghost", 0, 1)


# ---------------------------------------------------------------------------
# Тесты update_plugin_config
# ---------------------------------------------------------------------------

def test_update_plugin_config(section: ProcessesSectionView, plugin_a: dict) -> None:
    """update_plugin_config обновляет поля плагина."""
    section.add_plugin("cam", plugin_a)

    section.update_plugin_config("cam", 0, {"h_min": 30, "h_max": 90})

    plugin = section.plugins_for_process("cam")[0]
    assert plugin["h_min"] == 30
    assert plugin["h_max"] == 90
    # Исходные поля не затронуты
    assert plugin["plugin_name"] == "capture"


def test_update_plugin_config_bad_index(section: ProcessesSectionView, plugin_a: dict) -> None:
    """IndexError при неверном индексе обновления."""
    section.add_plugin("cam", plugin_a)

    with pytest.raises(IndexError):
        section.update_plugin_config("cam", 5, {"h_min": 30})


def test_update_plugin_config_nonexistent_process(section: ProcessesSectionView) -> None:
    """KeyError при обновлении плагина в несуществующем процессе."""
    with pytest.raises(KeyError, match="ghost"):
        section.update_plugin_config("ghost", 0, {"h_min": 30})


# ---------------------------------------------------------------------------
# Тест snapshot
# ---------------------------------------------------------------------------

def test_full_snapshot_includes_plugins(section: ProcessesSectionView, plugin_a: dict) -> None:
    """full_snapshot содержит plugins внутри processes."""
    section.add_plugin("cam", plugin_a)

    snap = section.full_snapshot()
    assert "processes" in snap
    assert "cam" in snap["processes"]
    cam_in_snap = snap["processes"]["cam"]
    assert "plugins" in cam_in_snap
    assert len(cam_in_snap["plugins"]) == 1
    assert cam_in_snap["plugins"][0]["plugin_name"] == "capture"


# ---------------------------------------------------------------------------
# Тест notification при каждой мутации
# ---------------------------------------------------------------------------

def test_notification_on_mutation(
    section: ProcessesSectionView,
    plugin_a: dict,
    plugin_b: dict,
) -> None:
    """Каждая мутация вызывает callback подписчика."""
    from multiprocess_prototype.registers.system_topology.schemas import SECTION_PROCESSES

    calls: list[str] = []

    def on_change() -> None:
        calls.append("notified")

    section._editor.subscribe(SECTION_PROCESSES, on_change)

    # add_plugin
    section.add_plugin("cam", plugin_a)
    assert len(calls) == 1, "add_plugin должен уведомить"

    section.add_plugin("cam", plugin_b)
    assert len(calls) == 2

    # update_plugin_config
    section.update_plugin_config("cam", 0, {"h_min": 10})
    assert len(calls) == 3, "update_plugin_config должен уведомить"

    # move_plugin (from != to)
    section.move_plugin("cam", 0, 1)
    assert len(calls) == 4, "move_plugin должен уведомить"

    # remove_plugin
    section.remove_plugin("cam", 0)
    assert len(calls) == 5, "remove_plugin должен уведомить"
