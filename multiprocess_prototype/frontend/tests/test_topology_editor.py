"""Тесты Topology Editor — Task 4.3.

Покрывает: TopologyPresenter (CRUD, load/save, валидация)
           TopologyEditorWidget (создание без crash).
"""

from __future__ import annotations

from pathlib import Path


from multiprocess_prototype.frontend.widgets.topology.presenter import TopologyPresenter
from multiprocess_prototype.frontend.widgets.topology.editor import TopologyEditorWidget


# ------------------------------------------------------------------ #
#  Тесты TopologyPresenter                                            #
# ------------------------------------------------------------------ #


def test_presenter_new_topology():
    """Новый presenter: processes == [], wires == []."""
    presenter = TopologyPresenter()
    assert presenter.get_process_names() == []
    assert presenter.blueprint.wires == []


def test_presenter_add_remove_process():
    """add_process() добавляет процесс; remove_process() удаляет."""
    presenter = TopologyPresenter()

    presenter.add_process("camera_0")
    names = presenter.get_process_names()
    assert "camera_0" in names

    presenter.remove_process("camera_0")
    assert "camera_0" not in presenter.get_process_names()


def test_presenter_add_remove_wire():
    """add_wire() добавляет wire; remove_wire(0) удаляет."""
    presenter = TopologyPresenter()

    presenter.add_wire("camera_0.capture.frame", "proc_0.color_mask.frame")
    assert len(presenter.blueprint.wires) == 1

    presenter.remove_wire(0)
    assert len(presenter.blueprint.wires) == 0


def test_presenter_remove_process_cascades_wires():
    """Удаление процесса каскадно удаляет связанные wires."""
    presenter = TopologyPresenter()

    presenter.add_process("camera_0")
    presenter.add_process("processor_0")
    presenter.add_wire("camera_0.capture.frame", "processor_0.color_mask.frame")

    assert len(presenter.blueprint.wires) == 1

    presenter.remove_process("camera_0")

    # Wire должен быть удалён — source начинается с "camera_0."
    assert len(presenter.blueprint.wires) == 0
    # processor_0 должен остаться
    assert "processor_0" in presenter.get_process_names()


def test_presenter_load_save_yaml(tmp_path: Path):
    """save_to_file() → load_from_file() → blueprint.name совпадает."""
    presenter = TopologyPresenter()
    presenter.new_topology("test_topo")
    presenter.add_process("proc_a")

    save_path = tmp_path / "topology.yaml"
    presenter.save_to_file(save_path)
    assert save_path.exists()

    # Загрузить в новый presenter
    presenter2 = TopologyPresenter()
    presenter2.load_from_file(save_path)

    assert presenter2.blueprint.name == "test_topo"
    assert "proc_a" in presenter2.get_process_names()
    assert presenter2.file_path == save_path


def test_presenter_validate_empty():
    """Пустой blueprint не содержит ошибок валидации."""
    presenter = TopologyPresenter()
    errors = presenter.validate()
    assert errors == []


def test_presenter_validate_duplicate_process_names():
    """Два процесса с одинаковым именем — ошибка валидации."""
    presenter = TopologyPresenter()
    presenter.add_process("worker")
    presenter.add_process("worker")  # дублирование

    errors = presenter.validate()
    # Должна быть хотя бы одна ошибка о дублировании
    assert any("worker" in e for e in errors)


def test_presenter_yaml_preview():
    """get_yaml_preview() возвращает строку с именем topology."""
    presenter = TopologyPresenter()
    presenter.new_topology("preview_topo")
    preview = presenter.get_yaml_preview()
    assert "preview_topo" in preview


def test_presenter_add_process_with_plugins():
    """add_process() с plugins сохраняет их в blueprint."""
    presenter = TopologyPresenter()
    plugins = [{"plugin_class": "some.module.Plugin", "plugin_name": "my_plugin"}]
    presenter.add_process("proc_0", plugins=plugins)

    proc = presenter.blueprint.processes[0]
    assert proc.process_name == "proc_0"
    assert len(proc.plugins) == 1
    assert proc.plugins[0]["plugin_name"] == "my_plugin"


def test_presenter_remove_wire_invalid_index():
    """remove_wire() с невалидным индексом не бросает исключение."""
    presenter = TopologyPresenter()
    # Не должно быть исключения
    presenter.remove_wire(99)
    presenter.remove_wire(-1)


def test_presenter_file_path_none_after_new():
    """После new_topology() file_path == None."""
    presenter = TopologyPresenter()
    presenter.new_topology("fresh")
    assert presenter.file_path is None


# ------------------------------------------------------------------ #
#  Тесты GUI-виджетов                                                 #
# ------------------------------------------------------------------ #


def test_topology_editor_widget_creates(qtbot):
    """TopologyEditorWidget создаётся без crash."""
    widget = TopologyEditorWidget()
    qtbot.addWidget(widget)
    assert widget is not None


def test_topology_editor_has_presenter(qtbot):
    """TopologyEditorWidget содержит TopologyPresenter."""
    widget = TopologyEditorWidget()
    qtbot.addWidget(widget)
    assert isinstance(widget._presenter, TopologyPresenter)


def test_topology_editor_initial_state(qtbot):
    """После создания ProcessListWidget пустой."""
    widget = TopologyEditorWidget()
    qtbot.addWidget(widget)
    assert widget._process_list._list.count() == 0
