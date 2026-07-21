"""Тесты для build_initial_state — State Bootstrap."""

import pytest

from multiprocess_prototype.backend.state.bootstrap import (
    _build_process_entry,
    _build_system_section,
    _build_wires_section,
    build_initial_state,
)
from multiprocess_prototype.backend.config.schemas import DisplayEntrySchema, DisplaysConfig
from multiprocess_prototype.registers.manager import build_rm_from_topology, _RawRegisterData


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture()
def empty_topology() -> dict:
    """Пустой topology — нет процессов, нет wire-ов."""
    return {
        "name": "empty",
        "description": "Пустой topology для тестов",
        "processes": [],
        "wires": [],
    }


@pytest.fixture()
def topology_no_plugins() -> dict:
    """Topology с одним процессом без плагинов."""
    return {
        "name": "test",
        "processes": [
            {
                "process_name": "gui",
                "plugins": [],
            }
        ],
        "wires": [],
    }


@pytest.fixture()
def topology_one_process() -> dict:
    """Topology с одним процессом (capture-плагин)."""
    return {
        "name": "test",
        "processes": [
            {
                "process_name": "camera_0",
                "priority": "high",
                "chain_targets": ["preprocessor"],
                "plugins": [
                    {
                        "plugin_class": "Plugins.sources.capture.plugin.CapturePlugin",
                        "plugin_name": "capture",
                        "category": "source",
                        "camera_id": 0,
                    }
                ],
            }
        ],
        "wires": [],
    }


@pytest.fixture()
def topology_with_wires() -> dict:
    """Topology с несколькими процессами и wire-ами (аналог region_pipeline.yaml)."""
    return {
        "name": "region_pipeline",
        "description": "Camera → Resize → GUI",
        "processes": [
            {
                "process_name": "camera_0",
                "priority": "high",
                "chain_targets": ["preprocessor"],
                "plugins": [
                    {
                        "plugin_name": "capture",
                        "category": "source",
                    }
                ],
            },
            {
                "process_name": "preprocessor",
                "priority": "normal",
                "chain_targets": ["gui"],
                "plugins": [
                    {
                        "plugin_name": "resize",
                        "category": "processing",
                    }
                ],
            },
            {
                "process_name": "gui",
                "plugins": [],
            },
        ],
        "wires": [
            {
                "source": "camera_0.capture.frame",
                "target": "preprocessor.resize.frame",
                "description": "BGR-кадры → масштабирование",
            },
            {
                "source": "preprocessor.resize.frame",
                "target": "gui.display.frame",
                "description": "Масштабированный кадр → GUI",
            },
        ],
    }


@pytest.fixture()
def topology_no_wires_key() -> dict:
    """Topology вообще без ключа wires."""
    return {
        "name": "no_wires",
        "processes": [
            {
                "process_name": "camera_0",
                "plugins": [{"plugin_name": "capture", "category": "source"}],
            }
        ],
        # ключ wires отсутствует
    }


@pytest.fixture()
def default_sys_config() -> dict:
    """sys_config_dict с defaults (пустой dict)."""
    return {}


@pytest.fixture()
def custom_sys_config() -> dict:
    """sys_config_dict с кастомными значениями."""
    return {
        "system": {
            "stop_timeout": 10.0,
            "shm_budget_mb": 1024,
            "log_dir": "/var/log/inspector",
        }
    }


# ---------------------------------------------------------------------------
# Тест 1: Пустой topology → пустые processes и wires
# ---------------------------------------------------------------------------


def test_empty_topology_gives_empty_processes_and_wires(empty_topology, default_sys_config):
    """Пустой topology должен давать пустые processes и wires."""
    result = build_initial_state(empty_topology, default_sys_config)

    assert result["processes"] == {}
    assert result["wires"] == {}


# ---------------------------------------------------------------------------
# Тест 2: Один процесс без плагинов
# ---------------------------------------------------------------------------


