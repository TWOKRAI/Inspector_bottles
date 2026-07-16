"""Тесты BlueprintAssembler — паритет с дорогой A (boot).

Проверяем:
1. Паритет: assembler.assemble == старый инлайн-чейн (дорога A).
2. Чистота: входной dict не мутируется; повтор даёт идентичный результат.
3. BlueprintInvalid при невалидном blueprint.
4. Grep-чистота: в assembler.py нет ``multiprocess_prototype`` в import'ах.
5. Ф4.7: join/inspector из wires — регресс-тест на реальном assemble()-пути
   (без ЛЮБОЙ inspector-декларации join не деградирует в fanin).
6. PC 1.3: overlay секции telemetry (global + per-process merge, backward-compat)
   и что она реально доезжает до ``ProcessConfigHandler.get_config("telemetry")``.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from multiprocess_framework.modules.data_schema_module import process
from multiprocess_framework.modules.data_schema_module.core.helpers import (
    merge_with_defaults,
)
from multiprocess_framework.modules.process_manager_module.launcher.schema import (
    DEFAULT_PROCESS_SCHEMA,
)
from multiprocess_framework.modules.process_module.configs import expand_observability
from multiprocess_framework.modules.process_module.configs.managers_config import (
    merge_managers,
)
from multiprocess_framework.modules.process_module.configs.process_config_handler import (
    ProcessConfigHandler,
)
from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
    SystemBlueprint,
)
from multiprocess_framework.modules.process_module.plugins.base import ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry

from multiprocess_prototype.backend.assembly.assembler import (
    BlueprintAssembler,
    BlueprintInvalid,
)


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

# Минимальная валидная топология — один процесс без плагинов.
_MINIMAL_BLUEPRINT: dict = {
    "name": "test_topology",
    "description": "Топология для тестов assembler",
    "processes": [
        {
            "process_name": "worker_a",
            "process_class": "some.module.WorkerA",
            "plugins": [],
        },
    ],
    "wires": [],
}

# Топология с несколькими процессами — ближе к production.
_MULTI_PROCESS_BLUEPRINT: dict = {
    "name": "multi_test",
    "description": "Несколько процессов",
    "processes": [
        {
            "process_name": "camera_0",
            "process_class": "some.module.CameraApp",
            "priority": "high",
            "plugins": [],
        },
        {
            "process_name": "processor",
            "process_class": "some.module.ProcessorApp",
            "plugins": [],
        },
        {
            "process_name": "renderer",
            "process_class": "some.module.RendererApp",
            "plugins": [],
        },
    ],
    "wires": [],
}

# Observability overlay для тестов (типичная структура).
_OBS_OVERLAY: dict = expand_observability({"log_level": "DEBUG"})


def _build_reference_road_a(
    bp_dict: dict,
    obs_overlay: dict,
    log_dir: str = "logs",
) -> dict[str, dict]:
    """Эталонная дорога A: СТАРЫЙ инлайн-чейн из ``SystemBuilder.build``.

    Реплицирует точную последовательность:
    1. model_validate → check → build_configs
    2. log_dir loop
    3. process(cfg) → merge_managers → merge_with_defaults
    """
    topology = SystemBlueprint.model_validate(bp_dict)
    errors = topology.check()
    assert not errors, f"Эталон-топология невалидна: {errors}"

    configs = topology.build_configs()
    for cfg in configs:
        if not cfg.log_dir:
            cfg.log_dir = log_dir

    result: dict[str, dict] = {}
    for cfg in configs:
        name, proc_dict = process(cfg)
        proc_dict["managers"] = merge_managers(proc_dict.get("managers", {}), obs_overlay)
        proc_dict = merge_with_defaults(proc_dict, DEFAULT_PROCESS_SCHEMA)
        result[name] = proc_dict

    return result


# ---------------------------------------------------------------------------
# Тесты паритета с дорогой A
# ---------------------------------------------------------------------------


class TestRoadAParity:
    """Assembler.assemble == старый инлайн-чейн (дорога A)."""

    def test_minimal_blueprint_parity(self) -> None:
        """Минимальная топология: assembler == дорога A."""
        bp = copy.deepcopy(_MINIMAL_BLUEPRINT)
        reference = _build_reference_road_a(bp, _OBS_OVERLAY)

        bp2 = copy.deepcopy(_MINIMAL_BLUEPRINT)
        assembler = BlueprintAssembler(observability_dict=_OBS_OVERLAY, log_dir="logs")
        actual = assembler.assemble(bp2)

        assert actual == reference

    def test_multi_process_parity(self) -> None:
        """Несколько процессов: assembler == дорога A."""
        bp = copy.deepcopy(_MULTI_PROCESS_BLUEPRINT)
        reference = _build_reference_road_a(bp, _OBS_OVERLAY)

        bp2 = copy.deepcopy(_MULTI_PROCESS_BLUEPRINT)
        assembler = BlueprintAssembler(observability_dict=_OBS_OVERLAY, log_dir="logs")
        actual = assembler.assemble(bp2)

        assert actual == reference

    def test_custom_log_dir_parity(self, tmp_path) -> None:
        """Кастомный log_dir: assembler == дорога A.

        tmp_path вместо системного пути: managers_from_log_dir делает mkdir
        каталога логов, а /var/log/* требует root → PermissionError на macOS.
        """
        custom_log_dir = str(tmp_path / "custom_logs")
        bp = copy.deepcopy(_MINIMAL_BLUEPRINT)
        reference = _build_reference_road_a(bp, _OBS_OVERLAY, log_dir=custom_log_dir)

        bp2 = copy.deepcopy(_MINIMAL_BLUEPRINT)
        assembler = BlueprintAssembler(observability_dict=_OBS_OVERLAY, log_dir=custom_log_dir)
        actual = assembler.assemble(bp2)

        assert actual == reference

    def test_process_names_match(self) -> None:
        """Ключи результата == имена процессов из topology."""
        assembler = BlueprintAssembler(observability_dict=_OBS_OVERLAY)
        result = assembler.assemble(copy.deepcopy(_MULTI_PROCESS_BLUEPRINT))
        assert set(result.keys()) == {"camera_0", "processor", "renderer"}

    def test_merge_with_defaults_applied(self) -> None:
        """merge_with_defaults применён: обязательные ключи заполнены."""
        assembler = BlueprintAssembler(observability_dict=_OBS_OVERLAY)
        result = assembler.assemble(copy.deepcopy(_MINIMAL_BLUEPRINT))

        proc_dict = result["worker_a"]
        for key in DEFAULT_PROCESS_SCHEMA:
            assert key in proc_dict, f"Ключ '{key}' отсутствует после merge_with_defaults"

    def test_observability_overlay_applied(self) -> None:
        """Observability overlay применён к managers каждого процесса."""
        obs = expand_observability({"log_level": "WARNING"})
        assembler = BlueprintAssembler(observability_dict=obs)
        result = assembler.assemble(copy.deepcopy(_MINIMAL_BLUEPRINT))

        proc_dict = result["worker_a"]
        managers = proc_dict.get("managers", {})
        # overlay должен был проставить уровни логирования
        assert managers, "managers пуст — overlay не применён"


# ---------------------------------------------------------------------------
# Тесты чистоты
# ---------------------------------------------------------------------------


class TestPurity:
    """assemble не мутирует входной dict; детерминирован."""

    def test_input_not_mutated(self) -> None:
        """Входной blueprint dict не мутируется после assemble."""
        original = copy.deepcopy(_MINIMAL_BLUEPRINT)
        snapshot = copy.deepcopy(original)

        assembler = BlueprintAssembler(observability_dict=_OBS_OVERLAY)
        assembler.assemble(original)

        assert original == snapshot, "assemble мутировал входной dict"

    def test_deterministic(self) -> None:
        """Повторный вызов с тем же входом даёт идентичный результат."""
        assembler = BlueprintAssembler(observability_dict=_OBS_OVERLAY)
        result_1 = assembler.assemble(copy.deepcopy(_MINIMAL_BLUEPRINT))
        result_2 = assembler.assemble(copy.deepcopy(_MINIMAL_BLUEPRINT))
        assert result_1 == result_2


# ---------------------------------------------------------------------------
# Тесты валидации
# ---------------------------------------------------------------------------


class TestValidation:
    """Невалидный blueprint → BlueprintInvalid."""

    def test_invalid_duplicate_process_names(self) -> None:
        """Дублирующиеся имена процессов → BlueprintInvalid с ошибками."""
        bp = {
            "name": "invalid",
            "processes": [
                {"process_name": "dup", "process_class": "a.B", "plugins": []},
                {"process_name": "dup", "process_class": "c.D", "plugins": []},
            ],
            "wires": [],
        }
        assembler = BlueprintAssembler(observability_dict=_OBS_OVERLAY)
        with pytest.raises(BlueprintInvalid) as exc_info:
            assembler.assemble(bp)
        assert len(exc_info.value.errors) > 0
        assert any("dup" in e for e in exc_info.value.errors)

    def test_blueprint_invalid_has_errors_list(self) -> None:
        """BlueprintInvalid содержит атрибут errors: list[str]."""
        bp = {
            "name": "invalid",
            "processes": [
                {"process_name": "x", "process_class": "a.B", "plugins": []},
                {"process_name": "x", "process_class": "c.D", "plugins": []},
            ],
            "wires": [],
        }
        assembler = BlueprintAssembler(observability_dict=_OBS_OVERLAY)
        with pytest.raises(BlueprintInvalid) as exc_info:
            assembler.assemble(bp)
        assert isinstance(exc_info.value.errors, list)
        assert all(isinstance(e, str) for e in exc_info.value.errors)


# ---------------------------------------------------------------------------
# PC 1.3: telemetry overlay — global default + per-process override
# ---------------------------------------------------------------------------

# Глобальный дефолт telemetry.publish (форма TelemetryPublishConfig.model_dump()).
_TELEMETRY_GLOBAL: dict = {
    "default_interval_sec": 1.0,
    "metrics": {
        "fps": {"enabled": True, "interval_sec": 1.0},
        "cycle_duration_ms": {"enabled": False, "interval_sec": None},
    },
}

# Топология с per-process telemetry override только у "processor" (fps выключен).
_TELEMETRY_OVERRIDE_BLUEPRINT: dict = {
    "name": "telemetry_test",
    "description": "per-process telemetry override у одного процесса",
    "processes": [
        {
            "process_name": "camera_0",
            "process_class": "some.module.CameraApp",
            "plugins": [],
        },
        {
            "process_name": "processor",
            "process_class": "some.module.ProcessorApp",
            "plugins": [],
            "telemetry": {"metrics": {"fps": {"enabled": False}}},
        },
        {
            "process_name": "renderer",
            "process_class": "some.module.RendererApp",
            "plugins": [],
        },
    ],
    "wires": [],
}


class TestTelemetryOverlay:
    """proc_dict['config']['telemetry'] — только когда реально задано (backward-compat)."""

    def test_no_telemetry_anywhere_no_key_injected(self) -> None:
        """Нет telemetry_dict в конструкторе И нет per-process override → ключ 'telemetry'
        отсутствует НИ В ОДНОМ proc_dict (critical для PC 1.2: TelemetryGate=None)."""
        assembler = BlueprintAssembler(observability_dict=_OBS_OVERLAY, log_dir="logs")
        result = assembler.assemble(copy.deepcopy(_MULTI_PROCESS_BLUEPRINT))

        for name, proc_dict in result.items():
            assert "telemetry" not in proc_dict["config"], (
                f"proc_dict['{name}']['config'] содержит 'telemetry' без явной секции нигде"
            )

    def test_global_default_applied_to_all_processes(self) -> None:
        """Глобальный telemetry_dict → ВСЕ proc_dict получают одинаковую секцию telemetry."""
        assembler = BlueprintAssembler(
            observability_dict=_OBS_OVERLAY,
            log_dir="logs",
            telemetry_dict=_TELEMETRY_GLOBAL,
        )
        result = assembler.assemble(copy.deepcopy(_MULTI_PROCESS_BLUEPRINT))

        for name, proc_dict in result.items():
            assert proc_dict["config"]["telemetry"] == {"publish": _TELEMETRY_GLOBAL}, name

    def test_per_process_override_merges_over_global(self) -> None:
        """Per-process override перекрывает ТОЛЬКО свою метрику; у других процессов —
        global без изменений (регресс-тест на merge-семантику)."""
        assembler = BlueprintAssembler(
            observability_dict=_OBS_OVERLAY,
            log_dir="logs",
            telemetry_dict=_TELEMETRY_GLOBAL,
        )
        result = assembler.assemble(copy.deepcopy(_TELEMETRY_OVERRIDE_BLUEPRINT))

        # "processor" — fps выключен override'ом, cycle_duration_ms не тронут (наследован).
        processor_publish = result["processor"]["config"]["telemetry"]["publish"]
        assert processor_publish["metrics"]["fps"]["enabled"] is False
        assert processor_publish["metrics"]["cycle_duration_ms"]["enabled"] is False
        assert processor_publish["default_interval_sec"] == 1.0

        # "camera_0"/"renderer" — без override, глобальный default как есть (fps enabled).
        for name in ("camera_0", "renderer"):
            publish = result[name]["config"]["telemetry"]["publish"]
            assert publish == _TELEMETRY_GLOBAL, name

    def test_per_process_only_no_global(self) -> None:
        """Нет глобального telemetry_dict, но у ОДНОГО процесса есть override →
        telemetry-ключ появляется ТОЛЬКО у него."""
        assembler = BlueprintAssembler(observability_dict=_OBS_OVERLAY, log_dir="logs")
        result = assembler.assemble(copy.deepcopy(_TELEMETRY_OVERRIDE_BLUEPRINT))

        assert "telemetry" not in result["camera_0"]["config"]
        assert "telemetry" not in result["renderer"]["config"]
        assert result["processor"]["config"]["telemetry"] == {"publish": {"metrics": {"fps": {"enabled": False}}}}

    def test_default_interval_sec_override_replaces_global_scalar(self) -> None:
        """default_interval_sec — скалярное поле, per-process override заменяет
        значение целиком (не мержится по-полям)."""
        bp = copy.deepcopy(_MINIMAL_BLUEPRINT)
        bp["processes"][0]["telemetry"] = {"default_interval_sec": 5.0}
        assembler = BlueprintAssembler(
            observability_dict=_OBS_OVERLAY,
            log_dir="logs",
            telemetry_dict=_TELEMETRY_GLOBAL,
        )
        result = assembler.assemble(bp)

        publish = result["worker_a"]["config"]["telemetry"]["publish"]
        assert publish["default_interval_sec"] == 5.0
        # metrics по-прежнему унаследованы из global (не стёрты override'ом).
        assert publish["metrics"] == _TELEMETRY_GLOBAL["metrics"]

    def test_telemetry_overlay_does_not_mutate_input(self) -> None:
        """assemble() с telemetry-override не мутирует входной blueprint_dict."""
        original = copy.deepcopy(_TELEMETRY_OVERRIDE_BLUEPRINT)
        snapshot = copy.deepcopy(original)

        assembler = BlueprintAssembler(
            observability_dict=_OBS_OVERLAY,
            log_dir="logs",
            telemetry_dict=_TELEMETRY_GLOBAL,
        )
        assembler.assemble(original)

        assert original == snapshot, "assemble() мутировал входной dict (telemetry override)"

    def test_telemetry_dict_constructor_arg_not_mutated(self) -> None:
        """Повторные assemble() не мутируют _TELEMETRY_GLOBAL, переданный в конструктор."""
        snapshot = copy.deepcopy(_TELEMETRY_GLOBAL)
        assembler = BlueprintAssembler(
            observability_dict=_OBS_OVERLAY,
            log_dir="logs",
            telemetry_dict=_TELEMETRY_GLOBAL,
        )
        assembler.assemble(copy.deepcopy(_TELEMETRY_OVERRIDE_BLUEPRINT))
        assembler.assemble(copy.deepcopy(_TELEMETRY_OVERRIDE_BLUEPRINT))

        assert _TELEMETRY_GLOBAL == snapshot, "telemetry_dict конструктора был мутирован"

    def test_get_config_telemetry_reaches_process_config_handler(self) -> None:
        """Интеграция: proc_dict['config'] → ProcessConfigHandler.get_config('telemetry')
        отдаёт ту же секцию, что собрал assembler (путь, которым реально читает heartbeat,
        см. process_heartbeat.py::_build_telemetry_gate → get_config('telemetry'))."""
        assembler = BlueprintAssembler(
            observability_dict=_OBS_OVERLAY,
            log_dir="logs",
            telemetry_dict=_TELEMETRY_GLOBAL,
        )
        result = assembler.assemble(copy.deepcopy(_TELEMETRY_OVERRIDE_BLUEPRINT))

        handler = ProcessConfigHandler("processor", config=result["processor"]["config"])
        telemetry = handler.get_config("telemetry")

        assert telemetry == result["processor"]["config"]["telemetry"]
        assert telemetry["publish"]["metrics"]["fps"]["enabled"] is False

    def test_get_config_telemetry_none_when_not_configured(self) -> None:
        """Backward-compat через тот же путь: без секции нигде get_config('telemetry')
        отдаёт default (None) — heartbeat трактует это как «гейт неактивен»."""
        assembler = BlueprintAssembler(observability_dict=_OBS_OVERLAY, log_dir="logs")
        result = assembler.assemble(copy.deepcopy(_MINIMAL_BLUEPRINT))

        handler = ProcessConfigHandler("worker_a", config=result["worker_a"]["config"])
        assert handler.get_config("telemetry", None) is None


# ---------------------------------------------------------------------------
# Grep-проверка: в assembler.py нет multiprocess_prototype в import'ах
# ---------------------------------------------------------------------------


class TestImportPurity:
    """assembler.py не импортирует multiprocess_prototype — framework-чист."""

    def test_no_prototype_imports(self) -> None:
        """В assembler.py нет строк import с 'multiprocess_prototype'."""
        assembler_path = Path(__file__).resolve().parent.parent / "assembler.py"
        source = assembler_path.read_text(encoding="utf-8")
        for i, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            # Пропускаем комментарии и docstrings
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'"):
                continue
            if "import" in stripped and "multiprocess_prototype" in stripped:
                pytest.fail(f"assembler.py:{i} содержит prototype-импорт: {stripped!r}")

    def test_no_system_config_import(self) -> None:
        """В assembler.py нет импорта SystemConfig."""
        assembler_path = Path(__file__).resolve().parent.parent / "assembler.py"
        source = assembler_path.read_text(encoding="utf-8")
        for i, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "import" in stripped and "SystemConfig" in stripped:
                pytest.fail(f"assembler.py:{i} содержит SystemConfig-импорт: {stripped!r}")


# ---------------------------------------------------------------------------
# Ф4.7: join/inspector из wires — регресс на реальном assemble()-пути
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=False)
def _clean_registry():
    """Изолировать глобальный PluginRegistry вокруг join-тестов — snapshot/restore.

    НЕ ``PluginRegistry.clear()`` (как в test_blueprint_chain_validation.py): этот файл
    лежит в multiprocess_prototype и в общем pytest-прогоне (``pytest multiprocess_
    prototype``) собирается/выполняется РАНЬШЕ ``test_build_characterization.py`` и
    frontend-тестов (sandbox_e2e/control_panel), которым нужна РЕАЛЬНАЯ discovery
    ``Plugins/*`` — ``clear()`` стирал бы её безвозвратно: ``PluginRegistry.discover()``
    импортирует plugin-модули через ``importlib.import_module``, а уже импортированный
    модуль Python не переисполняет ``@register_plugin`` при повторном discover() (кеш
    ``sys.modules``), поэтому once-cleared реестр НЕ самовосстанавливается — ловили
    регрессию (25 упавших тестов в full-suite прогоне) именно на этом.

    Публичный ``snapshot()``/``restore()`` (AU-5, follow-up В1) — вместо прямого
    доступа к приватному ``_plugins``.
    """
    snapshot = PluginRegistry.snapshot()
    PluginRegistry.clear()
    yield
    PluginRegistry.clear()
    PluginRegistry.restore(snapshot)


class _CircleDetector(ProcessModulePlugin):
    """Источник frame+detections одним item (двойник vision.circle_detector)."""

    name = "circle_detector"
    category = "processing"
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)"),
        Port(name="detections", dtype="list[dict]", shape="N"),
    ]

    def configure(self, ctx): ...
    def start(self, ctx): ...


class _LineFilter(ProcessModulePlugin):
    """Источник overlay-item (двойник line.line_filter)."""

    name = "line_filter"
    category = "processing"
    outputs = [Port(name="overlay", dtype="dict", shape="-")]

    def configure(self, ctx): ...
    def start(self, ctx): ...


class _OverlayDraw(ProcessModulePlugin):
    """draw-подобный join: frame+overlay REQUIRED (двойник overlay_draw)."""

    name = "overlay_draw"
    category = "rendering"
    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)"),
        Port(name="overlay", dtype="dict", shape="-"),
    ]
    outputs = [Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")]

    def configure(self, ctx): ...
    def start(self, ctx): ...


_JOIN_BLUEPRINT: dict = {
    "name": "join_from_wires",
    "description": "draw-подобный join БЕЗ единой inspector-декларации где-либо",
    "processes": [
        {
            "process_name": "vision",
            "plugins": [{"plugin_name": "circle_detector", "plugin_class": ""}],
        },
        {
            "process_name": "line",
            "plugins": [{"plugin_name": "line_filter", "plugin_class": ""}],
        },
        {
            "process_name": "draw",
            "plugins": [{"plugin_name": "overlay_draw", "plugin_class": ""}],
        },
    ],
    "wires": [
        {"source": "vision.circle_detector.frame", "target": "draw.overlay_draw.frame"},
        {"source": "line.line_filter.overlay", "target": "draw.overlay_draw.overlay"},
    ],
}


class TestJoinFromWires:
    """Ф4.7: join выводится из wires на реальном assemble()-пути (снят hoist-костыль)."""

    def test_join_not_degraded_to_fanin(self, _clean_registry) -> None:
        """Регресс-тест (acceptance Ф4.7): без ЛЮБОЙ inspector-декларации join не
        деградирует в fanin — assembler.assemble() выводит его из wires."""
        for cls in (_CircleDetector, _LineFilter, _OverlayDraw):
            PluginRegistry.register(name=cls.name, plugin_class=cls, category=cls.category)

        assembler = BlueprintAssembler(observability_dict=_OBS_OVERLAY)
        result = assembler.assemble(copy.deepcopy(_JOIN_BLUEPRINT))

        inspector = result["draw"]["config"]["inspector"]
        assert inspector["mode"] == "join", inspector
        assert inspector["mode"] != "fanin"
        assert sorted(inspector["inputs"]) == ["frame", "overlay"]
        assert inspector["primary"] == "frame"
