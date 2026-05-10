"""Тесты Task 2.6: CrossTabComboBox — авто-обновляемый QComboBox.

Используем QApplication fixture (паттерн проекта — без pytest-qt).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_V3_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _V3_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Импортируем CrossTabComboBox напрямую из файла, минуя base/__init__.py
# (тот содержит циклический импорт через recipe_panel_base)
_combo_spec = importlib.util.spec_from_file_location(
    "cross_tab_combo",
    _V3_ROOT / "frontend" / "widgets" / "base" / "editor" / "cross_tab_combo.py",
)
_combo_mod = importlib.util.module_from_spec(_combo_spec)
_combo_spec.loader.exec_module(_combo_mod)
CrossTabComboBox = _combo_mod.CrossTabComboBox

from multiprocess_prototype.frontend.models.system_topology_editor import SystemTopologyEditor
from multiprocess_prototype.registers.system_topology.schemas import (
    SECTION_PROCESSES,
    SECTION_SOURCES,
)

from PySide6 import QtWidgets


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def qapp():
    """QApplication — один на всю сессию."""
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


@pytest.fixture
def editor() -> SystemTopologyEditor:
    """Свежий SystemTopologyEditor."""
    return SystemTopologyEditor()


# ---------------------------------------------------------------------------
# Тесты создания
# ---------------------------------------------------------------------------


def test_combo_creates_without_error(qapp, editor):
    """CrossTabComboBox создаётся без исключений."""
    combo = CrossTabComboBox(editor, editor.process_names, SECTION_PROCESSES)
    assert combo is not None
    combo.hide()


def test_combo_initially_empty_for_empty_editor(qapp, editor):
    """Свежий editor → combo пустой."""
    combo = CrossTabComboBox(editor, editor.process_names, SECTION_PROCESSES)
    assert combo.count() == 0
    combo.hide()


def test_combo_initially_filled_when_editor_has_data(qapp, editor):
    """Если в editor уже есть процессы при создании combo — items заполнены."""
    editor.processes.add_process("existing_proc", "pkg.Existing")
    combo = CrossTabComboBox(editor, editor.process_names, SECTION_PROCESSES)
    assert combo.count() == 1
    assert combo.itemText(0) == "existing_proc"
    combo.hide()


# ---------------------------------------------------------------------------
# Тесты авто-обновления
# ---------------------------------------------------------------------------


def test_combo_updates_on_process_added(qapp, editor):
    """Добавление процесса в editor → combo.count() увеличивается."""
    combo = CrossTabComboBox(editor, editor.process_names, SECTION_PROCESSES)
    assert combo.count() == 0

    editor.processes.add_process("new_proc", "pkg.NewProc")

    assert combo.count() == 1
    assert combo.itemText(0) == "new_proc"
    combo.hide()


def test_combo_updates_on_multiple_processes_added(qapp, editor):
    """Добавление нескольких процессов → combo обновляется после каждого."""
    combo = CrossTabComboBox(editor, editor.process_names, SECTION_PROCESSES)

    editor.processes.add_process("proc_a", "pkg.A")
    assert combo.count() == 1

    editor.processes.add_process("proc_b", "pkg.B")
    assert combo.count() == 2
    combo.hide()


def test_combo_updates_on_process_removed(qapp, editor):
    """Удаление процесса из editor → combo.count() уменьшается."""
    editor.processes.add_process("proc_to_remove", "pkg.Class")
    combo = CrossTabComboBox(editor, editor.process_names, SECTION_PROCESSES)
    assert combo.count() == 1

    editor.processes.remove_process("proc_to_remove")

    assert combo.count() == 0
    combo.hide()


def test_combo_not_updated_on_other_section_change(qapp, editor):
    """Изменение SECTION_SOURCES не обновляет combo подписанный на SECTION_PROCESSES."""
    combo = CrossTabComboBox(editor, editor.process_names, SECTION_PROCESSES)
    count_before = combo.count()

    # Изменяем sources — combo не должен обновиться
    editor.sources.add_camera("simulator")

    assert combo.count() == count_before
    combo.hide()


# ---------------------------------------------------------------------------
# Тесты сохранения выбора
# ---------------------------------------------------------------------------


def test_combo_preserves_selection_on_new_item_added(qapp, editor):
    """Выбор сохраняется при добавлении нового элемента в список."""
    editor.processes.add_process("alpha", "pkg.Alpha")
    editor.processes.add_process("beta", "pkg.Beta")

    combo = CrossTabComboBox(editor, editor.process_names, SECTION_PROCESSES)

    # Выбираем "beta"
    idx = combo.findText("beta")
    assert idx >= 0
    combo.setCurrentIndex(idx)
    assert combo.currentText() == "beta"

    # Добавляем новый процесс — выбор "beta" должен сохраниться
    editor.processes.add_process("gamma", "pkg.Gamma")

    assert combo.currentText() == "beta"
    combo.hide()


def test_combo_selection_cleared_when_selected_item_removed(qapp, editor):
    """Если выбранный элемент удалён — combo не крашится."""
    editor.processes.add_process("will_be_removed", "pkg.Class")
    editor.processes.add_process("will_stay", "pkg.Class2")

    combo = CrossTabComboBox(editor, editor.process_names, SECTION_PROCESSES)

    # Выбираем "will_be_removed"
    idx = combo.findText("will_be_removed")
    combo.setCurrentIndex(idx)
    assert combo.currentText() == "will_be_removed"

    # Удаляем выбранный элемент — не должно быть исключений
    editor.processes.remove_process("will_be_removed")

    # "will_be_removed" больше нет в списке
    assert combo.findText("will_be_removed") == -1
    assert combo.count() == 1  # остался только "will_stay"
    combo.hide()


# ---------------------------------------------------------------------------
# Тест blockSignals при refresh
# ---------------------------------------------------------------------------


def test_combo_refresh_does_not_emit_current_index_changed(qapp, editor):
    """_refresh() не генерирует лишний currentIndexChanged (blockSignals работает).

    При перестройке списка (clear → addItems) сигнал должен быть заблокирован.
    Допускается максимум один сигнал (от setCurrentIndex при восстановлении выбора).
    """
    combo = CrossTabComboBox(editor, editor.process_names, SECTION_PROCESSES)

    signal_count = []
    combo.currentIndexChanged.connect(lambda idx: signal_count.append(idx))

    # Добавляем процесс — это вызывает _refresh() внутри
    editor.processes.add_process("block_signals_proc", "pkg.Class")

    # blockSignals в _refresh() предотвращает сигналы при clear/addItems
    # Допускается не более одного сигнала (от setCurrentIndex при восстановлении)
    assert len(signal_count) <= 1
    combo.hide()


# ---------------------------------------------------------------------------
# Тест disconnect_editor
# ---------------------------------------------------------------------------


def test_disconnect_editor_stops_updates(qapp, editor):
    """После disconnect_editor() combo больше не обновляется при изменениях editor."""
    combo = CrossTabComboBox(editor, editor.process_names, SECTION_PROCESSES)

    editor.processes.add_process("before_disconnect", "pkg.Class")
    assert combo.count() == 1

    combo.disconnect_editor()

    # После отписки новые процессы не должны обновлять combo
    editor.processes.add_process("after_disconnect", "pkg.Class")
    assert combo.count() == 1  # не изменился
    combo.hide()


# ---------------------------------------------------------------------------
# Тест с camera_keys provider (SECTION_SOURCES)
# ---------------------------------------------------------------------------


def test_combo_with_camera_keys_provider(qapp, editor):
    """CrossTabComboBox работает с provider=editor.camera_keys и section=SECTION_SOURCES."""
    combo = CrossTabComboBox(editor, editor.camera_keys, SECTION_SOURCES)
    assert combo.count() == 0

    cam_key, _ = editor.sources.add_camera("simulator")
    assert combo.count() == 1
    assert combo.itemText(0) == cam_key
    combo.hide()
