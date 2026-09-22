# -*- coding: utf-8 -*-
"""Приёмочные RED-тесты (Task 1.5 плана line-sim) для нового kwarg
``telemetry_section`` у ``assemble_proc_dicts`` + проводки ``SystemBuilder._build_generic``
(читает ``telemetry.publish`` из файла ``manifest.system``, передаёт как ``telemetry_section``).

Независимый тестер, БЕЗ реализации (worktree на коммите 340b301a, ДО неё). Контракт — из
DESIGN-секции брифа lead'а (не из кода, кроме уже существующего typed-поля
``SystemBlueprint`` process-модели ``telemetry: dict | None`` — оно уже в дереве, подтверждено
чтением ``multiprocess_framework/modules/process_manager_module/topology/blueprint.py:183-192``,
но СЕГОДНЯ нигде не читается: ``assemble_proc_dicts`` не принимает ``telemetry_section`` и не
трогает ``cfg.telemetry`` вовсе — RED по конструкции, не гипотеза).

Потребитель ключа ``telemetry`` уже есть во фреймворке — ``ProcessHeartbeat._build_telemetry_gate``
(``process_heartbeat.py:540-619``) читает ``proc_dict["config"]["telemetry"]["publish"]`` через
``read_process_config`` (плоский адрес ИЛИ ``config.<ключ>``). Тесты ниже пинают ФОРМУ, которую
кладёт ассемблер, не поведение гейта (гейт — не в скоупе этой задачи).

Слияние global+per-process — канонический ``deep_merge`` (``data_schema_module/core/helpers.py``):
overlay побеждает по ключу, вложенные dict рекурсивно сливаются. Литералы ожиданий ниже посчитаны
РУКАМИ по этому правилу, а не вызовом ``deep_merge`` из теста (тест не должен доказывать себя кодом
под тестом).

Форма для SystemBuilder-тестов (T5) — тот же приём, что ``test_state_bootstrap_unpicklable_result_
names_hook`` в ``test_builder.py``: временные ``app.yaml``/``pipeline.yaml`` в ``tmp_path``, плагин
``examples.minimal_app.plugins.tick_source.plugin.TickSourcePlugin`` (уже зарегистрирован импортом
в T1-T4 модульного уровня — reuse, не новый плагин).

Шов: ``assemble_proc_dicts(...)`` возвращает ``{name: proc_dict}`` напрямую (T1-T4); для
SystemBuilder — ``SystemBuilder(spec).build()._processes`` (``List[Tuple[str, dict]]``, тот же
приватный атрибут, что использует ``test_builder.py::test_generic_build_produces_launcher`` —
самый мелкий публичный шов без запуска процессов, подтверждено чтением ``system_launcher.py::
add_process`` — ``merge_with_defaults`` не режет незнакомые ключи, значит ``telemetry`` в
``proc_dict["config"]`` доедет до ``_processes`` как есть).
"""

from __future__ import annotations

from pathlib import Path

import examples.minimal_app.plugins.tick_source.plugin  # noqa: F401 — регистрирует плагин для check()

from multiprocess_framework.modules.app_module import AppSpec, SystemBuilder, assemble_proc_dicts

_GENERIC_PROCESS = "multiprocess_framework.modules.process_module.generic.generic_process.GenericProcess"
_TICK_PLUGIN = "examples.minimal_app.plugins.tick_source.plugin.TickSourcePlugin"

_GLOBAL_PUBLISH = {
    "default_enabled": False,
    "default_interval_sec": 1.0,
    "metrics": {
        "fps": {"enabled": True, "interval_sec": 1.0},
        "latency_ms": {"enabled": True, "interval_sec": 1.0},
    },
}


def _process_entry(name: str, *, telemetry: dict | None = None) -> dict:
    entry: dict = {
        "process_name": name,
        "process_class": _GENERIC_PROCESS,
        "plugins": [
            {
                "plugin_class": _TICK_PLUGIN,
                "plugin_name": f"tick_source_{name}",
                "category": "utility",
            }
        ],
    }
    if telemetry is not None:
        entry["telemetry"] = telemetry
    return entry


