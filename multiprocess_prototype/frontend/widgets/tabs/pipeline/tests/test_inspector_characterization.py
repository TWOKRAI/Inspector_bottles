# -*- coding: utf-8 -*-
"""Характеризационные тесты NodeInspectorPanel — ДО разреза god-файла (F.6).

Фиксируют наблюдаемое поведение панели, которое разрез на секции-виджеты
(cam_actual/exec_info/process_selector/params_form/hikvision/selectors_data)
обязан сохранить без изменений. Внешние сигналы и публичные методы панели —
контракт MERGE-GATE F.

Ключевое (acceptance задачи): при смене camera→не-camera ноды баланс
bind/unbind actual-подписок = 0 (все хэндлы GuiStateBindings сняты).

Refs: plans/2026-07-03_god-split-design.md (§3, порядок разреза inspector).
"""

from __future__ import annotations

from typing import Any

from multiprocess_prototype.frontend.widgets.tabs.pipeline.inspector import (
    NodeInspectorPanel,
)

from ._helpers import make_pipeline_services

# Топология с явным воркером — для проверки списка воркеров и preselect.
_TOPO_WORKERS = {
    "processes": [
        {
            "process_name": "capture_proc",
            "plugins": [{"plugin_name": "blur"}],
            "workers": [
                {"worker_name": "grabber", "priority": "REALTIME", "target_interval_ms": 33},
            ],
        },
    ],
    "wires": [],
}


class _CountingBindings:
    """Двойник GuiStateBindings со счётчиками bind/unbind (баланс подписок)."""

    def __init__(self) -> None:
        self.bind_count = 0
        self.unbind_count = 0
        self.live: int = 0

    def bind(self, path: str, widget: Any, prop: str = "value", *, formatter: Any = None) -> tuple:
        self.bind_count += 1
        self.live += 1
        return ("handle", path, self.bind_count)

    def unbind(self, handle: Any) -> None:
        self.unbind_count += 1
        self.live -= 1


def _show_camera(panel: NodeInspectorPanel) -> None:
    panel.show_plugin_node(
        "camera_0.camera_service",
        category="source",
        plugin_name="camera_service",
        process_name="camera_0",
    )


def _show_processing(panel: NodeInspectorPanel) -> None:
    panel.show_plugin_node(
        "proc.color_mask",
        category="processing",
        plugin_name="color_mask",
        process_name="proc",
    )


# ------------------------------------------------------------------ #
#  show_plugin_node: заголовок / badge / видимость форм / индекс      #
# ------------------------------------------------------------------ #


