# -*- coding: utf-8 -*-
"""S-24 / S-25 — приёмочные тесты горячей пересборки топологии.

S-24: слой L1 наблюдаемости (секция ``observability`` system.yaml, СЫРАЯ —
``SystemConfig.observability.model_dump(exclude_unset=True)``) не имеет права
материализоваться (обрасти дефолтами фреймворка) при переезде дампа
``SystemConfig`` из лончера в ProcessManager.

S-25: устройства top-level секции ``devices:`` рецепта обязаны доезжать до
конфига плагина ``device_hub`` процесса ``devices`` и при ГОРЯЧЕЙ пересборке
(не только на boot).

НЕЗАВИСИМЫЙ ТЕСТЕР: ``launch.py``, ``orchestrator_hooks.py`` и
``recipes/devices_sync.py`` НЕ читались — критерии проверяются по контракту,
описанному в задании и подтверждённому разрешёнными файлами (``schemas.py``,
``assembly/assembler.py``, существующие тесты). Часть тестов ниже — заведомо
КРАСНАЯ, пока фикс не внесён; это ожидаемый результат независимой приёмки, а
не брак теста.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from multiprocess_framework.modules.process_module.configs.observability_layers import (
    APP_CONFIG_KEY,
)
from multiprocess_prototype.backend.config.schemas import SystemConfig, load_system_config
from multiprocess_prototype.backend.launch import sys_config_for_orchestrator
from multiprocess_prototype.backend.orchestrator_hooks import configure_topology_engine

from ._orchestrator_stub_contract import assert_stub_speaks_the_real_class_surface

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HEADLESS_CLASS = "multiprocess_prototype.frontend.headless_process.HeadlessGuiProcess"
GENERIC_CLASS = "multiprocess_prototype.generic_process_app.GenericProcessApp"
DEVICE_HUB_CLASS = "Plugins.hub.device_hub.plugin.DeviceHubPlugin"

#: Самодельный минимальный system.yaml — только ДВА ключа секции observability
#: заданы явно (log_level, console). Остальные ключи схемы обязаны остаться
#: "unset" — на этом держатся A3/A4/A5.
_MINIMAL_YAML = """
observability:
  log_level: DEBUG
  console: false