def _blueprint(*processes: dict) -> dict:
    return {"name": "t15", "processes": list(processes), "wires": []}


# --------------------------------------------------------------------------- #
# T1: telemetry_section (global) без per-process override — на каждом процессе#
# --------------------------------------------------------------------------- #


def test_global_telemetry_only_merges_into_every_process() -> None:
    """Пин: telemetry_section=<global> без per-process override -> config['telemetry'] ==
    {'publish': <global как есть>}; ключа 'telemetry_override' нет (override не задан).

    Провал сегодня: assemble_proc_dicts не принимает kwarg telemetry_section -> TypeError.
    """
    blueprint = _blueprint(_process_entry("ticker"))

    proc_dicts = assemble_proc_dicts(blueprint, telemetry_section=_GLOBAL_PUBLISH)

    cfg = proc_dicts["ticker"]["config"]
    assert cfg.get("telemetry") == {"publish": _GLOBAL_PUBLISH}, f"telemetry не совпал: {cfg.get('telemetry')!r}"
    assert "telemetry_override" not in cfg, f"telemetry_override появился без per-process override: {cfg!r}"


# --------------------------------------------------------------------------- #
# T2: per-process metrics.<name> побеждает, остальные global-метрики остаются #
# --------------------------------------------------------------------------- #


def test_per_process_metric_override_wins_others_stay() -> None:
    """Пин: per-process telemetry={'metrics': {'fps': {'enabled': False}}} поверх глобального
    -> merged.metrics.fps == {'enabled': False, 'interval_sec': 1.0} (interval_sec унаследован
    от global — deep_merge рекурсивно сливает вложенный dict, а не заменяет целиком),
    merged.metrics.latency_ms остаётся как в global (ключ не тронут); merged.default_enabled/
    default_interval_sec — как в global (per-process их не называл). Сосед без override
    (ticker) получает чистый global, без утечки override'а.

    Провал сегодня: assemble_proc_dicts не принимает telemetry_section -> TypeError (тот же
    класс отказа, что T1 — форма ошибки подтверждает, что kwarg вообще не существует, не
    что merge неверен).
    """
    override = {"metrics": {"fps": {"enabled": False}}}
    blueprint = _blueprint(
        _process_entry("ticker"),
        _process_entry("ticker2", telemetry=override),
    )

    proc_dicts = assemble_proc_dicts(blueprint, telemetry_section=_GLOBAL_PUBLISH)

    expected_merged = {
        "default_enabled": False,
        "default_interval_sec": 1.0,
        "metrics": {
            "fps": {"enabled": False, "interval_sec": 1.0},
            "latency_ms": {"enabled": True, "interval_sec": 1.0},
        },
    }
    cfg2 = proc_dicts["ticker2"]["config"]
    assert cfg2.get("telemetry") == {"publish": expected_merged}, f"merge неверен: {cfg2.get('telemetry')!r}"
    assert cfg2.get("telemetry_override") == override, (
        f"сырой override не сохранён как есть: {cfg2.get('telemetry_override')!r}"
    )

    cfg1 = proc_dicts["ticker"]["config"]
    assert cfg1.get("telemetry") == {"publish": _GLOBAL_PUBLISH}, f"сосед без override задет: {cfg1.get('telemetry')!r}"
    assert "telemetry_override" not in cfg1, f"override соседа утёк на ticker: {cfg1!r}"


# --------------------------------------------------------------------------- #
# T3 (предсказано ЗЕЛЁНЫМ сегодня): ни то ни другое не задано -> ключа нет    #
# --------------------------------------------------------------------------- #


