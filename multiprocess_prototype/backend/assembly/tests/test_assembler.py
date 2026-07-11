"""Тесты BlueprintAssembler — паритет с дорогой A (boot).

Проверяем:
1. Паритет: assembler.assemble == старый инлайн-чейн (дорога A).
2. Чистота: входной dict не мутируется; повтор даёт идентичный результат.
3. BlueprintInvalid при невалидном blueprint.
4. Grep-чистота: в assembler.py нет ``multiprocess_prototype`` в import'ах.
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
from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
    SystemBlueprint,
)

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
