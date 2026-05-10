"""Интеграционные тесты Phase 6 — полный flow с плагинами.

Проверяем сквозной data model flow (без Qt):
  - создание процесса → добавление плагинов → редактирование config → валидация
  - CRUD плагинов: add, remove, move, update_config
  - dirty tracking после мутаций
  - snapshot содержит plugins
  - валидация дублей plugin_name
  - валидация обязательных полей ProcessDefinition
  - multi-process: два процесса с независимыми plugin-списками
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Прокидываем пути для импорта из корня проекта
_ROOT = Path(__file__).resolve().parents[3]
_V3_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _V3_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multiprocess_prototype.frontend.models.system_topology_editor import SystemTopologyEditor
from multiprocess_prototype.registers.system_topology.schemas import (
    SECTION_PROCESSES,
    ProcessDefinition,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def editor() -> SystemTopologyEditor:
    """Свежий SystemTopologyEditor для каждого теста."""
    return SystemTopologyEditor()


# ---------------------------------------------------------------------------
# Test 1: полный flow — создание процесса, добавление плагинов, проверка порядка
# ---------------------------------------------------------------------------


class TestFullPluginFlow:
    """Сквозной flow: создание → добавление плагинов → чтение."""

    def test_add_two_plugins_and_verify_order(self, editor):
        """Два плагина добавляются в правильном порядке."""
        section = editor.processes
        proc_key = section.add_process("camera_0", "GenericProcess")

        section.add_plugin(proc_key, {
            "plugin_class": "capture.plugin.CapturePlugin",
            "plugin_name": "capture",
            "category": "source",
        })
        section.add_plugin(proc_key, {
            "plugin_class": "color_mask.plugin.ColorMaskPlugin",
            "plugin_name": "color_mask",
            "category": "processing",
        })

        plugins = section.plugins_for_process(proc_key)
        assert len(plugins) == 2
        assert plugins[0]["plugin_name"] == "capture"
        assert plugins[1]["plugin_name"] == "color_mask"

    def test_add_plugin_returns_correct_index(self, editor):
        """add_plugin возвращает индекс нового плагина."""
        section = editor.processes
        proc_key = section.add_process("proc", "GenericProcess")

        idx0 = section.add_plugin(proc_key, {
            "plugin_class": "a.A", "plugin_name": "A", "category": "source",
        })
        idx1 = section.add_plugin(proc_key, {
            "plugin_class": "b.B", "plugin_name": "B", "category": "processing",
        })

        assert idx0 == 0
        assert idx1 == 1

    def test_add_plugin_unknown_process_raises_key_error(self, editor):
        """Добавление плагина в несуществующий процесс → KeyError."""
        section = editor.processes
        with pytest.raises(KeyError):
            section.add_plugin("nonexistent", {
                "plugin_class": "x", "plugin_name": "x", "category": "source",
            })


# ---------------------------------------------------------------------------
# Test 2: move plugin — изменение порядка в цепочке
# ---------------------------------------------------------------------------


class TestMovePlugin:
    """Перемещение плагинов внутри цепочки."""

    def test_move_plugin_changes_order(self, editor):
        """move_plugin(0, 1) меняет A↔B местами."""
        section = editor.processes
        proc_key = section.add_process("proc", "GenericProcess")

        section.add_plugin(proc_key, {"plugin_class": "a", "plugin_name": "A", "category": "source"})
        section.add_plugin(proc_key, {"plugin_class": "b", "plugin_name": "B", "category": "processing"})

        section.move_plugin(proc_key, 0, 1)

        plugins = section.plugins_for_process(proc_key)
        assert plugins[0]["plugin_name"] == "B"
        assert plugins[1]["plugin_name"] == "A"

    def test_move_plugin_same_index_is_noop(self, editor):
        """move_plugin с одинаковым from/to — no-op, порядок не меняется."""
        section = editor.processes
        proc_key = section.add_process("proc", "GenericProcess")

        section.add_plugin(proc_key, {"plugin_class": "a", "plugin_name": "A", "category": "source"})
        section.add_plugin(proc_key, {"plugin_class": "b", "plugin_name": "B", "category": "processing"})

        section.move_plugin(proc_key, 0, 0)

        plugins = section.plugins_for_process(proc_key)
        assert plugins[0]["plugin_name"] == "A"
        assert plugins[1]["plugin_name"] == "B"

    def test_move_plugin_out_of_bounds_raises_index_error(self, editor):
        """move_plugin с невалидным индексом → IndexError."""
        section = editor.processes
        proc_key = section.add_process("proc", "GenericProcess")

        section.add_plugin(proc_key, {"plugin_class": "a", "plugin_name": "A", "category": "source"})

        with pytest.raises(IndexError):
            section.move_plugin(proc_key, 0, 5)


# ---------------------------------------------------------------------------
# Test 3: update_plugin_config — обновление полей конфига
# ---------------------------------------------------------------------------


class TestUpdatePluginConfig:
    """Обновление конфига плагина по индексу."""

    def test_update_plugin_config_merges_fields(self, editor):
        """update_plugin_config обновляет только переданные поля."""
        section = editor.processes
        proc_key = section.add_process("proc", "GenericProcess")

        section.add_plugin(proc_key, {
            "plugin_class": "x",
            "plugin_name": "X",
            "category": "processing",
            "h_min": 0,
            "h_max": 180,
        })

        section.update_plugin_config(proc_key, 0, {"h_min": 35, "h_max": 85})

        plugins = section.plugins_for_process(proc_key)
        assert plugins[0]["h_min"] == 35
        assert plugins[0]["h_max"] == 85
        # plugin_class и plugin_name остались нетронутыми
        assert plugins[0]["plugin_class"] == "x"
        assert plugins[0]["plugin_name"] == "X"

    def test_update_plugin_config_adds_new_fields(self, editor):
        """update_plugin_config добавляет новые ключи в конфиг плагина."""
        section = editor.processes
        proc_key = section.add_process("proc", "GenericProcess")

        section.add_plugin(proc_key, {
            "plugin_class": "x", "plugin_name": "X", "category": "source",
        })

        section.update_plugin_config(proc_key, 0, {"threshold": 128, "invert": True})

        plugins = section.plugins_for_process(proc_key)
        assert plugins[0]["threshold"] == 128
        assert plugins[0]["invert"] is True

    def test_update_plugin_config_out_of_bounds_raises(self, editor):
        """update_plugin_config с невалидным индексом → IndexError."""
        section = editor.processes
        proc_key = section.add_process("proc", "GenericProcess")

        with pytest.raises(IndexError):
            section.update_plugin_config(proc_key, 0, {"key": "val"})


# ---------------------------------------------------------------------------
# Test 4: remove_plugin — удаление из цепочки
# ---------------------------------------------------------------------------


class TestRemovePlugin:
    """Удаление плагинов из цепочки."""

    def test_remove_plugin_returns_removed_dict(self, editor):
        """remove_plugin возвращает удалённый dict."""
        section = editor.processes
        proc_key = section.add_process("proc", "GenericProcess")

        section.add_plugin(proc_key, {"plugin_class": "a", "plugin_name": "A", "category": "source"})
        section.add_plugin(proc_key, {"plugin_class": "b", "plugin_name": "B", "category": "processing"})

        removed = section.remove_plugin(proc_key, 0)

        assert removed["plugin_name"] == "A"
        assert len(section.plugins_for_process(proc_key)) == 1

    def test_remove_plugin_shifts_remaining(self, editor):
        """После удаления первого плагина второй занимает его место."""
        section = editor.processes
        proc_key = section.add_process("proc", "GenericProcess")

        section.add_plugin(proc_key, {"plugin_class": "a", "plugin_name": "A", "category": "source"})
        section.add_plugin(proc_key, {"plugin_class": "b", "plugin_name": "B", "category": "processing"})

        section.remove_plugin(proc_key, 0)

        plugins = section.plugins_for_process(proc_key)
        assert plugins[0]["plugin_name"] == "B"

    def test_remove_plugin_out_of_bounds_raises(self, editor):
        """remove_plugin с невалидным индексом → IndexError."""
        section = editor.processes
        proc_key = section.add_process("proc", "GenericProcess")

        with pytest.raises(IndexError):
            section.remove_plugin(proc_key, 0)


# ---------------------------------------------------------------------------
# Test 5: dirty tracking — грязный флаг после мутаций плагинов
# ---------------------------------------------------------------------------


class TestDirtyTracking:
    """Dirty tracking при мутациях плагинов."""

    def test_dirty_after_add_plugin(self, editor):
        """Секция помечается dirty после add_plugin."""
        section = editor.processes
        proc_key = section.add_process("proc", "GenericProcess")

        # Фиксируем чистое состояние после создания процесса
        editor.mark_clean(SECTION_PROCESSES)
        assert not section.dirty

        section.add_plugin(proc_key, {
            "plugin_class": "a", "plugin_name": "A", "category": "source",
        })

        assert section.dirty

    def test_dirty_after_remove_plugin(self, editor):
        """Секция помечается dirty после remove_plugin."""
        section = editor.processes
        proc_key = section.add_process("proc", "GenericProcess")
        section.add_plugin(proc_key, {
            "plugin_class": "a", "plugin_name": "A", "category": "source",
        })

        editor.mark_clean(SECTION_PROCESSES)
        assert not section.dirty

        section.remove_plugin(proc_key, 0)
        assert section.dirty

    def test_dirty_after_move_plugin(self, editor):
        """Секция помечается dirty после move_plugin."""
        section = editor.processes
        proc_key = section.add_process("proc", "GenericProcess")
        section.add_plugin(proc_key, {"plugin_class": "a", "plugin_name": "A", "category": "source"})
        section.add_plugin(proc_key, {"plugin_class": "b", "plugin_name": "B", "category": "processing"})

        editor.mark_clean(SECTION_PROCESSES)
        assert not section.dirty

        section.move_plugin(proc_key, 0, 1)
        assert section.dirty

    def test_dirty_after_update_plugin_config(self, editor):
        """Секция помечается dirty после update_plugin_config."""
        section = editor.processes
        proc_key = section.add_process("proc", "GenericProcess")
        section.add_plugin(proc_key, {"plugin_class": "a", "plugin_name": "A", "category": "source"})

        editor.mark_clean(SECTION_PROCESSES)
        assert not section.dirty

        section.update_plugin_config(proc_key, 0, {"threshold": 42})
        assert section.dirty

    def test_mark_clean_clears_dirty(self, editor):
        """mark_clean после мутации снимает dirty флаг."""
        section = editor.processes
        proc_key = section.add_process("proc", "GenericProcess")
        section.add_plugin(proc_key, {"plugin_class": "a", "plugin_name": "A", "category": "source"})

        assert section.dirty

        editor.mark_clean(SECTION_PROCESSES)
        assert not section.dirty


# ---------------------------------------------------------------------------
# Test 6: snapshot — снимок включает plugins
# ---------------------------------------------------------------------------


class TestSnapshot:
    """Snapshot секции содержит актуальные plugins."""

    def test_snapshot_includes_plugins(self, editor):
        """full_snapshot возвращает plugins в данных процесса."""
        section = editor.processes
        proc_key = section.add_process("proc", "GenericProcess")

        section.add_plugin(proc_key, {
            "plugin_class": "a",
            "plugin_name": "A",
            "category": "source",
        })

        snap = section.full_snapshot()

        assert "processes" in snap
        assert proc_key in snap["processes"]
        assert "plugins" in snap["processes"][proc_key]
        assert len(snap["processes"][proc_key]["plugins"]) == 1

    def test_snapshot_is_deepcopy(self, editor):
        """Изменения после snapshot не влияют на сам снимок."""
        section = editor.processes
        proc_key = section.add_process("proc", "GenericProcess")
        section.add_plugin(proc_key, {"plugin_class": "a", "plugin_name": "A", "category": "source"})

        snap = section.full_snapshot()

        # Мутируем после snapshot
        section.add_plugin(proc_key, {"plugin_class": "b", "plugin_name": "B", "category": "processing"})

        # Снимок не должен измениться
        assert len(snap["processes"][proc_key]["plugins"]) == 1

    def test_load_from_snapshot_restores_state(self, editor):
        """load_from_snapshot восстанавливает state из снимка."""
        section = editor.processes
        proc_key = section.add_process("proc", "GenericProcess")
        section.add_plugin(proc_key, {"plugin_class": "a", "plugin_name": "A", "category": "source"})

        snap = section.full_snapshot()

        # Добавляем ещё плагин и удаляем исходный
        section.add_plugin(proc_key, {"plugin_class": "b", "plugin_name": "B", "category": "processing"})
        section.remove_plugin(proc_key, 0)

        # Восстанавливаем
        section.load_from_snapshot(snap)

        plugins = section.plugins_for_process(proc_key)
        assert len(plugins) == 1
        assert plugins[0]["plugin_name"] == "A"


# ---------------------------------------------------------------------------
# Test 7: валидация — дубли plugin_name
# ---------------------------------------------------------------------------


class TestValidateDuplicatePluginName:
    """Валидация уникальности plugin_name в рамках процесса."""

    def test_add_duplicate_plugin_name_raises_value_error(self, editor):
        """add_plugin с дублирующимся plugin_name → ValueError."""
        section = editor.processes
        proc_key = section.add_process("proc", "GenericProcess")

        section.add_plugin(proc_key, {
            "plugin_class": "a", "plugin_name": "A", "category": "source",
        })

        with pytest.raises(ValueError, match="plugin_name='A'"):
            section.add_plugin(proc_key, {
                "plugin_class": "b", "plugin_name": "A", "category": "processing",
            })

    def test_duplicate_allowed_in_different_processes(self, editor):
        """Одинаковый plugin_name допустим в разных процессах."""
        section = editor.processes
        p1 = section.add_process("proc1", "GenericProcess")
        p2 = section.add_process("proc2", "GenericProcess")

        # Оба процесса могут иметь плагин с именем "capture"
        section.add_plugin(p1, {"plugin_class": "a", "plugin_name": "capture", "category": "source"})
        section.add_plugin(p2, {"plugin_class": "b", "plugin_name": "capture", "category": "source"})

        assert section.plugins_for_process(p1)[0]["plugin_name"] == "capture"
        assert section.plugins_for_process(p2)[0]["plugin_name"] == "capture"


# ---------------------------------------------------------------------------
# Test 8: валидация — обязательные поля плагина через validate_refs
# ---------------------------------------------------------------------------


class TestValidateMissingPluginFields:
    """Валидация обязательных полей плагина через SystemTopology.validate_refs."""

    def test_validate_refs_catches_missing_plugin_class(self, editor):
        """validate_refs возвращает ошибку при отсутствии plugin_class."""
        from multiprocess_prototype.registers.system_topology.schemas import SystemTopology

        data = SystemTopology().model_dump()
        # Добавляем процесс с плагином без plugin_class
        data["processes"]["proc"] = {
            "name": "proc",
            "class_path": "GenericProcess",
            "priority": "normal",
            "auto_start": True,
            "sort_order": 0,
            "plugins": [
                {"plugin_name": "x"}  # нет plugin_class
            ],
        }

        st = SystemTopology.model_validate(data)
        errors = st.validate_refs()

        # Ожидаем ошибку про отсутствующий ключ plugin_class
        assert any("plugin_class" in e for e in errors), (
            f"Ожидалась ошибка про plugin_class, получено: {errors}"
        )

    def test_validate_refs_catches_missing_plugin_name(self, editor):
        """validate_refs возвращает ошибку при отсутствии plugin_name."""
        from multiprocess_prototype.registers.system_topology.schemas import SystemTopology

        data = SystemTopology().model_dump()
        data["processes"]["proc"] = {
            "name": "proc",
            "class_path": "GenericProcess",
            "priority": "normal",
            "auto_start": True,
            "sort_order": 0,
            "plugins": [
                {"plugin_class": "some.Class"}  # нет plugin_name
            ],
        }

        st = SystemTopology.model_validate(data)
        errors = st.validate_refs()

        assert any("plugin_name" in e for e in errors), (
            f"Ожидалась ошибка про plugin_name, получено: {errors}"
        )

    def test_validate_refs_no_error_for_valid_plugin(self, editor):
        """validate_refs без ошибок для корректного плагина."""
        from multiprocess_prototype.registers.system_topology.schemas import SystemTopology

        data = SystemTopology().model_dump()
        data["processes"]["proc"] = {
            "name": "proc",
            "class_path": "GenericProcess",
            "priority": "normal",
            "auto_start": True,
            "sort_order": 0,
            "plugins": [
                {"plugin_class": "some.Class", "plugin_name": "valid_plugin"},
            ],
        }
        # Добавляем protected воркер, чтобы не получить ошибку от _validate_processes
        data["workers"]["proc_main"] = {
            "process_ref": "proc",
            "name": "main",
            "worker_type": "router_poll",
            "enabled": True,
            "protected": True,
            "target_interval_ms": 0,
            "sort_order": 0,
        }

        st = SystemTopology.model_validate(data)
        errors = st.validate_refs()

        plugin_errors = [e for e in errors if "plugin" in e.lower()]
        assert plugin_errors == [], f"Неожиданные ошибки плагина: {plugin_errors}"


# ---------------------------------------------------------------------------
# Test 9: multi-process — два процесса с независимыми plugin-списками
# ---------------------------------------------------------------------------


class TestMultipleProcessesWithPlugins:
    """Два процесса с независимыми цепочками плагинов."""

    def test_plugins_isolated_per_process(self, editor):
        """Плагины одного процесса не влияют на плагины другого."""
        section = editor.processes

        p1 = section.add_process("cam", "GenericProcess")
        p2 = section.add_process("proc", "GenericProcess")

        section.add_plugin(p1, {"plugin_class": "a", "plugin_name": "capture", "category": "source"})
        section.add_plugin(p2, {"plugin_class": "b", "plugin_name": "color_mask", "category": "processing"})

        p1_plugins = section.plugins_for_process(p1)
        p2_plugins = section.plugins_for_process(p2)

        assert len(p1_plugins) == 1
        assert len(p2_plugins) == 1
        assert p1_plugins[0]["plugin_name"] == "capture"
        assert p2_plugins[0]["plugin_name"] == "color_mask"

    def test_remove_process_removes_its_plugins(self, editor):
        """Удаление процесса (cascade) не затрагивает плагины другого."""
        section = editor.processes

        p1 = section.add_process("cam", "GenericProcess")
        p2 = section.add_process("proc", "GenericProcess")

        section.add_plugin(p1, {"plugin_class": "a", "plugin_name": "capture", "category": "source"})
        section.add_plugin(p2, {"plugin_class": "b", "plugin_name": "color_mask", "category": "processing"})

        # Удаляем первый процесс
        section.remove_process(p1)

        # Второй процесс со своими плагинами остаётся нетронутым
        p2_plugins = section.plugins_for_process(p2)
        assert len(p2_plugins) == 1
        assert p2_plugins[0]["plugin_name"] == "color_mask"

    def test_multiple_processes_snapshot_contains_all(self, editor):
        """full_snapshot содержит плагины для обоих процессов."""
        section = editor.processes

        p1 = section.add_process("cam", "GenericProcess")
        p2 = section.add_process("proc", "GenericProcess")

        section.add_plugin(p1, {"plugin_class": "a", "plugin_name": "capture", "category": "source"})
        section.add_plugin(p2, {"plugin_class": "b", "plugin_name": "color_mask", "category": "processing"})

        snap = section.full_snapshot()

        assert p1 in snap["processes"]
        assert p2 in snap["processes"]
        assert len(snap["processes"][p1]["plugins"]) == 1
        assert len(snap["processes"][p2]["plugins"]) == 1


# ---------------------------------------------------------------------------
# Test 10: editor.validate — валидация chain через SystemTopologyEditor
# ---------------------------------------------------------------------------


class TestEditorValidation:
    """Валидация chain через SystemTopologyEditor.validate()."""

    def test_validate_plugin_chain_graceful_without_registry(self, editor):
        """Валидация chain не падает, когда плагин не найден в PluginRegistry.

        В design-time реестр может быть пустым — graceful degradation.
        """
        section = editor.processes
        proc_key = section.add_process("proc", "GenericProcess")
        section.add_plugin(proc_key, {"plugin_class": "a", "plugin_name": "A", "category": "source"})
        section.add_plugin(proc_key, {"plugin_class": "b", "plugin_name": "B", "category": "processing"})

        # Валидация не должна бросать исключение
        errors = editor.validate(section="processes")

        # Ошибки могут быть, но не от validate_chain (graceful degradation)
        # Проверяем что нет краша
        assert isinstance(errors, list)

    def test_validate_duplicate_plugin_name_via_editor_validate_refs(self, editor):
        """validate_refs из SystemTopology находит дубль plugin_name."""
        from multiprocess_prototype.registers.system_topology.schemas import SystemTopology

        data = SystemTopology().model_dump()
        data["processes"]["proc"] = {
            "name": "proc",
            "class_path": "GenericProcess",
            "priority": "normal",
            "auto_start": True,
            "sort_order": 0,
            "plugins": [
                {"plugin_class": "a", "plugin_name": "dup"},
                {"plugin_class": "b", "plugin_name": "dup"},  # дубль
            ],
        }
        data["workers"]["proc_main"] = {
            "process_ref": "proc",
            "name": "main",
            "worker_type": "router_poll",
            "enabled": True,
            "protected": True,
            "target_interval_ms": 0,
            "sort_order": 0,
        }

        st = SystemTopology.model_validate(data)
        errors = st.validate_refs()

        assert any("dup" in e for e in errors), (
            f"Ожидалась ошибка про дублирующийся plugin_name 'dup', получено: {errors}"
        )
