"""Авторские hazard-тесты горячей пересборки: S-24 (слой L1) и S-25 (устройства).

Приёмка независимого тестера (``test_hot_rebuild_parity_acceptance.py``) стережёт
контракт «что обязано доехать». Здесь — опасности САМОГО механизма, которые
видно только изнутри: они найдены не рассуждением, а инъекциями против той
приёмки, и каждая закрывает место, где приёмка осталась зелёной под сломанным
кодом.

Три таких места:

1. **Снятие ``copy.deepcopy`` вокруг ``unwrap_recipe`` не убило никого.**
   Инъекция И7 предсказывала красный A10 («вход не мутируется») — и промахнулась.
   Замер объяснил почему: ``normalize_blueprint`` дописывает per-category
   defaults **in place**, но только тем плагинам, у чьей категории эти дефолты
   вообще есть. Пересчитано по всем 9 категориям, встречающимся в рецептах:
   ``source`` получает пять ключей (``fps``, ``source_type``, две ``resolution_*``,
   ``ring_buffer_size``) и встречается в 17 рецептах из 17; ``processing`` —
   ``worker_pool_size``; ``output`` — ``enabled``; у остальных шести
   (``calibration``, ``filter``, ``hub``, ``io``, ``rendering``, ``sink``)
   дефолтов нет. В рецептах приёмки плагины только категории ``hub`` — потому
   она и была зелена.

   Первая редакция этого объяснения была НЕВЕРНА и названа ревью: я замерял
   категории по именам ``sources`` и ``utility``, которых не существует, и
   пустой ответ ``defaults_for_category`` прочёл как «у категории нет дефолтов»
   вместо «такой категории нет». Вывод уцелел, объяснение — нет; оставить
   уверенное неверное объяснение опаснее, чем не написать никакого.

2. **Рецепт без ключа ``name``.** Инъекция И8 (``bp.get("name")`` →
   ``bp["name"]``) не убила никого: у всех рецептов приёмки имя есть. Фолбэк на
   имя файла рецепта не стерёг никто.

3. **Обвязка приёмки — стаб.** Все её тесты кладут ``sys_config`` в стаб
   оркестратора сами, через шов. Перестань лончер звать этот шов — приёмка
   останется полностью зелёной. Нужен один тест, который проводит НАСТОЯЩУЮ
   сборку.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from multiprocess_prototype.backend.config.schemas import SystemConfig, load_system_config
from multiprocess_prototype.backend.launch import sys_config_for_orchestrator
from multiprocess_prototype.backend.orchestrator_hooks import configure_topology_engine

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GENERIC_CLASS = "multiprocess_prototype.generic_process_app.GenericProcessApp"
DEVICE_HUB_CLASS = "Plugins.hub.device_hub.plugin.DeviceHubPlugin"
COLOR_MASK_CLASS = "Plugins.processing.color_mask.plugin.ColorMaskPlugin"


class _TopologyManagerStub:
    def __init__(self) -> None:
        self.configured: dict[str, Any] = {}

    def configure(self, **kwargs: Any) -> None:
        self.configured = kwargs


class _OrchestratorStub:
    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self.logger_manager = None
        self.error_manager = None
        self.stats_manager = None
        self._topology_manager = _TopologyManagerStub()
        self._full_replace_planner = None

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def _log_info(self, message: str, *args: Any, **kwargs: Any) -> None:
        return None

    def _log_error(self, message: str, *args: Any, **kwargs: Any) -> None:
        return None

    def _get_protected_names(self) -> set[str]:
        return set()

    def _topology_current_names(self) -> set[str]:
        return set()

    def live_process_config(self, name: str) -> dict | None:
        return None


def _launcher_config() -> SystemConfig:
    return load_system_config(PROJECT_ROOT / "multiprocess_prototype" / "backend" / "config" / "system.yaml")


def _rebuild(recipe: dict[str, Any], *, recipe_path: str = "") -> dict[str, Any]:
    """Прогнать рецепт ровно тем путём, которым его гоняет switch."""
    config: dict[str, Any] = {"sys_config": sys_config_for_orchestrator(_launcher_config())}
    if recipe_path:
        config["observability_recipe_path"] = recipe_path
    orch = _OrchestratorStub(config)
    configure_topology_engine(orch)
    assert orch._full_replace_planner is not None
    return orch._full_replace_planner._proc_dicts_fn(recipe)


def _devices_process() -> dict[str, Any]:
    return {
        "process_name": "devices",
        "process_class": GENERIC_CLASS,
        "plugins": [
            {
                "plugin_name": "device_hub",
                "plugin_class": DEVICE_HUB_CLASS,
                "category": "hub",
                "config": {"registry_path": "data/devices.yaml"},
            }
        ],
        "workers": [],
    }


def _hub_entry(proc_dicts: dict[str, Any]) -> dict[str, Any]:
    """Запись плагина ``device_hub`` целиком — инжект пишет ПЛОСКО в неё."""
    for plugin in proc_dicts["devices"].get("config", {}).get("plugins", []):
        if plugin.get("plugin_name") == "device_hub":
            return plugin
    raise AssertionError("плагин device_hub не пережил пересборку")


# ---------------------------------------------------------------------------
# Опасность 1 — copy.deepcopy входа
# ---------------------------------------------------------------------------


def test_deepcopy_of_the_input_is_load_bearing() -> None:
    """Пересборка не имеет права дописать что-либо в рецепт вызывающего.

    Берётся НАСТОЯЩИЙ рецепт (``color_inspect.yaml``) — не самодельный: в нём
    есть плагин категории ``processing``, а замером показано, что
    ``normalize_blueprint`` дописывает такому плагину ``worker_pool_size``
    **в тот же объект**, тогда как ``unwrap_recipe`` отдаёт shallow-copy
    (``dict(raw["blueprint"])`` — список processes тот же самый). Без
    ``copy.deepcopy`` в ``_build_proc_dicts`` рецепт, приехавший по IPC,
    обогащался бы на каждом switch, и следующий switch видел бы уже не то,
    что прислал инициатор.

    Категория здесь несущая, а не декоративная: у ``hub`` — единственной, что
    есть в рецептах приёмки, — per-category defaults пусты, и тот же тест на ней
    прошёл бы при полностью снятом ``deepcopy``; именно поэтому приёмка тестера
    осталась зелёной под инъекцией И7. Годился бы и любой ``source``-плагин (пять
    дописываемых ключей вместо одного); ``processing`` выбран потому, что
    ``color_inspect.yaml`` — самый маленький настоящий рецепт с ним.
    """
    import yaml

    recipe_file = PROJECT_ROOT / "multiprocess_prototype" / "recipes" / "color_inspect.yaml"
    recipe = yaml.safe_load(recipe_file.read_text(encoding="utf-8"))
    snapshot = copy.deepcopy(recipe)

    _rebuild(recipe)

    assert recipe == snapshot, "пересборка обогатила рецепт вызывающего"


# ---------------------------------------------------------------------------
# Опасность 2 — рецепт без ключа `name`
# ---------------------------------------------------------------------------


def test_recipe_without_a_name_falls_back_to_the_active_recipe_file() -> None:
    """У рецепта может не быть ``name`` — тогда происхождение берётся от файла.

    Сырой dict приезжает по IPC от инициатора switch'а, и ключ ``name`` в нём
    не обязателен: прямое обращение ``bp["name"]`` уронило бы всю пересборку
    (``KeyError``), а не один только ``recipe_origin``. Приёмка это не ловит —
    у всех её рецептов имя есть.
    """
    recipe = {
        "version": 3,
        "devices": [{"id": "robot_main", "kind": "robot"}],
        "blueprint": {"processes": [_devices_process()], "wires": []},
    }

    hub = _hub_entry(_rebuild(recipe, recipe_path="data/recipes/letters_disk.yaml"))

    assert hub["recipe_devices"] == [{"id": "robot_main", "kind": "robot"}]
    assert hub["recipe_origin"] == "recipe:letters_disk"


def test_recipe_without_a_name_and_without_a_path_still_delivers_devices() -> None:
    """Ни имени, ни адреса рецепта — устройства всё равно обязаны доехать.

    Происхождение в этом случае назвать нечем, и ключ ``recipe_origin`` не
    ставится вовсе: пустая строка означала бы «происхождение известно и оно
    пустое». Устройства при этом теряться не имеют права — их наличие и их
    происхождение это два разных факта.
    """
    recipe = {
        "version": 3,
        "devices": [{"id": "vfd_belt", "kind": "vfd"}],
        "blueprint": {"processes": [_devices_process()], "wires": []},
    }

    hub = _hub_entry(_rebuild(recipe))

    assert hub["recipe_devices"] == [{"id": "vfd_belt", "kind": "vfd"}]
    assert "recipe_origin" not in hub


# ---------------------------------------------------------------------------
# Опасность 3 — обвязка приёмки целиком на стабе
# ---------------------------------------------------------------------------


def test_the_real_launcher_ships_a_thin_sys_config() -> None:
    """НАСТОЯЩАЯ сборка кладёт в orchestrator_config тонкий дамп, а не полный.

    Каждый тест приёмки кладёт ``sys_config`` в стаб сам, через шов
    ``sys_config_for_orchestrator``. Перестань ``SystemBuilder.build`` звать
    этот шов — вся приёмка останется зелёной, а материализация слоя вернётся.
    Здесь поднимается реальный ``SystemBuilder`` из боевого манифеста, и
    проверяется то, что физически уехало бы в ПМ.

    Наблюдаемое — ``flight``: этой секции в боевом ``system.yaml`` нет, значит в
    слое L1 её быть не должно. Парный конец — ``log_level``, который в файле
    есть и обязан уцелеть: без него тест прошёл бы и на пустом словаре.
    """
    from multiprocess_prototype.backend.config.manifest import load_manifest
    from multiprocess_prototype.backend.launch import SystemBuilder

    app = load_manifest(PROJECT_ROOT / "multiprocess_prototype" / "app.yaml")
    launcher = SystemBuilder.from_manifest(app, "phone_sketch").build()

    shipped = launcher._orchestrator_config["sys_config"]["observability"]

    assert "flight" not in shipped, (
        f"слой L1 материализовался: ключа нет в system.yaml, но он уехал в ПМ — {sorted(shipped)}"
    )
    assert "log_level" in shipped, "заданный в system.yaml ключ обязан уцелеть"


# ---------------------------------------------------------------------------
# Опасность 4 — паритет двух дорог никто не сверяет
# ---------------------------------------------------------------------------


def _boot_devices_entry(manifest_path: Path, pipeline: str | None) -> dict[str, Any]:
    """Запись плагина ``device_hub`` так, как её собирает BOOT-дорога."""
    from multiprocess_prototype.backend.config.manifest import load_manifest
    from multiprocess_prototype.backend.launch import SystemBuilder

    app = load_manifest(manifest_path)
    launcher = SystemBuilder.from_manifest(app, pipeline).build()
    procs = dict(launcher._processes)
    for plugin in procs["devices"]["config"]["plugins"]:
        if plugin.get("plugin_name") == "device_hub":
            return plugin
    raise AssertionError("boot не собрал плагин device_hub")


def test_boot_and_hot_rebuild_agree_on_recipe_devices() -> None:
    """Две дороги обязаны прийти к одному по устройствам рецепта.

    Сборка живёт в ДВУХ местах — ``launch.from_manifest`` (boot) и
    ``orchestrator_hooks._build_proc_dicts`` (switch), — и до этого коммита они
    расходились: горячая не инжектила устройства вовсе. Ни один тест сравнения
    между дорогами не делал, поэтому расхождение и дожило до живого стенда.
    Здесь берётся один и тот же настоящий рецепт и прогоняется обеими.
    """
    import yaml

    recipe_file = PROJECT_ROOT / "multiprocess_prototype" / "recipes" / "phone_sketch.yaml"
    raw = yaml.safe_load(recipe_file.read_text(encoding="utf-8"))

    boot = _boot_devices_entry(PROJECT_ROOT / "multiprocess_prototype" / "app.yaml", "phone_sketch")
    hot = _hub_entry(_rebuild(raw, recipe_path=str(recipe_file)))

    assert hot.get("recipe_devices") == boot.get("recipe_devices")
    assert hot.get("recipe_origin") == boot.get("recipe_origin")
    assert boot.get("recipe_devices"), "рецепт обязан нести устройства — иначе тест сверяет два пустых места"


def test_a_recipe_without_a_name_value_gets_the_same_origin_on_both_roads(tmp_path) -> None:
    """`name:` без значения — и происхождение всё равно одно на обеих дорогах.

    Найдено ревью: boot читал имя как ``raw.get("name", bp_path.stem)``, а такой
    вызов при ключе со значением ``None`` возвращает ``None``, а не имя файла —
    происхождение молча не проставлялось. Горячая дорога подставляла имя файла.
    На таком рецепте ``devices`` (он protected) числился бы разошедшимся при
    каждом switch — ровно тот вечный шум, который этот коммит и убирает.
    """
    import shutil

    import yaml

    proto = PROJECT_ROOT / "multiprocess_prototype"
    raw = yaml.safe_load((proto / "recipes" / "phone_sketch.yaml").read_text(encoding="utf-8"))
    raw["name"] = None

    (tmp_path / "recipes").mkdir()
    recipe_file = tmp_path / "recipes" / "noname.yaml"
    recipe_file.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")

    app_raw = yaml.safe_load((proto / "app.yaml").read_text(encoding="utf-8"))
    app_raw["pipeline"] = "recipes/noname.yaml"
    for key in ("system", "base", "presentation"):
        if app_raw.get(key):
            app_raw[key] = str((proto / app_raw[key]).resolve())
    manifest = tmp_path / "app.yaml"
    manifest.write_text(yaml.safe_dump(app_raw, allow_unicode=True, sort_keys=False), encoding="utf-8")

    try:
        boot = _boot_devices_entry(manifest, None)
        hot = _hub_entry(_rebuild(raw, recipe_path=str(recipe_file)))

        assert boot.get("recipe_origin") == "recipe:noname", (
            f"boot обязан взять имя от файла, когда `name:` пуст — получено {boot.get('recipe_origin')!r}"
        )
        assert hot.get("recipe_origin") == boot.get("recipe_origin")
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