class TestShowPluginNodeCharacterization:
    def test_title_badge_and_exec_info_visible(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show_plugin_node(
            "preprocessor",
            category="processing",
            plugin_name="resize",
            plugins=[{"plugin_name": "resize", "category": "processing"}],
            plugin_index=0,
        )
        assert panel._title.text() == "preprocessor"
        assert panel._category_badge.text() == "processing"
        assert not panel._content.isHidden()
        assert not panel._exec_info_form.isHidden()

    def test_plugin_index_propagated(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show_plugin_node(
            "preproc.grayscale",
            category="utility",
            plugin_name="grayscale",
            process_name="preproc",
            plugin_index=1,
        )
        assert panel.current_process == "preproc"
        assert panel.current_plugin_index == 1

    def test_target_process_form_hidden_without_processes(self, qtbot):
        """Форма IPC-таргета скрыта, когда список процессов рецепта пуст."""
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(make_pipeline_services(topology=_TOPO_WORKERS))
        _show_processing(panel)
        # Рецепт (FakeRecipeStore) пуст → combo disabled → форма скрыта.
        assert not panel._target_process_form.isVisibleTo(panel)

    def test_move_process_form_visible_in_plugin_mode(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(make_pipeline_services(topology=_TOPO_WORKERS))
        panel.show_plugin_node(
            "capture_proc.blur",
            category="processing",
            plugin_name="blur",
            process_name="capture_proc",
            plugins=[{"plugin_name": "blur"}],
        )
        # Строка «Процесс / Воркер» видима всегда в plugin-режиме.
        assert panel._move_process_form.isVisibleTo(panel)


# ------------------------------------------------------------------ #
#  show_display_node: display-combo / exec-info скрыт / io-debug спит  #
# ------------------------------------------------------------------ #


class TestShowDisplayNodeCharacterization:
    def test_display_mode_visibility(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        # Сначала plugin-нода, чтобы exec-info наполнился и потом очистился.
        panel.show_plugin_node(
            "preprocessor",
            category="processing",
            plugin_name="resize",
            plugins=[{"plugin_name": "resize", "category": "processing"}],
        )
        panel.show_display_node("main", "main", "Основной дисплей")

        assert panel._mode == "display"
        assert panel._display_id_form.isVisibleTo(panel)
        assert not panel._target_process_form.isVisibleTo(panel)
        assert not panel._move_process_form.isVisibleTo(panel)
        # Блок «Исполнение» очищен и скрыт.
        assert panel._exec_info_layout.count() == 0
        assert panel._exec_info_form.isHidden()


# ------------------------------------------------------------------ #
#  camera→не-camera: баланс bind/unbind = 0 (acceptance задачи)        #
# ------------------------------------------------------------------ #


class TestCameraActualBindBalance:
    def test_switch_camera_to_non_camera_balances(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        binds = _CountingBindings()
        panel.set_services(make_pipeline_services(topology=_TOPO_WORKERS), bindings=binds)

        _show_camera(panel)
        assert binds.bind_count > 0
        assert binds.live == binds.bind_count  # все подписки живы

        _show_processing(panel)
        # Все actual-хэндлы сняты при переходе на не-camera ноду.
        assert binds.unbind_count == binds.bind_count
        assert binds.live == 0
        assert panel._cam_actual_handles == []
        assert panel._cam_actual_form.isHidden()

    def test_clear_balances(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        binds = _CountingBindings()
        panel.set_services(make_pipeline_services(topology=_TOPO_WORKERS), bindings=binds)

        _show_camera(panel)
        panel.clear()
        assert binds.live == 0
        assert panel._cam_actual_handles == []

    def test_dispose_balances(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        binds = _CountingBindings()
        panel.set_services(make_pipeline_services(topology=_TOPO_WORKERS), bindings=binds)

        _show_camera(panel)
        panel.dispose()
        assert binds.live == 0
        assert panel._cam_actual_handles == []


# ------------------------------------------------------------------ #
#  Воркер-combo: preselect + field_changed один раз / ноль при suppress
# ------------------------------------------------------------------ #


class TestWorkerComboCharacterization:
    def _show_blur(self, panel: NodeInspectorPanel, params: dict | None = None) -> None:
        panel.show_plugin_node(
            node_id="capture_proc.blur",
            category="processing",
            process_name="capture_proc",
            plugin_name="blur",
            plugins=[{"plugin_name": "blur"}],
            params=params or {},
        )

    def test_preselect_assigned_worker(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(make_pipeline_services(topology=_TOPO_WORKERS))
        self._show_blur(panel, params={"assigned_worker": "grabber"})
        assert panel._move_worker_combo.currentData() == "grabber"

    def test_no_field_changed_during_populate(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(make_pipeline_services(topology=_TOPO_WORKERS))
        captured: list[tuple] = []
        panel.field_changed.connect(lambda p, f, v: captured.append((p, f, v)))
        self._show_blur(panel, params={"assigned_worker": "grabber"})
        assert all(f != "assigned_worker" for _p, f, _v in captured)

    def test_worker_selection_emits_once(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(make_pipeline_services(topology=_TOPO_WORKERS))
        self._show_blur(panel)
        captured: list[tuple] = []
        panel.field_changed.connect(lambda p, f, v: captured.append((p, f, v)))
        combo = panel._move_worker_combo
        idx = combo.findData("grabber")
        assert idx >= 0
        combo.setCurrentIndex(idx)
        assert captured.count(("capture_proc", "assigned_worker", "grabber")) == 1


# ------------------------------------------------------------------ #
#  clear() → нет дублей строк при повторном show; refresh no-op        #
# ------------------------------------------------------------------ #


class TestClearAndRefreshCharacterization:
    def test_no_duplicate_editors_on_reshow(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.show_node("camera", "source", params={"fps": "30", "gain": "1"})
        first_editors = set(panel._field_editors.keys())

        panel.show_node("camera", "source", params={"fps": "30", "gain": "1"})
        # Повторный show не накапливает редакторы (clear отработал).
        assert set(panel._field_editors.keys()) == first_editors
        assert len(panel._field_editors) == 2

    def test_refresh_display_combo_noop_in_plugin_mode(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(make_pipeline_services(topology=_TOPO_WORKERS))
        _show_processing(panel)
        assert panel._mode == "plugin"
        # В plugin-режиме refresh_display_combo — no-op (не падает, режим не меняется).
        panel.refresh_display_combo()
        assert panel._mode == "plugin"


# ------------------------------------------------------------------ #
#  Чистая логика (через стабильные швы панели): worker_label,          #
#  process_names_from_recipe, workers_for_process                      #
# ------------------------------------------------------------------ #


class TestPureLogicCharacterization:
    def test_worker_label_source(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        assert panel._worker_for_plugin("source", "capture", 0, 0) == (
            "source_producer_capture · свой поток (параллельно)"
        )

    def test_worker_label_processing_multi_step(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        label = panel._worker_for_plugin("processing", "resize", 2, 3)
        assert "pipeline_executor" in label
        assert "шаг 2/3" in label

    def test_worker_label_processing_single(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        assert panel._worker_for_plugin("processing", "resize", 1, 1) == (
            "pipeline_executor · последовательно"
        )

    def test_process_names_empty_without_recipe(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(make_pipeline_services(topology=_TOPO_WORKERS))
        # FakeRecipeStore пуст → нет активного рецепта → пустой список.
        assert panel._get_process_names_from_recipe() == []

    def test_process_names_from_recipe(self, qtbot):
        from multiprocess_prototype.domain.tests._fakes import FakeRecipeStore
        from multiprocess_prototype.domain.tests.conftest import make_test_app_services

        raw = {
            "r": {"blueprint": {"processes": [{"process_name": "a"}, {"process_name": "b"}], "wires": []}}
        }
        services = make_test_app_services(recipes=FakeRecipeStore(raw=raw, active="r"))
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(services)
        assert panel._get_process_names_from_recipe() == ["a", "b"]

    def test_workers_for_process_inserts_message_processor(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        panel.set_services(make_pipeline_services(topology=_TOPO_WORKERS))
        workers = panel._get_workers_for_process("capture_proc")
        assert workers[0] == "message_processor"
        assert "grabber" in workers

    def test_workers_for_process_no_services(self, qtbot):
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        # Без services — синтетический message_processor.
        assert panel._get_workers_for_process("whatever") == ["message_processor"]