"""


# ---------------------------------------------------------------------------
# Обвязка (взята из разрешённого примера test_presentation_overlay_on_hot_swap.py)
# ---------------------------------------------------------------------------


class _TopologyManagerStub:
    def __init__(self) -> None:
        self.configured: dict[str, Any] = {}

    def configure(self, **kwargs: Any) -> None:
        self.configured = kwargs


class _OrchestratorStub:
    """Минимум, который читает ``configure_topology_engine`` (duck-typed)."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self.logger_manager = None
        self.error_manager = None
        self.stats_manager = None
        self._topology_manager = _TopologyManagerStub()
        self._full_replace_planner = None
        self.infos: list[str] = []
        self.errors: list[str] = []

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def _log_info(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.infos.append(message)

    def _log_error(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.errors.append(message)

    def _get_protected_names(self) -> set[str]:
        return set()

    def _topology_current_names(self) -> set[str]:
        return set()

    def live_process_config(self, name: str) -> dict | None:
        return None


def _real_launcher_config() -> SystemConfig:
    """Модель, как её строит лончер из боевого system.yaml прототипа."""
    return load_system_config(PROJECT_ROOT / "multiprocess_prototype" / "backend" / "config" / "system.yaml")


def _minimal_config_from(tmp_path, yaml_text: str) -> SystemConfig:
    """Модель из самодельного system.yaml (для A3/A4/A5 — минимум ключей)."""
    path = tmp_path / "system.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    return load_system_config(path)


def _proc_dicts(sys_config: SystemConfig, recipe: dict[str, Any]) -> dict[str, Any]:
    """Прогнать рецепт через настоящую горячую пересборку и вернуть proc_dict'ы.

    Ровно тот путь, которым ПМ конфигурирует пересборку: ``configure_topology_engine``
    поднимает ``_full_replace_planner`` с реальным ``_proc_dicts_fn`` (не застаблено —
    как в разрешённом примере S-23), затем ``_proc_dicts_fn(recipe)`` — то же самое,
    что планировщик дёргает на КАЖДЫЙ switch рецепта.
    """
    orch = _OrchestratorStub({"sys_config": sys_config_for_orchestrator(sys_config)})
    configure_topology_engine(orch)
    assert orch._full_replace_planner is not None, "configure_topology_engine обязан поднять планировщик"
    return orch._full_replace_planner._proc_dicts_fn(recipe)


# ============================================================================
# S-24 — слой L1 не должен материализоваться при переезде в ПМ
# ============================================================================


def test_a1_reconstructed_l1_matches_launcher_l1_by_keys_and_values() -> None:
    """A1. Дамп SystemConfig лончера, провалидированный в ПМ, обязан дать тот же
    exclude_unset-срез observability, что и исходная (ещё не переехавшая)
    модель лончера — и по множеству ключей, и по значениям.

    Наблюдается НАСТОЯЩИЙ шов: ``sys_config_for_orchestrator`` — единственное
    место, где ``SystemConfig`` пересекает границу процессов, — и валидация на
    той стороне. Тест НЕ повторяет правило дампа своей копией: зашей он сюда
    ``model_dump()`` литералом, критерий стал бы неисполнимым ни одной
    реализацией (pydantic после полного дампа не может вернуть "unset"), и
    краснел бы вечно, ни на что не указывая. Сравнивается по
    ``observability.model_dump(exclude_unset=True)`` с исходной моделью.
    Если лончер (или ПМ) где-то по пути кладёт ПОЛНЫЙ дамп без сохранения
    "unset"-разметки — все поля секции у пересозданной модели окажутся
    "set", и это сравнение поймает разницу как лишние ключи.
    """
    original = _real_launcher_config()
    reconstructed = SystemConfig.model_validate(sys_config_for_orchestrator(original))

    got = reconstructed.observability.model_dump(exclude_unset=True)
    want = original.observability.model_dump(exclude_unset=True)
    assert got == want, f"лишние/потерянные ключи L1 после переезда: {set(got) ^ set(want)}"


def test_a2_full_dump_survives_the_round_trip_without_losing_values() -> None:
    """A2. Значения не теряются при переезде: полный ``model_dump()``
    пересозданной модели совпадает с полным ``model_dump()`` исходной — даже
    если A1 покажет, что exclude_unset-срез разъехался. Материализация — это
    ЛИШНИЕ ключи в L1, а не потерянные значения; без этого теста A1 мог бы
    поймать чужой дефект (потерю данных), а не собственно материализацию.
    """
    original = _real_launcher_config()
    reconstructed = SystemConfig.model_validate(sys_config_for_orchestrator(original))

    assert reconstructed.model_dump() == original.model_dump()


def test_a3_key_absent_from_yaml_stays_absent_after_the_move(tmp_path) -> None:
    """A3. Ключ верхнего уровня секции observability, которого В system.yaml НЕТ
    (в самодельном файле заданы только ``log_level`` и ``console``), не имеет
    права появиться в L1 после переезда через ПМ. Проверено на нескольких
    заведомо не заданных ключах — скалярных и под-секциях.

    Наблюдается: тот же переезд, что в A1 (``model_validate(model_dump())``),
    но на МИНИМАЛЬНОМ конфиге, где "постороннего" почти ничего не задано —
    иначе A1 на боевом system.yaml (там задано почти всё) не отличил бы
    материализацию от легитимных значений.
    """
    original = _minimal_config_from(tmp_path, _MINIMAL_YAML)
    reconstructed = SystemConfig.model_validate(sys_config_for_orchestrator(original))
    l1 = reconstructed.observability.model_dump(exclude_unset=True)

    absent_keys = [
        "retention_days",
        "retention_total_mb",
        "compress_rotated",
        "errors",
        "documents",
        "flight",
        "events",
        "sampling_first_n",
        "log_directory",
        "session_ttl_sec",
    ]
    leaked = [k for k in absent_keys if k in l1]
    assert leaked == [], f"ключи, которых не было в system.yaml, материализовались в L1: {leaked}"


def test_a4_key_present_in_yaml_survives_with_its_value(tmp_path) -> None:
    """A4. Пара к A3: ключ, который В system.yaml ЕСТЬ (``log_level``,
    ``console``), после переезда остаётся в L1 и с тем же значением. Без этого
    теста A3 проходил бы и на пустом словаре L1 (согласен с ЛЮБЫМ поведением,
    лишь бы оно не называло посторонних ключей) — паре нужны оба конца.
    """
    original = _minimal_config_from(tmp_path, _MINIMAL_YAML)
    reconstructed = SystemConfig.model_validate(sys_config_for_orchestrator(original))
    l1 = reconstructed.observability.model_dump(exclude_unset=True)

    assert l1.get("log_level") == "DEBUG"
    assert l1.get("console") is False


def test_a5_l1_that_configures_the_rebuild_equals_the_launcher_l1(tmp_path) -> None:
    """A5. Слой L1, которым ПМ РЕАЛЬНО конфигурирует ассемблер горячей
    пересборки, равен L1 лончера для того же system.yaml. Это НЕ повтор A1:
    A1 сравнивает две МОДЕЛИ (до/после ``model_validate``) напрямую, A5 —
    то, что действительно доехало до ассемблера через полный хук пересборки.

    Наблюдается: секция ``observability`` (``APP_CONFIG_KEY``) в proc_dict
    пересобранного процесса ПОСЛЕ настоящего вызова
    ``configure_topology_engine`` + ``_proc_dicts_fn`` — это ровно то, что
    ``BlueprintAssembler`` кладёт в конфиг КАЖДОГО процесса (см. разрешённый
    ``assembly/assembler.py``:
    ``if self._observability_section: proc_dict["config"][APP_CONFIG_KEY] = dict(self._observability_section)``).
    Если хук передаёт ассемблеру НЕ exclude_unset-срез, а материализованный —
    сравнение это поймает как лишние ключи в ``l1_delivered``.
    """
    original = _minimal_config_from(tmp_path, _MINIMAL_YAML)
    recipe = {
        "name": "_l1_probe",
        "version": 3,
        "blueprint": {
            "name": "_l1_probe",
            "processes": [
                {
                    "process_name": "probe",
                    "plugins": [],
                    "workers": [],
                    "process_class": HEADLESS_CLASS,
                    "priority": None,
                    "target_process": None,
                    "chain_targets": [],
                    "description": None,
                    "protected": True,
                    "category": None,
                    "metadata": {},
                },
            ],
            "wires": [],
            "displays": [],
        },
        "displays": [],
    }

    proc_dicts = _proc_dicts(original, recipe)
    l1_delivered = proc_dicts["probe"]["config"].get(APP_CONFIG_KEY)

    assert l1_delivered == original.observability.model_dump(exclude_unset=True), (
        f"L1, доехавший до ассемблера при пересборке: {l1_delivered}"
    )


# ============================================================================
# S-25 — устройства рецепта должны доезжать и при горячей пересборке
# ============================================================================


def _devices_process(plugins: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Процесс ``devices`` с плагином ``device_hub`` (как в реальных рецептах —
    см. webcam_sketch.yaml / camera_robot_calibration.yaml)."""
    return {
        "process_name": "devices",
        "plugins": (
            plugins
            if plugins is not None
            else [
                {
                    "plugin_name": "device_hub",
                    "plugin_class": DEVICE_HUB_CLASS,
                    "category": "hub",
                    "config": {"registry_path": "data/devices.yaml"},
                }
            ]
        ),
        "workers": [],
        "process_class": GENERIC_CLASS,
        "priority": None,
        "target_process": None,
        "chain_targets": [],
        "description": None,
        "protected": False,
        "category": None,
        "metadata": {},
    }


def _gui_process() -> dict[str, Any]:
    """Второй, посторонний по отношению к devices процесс — контроль на A8."""
    return {
        "process_name": "gui",
        "plugins": [],
        "workers": [],
        "process_class": HEADLESS_CLASS,
        "priority": None,
        "target_process": None,
        "chain_targets": [],
        "description": None,
        "protected": True,
        "category": None,
        "metadata": {},
    }


def _devices_recipe(*, name: str, devices: list[Any] | None, processes: list[dict[str, Any]]) -> dict[str, Any]:
    """Рецепт-«raw-yaml» формы: top-level name/blueprint/displays (+ devices)."""
    recipe: dict[str, Any] = {
        "name": name,
        "version": 3,
        "blueprint": {
            "name": name,
            "processes": processes,
            "wires": [],
            "displays": [],
        },
        "displays": [],
    }
    if devices is not None:
        recipe["devices"] = devices
    return recipe


def _find_device_hub(proc_dicts: dict[str, Any]) -> dict[str, Any] | None:
    devices_proc = proc_dicts.get("devices")
    if devices_proc is None:
        return None
    for plugin in devices_proc.get("config", {}).get("plugins", []):
        if plugin.get("plugin_name") == "device_hub":
            return plugin
    return None


def test_a6_hot_rebuild_delivers_recipe_devices_to_device_hub() -> None:
    """A6. Горячая пересборка рецепта с top-level ``devices:`` кладёт
    ``recipe_devices`` и ``recipe_origin`` в конфиг плагина ``device_hub``
    процесса ``devices``.

    Наблюдается: плагин ``device_hub`` в ``proc_dicts["devices"]["config"]["plugins"]``
    после РЕАЛЬНОГО вызова горячей пересборки (``configure_topology_engine`` +
    ``_proc_dicts_fn``) на рецепте с двумя валидными устройствами.
    """
    devices = [
        {"id": "robot_main", "kind": "robot"},
        {"id": "vfd_belt", "kind": "vfd"},
    ]
    recipe = _devices_recipe(
        name="_devices_probe_a6",
        devices=devices,
        processes=[_gui_process(), _devices_process()],
    )

    proc_dicts = _proc_dicts(_real_launcher_config(), recipe)
    hub = _find_device_hub(proc_dicts)

    assert hub is not None, "плагин device_hub обязан пережить пересборку"
    assert hub.get("recipe_devices") == devices
    assert hub.get("recipe_origin") == "recipe:_devices_probe_a6"


def test_a7_recipe_without_devices_section_leaves_no_trace() -> None:
    """A7. Рецепт БЕЗ top-level ``devices:`` — ни ``recipe_devices``, ни
    ``recipe_origin`` не появляются в конфиге ``device_hub`` вовсе (не
    пустой список/строка — именно ОТСУТСТВИЕ ключа: пустого следа быть не
    должно).
    """
    recipe = _devices_recipe(
        name="_devices_probe_a7",
        devices=None,
        processes=[_gui_process(), _devices_process()],
    )

    proc_dicts = _proc_dicts(_real_launcher_config(), recipe)
    hub = _find_device_hub(proc_dicts)

    assert hub is not None
    assert "recipe_devices" not in hub
    assert "recipe_origin" not in hub


def test_a8_missing_devices_process_does_not_crash_the_rebuild() -> None:
    """A8 (вариант 1: нет процесса ``devices``). Рецепт с ``devices:``, но БЕЗ
    процесса ``devices`` в blueprint — пересборка не падает, остальные
    процессы (``gui``) собираются как обычно."""
    recipe = _devices_recipe(
        name="_devices_probe_a8a",
        devices=[{"id": "robot_main", "kind": "robot"}],
        processes=[_gui_process()],
    )

    proc_dicts = _proc_dicts(_real_launcher_config(), recipe)

    assert "gui" in proc_dicts, "процесс, не имеющий отношения к devices, обязан собраться как обычно"
    assert "devices" not in proc_dicts


def test_a8_missing_device_hub_plugin_does_not_crash_the_rebuild() -> None:
    """A8 (вариант 2: процесс есть, плагина нет). Рецепт с ``devices:``,
    процесс ``devices`` ЕСТЬ, но БЕЗ плагина ``device_hub`` — пересборка не
    падает, остальные процессы собираются."""
    recipe = _devices_recipe(
        name="_devices_probe_a8b",
        devices=[{"id": "robot_main", "kind": "robot"}],
        processes=[_gui_process(), _devices_process(plugins=[])],
    )

    proc_dicts = _proc_dicts(_real_launcher_config(), recipe)

    assert "gui" in proc_dicts
    assert "devices" in proc_dicts


def test_a9_only_valid_device_entries_survive_literal_expected_list() -> None:
    """A9. Из смеси валидных/битых записей ``devices`` до ``device_hub``
    доезжают ТОЛЬКО валидные (есть и ``id``, и ``kind``, запись — dict), в
    исходном порядке. Ожидаемый список — ЛИТЕРАЛ, задан по формулировке
    критерия, а не выведен из кода extract/inject.
    """
    devices_raw: list[Any] = [
        {"id": "robot_main", "kind": "robot"},
        "not_a_dict",
        {"id": "no_kind_here"},
        {"kind": "no_id_here"},
        {"id": "vfd_belt", "kind": "vfd"},
    ]
    expected = [
        {"id": "robot_main", "kind": "robot"},
        {"id": "vfd_belt", "kind": "vfd"},
    ]
    recipe = _devices_recipe(
        name="_devices_probe_a9",
        devices=devices_raw,
        processes=[_gui_process(), _devices_process()],
    )

    proc_dicts = _proc_dicts(_real_launcher_config(), recipe)
    hub = _find_device_hub(proc_dicts)

    assert hub is not None
    assert hub.get("recipe_devices") == expected


def test_a10_hot_rebuild_is_idempotent_and_does_not_mutate_the_input() -> None:
    """A10. Пересборка идемпотентна: два вызова подряд на ОДНОМ и том же
    объекте-рецепте дают равные результаты. И не мутирует вход: сам рецепт
    после обоих вызовов равен глубокой копии, снятой ДО первого вызова.
    """
    devices = [{"id": "robot_main", "kind": "robot"}, {"id": "vfd_belt", "kind": "vfd"}]
    recipe = _devices_recipe(
        name="_devices_probe_a10",
        devices=devices,
        processes=[_gui_process(), _devices_process()],
    )
    snapshot = copy.deepcopy(recipe)

    orch = _OrchestratorStub({"sys_config": sys_config_for_orchestrator(_real_launcher_config())})
    configure_topology_engine(orch)
    assert orch._full_replace_planner is not None

    first = orch._full_replace_planner._proc_dicts_fn(recipe)
    second = orch._full_replace_planner._proc_dicts_fn(recipe)

    assert first == second, "два вызова подряд на одном blueprint обязаны совпасть"
    assert recipe == snapshot, "вход пересборки не имеет права мутироваться сборкой"


# ============================================================================
# S-29 — дублёр оркестратора обязан совпадать по именам с настоящим классом
# ============================================================================


def test_the_stub_orchestrator_speaks_the_real_class_surface() -> None:
    """`_OrchestratorStub` этого файла обязан совпадать по именам с НАСТОЯЩИМ
    `GenericProcessManagerApp` — иначе переименование в проде остаётся
    незамеченным.

    Измерено (S-29, 2026-08-18): переименование `live_process_config` в
    `process_manager_process.py` не красило НИ ОДИН из десяти тестов A1-A10
    этого файла — все они гоняют `configure_topology_engine` против ЭТОГО
    дублёра, а не настоящего класса, и ни разу не заглядывают в оркестратор по
    имени. Общая проверка — `_orchestrator_stub_contract.py` (S-26, тот же
    дублёр-класс защищён впервые в `test_hot_rebuild_provenance_hazards.py`).
    """
    assert_stub_speaks_the_real_class_surface(_OrchestratorStub)