def test_one_process_no_plugins(topology_no_plugins, default_sys_config):
    """Процесс без плагинов → пустой список plugins в config."""
    result = build_initial_state(topology_no_plugins, default_sys_config)

    assert "gui" in result["processes"]
    gui = result["processes"]["gui"]
    assert gui["config"]["plugins"] == []
    assert gui["config"]["chain_targets"] == []


# ---------------------------------------------------------------------------
# Тест 3: Один процесс с capture-плагином
# ---------------------------------------------------------------------------


def test_one_process_with_capture_plugin(topology_one_process, default_sys_config):
    """Процесс с capture-плагином → правильный config и начальное state."""
    result = build_initial_state(topology_one_process, default_sys_config)

    assert "camera_0" in result["processes"]
    entry = result["processes"]["camera_0"]

    # Проверяем config
    assert entry["config"]["priority"] == "high"
    assert entry["config"]["chain_targets"] == ["preprocessor"]
    assert len(entry["config"]["plugins"]) == 1
    assert entry["config"]["plugins"][0]["plugin_name"] == "capture"

    # Проверяем начальное state
    state = entry["state"]
    assert state["status"] == "stopped"
    assert state["pid"] is None
    assert state["fps"] == 0.0
    assert state["frame_count"] == 0
    assert state["error"] is None


# ---------------------------------------------------------------------------
# Тест 4: Несколько процессов (аналог region_pipeline.yaml)
# ---------------------------------------------------------------------------


def test_multiple_processes(topology_with_wires, default_sys_config):
    """Несколько процессов — все должны попасть в processes dict."""
    result = build_initial_state(topology_with_wires, default_sys_config)

    assert set(result["processes"].keys()) == {"camera_0", "preprocessor", "gui"}

    # Проверяем priority preprocessor
    assert result["processes"]["preprocessor"]["config"]["priority"] == "normal"

    # Проверяем chain_targets camera_0
    assert result["processes"]["camera_0"]["config"]["chain_targets"] == ["preprocessor"]


# ---------------------------------------------------------------------------
# Тест 5: Wire-ы присутствуют → wires dict заполнен
# ---------------------------------------------------------------------------


def test_wires_present(topology_with_wires, default_sys_config):
    """Wire-ы из topology должны быть в wires dict со статусом pending."""
    result = build_initial_state(topology_with_wires, default_sys_config)

    wires = result["wires"]
    assert len(wires) == 2

    key = "camera_0.capture.frame->preprocessor.resize.frame"
    assert key in wires
    assert wires[key]["source"] == "camera_0.capture.frame"
    assert wires[key]["target"] == "preprocessor.resize.frame"
    assert wires[key]["status"] == "pending"


# ---------------------------------------------------------------------------
# Тест 6: Topology без wire-ов → пустой wires dict
# ---------------------------------------------------------------------------


def test_no_wires_gives_empty_dict(topology_no_wires_key, default_sys_config):
    """Topology без ключа wires → пустой wires dict (без исключений)."""
    result = build_initial_state(topology_no_wires_key, default_sys_config)

    assert result["wires"] == {}


# ---------------------------------------------------------------------------
# Тест 7: sys_config defaults (пустой dict)
# ---------------------------------------------------------------------------


def test_sys_config_defaults(empty_topology, default_sys_config):
    """Пустой sys_config_dict → defaults системной секции."""
    result = build_initial_state(empty_topology, default_sys_config)

    system = result["system"]
    assert system["stop_timeout"] == 5.0
    assert system["shm_budget_mb"] == 512
    assert system["log_dir"] == ""


# ---------------------------------------------------------------------------
# Тест 8: sys_config с кастомными значениями
# ---------------------------------------------------------------------------


