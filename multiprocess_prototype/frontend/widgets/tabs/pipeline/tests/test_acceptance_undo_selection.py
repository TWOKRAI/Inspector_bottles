# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты Task 1.1: «Отмена»/«Повтор» во вкладке pipeline возвращают выбор.

Контракт (plans/undo-restores-selection.md, таблица «Контракт»):

  | операция → действие                          | выбор после |
  | выбран A → добавить B → Отмена               | A           |
  | ничего → добавить B → Отмена                 | ничего      |
  | выбран B → удалить B → Отмена                | B выбран    |
  | (после предыдущей) Повтор                    | выбор сразу после исходного удаления |
  | выбран B → правка B → Отмена                 | B           |
  | запись вне этого редактора → Отмена          | уцелевшие из текущего выбора (G.6.3) |

Драйвер: реальный PipelinePresenter + GraphScene + CommandDispatcherOrchestrator (те же
helper'ы, что в test_presenter_domain_dispatch / test_place_display). Пользовательские
пути: add = presenter.add_process_from_plugin, delete = presenter.remove_selected,
правка поля = presenter._on_inspector_field_changed (dispatch SetPluginConfig),
Отмена/Повтор = services.commands.undo()/redo() — тот же объект, что у кнопок вкладки.

Узлы после перерисовки (clear_all) пересоздаются — сравниваем ТОЛЬКО node_id.
Ожидаемые значения — литеральные id узлов формата "<процесс>.<плагин>":
camera.capture, processor.color_mask, blur.blur, extra.blur.

Важно про «пользователь кликает между операцией и Отменой»: перерисовка сегодня
сохраняет уцелевших из выбора (G.6.3), поэтому голый сценарий «выбран A → добавить B →
Отмена» проходит и без memo. Чтобы тест проверял именно память записи, между операцией и
Отменой выбор меняется (пользователь кликает по новому узлу / по другому узлу / по пустому
месту) — ровно так контракт «выбор — часть записи истории» отличим от G.6.3.

Refs: plans/undo-restores-selection.md (Task 1.1, A1-A7)
"""

from __future__ import annotations

from multiprocess_prototype.domain.commands import AddProcess
from multiprocess_prototype.domain.entities.plugin import PluginInstance

from .test_place_display import _build_presenter_with_scene
from .test_presenter_domain_dispatch import _make_orchestrator_services


def _topology() -> dict:
    """Свежая дефолтная топология: camera --wire--> processor."""
    return {
        "processes": [
            {"process_name": "camera", "plugins": [{"plugin_name": "capture"}]},
            {"process_name": "processor", "plugins": [{"plugin_name": "color_mask"}]},
        ],
        "wires": [{"source": "camera.capture.frame", "target": "processor.color_mask.frame"}],
    }


def _build(qtbot):
    services = _make_orchestrator_services(topology=_topology())
    presenter, scene = _build_presenter_with_scene(services, qtbot)
    return services, presenter, scene


def _selected(scene) -> set[str]:
    """Выбор как множество node_id (объекты узлов после перерисовки другие)."""
    return {item.node_id for item in scene.selectedItems() if hasattr(item, "node_id")}


def _select(scene, *node_ids: str) -> None:
    """Пользователь выбирает ровно эти узлы (прежний выбор снимается)."""
    scene.clearSelection()
    for node_id in node_ids:
        node = scene.get_node(node_id)
        assert node is not None, f"узла {node_id!r} нет на сцене"
        node.setSelected(True)


def _plugin_config(services, process_name: str) -> dict:
    """config первого плагина процесса из репозитория топологии (истина домена)."""
    topo = services.topology.load().to_dict()
    proc = next(p for p in topo["processes"] if p["process_name"] == process_name)
    return dict(proc["plugins"][0].get("config", {}) or {})


# ---------------------------------------------------------------------------
# A1 / A2: добавление процесса
# ---------------------------------------------------------------------------


def test_a1_undo_add_restores_previous_selection(qtbot) -> None:
    """A1: выбран camera -> добавили blur -> кликнули по blur -> Отмена: выбран ровно camera."""
    services, presenter, scene = _build(qtbot)
    _select(scene, "camera.capture")

    assert presenter.add_process_from_plugin("blur") == "blur"
    assert scene.get_node("blur.blur") is not None
    _select(scene, "blur.blur")  # пользователь кликнул по только что добавленному узлу

    assert services.commands.undo() is True

    assert scene.get_node("blur.blur") is None
    assert _selected(scene) == {"camera.capture"}


def test_a2_undo_add_with_nothing_selected_leaves_nothing_selected(qtbot) -> None:
    """A2: ничего не выбрано -> добавили blur -> кликнули по нему -> Отмена: ничего не выбрано."""
    services, presenter, scene = _build(qtbot)
    scene.clearSelection()

    assert presenter.add_process_from_plugin("blur") == "blur"
    _select(scene, "blur.blur")

    assert services.commands.undo() is True

    assert scene.get_node("blur.blur") is None
    assert _selected(scene) == set()


# ---------------------------------------------------------------------------
# A3 / A4: удаление и повтор удаления
# ---------------------------------------------------------------------------


def test_a3_undo_delete_reselects_restored_node(qtbot) -> None:
    """A3: выбран camera -> удалили camera -> Отмена: camera вернулся И выбран, ровно он."""
    services, presenter, scene = _build(qtbot)
    _select(scene, "camera.capture")

    presenter.remove_selected(["camera.capture"])
    assert scene.get_node("camera.capture") is None
    assert _selected(scene) == set()  # исходная точка: удалённый узел не может быть выбран

    assert services.commands.undo() is True

    assert scene.get_node("camera.capture") is not None
    assert _selected(scene) == {"camera.capture"}


def test_a3_undo_delete_restores_whole_multi_selection(qtbot) -> None:
    """A3 (граница): выбраны camera и processor, удалили camera -> Отмена: выбраны оба."""
    services, presenter, scene = _build(qtbot)
    _select(scene, "camera.capture", "processor.color_mask")

    presenter.remove_selected(["camera.capture"])

    assert services.commands.undo() is True

    assert scene.get_node("camera.capture") is not None
    assert _selected(scene) == {"camera.capture", "processor.color_mask"}


def test_a4_redo_delete_restores_selection_after_delete(qtbot) -> None:
    """A4: выбраны camera+processor, удалили camera (остался выбран processor) -> Отмена ->
    кликнули по пустому месту -> Повтор: camera нет, выбор равен тому, что был сразу после
    удаления, то есть {processor}."""
    services, presenter, scene = _build(qtbot)
    _select(scene, "camera.capture", "processor.color_mask")
    presenter.remove_selected(["camera.capture"])
    assert _selected(scene) == {"processor.color_mask"}  # выбор сразу после исходного удаления

    assert services.commands.undo() is True
    assert scene.get_node("camera.capture") is not None
    scene.clearSelection()  # пользователь кликнул по пустому месту холста

    assert services.commands.redo() is True

    assert scene.get_node("camera.capture") is None
    assert _selected(scene) == {"processor.color_mask"}


# ---------------------------------------------------------------------------
# A5: правка поля (SetPluginConfig через путь инспектора)
# ---------------------------------------------------------------------------


def test_a5_undo_config_edit_keeps_edited_node_selected(qtbot) -> None:
    """A5: выбран camera -> правка поля camera -> Отмена: значение откатилось, выбран camera."""
    services, presenter, scene = _build(qtbot)
    _select(scene, "camera.capture")

    presenter._on_inspector_field_changed("camera", "threshold", 5)
    assert _plugin_config(services, "camera") == {"threshold": 5}

    assert services.commands.undo() is True

    assert _plugin_config(services, "camera") == {}
    assert _selected(scene) == {"camera.capture"}


def test_a5b_undo_config_edit_returns_selection_to_edited_node_after_reselect(qtbot) -> None:
    """A5b: выбран camera -> правка -> кликнули по processor -> Отмена: снова выбран camera.

    ТРАКТОВКА (не из таблицы буквально): таблица говорит «выбран B -> правка B -> Отмена -> B»,
    я обобщил на «выбор между правкой и Отменой сменился» — выбор часть записи истории.
    """
    services, presenter, scene = _build(qtbot)
    _select(scene, "camera.capture")
    presenter._on_inspector_field_changed("camera", "threshold", 5)
    _select(scene, "processor.color_mask")

    assert services.commands.undo() is True

    assert _plugin_config(services, "camera") == {}
    assert _selected(scene) == {"camera.capture"}


# ---------------------------------------------------------------------------
# A6: запись в обход вкладки (без memo) — прежний путь G.6.3
# ---------------------------------------------------------------------------


def test_a6_undo_of_direct_dispatch_keeps_survivors_of_current_selection(qtbot) -> None:
    """A6: dispatch в обход вкладки -> выбраны camera и extra -> Отмена: extra исчез,
    выбран уцелевший camera, исключений нет."""
    services, _presenter, scene = _build(qtbot)
    services.commands.dispatch(
        AddProcess(process_name="extra", plugins=(PluginInstance(plugin_name="blur", category="filter"),))
    )
    assert scene.get_node("extra.blur") is not None
    _select(scene, "camera.capture", "extra.blur")

    assert services.commands.undo() is True

    assert scene.get_node("extra.blur") is None
    assert _selected(scene) == {"camera.capture"}


def test_a6_undo_of_direct_dispatch_with_empty_selection_stays_empty(qtbot) -> None:
    """A6 (граница): нет выбора -> Отмена записи без memo -> выбора по-прежнему нет."""
    services, _presenter, scene = _build(qtbot)
    services.commands.dispatch(
        AddProcess(process_name="extra", plugins=(PluginInstance(plugin_name="blur", category="filter"),))
    )
    scene.clearSelection()

    assert services.commands.undo() is True

    assert scene.get_node("extra.blur") is None
    assert _selected(scene) == set()


# ---------------------------------------------------------------------------
# A7: серия правок с одним coalesce_key
# ---------------------------------------------------------------------------


def test_a7_coalesced_edits_undo_to_selection_before_first(qtbot) -> None:
    """A7: правка поля при выборе camera, кликнули processor, вторая правка того же поля
    (тот же coalesce_key) -> один Отмена: значения нет, выбран camera (ДО первой правки)."""
    services, presenter, scene = _build(qtbot)
    _select(scene, "camera.capture")
    presenter._on_inspector_field_changed("camera", "threshold", 1)
    _select(scene, "processor.color_mask")
    presenter._on_inspector_field_changed("camera", "threshold", 2)
    assert _plugin_config(services, "camera") == {"threshold": 2}

    assert services.commands.undo() is True

    assert _plugin_config(services, "camera") == {}  # серия откатилась одним шагом
    assert _selected(scene) == {"camera.capture"}
    assert services.commands.undo() is False  # больше в истории ничего нет


def test_a7_coalesced_edits_redo_to_selection_after_last(qtbot) -> None:
    """A7 (redo): та же серия -> Отмена -> клик по пустому месту -> Повтор: значение 2,
    выбран processor (выбор ПОСЛЕ последней правки серии)."""
    services, presenter, scene = _build(qtbot)
    _select(scene, "camera.capture")
    presenter._on_inspector_field_changed("camera", "threshold", 1)
    _select(scene, "processor.color_mask")
    presenter._on_inspector_field_changed("camera", "threshold", 2)
    assert services.commands.undo() is True
    scene.clearSelection()

    assert services.commands.redo() is True

    assert _plugin_config(services, "camera") == {"threshold": 2}
    assert _selected(scene) == {"processor.color_mask"}
