# -*- coding: utf-8 -*-
"""Приёмочные RED-тесты (Task 1.5 + 1.6 плана line-sim) для реальной сборки
``apps/line_sim/app.yaml``: гейт телеметрии (1.5) на всех трёх процессах + memory-канал
``flight_ring`` (1.6) на процессе ``camera``.

Независимый тестер, БЕЗ реализации (worktree на коммите 340b301a, ДО неё). Контракт —
DESIGN-секция брифа lead'а (литералы ниже — из него, не выведены из кода):
  - ``apps/line_sim/system.yaml`` получит ``telemetry.publish: {default_enabled: false,
    default_interval_sec: 1.0, metrics: {fps: {enabled: true, interval_sec: 1.0}, latency_ms:
    {enabled: true, interval_sec: 1.0}}}`` — БЕЗ per-process override (все три процесса
    получают один и тот же global);
  - ``apps/line_sim/pipeline.yaml`` получит ``observability.processes.camera``: канал
    ``flight_ring`` ``{type: memory, capacity: 500}`` + scope ``SYSTEM`` channels
    ``[console, system_file, flight_ring]`` (замещение оси, ЛОВУШКА брифа п.2: список из ТРЁХ
    имён, не только flight_ring — иначе console/system_file потеряны).

СЕГОДНЯ ни ``system.yaml``, ни ``pipeline.yaml`` этих секций не содержат (прочитано
непосредственно на коммите теста) — правка файлов вне скоупа тестера (OUT OF SCOPE брифа:
"производственный код любого рода"), поэтому тесты ниже красные против РЕАЛЬНЫХ конфигов
до реализации Task 1.5/1.6, и это ожидаемо (тот же класс RED, что ``test_f1_task11_
acceptance.py`` пинал будущую форму до правки конфигов).

Шов — тот же, что у ``test_task15_telemetry_gate_acceptance.py::test_system_builder_reads_
telemetry_publish_from_system_yaml`` (app_module tests, читал ДО написания этого файла):
``build_app(app_yaml)._processes`` -> ``List[Tuple[str, proc_dict]]``, сборка без запуска
процессов (не нужен backend_ctl/harness — быстрее и без сетевых портов).

Раскладка ``channels``/``loggers.SYSTEM.channels`` — прочитана в
``multiprocess_framework/modules/process_module/configs/observability_config.py::
expand_observability`` (строки ~958-987, allowed reading: consumer наблюдаемости) и
``observability_layers.py::apply_layers_to_proc_dict`` (строки 1038-1062): landing spot —
``proc_dict["managers"]["logger"]["channels"]`` (реестр именованных каналов) и
``proc_dict["managers"]["logger"]["loggers"]["SYSTEM"]["channels"]`` (правило скоупа SYSTEM,
скоуп — константа ``logger_module/log_enums.py::ScopeName.SYSTEM = "SYSTEM"``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from multiprocess_framework.modules.app_module import build_app

# .../apps/line_sim/tests/<file> -> parents[3] = корень репо.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_LINE_SIM_APP_YAML = _REPO_ROOT / "apps" / "line_sim" / "app.yaml"

_EXPECTED_PUBLISH = {
    "default_enabled": False,
    "default_interval_sec": 1.0,
    "metrics": {
        "fps": {"enabled": True, "interval_sec": 1.0},
        "latency_ms": {"enabled": True, "interval_sec": 1.0},
    },
}


@pytest.fixture(scope="module")
def line_sim_processes() -> dict:
    """proc_dicts реального line_sim (сборка без запуска, discovery per app.yaml)."""
    launcher = build_app(_LINE_SIM_APP_YAML)
    return dict(launcher._processes)


# --------------------------------------------------------------------------- #
# Task 1.5: telemetry.publish global на КАЖДОМ из трёх процессов              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("proc_name", ["robot", "camera", "mjpeg"])
def test_process_gets_global_telemetry_publish(line_sim_processes: dict, proc_name: str) -> None:
    """Пин: config['telemetry'] == {'publish': <literal из DESIGN>} на robot/camera/mjpeg —
    один и тот же global, без per-process override (1.5 не заводит override'ов для сима).

    Провал сегодня: apps/line_sim/system.yaml не содержит telemetry: вовсе -> ключа
    'telemetry' в config процесса нет -> AssertionError (сборка сама успешна).
    """
    cfg = line_sim_processes[proc_name]["config"]
    assert cfg.get("telemetry") == {"publish": _EXPECTED_PUBLISH}, (
        f"{proc_name}: telemetry не совпал с ожиданием DESIGN: {cfg.get('telemetry')!r}"
    )


# --------------------------------------------------------------------------- #
# Task 1.6: canal flight_ring объявлен на camera, type=memory, capacity=500   #
# --------------------------------------------------------------------------- #


def test_camera_flight_ring_channel_is_memory_with_capacity_500(line_sim_processes: dict) -> None:
    """Пин: proc_dict['managers']['logger']['channels']['flight_ring'] == {'type': 'memory',
    'capacity': 500} на процессе camera.

    Провал сегодня: pipeline.yaml не содержит observability.processes.camera -> канал не
    объявлен -> KeyError/AssertionError (channels либо отсутствует, либо не содержит flight_ring).
    """
    managers = line_sim_processes["camera"].get("managers", {})
    logger = managers.get("logger", {})
    channels = logger.get("channels", {})
    assert channels.get("flight_ring") == {"type": "memory", "capacity": 500}, (
        f"канал flight_ring не объявлен как {{'type': 'memory', 'capacity': 500}} на camera: {channels!r}"
    )


# --------------------------------------------------------------------------- #
# Task 1.6: SYSTEM-скоуп camera держит console+system_file+flight_ring        #
# --------------------------------------------------------------------------- #


def test_camera_system_scope_keeps_console_and_system_file_plus_flight_ring(line_sim_processes: dict) -> None:
    """Пин ЛОВУШКИ брифа (ось channels ЗАМЕЩАЕТ, не добавляет): SYSTEM-скоуп camera после
    правки содержит РОВНО {console, system_file, flight_ring} — не {flight_ring} в одиночку
    (что потеряло бы console/system_file при наивной правке).

    Маршрут скоупа живёт в ``managers.logger.scopes`` (раскладка
    ``expand_observability``), а не в ``loggers`` — там правила per-module. Первая версия
    теста (независимый тестер) искала его в ``loggers["SYSTEM"]`` и осталась бы красной
    при верном конфиге; путь исправлен ведущим, решение — в отчёте тестера Task 1.5/1.6.
    """
    managers = line_sim_processes["camera"].get("managers", {})
    logger = managers.get("logger", {})
    scopes = logger.get("scopes", {})
    system_rule = scopes.get("SYSTEM", {})
    channels_list = system_rule.get("channels")
    assert channels_list is not None, f"SYSTEM.channels не задан на camera: {scopes!r}"
    assert set(channels_list) == {"console", "system_file", "flight_ring"}, (
        f"SYSTEM.channels camera потерял console/system_file или не добавил flight_ring: {channels_list!r}"
    )


# --------------------------------------------------------------------------- #
# Task 1.6: robot и mjpeg НЕ получают flight_ring (только camera назван)      #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("proc_name", ["robot", "mjpeg"])
def test_neighbor_process_has_no_flight_ring_channel(line_sim_processes: dict, proc_name: str) -> None:
    """Пин негативного случая: pipeline.yaml называет ТОЛЬКО camera в observability.processes
    -> robot/mjpeg не получают канал flight_ring в реестре логгера.

    Замечание тестера (см. отчёт): этот тест может остаться ЗЕЛЁНЫМ уже сегодня (у процесса
    без per-process override канала 'flight_ring' и так нет ни у кого) — это не признак
    поломки прогона, а совпадение с "ничего ещё не сделано"; ценность теста — как регрессия
    ПОСЛЕ реализации 1.6 (чтобы правка camera не утекла на соседей).
    """
    managers = line_sim_processes[proc_name].get("managers", {})
    logger = managers.get("logger", {})
    channels = logger.get("channels", {})
    assert "flight_ring" not in channels, f"{proc_name}: неожиданно получил канал flight_ring: {channels!r}"