def test_sys_config_custom_values(empty_topology, custom_sys_config):
    """Кастомные значения в sys_config_dict должны попасть в system-секцию."""
    result = build_initial_state(empty_topology, custom_sys_config)

    system = result["system"]
    assert system["stop_timeout"] == 10.0
    assert system["shm_budget_mb"] == 1024
    assert system["log_dir"] == "/var/log/inspector"


# ---------------------------------------------------------------------------
# Тест 9: Структура результата — все обязательные ключи присутствуют
# ---------------------------------------------------------------------------


def test_result_has_required_top_level_keys(topology_one_process, custom_sys_config):
    """Результат всегда содержит все 7 корневых ключей Phase 0 + Phase 2-5 стабы."""
    result = build_initial_state(topology_one_process, custom_sys_config)

    assert "processes" in result
    assert "system" in result
    assert "wires" in result
    # Phase 2-5 заглушечные ветки
    assert "services" in result
    assert "displays" in result
    assert "recipes" in result
    assert "plugins" in result


# ---------------------------------------------------------------------------
# Вспомогательные юнит-тесты хелперов
# ---------------------------------------------------------------------------


def test_build_process_entry_defaults():
    """_build_process_entry использует defaults для отсутствующих полей."""
    entry = _build_process_entry({"process_name": "x"})

    assert entry["config"]["priority"] == "normal"
    assert entry["config"]["plugins"] == []
    assert entry["config"]["chain_targets"] == []
    assert entry["state"]["status"] == "stopped"


def test_build_process_entry_explicit_null_priority():
    """M-1: priority: null (явный YAML null, не отсутствие ключа) → default 'normal'.

    GUI-редактор пишет пустой скаляр (priority: без значения) → yaml.safe_load
    даёт None, а не отсутствующий ключ. .get("priority", "normal") пропускал бы
    этот случай (default сработал бы только на ОТСУТСТВУЮЩЕМ ключе).
    """
    entry = _build_process_entry({"process_name": "x", "priority": None})

    assert entry["config"]["priority"] == "normal"


def test_build_system_section_partial():
    """_build_system_section заполняет отсутствующие поля defaults."""
    section = _build_system_section({"system": {"stop_timeout": 15.0}})

    assert section["stop_timeout"] == 15.0
    assert section["shm_budget_mb"] == 512  # default
    assert section["log_dir"] == ""  # default


def test_build_wires_section_key_format():
    """_build_wires_section формирует ключ source->target."""
    wires = _build_wires_section([{"source": "a.b.c", "target": "d.e.f"}])

    assert "a.b.c->d.e.f" in wires
    assert wires["a.b.c->d.e.f"]["status"] == "pending"


# ---------------------------------------------------------------------------
# Тесты Task 0.8 — заглушечные ветки Phase 2-5
# ---------------------------------------------------------------------------


def test_services_branch_is_empty_dict(empty_topology, default_sys_config):
    """services — пустой dict при старте (Phase 3 наполнит)."""
    result = build_initial_state(empty_topology, default_sys_config)

    assert result["services"] == {}


def test_displays_branch_is_empty_dict(empty_topology, default_sys_config):
    """displays — пустой dict при старте (Phase 4 наполнит)."""
    result = build_initial_state(empty_topology, default_sys_config)

    assert result["displays"] == {}


def test_recipes_branch_has_correct_structure(empty_topology, default_sys_config):
    """recipes — active=None, available=[] при старте (Phase 5 наполнит)."""
    result = build_initial_state(empty_topology, default_sys_config)

    assert result["recipes"] == {"active": None, "available": []}
    assert result["recipes"]["active"] is None
    assert result["recipes"]["available"] == []


def test_plugins_branch_has_correct_structure(empty_topology, default_sys_config):
    """plugins — catalog=[], paths=[] при старте (Phase 2 наполнит)."""
    result = build_initial_state(empty_topology, default_sys_config)

    assert result["plugins"] == {"catalog": [], "paths": []}
    assert result["plugins"]["catalog"] == []
    assert result["plugins"]["paths"] == []


