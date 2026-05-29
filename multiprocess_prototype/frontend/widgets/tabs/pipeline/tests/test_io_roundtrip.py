"""Тесты двусторонней сериализации PipelineModel ↔ SystemBlueprint.

Без pytest-qt — чистый Python (io.py не зависит от Qt).
Запуск:
    python -m pytest multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_io_roundtrip.py -v
"""

from __future__ import annotations

import warnings

import pytest

from multiprocess_prototype.frontend.widgets.tabs.pipeline.io import (
    blueprint_to_graph,
    graph_to_blueprint,
)
from multiprocess_prototype.frontend.widgets.tabs.pipeline.model import PipelineModel


# ---------------------------------------------------------------------------
# Вспомогательные fixture'ы
# ---------------------------------------------------------------------------


def _make_model_two_procs_wire() -> PipelineModel:
    """Два процесса + один process-wire."""
    model = PipelineModel()
    model.add_process("cam", plugin_name="CapturePlugin", category="source")
    model.add_process("proc", plugin_name="ColorMaskPlugin", category="processing")
    model.add_wire("cam.CapturePlugin.frame", "proc.ColorMaskPlugin.frame")
    return model


def _make_model_full() -> PipelineModel:
    """Два процесса + process-wire + display-привязка (G.4.2b: binding, не wire)."""
    model = _make_model_two_procs_wire()
    # display = binding: node_id — source endpoint выхода, display_id — канал
    model.add_display("proc.ColorMaskPlugin.result", "main_output", display_name="Главный экран")
    return model


# ---------------------------------------------------------------------------
# Тест 1: пустой граф
# ---------------------------------------------------------------------------


class TestEmptyGraphRoundtrip:
    """Пустой граф → blueprint → graph → пустая модель."""

    def test_empty_graph_roundtrip(self) -> None:
        """Пустой граф сериализуется без ошибок, при восстановлении модель пуста."""
        model = PipelineModel()
        bp, bindings, positions = graph_to_blueprint(model, name="empty")

        # Blueprint корректный — пустые списки
        assert bp["name"] == "empty"
        assert bp["processes"] == []
        assert bp["wires"] == []
        assert bindings == []
        assert positions == {}

        # Восстановление
        model2 = PipelineModel()
        blueprint_to_graph(bp, bindings, model2)
        topo = model2.to_topology_dict()
        assert topo["processes"] == []
        assert topo["wires"] == []
        assert topo.get("displays", []) == []


# ---------------------------------------------------------------------------
# Тест 2: только процессы (без wires/displays)
# ---------------------------------------------------------------------------


class TestProcessesOnlyRoundtrip:
    """3 процесса с плагинами, без wires/displays."""

    def test_processes_only_roundtrip(self) -> None:
        """3 процесса восстанавливаются после round-trip."""
        model = PipelineModel()
        model.add_process("alpha", plugin_name="P1", category="source")
        model.add_process("beta", plugin_name="P2", category="processing")
        model.add_process("gamma", plugin_name="P3", category="output")

        bp, bindings, _ = graph_to_blueprint(model, name="three_procs")

        assert len(bp["processes"]) == 3
        names_in_bp = [p["process_name"] for p in bp["processes"]]
        assert "alpha" in names_in_bp
        assert "beta" in names_in_bp
        assert "gamma" in names_in_bp
        assert bindings == []
        assert bp["wires"] == []

        # Восстановление
        model2 = PipelineModel()
        blueprint_to_graph(bp, bindings, model2)
        assert sorted(model2.get_process_names()) == ["alpha", "beta", "gamma"]


# ---------------------------------------------------------------------------
# Тест 3: процессы + wires
# ---------------------------------------------------------------------------


class TestProcessesAndWiresRoundtrip:
    """Процессы + 2 process-wire."""

    def test_processes_and_wires_roundtrip(self) -> None:
        """Процессы и wire'ы корректно сериализуются и восстанавливаются."""
        model = PipelineModel()
        model.add_process("A", plugin_name="PA")
        model.add_process("B", plugin_name="PB")
        model.add_process("C", plugin_name="PC")
        model.add_wire("A.PA.out", "B.PB.in")
        model.add_wire("B.PB.out", "C.PC.in")

        bp, bindings, _ = graph_to_blueprint(model)
        assert len(bp["wires"]) == 2
        assert bindings == []

        # Источники/приёмники сохранились
        sources = {w["source"] for w in bp["wires"]}
        targets = {w["target"] for w in bp["wires"]}
        assert "A.PA.out" in sources
        assert "C.PC.in" in targets

        # Восстановление
        model2 = PipelineModel()
        blueprint_to_graph(bp, bindings, model2)
        wires2 = model2.get_wires()
        assert len(wires2) == 2


