# -*- coding: utf-8 -*-
"""Приёмочные тесты: провенанс слоя observability на ГОРЯЧЕЙ дороге пересборки.

Что охраняем: дочерний процесс умеет назвать СЛОЙ, из которого пришёл ключ его
конфига наблюдаемости (framework/app/recipe/session — снизу вверх). Ключ,
которого нет в ``system.yaml``, обязан быть приписан слою ``framework``.
Это свойство уже покрыто на загрузочной дороге (boot), но НЕ было покрыто на
дороге ГОРЯЧЕЙ пересборки — той, которой ``ProcessManager`` пересобирает
топологию при переключении рецепта, минуя boot целиком
(``orchestrator_hooks.configure_topology_engine`` → замыкание
``_build_proc_dicts``). Тест ниже гоняет ИМЕННО эту дорогу, от настоящего
``system.yaml`` до провенанса дочернего процесса, и отдельно (К4) сверяет её с
загрузочной дорогой на ОДНОМ и ТОМ ЖЕ ключе.

Независимость (см. ТЗ тестера): все числа-свидетели ниже — литералы, измеренные
ЭТИМ тестером на текущем ``system.yaml`` 2026-08-18, ДО чтения любых чужих
тестов на эту же тему. Если файл изменится осознанно — константы ниже придётся
поправить рукой, с объяснением в том же коммите (см. докстринг К3).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.configs.observability_layers import (
    APP_CONFIG_KEY,
    process_observability_layers,
)
from multiprocess_prototype.backend.assembly import BlueprintAssembler
from multiprocess_prototype.backend.assembly.normalize import normalize_blueprint
from multiprocess_prototype.backend.config import schemas as schemas_module
from multiprocess_prototype.backend.config.schemas import load_system_config
from multiprocess_prototype.backend.launch import (
    PROJECT_ROOT,
    load_topology_dict,
    sys_config_for_orchestrator,
)
from multiprocess_prototype.backend.orchestrator_hooks import configure_topology_engine

# --- реальные production-файлы (те же, что грузит лончер) -------------------
SYSTEM_YAML_PATH = Path(schemas_module.__file__).resolve().parent / "system.yaml"
BASE_TOPOLOGY_PATH = PROJECT_ROOT / "multiprocess_prototype" / "backend" / "topology" / "base.yaml"

# base.yaml — фундамент: ОДИН процесс ("devices"), БЕЗ секции observability на
# уровне рецепта (grep подтверждает: ключа "observability:" в файле нет). Выбран
# намеренно — пара framework/app наблюдается БЕЗ примеси слоя L2 (рецепт), иначе
# К1-К4 пришлось бы разбирать втроём, а не в двух слоях.
PROCESS_NAME = "devices"

# --- ключи-свидетели, измерены чтением system.yaml + provenance() 2026-08-18 -
# Поле схемы ObservabilityConfig, которого НЕТ ни в одной секции system.yaml —
# свидетель К1. (В файле есть: log_level, console, file, documents, channels,
# logger_groups, loggers, retention_days, retention_total_mb,
# retention_sweep_interval_sec, errors, stats — session_ttl_sec среди них нет.)
KEY_ABSENT_FROM_APP = "session_ttl_sec"
# Ключ, явно записанный в system.yaml (observability.log_level: INFO) — свидетель К2.
KEY_PRESENT_IN_APP = "log_level"
# Число ключей со слоем framework в provenance() процесса devices на ГОРЯЧЕЙ
# дороге, измеренное 2026-08-18 разведочным прогоном настоящей сборки против
# ТЕКУЩЕГО system.yaml. ЛИТЕРАЛ, а не выражение от кода под тестом: величина,
# вычисленная тем же резолвером, что и код под тестом, согласится с любым его
# ответом, включая "ноль". Если слой L1 расползётся и начнёт закрывать собой
# ключи, которые сегодня остаются дефолтом схемы (или наоборот, схема обрастёт
# новыми полями) — это число разойдётся с фактом, и тест покраснеет.
# 2026-08-25, Ф4 задачи 4.1 плана observation-port: 22 → 25. Схема
# `ObservabilityConfig` обросла секцией порта наблюдений `observation`, и она
# добавила РОВНО три framework-ключа: `observation.subtree_enabled`,
# `observation.subtree_interval_sec` и `observation.rules` (набор правил —
# ОДИН ключ: он объявлен непрозрачным листом слоёв, потому что его ключи —
# glob-паттерны с точками). В `system.yaml` секции `observation` нет, поэтому
# все три законно остаются дефолтом схемы. Прирост ровно на размер новой
# секции — это и есть проверка: расползись слой L1, число сошлось бы иначе.
# 2026-08-31, Ф1.4 задачи 1.4 плана observability-closure: 25 → 27. Схема
# `ObservabilityConfig` обросла секцией окон голоса `voices`, и она добавила
# РОВНО два framework-ключа: `voices.default_window_sec` и
# `voices.escalate_after_repeats` (оба — скаляры, непрозрачных листов у секции
# нет). В `system.yaml` секции `voices` нет, поэтому оба законно остаются
# дефолтом схемы. Прирост ровно на размер новой секции — это и есть проверка:
# расползись слой L1, число сошлось бы иначе.
# 2026-09-03, Ф2 плана observability-closure: 27 → 37. Прирост накопился за
# ЧЕТЫРЕ задачи и был замечен только сейчас — этот файл живёт в КОРНЕВОМ гейте,
# а фаза гонялась фреймворковым, который его не собирает. Это и есть тот случай,
# ради которого правило «гонять ОБА гейта» записано; здесь оно было нарушено.
# Десять ключей, снятых сравнением множеств (не разностью чисел: 338b48c6 → HEAD,
# добавлено 10, удалено 0 — проверено отдельно, потому что «+10» одинаково
# выглядит у «добавили 10» и у «добавили 11, потеряли 1»):
#   * `history.db_path`, `history.enabled`, `history.level`, `history.max_age_sec`,
#     `history.max_rows`, `history.purge_interval_sec` — Task 2.2 (`52c0f585`),
#     секция `history` стала под-схемой; в `system.yaml` её нет, все шесть законно
#     остаются дефолтом схемы;
#   * `voices.max_tracked_keys`, `voices.stale_windows` — Task 2.7 (`a79cb2fa`):
#     потолок карты ключей и такт протухания были литералами без ручки, стали
#     ручками с readback;
#   * `stats.log_snapshots` — Task 2.1 (`fa0b2490`, Р-3а): судьбу ЛОГ-КАНАЛА
#     теперь решает отдельный ключ, а `stats.enabled` стал плоскостью чисел;
#   * `heartbeat_interval_sec` — Task 2.3 (`98afa654`), честный такт в readback.
# Прирост ровно на сумму новых секций и ни одного ключа сверх — это и есть
# проверка: расползись слой L1, множество сошлось бы иначе, а не только число.
EXPECTED_FRAMEWORK_KEY_COUNT = 37


class _FakeChildProcess:
    """Дублёр процесса-получателя: ``get_config`` читает из ЕГО proc_dict.

    Настоящий дочерний процесс получает proc_dict ЦЕЛИКОМ (``process_runner``
    отдаёт ``custom["process_config"]``), поэтому ``read_process_config``
    (``observability_layers.py``) сперва пробует ПЛОСКИЙ ключ (у ребёнка это
    промах — его пространство имён вложено под ``config.``), потом
    ``"config.<key>"``. Дублёр воспроизводит РОВНО эти два случая — не более
    того, ничего не досочиняя поверх задокументированного контракта.
    """

    def __init__(self, proc_dict: dict[str, Any]) -> None:
        self._proc_dict = proc_dict

    def get_config(self, key: str, default: Any = None) -> Any:
        if key.startswith("config."):
            return self._proc_dict.get("config", {}).get(key[len("config.") :], default)
        return self._proc_dict.get(key, default)


class _StubTopologyManager:
    """Дублёр ``TopologyManager``: только сохраняет diff_fn/commands_fn.

    ``configure_topology_engine`` лишь ПОДКЛЮЧАЕТ планировщик сюда — сама
    машинерия применения топологии (``apply_topology``, provision/create/start
    у реальных процессов) в этой задаче не нужна и не тестируется: провенанс
    результата закрывается на уровне собранных ``proc_dict``, до старта
    процессов.
    """

    def configure(self, *, diff_fn: Any, commands_fn: Any) -> None:
        self.diff_fn = diff_fn
        self.commands_fn = commands_fn


class _StubOrchestrator:
    """Минимальный дублёр ``GenericProcessManagerApp`` — РОВНО то, что читает
    ``configure_topology_engine`` (см. ``orchestrator_hooks.py``), и не больше.

    Ключевое для К5: ``sys_config`` приезжает СЮДА уже в форме IPC-словаря
    (результат ``sys_config_for_orchestrator``) — той же, в которой он едет
    через spawn настоящему ``ProcessManager``. Дублёр НЕ строит секцию
    observability сам — её строит ``configure_topology_engine`` внутри себя,
    как в проде (``SystemConfig.model_validate`` → ``.observability.model_dump``).
    """

    def __init__(self, sys_config_dict: dict[str, Any], *, app_config_path: str, recipe_path: str) -> None:
        self._cfg: dict[str, Any] = {
            "sys_config": sys_config_dict,
            "observability_config_path": app_config_path,
            "observability_recipe_path": recipe_path,
            "presentation_overlay": None,
        }
        self._topology_manager = _StubTopologyManager()
        self._full_replace_planner: Any = None
        self.logger_manager = None
        self.error_manager = None
        self.stats_manager = None

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._cfg.get(key, default)

    def _log_info(self, message: str) -> None:  # noqa: D401 — дублёр-заглушка, голос не нужен тесту
        pass

    def _get_protected_names(self) -> set[str]:
        return set()

    def _topology_current_names(self) -> set[str]:
        return set()

    def live_process_config(self, name: str) -> dict | None:
        return None


@dataclass(frozen=True)
class _Scenario:
    """Результат ОДНОГО прогона настоящей сборки — и загрузочной, и горячей дороги."""

    sys_config: Any
    hot_config: dict[str, Any]
    hot_provenance: dict[str, dict[str, str]]
    boot_provenance: dict[str, dict[str, str]]


@pytest.fixture(scope="module")
def scenario() -> _Scenario:
    """Собрать процесс "devices" ОБЕИМИ дорогами против настоящего system.yaml.

    Module-scope: обе дороги — чистая функция от файлов на диске (детерминизм),
    а горячая дорога попутно гоняет настоящее обнаружение плагинов
    (``sys_config.discovery.auto_discover`` в боевом system.yaml — ``true``, и
    здесь он НЕ подменяется на ``false`` намеренно: К5 запрещает подстраивать
    вход под тест, а discovery — часть настоящего шва). Пересчёт на каждый тест
    не добавил бы уверенности, только время.
    """
    assert SYSTEM_YAML_PATH.exists(), f"system.yaml не найден: {SYSTEM_YAML_PATH}"
    assert BASE_TOPOLOGY_PATH.exists(), f"базовая топология не найдена: {BASE_TOPOLOGY_PATH}"

    sys_config = load_system_config()  # тот же дефолтный путь, что резолвит launch.py
    obs_section = sys_config.observability.model_dump(exclude_unset=True)

    # --- дорога BOOT: тот же кусок сборки, что SystemBuilder.build() (launch.py,
    #     п. "Слой L1 — секция observability из system.yaml, СЫРАЯ"), без тяжёлой
    #     обвязки (initial_state/throttle_rules/SystemLauncher), которая провенанса
    #     не касается. normalize_blueprint МУТИРУЕТ вход — свежий dict, не общий
    #     с hot-дорогой ниже (иначе "независимые" дороги делили бы одну мутацию).
    boot_raw_topology = load_topology_dict(BASE_TOPOLOGY_PATH)
    boot_topology = normalize_blueprint(boot_raw_topology, sys_config)
    boot_assembler = BlueprintAssembler(
        observability_section=obs_section,
        log_dir=sys_config.system.log_dir or "logs",
        telemetry_dict=(
            sys_config.telemetry.publish.model_dump() if sys_config.telemetry.publish is not None else None
        ),
        recipe_path=str(BASE_TOPOLOGY_PATH),
        app_config_path=str(SYSTEM_YAML_PATH),
    )
    boot_proc_dicts = boot_assembler.assemble(boot_topology)
    assert PROCESS_NAME in boot_proc_dicts, f"boot: процесс {PROCESS_NAME!r} не собран"
    boot_provenance = process_observability_layers(_FakeChildProcess(boot_proc_dicts[PROCESS_NAME])).provenance()

    # --- дорога HOT: настоящий IPC-шов + настоящая горячая пересборка ---------
    # sys_config_for_orchestrator — ИМЕННО та функция, что launch.py кладёт в
    # orchestrator_config при спавне ProcessManager (S-24). Дублёр-оркестратор
    # получает её РЕЗУЛЬТАТ, не сырой sys_config и не написанный руками словарь.
    sys_config_dict = sys_config_for_orchestrator(sys_config)
    orchestrator = _StubOrchestrator(
        sys_config_dict,
        app_config_path=str(SYSTEM_YAML_PATH),
        recipe_path=str(BASE_TOPOLOGY_PATH),
    )
    configure_topology_engine(orchestrator)  # тот же runtime-хук, что PM вызывает на switch
    planner = orchestrator._full_replace_planner
    assert planner is not None, "configure_topology_engine не сконфигурировал планировщик (sys_config пуст?)"

    hot_raw_topology = load_topology_dict(BASE_TOPOLOGY_PATH)  # свежий — см. предупреждение normalize выше
    commands = planner.commands({"has_changes": True}, hot_raw_topology)
    hot_proc_dicts = {cmd["process_name"]: cmd["proc_dict"] for cmd in commands if cmd["cmd"] == "process.provision"}
    assert PROCESS_NAME in hot_proc_dicts, f"hot: процесс {PROCESS_NAME!r} не пересобран горячей дорогой"
    hot_config = hot_proc_dicts[PROCESS_NAME]["config"]
    hot_provenance = process_observability_layers(_FakeChildProcess(hot_proc_dicts[PROCESS_NAME])).provenance()

    return _Scenario(
        sys_config=sys_config,
        hot_config=hot_config,
        hot_provenance=hot_provenance,
        boot_provenance=boot_provenance,
    )


# --------------------------------------------------------------------------- К1


def test_hot_rebuild_key_absent_from_system_yaml_is_framework_layer(scenario: _Scenario) -> None:
    """К1: ключ, которого НЕТ в system.yaml, обязан прийти на дочерний процесс
    слоем framework (и layer, и source) — ПОСЛЕ горячей пересборки рецепта,
    не только на старте.

    Если это не так: оператор, спросивший "почему у меня такое значение
    session_ttl_sec" СРАЗУ ПОСЛЕ переключения рецепта (а не на старте
    системы), получит враньё об источнике — например, "app" там, где system.yaml
    молчит. introspect.observability станет ненадёжным ровно там, где к нему
    чаще всего обращаются: сразу после live-смены конфигурации.
    """
    entry = scenario.hot_provenance.get(KEY_ABSENT_FROM_APP)
    assert entry == {"layer": "framework", "source": "framework"}, (
        f"{KEY_ABSENT_FROM_APP!r} на горячей дороге получил {entry!r}, а обязан "
        f"{{'layer': 'framework', 'source': 'framework'}} — ключа нет в system.yaml, "
        f"приписывать его app/recipe/session нельзя"
    )


# --------------------------------------------------------------------------- К2


def test_hot_rebuild_key_present_in_system_yaml_is_app_layer(scenario: _Scenario) -> None:
    """К2 (контроль от вакуумного прохода К1): ключ, который В system.yaml
    ЕСТЬ, обязан остаться слоем app с source == абсолютный путь ИМЕННО этого
    system.yaml — после горячей пересборки, не только на старте.

    Без этого контроля К1 прошёл бы и на реализации, которая отвечает
    "framework" на ЛЮБОЙ ключ без разбора (вакуумный зелёный). Тогда оператор
    не смог бы отличить "это дефолт фреймворка" от "я сам выставил это в
    system.yaml" — а правка, случайно улетевшая не в тот файл, осталась бы
    незамеченной НАВСЕГДА, потому что источник всегда говорил бы правду с
    вероятностью совпадения, а не по построению.
    """
    entry = scenario.hot_provenance.get(KEY_PRESENT_IN_APP)
    assert entry is not None, f"свидетель {KEY_PRESENT_IN_APP!r} отсутствует в provenance() горячей дороги"
    assert entry["layer"] == "app", (
        f"{KEY_PRESENT_IN_APP!r} задан в system.yaml, но горячая дорога называет слой {entry['layer']!r}, а не 'app'"
    )
    assert entry["source"] == str(SYSTEM_YAML_PATH), (
        f"{KEY_PRESENT_IN_APP!r}: source горячей дороги = {entry['source']!r}, а обязан быть "
        f"абсолютным путём {str(SYSTEM_YAML_PATH)!r} — оператору, который пойдёт править файл, "
        f"нужен путь ДО файла, а не абстрактное имя слоя"
    )


# --------------------------------------------------------------------------- К3


def test_hot_rebuild_framework_layer_key_count_is_pinned(scenario: _Scenario) -> None:
    """К3: число ключей со слоем framework — литерал, зафиксированный вручную
    измерением на реальном system.yaml (не выражение от кода под тестом).

    Если резолвер провенанса когда-нибудь начнёт засчитывать L1 "заданным" по
    ключам, которые оператор не писал (класс регресса "exclude_unset потерялся
    на границе процессов" — см. докстринг sys_config_for_orchestrator в
    launch.py: тот же класс дефекта раздувал L1 с 12 до 23 ключей на боевом
    файле) — framework-набор молча просядет к нулю или расползётся, а тест,
    сравнивающий систему саму с собой, прошёл бы в обоих случаях. Число ниже —
    внешняя, независимая точка отсчёта именно против этого.
    """
    framework_keys = sorted(k for k, v in scenario.hot_provenance.items() if v["layer"] == "framework")
    assert len(framework_keys) == EXPECTED_FRAMEWORK_KEY_COUNT, (
        f"framework-ключей на горячей дороге: {len(framework_keys)} (список: {framework_keys}), "
        f"а зафиксировано {EXPECTED_FRAMEWORK_KEY_COUNT} — слой L1 расширился или сузился незамеченным; "
        f"если system.yaml поменяли осознанно — замените константу и объясните почему в этом же коммите"
    )


# --------------------------------------------------------------------------- К4


def test_boot_and_hot_road_agree_on_layer(scenario: _Scenario) -> None:
    """К4: загрузочная и горячая дороги обязаны сходиться в ОДНОМ и ТОМ ЖЕ слое
    для ОДНОГО и ТОГО ЖЕ ключа — полное совпадение framework-множеств плюс оба
    ключа-свидетеля дословно.

    Расхождение здесь означает, что introspect.observability отвечает
    ПО-РАЗНОМУ до первого switch и после: оператор получил бы один ответ на
    старте системы и другой — после первой же смены рецепта на ТОМ ЖЕ
    system.yaml, хотя единственное, что поменялось, — это дорога сборки, а не
    содержимое файла. Ложное "источник изменился" после каждого switch —
    даже без единой правки конфига — было бы такой находкой.

    **Предел, который надо знать, читая зелёный цвет** (найдено ревью 2026-08-18
    воспроизведением): boot-сторона здесь — РЕКОНСТРУКЦИЯ куска
    ``SystemBuilder.build()``, а не сам builder. Инъекция «настоящий boot теряет
    ``exclude_unset``» оставила все девять тестов обоих файлов зелёными, и её
    поймали только снапшоты ``test_build_characterization.py`` (2 красных).
    То есть паритет здесь — «моя реконструкция ↔ настоящая горячая»; настоящий
    boot стерегут снапшоты характеризации и
    ``test_hot_rebuild_parity_hazards.py::test_the_real_launcher_ships_a_thin_sys_config``,
    который поднимает живой ``SystemBuilder``. Чинить это подъёмом builder'а
    здесь не стали намеренно: третья копия сборки — третья модель одного шва.
    """
    boot_framework = {k for k, v in scenario.boot_provenance.items() if v["layer"] == "framework"}
    hot_framework = {k for k, v in scenario.hot_provenance.items() if v["layer"] == "framework"}
    assert hot_framework == boot_framework, (
        f"framework-набор разошёлся между дорогами: только на boot "
        f"{sorted(boot_framework - hot_framework)!r}, только на hot {sorted(hot_framework - boot_framework)!r}"
    )
    for key in (KEY_ABSENT_FROM_APP, KEY_PRESENT_IN_APP):
        assert scenario.hot_provenance.get(key) == scenario.boot_provenance.get(key), (
            f"{key!r} разошёлся между дорогами: hot={scenario.hot_provenance.get(key)!r}, "
            f"boot={scenario.boot_provenance.get(key)!r}"
        )


# --------------------------------------------------------------------------- К5


def test_hot_rebuild_config_matches_the_real_ipc_seam(scenario: _Scenario) -> None:
    """К5 (главный критерий): секция observability, доехавшая до ребёнка
    горячей дорогой, обязана быть ТЕМ, что настоящий production-шов
    (``sys_config_for_orchestrator``) реально кладёт в ``orchestrator_config`` —
    измеренным здесь НЕЗАВИСИМЫМ повторным вызовом той же функции, а не тем,
    что тест сочинил сам как словарь.

    Если бы этот тест сверялся с руками собранным словарём вместо результата
    настоящего производственного шва, он продолжил бы быть зелёным и ПОСЛЕ
    того, как реальный шов сломается (переименуют ключ ``observability`` в
    IPC-конверте, потеряют ``exclude_unset``, поменяют форму дампа) — ровно
    так на прошлой задаче мимо цели прошли три теста из десяти: зелёный цвет
    ничего не доказывал про прод. Вторая часть проверки — историческая граница
    именно этого шва (докстринг ``sys_config_for_orchestrator``): 12 ключей
    верхнего уровня на боевом файле, а не 23 (полный дамп без ``exclude_unset``,
    прежний регресс).
    """
    independent_dump = sys_config_for_orchestrator(scenario.sys_config)  # НЕЗАВИСИМЫЙ повторный вызов шва
    expected_app_section = independent_dump.get("observability")
    assert expected_app_section, "sys_config_for_orchestrator не дал секцию observability — сверяться не с чем"

    assert scenario.hot_config.get(APP_CONFIG_KEY) == expected_app_section, (
        "секция observability на дочернем процессе (горячая дорога) не совпала с независимым "
        "вызовом sys_config_for_orchestrator — вход пришёл не тем швом, каким он едет в проде"
    )
    assert len(expected_app_section) == 12, (
        f"sys_config_for_orchestrator().observability имеет {len(expected_app_section)} ключей "
        f"верхнего уровня, а не 12 — похоже, exclude_unset перестал действовать на границе "
        f"launcher -> ProcessManager, и слой L1 больше не умеет молчать"
    )