def test_all_seven_top_level_keys_present(topology_with_wires, custom_sys_config):
    """build_initial_state возвращает ровно 7 корневых ключей (Task 0.8 acceptance)."""
    result = build_initial_state(topology_with_wires, custom_sys_config)

    expected_keys = {"processes", "system", "wires", "services", "displays", "recipes", "plugins"}
    assert set(result.keys()) == expected_keys


def test_stub_branches_independent_of_topology(topology_with_wires, empty_topology, default_sys_config):
    """Заглушечные ветки не зависят от topology — всегда одинаковые при старте."""
    result_full = build_initial_state(topology_with_wires, default_sys_config)
    result_empty = build_initial_state(empty_topology, default_sys_config)

    # Заглушки идентичны независимо от topology
    assert result_full["services"] == result_empty["services"]
    assert result_full["displays"] == result_empty["displays"]
    assert result_full["recipes"] == result_empty["recipes"]
    assert result_full["plugins"] == result_empty["plugins"]


# ---------------------------------------------------------------------------
# Тесты Task 4.8 — displays_config (Phase 4)
# ---------------------------------------------------------------------------


def _make_displays_config(*ids: str) -> DisplaysConfig:
    """Создать DisplaysConfig с записями для заданных id."""
    return DisplaysConfig(
        displays=[
            DisplayEntrySchema(
                id=did,
                name=f"Дисплей {did}",
                width=1280,
                height=720,
                format="BGR",
                fps_limit=30.0,
                ring_buffer_blocks=3,
            )
            for did in ids
        ]
    )


def test_bootstrap_with_displays_config(empty_topology, default_sys_config):
    """build_initial_state с 2 дисплеями → state['displays'] содержит 2 ключа со структурой."""
    displays_cfg = _make_displays_config("main", "debug")
    result = build_initial_state(empty_topology, default_sys_config, displays_config=displays_cfg)

    displays = result["displays"]
    assert len(displays) == 2
    assert "main" in displays
    assert "debug" in displays

    for did in ("main", "debug"):
        entry = displays[did]
        assert entry["status"] == "registered"
        assert "config" in entry
        assert isinstance(entry["config"], dict)


def test_bootstrap_displays_config_none_backward_compat(empty_topology, default_sys_config):
    """build_initial_state(..., displays_config=None) — обратная совместимость, displays пуст."""
    result = build_initial_state(empty_topology, default_sys_config, displays_config=None)

    assert result["displays"] == {}


# ---------------------------------------------------------------------------
# Тесты Task 5.3 — recipes_dir в build_initial_state
# ---------------------------------------------------------------------------


def test_build_initial_state_recipes_available(tmp_path, empty_topology, default_sys_config):
    """recipes_dir с двумя yaml → available содержит оба slug'а в отсортированном порядке."""
    # Создаём два yaml-файла в tmp_path
    (tmp_path / "bottle_inspection.yaml").write_text("name: bottle\n", encoding="utf-8")
    (tmp_path / "cup_inspection.yaml").write_text("name: cup\n", encoding="utf-8")

    result = build_initial_state(empty_topology, default_sys_config, recipes_dir=tmp_path)

    available = result["recipes"]["available"]
    assert available == ["bottle_inspection", "cup_inspection"]


def test_build_initial_state_recipes_empty_dir(tmp_path, empty_topology, default_sys_config):
    """Пустая recipes_dir → available == []."""
    result = build_initial_state(empty_topology, default_sys_config, recipes_dir=tmp_path)

    assert result["recipes"]["available"] == []


def test_build_initial_state_no_recipes_dir(empty_topology, default_sys_config):
    """recipes_dir=None → available == [] (обратная совместимость)."""
    result = build_initial_state(empty_topology, default_sys_config, recipes_dir=None)

    assert result["recipes"]["available"] == []