def test_neither_global_nor_per_process_key_absent() -> None:
    """Пин обратной совместимости: assemble_proc_dicts(blueprint) без telemetry_section и без
    per-process telemetry -> ключа 'telemetry' в config нет вовсе (не None, не {'publish': {}}).

    Предсказано ЗЕЛЁНЫМ уже сегодня: сегодняшний assemble_proc_dicts вообще не знает про
    telemetry и ничего в config под этим именем не кладёт — это и есть нужный дефолт, тест
    фиксирует его ДО правки, чтобы после неё он не стал регрессией.
    """
    blueprint = _blueprint(_process_entry("ticker"))

    proc_dicts = assemble_proc_dicts(blueprint)

    assert "telemetry" not in proc_dicts["ticker"]["config"], (
        f"ключ появился без источника: {proc_dicts['ticker']['config']!r}"
    )


# --------------------------------------------------------------------------- #
# T4: явный {} (global) -> ключ ЕСТЬ, {'publish': {}} — не схлопывается       #
# --------------------------------------------------------------------------- #


def test_explicit_empty_global_section_key_present_not_collapsed() -> None:
    """Пин ловушки: telemetry_section={} (явно пустой dict, не None) -> config['telemetry'] ==
    {'publish': {}} — ключ ЕСТЬ. Соседний ``observability_section`` в этом же файле использует
    ``app_layer = observability_section or {}`` + ``if app_layer:`` (falsy-проверка схлопывает
    пустое с молчанием) — DESIGN явно требует ДРУГОГО поведения для telemetry: пустое ≠
    отсутствующее. Наивная копипаста того же ``or {}`` + ``if ...:`` паттерна дала бы тут
    ложный отказ этого теста (ключа не было бы вовсе).

    Провал сегодня: TypeError (kwarg не существует), тот же класс, что T1/T2.
    """
    blueprint = _blueprint(_process_entry("ticker"))

    proc_dicts = assemble_proc_dicts(blueprint, telemetry_section={})

    cfg = proc_dicts["ticker"]["config"]
    assert "telemetry" in cfg, f"пустая секция схлопнулась в отсутствие ключа: {cfg!r}"
    assert cfg["telemetry"] == {"publish": {}}, f"форма пустой секции неверна: {cfg['telemetry']!r}"


# --------------------------------------------------------------------------- #
# T5: SystemBuilder читает telemetry.publish файла manifest.system            #
# --------------------------------------------------------------------------- #


def test_system_builder_reads_telemetry_publish_from_system_yaml(tmp_path: Path) -> None:
    """Пин проводки: ``SystemBuilder._build_generic`` читает секцию ``telemetry.publish`` файла,
    названного ``manifest.system`` (ТОТ ЖЕ файл, что уже отдаёт ``observability``), и передаёт
    её как ``telemetry_section`` в ``assemble_proc_dicts`` — собранный (не запущенный) launcher
    несёт ``telemetry`` в config процесса.

    Провал сегодня: ``_build_generic`` не читает ``telemetry:`` из ``system.yaml`` вовсе (нет
    такого кода) -> ключа 'telemetry' в проце нет -> AssertionError (не TypeError — сборка сама
    по себе сегодня уже работает, просто без телеметрии).
    """
    (tmp_path / "pipeline.yaml").write_text(
        "name: p\nprocesses:\n"
        f"  - process_name: ticker\n"
        f"    process_class: {_GENERIC_PROCESS}\n"
        "    plugins:\n"
        f"      - plugin_class: {_TICK_PLUGIN}\n"
        "        plugin_name: tick_source_sb\n"
        "        category: utility\n"
        "wires: []\n",
        encoding="utf-8",
    )
    (tmp_path / "system.yaml").write_text(
        "telemetry:\n  publish:\n    default_enabled: false\n    metrics:\n      fps:\n        enabled: true\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "app.yaml"
    manifest.write_text("name: SBTelemetryApp\npipeline: pipeline.yaml\nsystem: system.yaml\n", encoding="utf-8")

    spec = AppSpec(manifest_path=manifest)
    launcher = SystemBuilder(spec).build()

    processes = dict(launcher._processes)
    cfg = processes["ticker"]["config"]
    assert cfg.get("telemetry") == {"publish": {"default_enabled": False, "metrics": {"fps": {"enabled": True}}}}, (
        f"telemetry из system.yaml не доехал до proc_dict: {cfg.get('telemetry')!r}"
    )