# ---------------------------------------------------------------------------
# Тест 4: полный round-trip с displays
# ---------------------------------------------------------------------------


class TestFullRoundtripWithDisplays:
    """2 процесса + process-wire + display + display-binding."""

    def test_full_roundtrip_with_displays(self) -> None:
        """Полный round-trip с display-привязкой сохраняет все компоненты (G.4.2b)."""
        model = _make_model_full()

        bp, bindings, _ = graph_to_blueprint(model, name="full_test")

        # Восстановление
        model2 = PipelineModel()
        blueprint_to_graph(bp, bindings, model2)

        # Процессы сохранились
        assert sorted(model2.get_process_names()) == ["cam", "proc"]

        # Display-привязка восстановлена (binding: source endpoint → канал)
        displays = model2.get_displays()
        assert len(displays) == 1
        assert displays[0]["display_id"] == "main_output"
        assert displays[0]["node_id"] == "proc.ColorMaskPlugin.result"

        # Wire'ы: только один process-wire (display-wire не существует)
        wires = model2.get_wires()
        assert len(wires) == 1
        assert not any(w["target"].startswith("display.") for w in wires)


# ---------------------------------------------------------------------------
# Тест 5: display wire'ы исключены из blueprint["wires"]
# ---------------------------------------------------------------------------


class TestDisplayWiresExcludedFromBlueprint:
    """display-привязки идут в display_bindings, не в blueprint["wires"]."""

    def test_display_bindings_separate_from_wires(self) -> None:
        """blueprint['wires'] не содержит display-endpoint; привязка — в bindings."""
        model = _make_model_full()
        bp, bindings, _ = graph_to_blueprint(model)

        # Ни один wire в blueprint["wires"] не должен иметь display-endpoint
        for wire in bp["wires"]:
            assert not wire["target"].startswith("display."), f"Wire к display найден в blueprint: {wire}"

        # display-привязка попала в bindings
        assert len(bindings) == 1


# ---------------------------------------------------------------------------
# Тест 6: формат display_bindings
# ---------------------------------------------------------------------------


class TestDisplayBindingsFormat:
    """display_binding имеет правильную структуру."""

    def test_display_bindings_format(self) -> None:
        """Каждая запись display_bindings содержит ключи node_id и display_id (v3)."""
        model = _make_model_full()
        _, bindings, _ = graph_to_blueprint(model)

        assert len(bindings) == 1
        binding = bindings[0]

        assert "node_id" in binding, "Отсутствует ключ 'node_id' в binding"
        assert "display_id" in binding, "Отсутствует ключ 'display_id' в binding"

        # node_id — строка вида "proc.plugin.port" (источник-эндпоинт)
        assert isinstance(binding["node_id"], str)
        assert binding["node_id"].count(".") >= 2

        # display_id — идентификатор дисплея (строка)
        assert binding["display_id"] == "main_output"


# ---------------------------------------------------------------------------
# Тест 7: blueprint_to_graph очищает модель
# ---------------------------------------------------------------------------


class TestBlueprintToGraphClearsModel:
    """Модель с предыдущими данными очищается перед заполнением."""

    def test_blueprint_to_graph_clears_model(self) -> None:
        """Предыдущие данные модели не остаются после blueprint_to_graph."""
        # Модель с «грязными» данными
        dirty_model = PipelineModel()
        dirty_model.add_process("OLD_PROC", plugin_name="OldPlugin")
        dirty_model.add_display("old_display", "old_id")

        # Чистый blueprint без процессов из «грязной» модели
        clean_model = PipelineModel()
        clean_model.add_process("NEW_PROC", plugin_name="NewPlugin")
        bp, bindings, _ = graph_to_blueprint(clean_model, name="clean")

        # Загружаем в грязную модель — должно очиститься
        blueprint_to_graph(bp, bindings, dirty_model)

        process_names = dirty_model.get_process_names()
        assert "OLD_PROC" not in process_names
        assert "NEW_PROC" in process_names
        assert dirty_model.get_displays() == []