def test_build_initial_state_recipes_dir_not_exists(tmp_path, empty_topology, default_sys_config):
    """recipes_dir указан, но не существует → available == [] (без FileNotFoundError)."""
    nonexistent = tmp_path / "does_not_exist"

    result = build_initial_state(empty_topology, default_sys_config, recipes_dir=nonexistent)

    assert result["recipes"]["available"] == []


def test_build_initial_state_recipes_active_always_none(tmp_path, empty_topology, default_sys_config):
    """active всегда None при bootstrap (независимо от наличия yaml-файлов)."""
    (tmp_path / "some_recipe.yaml").write_text("name: test\n", encoding="utf-8")

    result = build_initial_state(empty_topology, default_sys_config, recipes_dir=tmp_path)

    assert result["recipes"]["active"] is None


# ---------------------------------------------------------------------------
# Тесты Task 5.3 — base_registers_dir в build_rm_from_topology
# ---------------------------------------------------------------------------


def test_build_rm_base_layer(tmp_path):
    """base_registers_dir с одним yaml → регистр из него попадает в менеджер."""
    # Создаём базовый yaml-регистр
    (tmp_path / "capture.yaml").write_text("camera_id: 0\nfps: 30\n", encoding="utf-8")

    topology = {"processes": []}
    rm = build_rm_from_topology(topology, base_registers_dir=tmp_path)

    # Регистр "capture" должен присутствовать в менеджере
    assert "capture" in rm.register_names()
    reg = rm.get_register("capture")
    assert reg is not None
    assert isinstance(reg, _RawRegisterData)
    assert reg.data == {"camera_id": 0, "fps": 30}


def test_build_rm_active_overrides_base(tmp_path):
    """Base YAML + topology с тем же именем → topology wins (целиком, не merge полей)."""
    from pydantic import BaseModel

    # Создаём базовый yaml-регистр для "capture"
    (tmp_path / "capture.yaml").write_text("camera_id: 99\nfps: 10\n", encoding="utf-8")

    # Создаём mock plugin_registry с register_classes для "capture"
    class CaptureRegisters(BaseModel):
        camera_id: int = 0
        fps: float = 25.0

    class MockEntry:
        register_classes = [CaptureRegisters]
        category = "source"

    class MockPluginRegistry:
        def get(self, name: str) -> MockEntry | None:
            if name == "capture":
                return MockEntry()
            return None

    topology = {
        "processes": [
            {
                "process_name": "camera_proc",
                "plugins": [
                    {"plugin_name": "capture", "camera_id": 1, "fps": 25.0},
                ],
            }
        ]
    }

    rm = build_rm_from_topology(
        topology,
        plugin_registry=MockPluginRegistry(),
        base_registers_dir=tmp_path,
    )

    # Регистр должен быть — из topology (CaptureRegisters), не из base (_RawRegisterData)
    assert "capture" in rm.register_names()
    reg = rm.get_register("capture")
    assert isinstance(reg, CaptureRegisters)
    # Topology-значения: camera_id=1, не base (camera_id=99)
    assert reg.camera_id == 1


def test_build_rm_base_layer_invalid_yaml(tmp_path):
    """Невалидный YAML в base_registers_dir → пропустить файл, не падать."""
    (tmp_path / "bad_register.yaml").write_text("{ invalid: yaml: content:\n", encoding="utf-8")
    (tmp_path / "good_register.yaml").write_text("key: value\n", encoding="utf-8")

    topology = {"processes": []}
    # Не должно бросать исключений
    rm = build_rm_from_topology(topology, base_registers_dir=tmp_path)

    # bad_register пропущен, good_register загружен
    assert "good_register" in rm.register_names()
    assert "bad_register" not in rm.register_names()


def test_build_rm_no_base_dir_backward_compat():
    """build_rm_from_topology без base_registers_dir → прежнее поведение."""
    topology = {"processes": []}
    rm = build_rm_from_topology(topology)

    # Менеджер пустой — без регистров (topology тоже пустой)
    assert rm.register_names() == []