# ---------------------------------------------------------------------------
# Тест 8: target_process сохраняется при round-trip
# ---------------------------------------------------------------------------


class TestTargetProcessPreserved:
    """Поле target_process сохраняется при round-trip."""

    def test_target_process_preserved(self) -> None:
        """target_process из topology['processes'] не теряется при round-trip."""
        model = PipelineModel()
        model.add_process("plugin_node", plugin_name="SomePlugin")

        # Вручную добавляем target_process (как это делает presenter)
        for p in model._topology.get("processes", []):
            if p.get("process_name") == "plugin_node":
                p["target_process"] = "worker_proc"
                break

        bp, bindings, _ = graph_to_blueprint(model)

        # target_process присутствует в blueprint
        proc_in_bp = next((p for p in bp["processes"] if p.get("process_name") == "plugin_node"), None)
        assert proc_in_bp is not None
        assert proc_in_bp.get("target_process") == "worker_proc"

        # После восстановления — поле сохранено в topology
        model2 = PipelineModel()
        blueprint_to_graph(bp, bindings, model2)

        restored_proc = next(
            (p for p in model2._topology.get("processes", []) if p.get("process_name") == "plugin_node"),
            None,
        )
        assert restored_proc is not None
        assert restored_proc.get("target_process") == "worker_proc"


# ---------------------------------------------------------------------------
# Тест 9: SystemBlueprint.model_validate не падает
# ---------------------------------------------------------------------------


class TestBlueprintPydanticValidation:
    """graph_to_blueprint возвращает dict, совместимый с SystemBlueprint.model_validate."""

    def test_blueprint_pydantic_validation(self) -> None:
        """SystemBlueprint.model_validate(blueprint_dict) не вызывает исключение."""
        from multiprocess_framework.modules.process_module.generic.blueprint import (
            SystemBlueprint,
        )

        model = _make_model_two_procs_wire()
        bp, _, _ = graph_to_blueprint(model, name="validated")

        # Не должно упасть
        parsed = SystemBlueprint.model_validate(bp)
        assert parsed.name == "validated"
        assert len(parsed.wires) == 1

    def test_blueprint_pydantic_validation_with_target_process(self) -> None:
        """target_process в processes не ломает SystemBlueprint.model_validate."""
        from multiprocess_framework.modules.process_module.generic.blueprint import (
            SystemBlueprint,
        )

        model = PipelineModel()
        model.add_process("node1", plugin_name="P1")

        # Добавляем мета-поле
        for p in model._topology.get("processes", []):
            if p.get("process_name") == "node1":
                p["target_process"] = "some_worker"

        bp, _, _ = graph_to_blueprint(model)

        # Pydantic должен валидировать без ошибок (extra поля игнорируются)
        try:
            SystemBlueprint.model_validate(bp)
        except Exception as exc:
            pytest.fail(f"SystemBlueprint.model_validate упал с ошибкой: {exc}")


# ---------------------------------------------------------------------------
# Тест 10: orphan display_binding не вызывает краш
# ---------------------------------------------------------------------------


class TestOrphanDisplayBindingNoCrash:
    """display_binding ссылается на отсутствующий source — load не падает."""

    def test_orphan_display_binding_no_crash(self) -> None:
        """Загрузка binding'а с несуществующим source-процессом не падает."""
        # Blueprint без процессов
        bp: dict = {
            "name": "orphan_test",
            "description": "",
            "processes": [],
            "wires": [],
        }
        # Binding ссылается на несуществующий процесс (формат v3)
        bindings = [{"node_id": "ghost_proc.ghost_plugin.frame", "display_id": "missing_display"}]

        model = PipelineModel()

        # Не должно падать — только warning
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            blueprint_to_graph(bp, bindings, model)

        # display-узел создан (display_id = "missing_display")
        displays = model.get_displays()
        assert len(displays) == 1
        assert displays[0]["display_id"] == "missing_display"

    def test_orphan_display_binding_display_registry_none(self) -> None:
        """display_registry=None не вызывает исключение."""
        bp: dict = {
            "name": "no_registry",
            "description": "",
            "processes": [],
            "wires": [],
        }
        bindings = [{"node_id": "proc.plugin.port", "display_id": "some_display"}]

        model = PipelineModel()

        # display_registry=None по умолчанию — не падаем
        blueprint_to_graph(bp, bindings, model, display_registry=None)

        displays = model.get_displays()
        assert len(displays) == 1
        assert displays[0]["display_name"] == ""
