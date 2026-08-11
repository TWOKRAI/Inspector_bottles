# -*- coding: utf-8 -*-
"""Живой гейт этапа 2 плана observability-roadmap — стенд webcam_sketch.

Тесты доказали МЕХАНИКУ трёх задач; здесь судится то, чего в тестах нет:

* **2.3 — рождение менеджеров.** Приёмка сформулирована как «boot: 0
  предупреждений», и проверить её можно только реальным стартом: оркестратор
  спавнится отдельным кодом, и в unit-тесте этого пути нет. До задачи его
  ``StatsManager`` на каждом старте писал предупреждение о собственном конфиге.
* **2.2 — типы параметров.** Живая дорога длиннее тестовой: сокет → роутер →
  receive-мидлварь → диспетчер → обёртка. Находка Н-5 («Dispatch failed: 'bool'
  object is not iterable») пришла именно оттуда, при зелёных тестах.
* **2.1 — содержимое телеметрии.** Главное следствие находки было НЕ на своей
  плоскости: отравленный слой ломал следующий, ни в чём не виноватый
  ``config.reload`` соседа. Такое видно только на живом процессе с общим слоем.

Проверки:

    S1  boot: ни одного предупреждения «ниже пола» ни от одного процесса стенда
        (читается из файлов прогона — артефакт, а не память зонда).
    S2  детектор из S1 ЖИВ: настоящее нарушение пола на живом процессе даёт
        предупреждение в хвосте. Без этой пары «0 предупреждений» доказывало бы
        заглушенный логгер.
    S3  различающий замер: рецепт задаёт оркестратору ``flush_interval: 2.0``
        поимённо; у ПМ действующий пол 2.0, у ребёнка — дефолтные 10.0.
        Проверять ``aggregation_interval`` бессмысленно: темп это
        ``max(flush, agg)``, и ``max(5,10) == max(10,10)`` — он совпал бы и при
        полностью не доехавшем конфиге.
    S4  типы (2.2): чужой тип в объявленное поле команды наблюдаемости →
        ``success=false``, в отказе имя поля и ожидаемый тип. Ни одного
        ``Dispatch failed`` на всей поверхности.
    S5  четыре плоскости (гейт этапа): мусор в logger / error / stats /
        telemetry → адресный отказ, слой L3 не тронут.
    S6  сосед не отравлен: после отказа телеметрии обычный ``config.reload``
        соседней плоскости проходит.
    S7  приёмная сторона: валидные формы всех дорог действуют — иначе
        «отвергать всё» прошло бы проверки выше.

Запуск: ``python -m backend_ctl.probes.probe_stage2_observability_gate``
Стенд одиночный — порт 8765 не терпит двух. Прогон ~3 минуты.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["BACKEND_CTL"] = "1"

#: Свой каталог логов на прогон. Метка времени берётся ТОЛЬКО если каталог ещё
#: не назначен: на Windows дети спавнятся переимпортом модуля, и безусловный
#: расчёт метки разводил писателей по разным каталогам (грабля прогона 1.6).
_inherited = os.environ.get("MULTIPROCESS_LOG_DIR")
LOG_DIR = Path(_inherited) if _inherited else PROJECT_ROOT / "logs_live" / f"stage2_{int(time.time())}"
LOG_DIR.mkdir(parents=True, exist_ok=True)
os.environ["MULTIPROCESS_LOG_DIR"] = str(LOG_DIR)

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

from backend_ctl.harness import BackendHarness  # noqa: E402
from backend_ctl.protocol import _leaf_result  # noqa: E402

RECIPES = PROJECT_ROOT / "multiprocess_prototype" / "recipes"
BASE_RECIPE = RECIPES / "webcam_sketch.yaml"
#: Рецепт стенда пишется зондом и удаляется им же — трекаемые файлы не трогаем.
STAND_RECIPE = RECIPES / "_probe_stage2_webcam.yaml"

PM = "ProcessManager"
CHILD = "camera_0"

#: Пара, на которой ветки РАСХОДЯТСЯ (см. S3). Дефолты схемы — 5.0 / 10.0.
DIVERGING = {"aggregation_interval": 10.0, "flush_interval": 2.0}

#: Текст, которым StatsManager сообщает о сработавшем поле.
FLOOR_MARK = "ниже пола"

FAILURES: List[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


def make_stand_recipe() -> None:
    """webcam_sketch + секция наблюдаемости с расходящейся парой для ПМ.

    Секция кладётся ВНУТРЬ ``blueprint:`` — рецепт v3 разворачивается
    ``unwrap_recipe``, плоская секция до неё не доехала бы. Оркестратор
    адресуется ПОИМЁННО: оптовый ключ ``defaults`` на него не действует
    (решение владельца Р1 задачи 5.13).
    """
    import yaml

    data = yaml.safe_load(BASE_RECIPE.read_text(encoding="utf-8"))
    data["blueprint"]["observability"] = {"processes": {PM: {"stats": dict(DIVERGING)}}}
    STAND_RECIPE.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def cmd(drv, process: str, command: str, data: Dict[str, Any] | None = None, timeout: float = 25.0) -> Dict[str, Any]:
    """Команда процессу. Транспортный сбой возвращается КАК ответ, а не молчанием."""
    try:
        return _leaf_result(drv.send_command(process, command, data or {}, timeout=timeout)) or {}
    except Exception as exc:  # noqa: BLE001
        return {"success": None, "reason": f"<транспорт: {type(exc).__name__}: {exc}>"}


def obs(drv, process: str) -> Dict[str, Any]:
    return cmd(drv, process, "introspect.observability", {"audit_limit": 3})


def stats_of(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    return ((snapshot.get("effective") or {}).get("stats") or {}) if isinstance(snapshot, dict) else {}


def session_keys(drv, process: str) -> List[str]:
    return list(((obs(drv, process).get("layers") or {}).get("session_keys")) or [])


def process_names(drv) -> List[str]:
    overview = drv.system_overview(timeout=30.0) or {}
    for key in ("processes", "process_list", "topology"):
        section = overview.get(key)
        if isinstance(section, dict) and section:
            return sorted(str(k) for k in section)
        if isinstance(section, list) and section:
            names = []
            for item in section:
                if isinstance(item, str):
                    names.append(item)
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("process")
                    if name:
                        names.append(str(name))
            if names:
                return sorted(set(names))
    return []


# --------------------------------------------------------------------------
# S1 / S2 / S3 — задача 2.3
# --------------------------------------------------------------------------


def s1_boot_is_silent_about_its_own_config() -> None:
    log("\n--- S1: boot — ни одного предупреждения «ниже пола» ---")
    hits: List[str] = []
    scanned = 0
    for path in sorted(LOG_DIR.rglob("*.log")):
        scanned += 1
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if FLOOR_MARK in line:
                hits.append(f"{path.name}: {line.strip()[:150]}")
    check(scanned > 0, "файлы логов прогона найдены", f"просмотрено файлов: {scanned} в {LOG_DIR}")
    check(not hits, "ни один процесс не предупредил о своём конфиге на старте", f"найдено строк: {len(hits)}")
    for hit in hits[:5]:
        log(f"         {hit}")


def s2_the_detector_is_alive(drv) -> None:
    log("\n--- S2: детектор жив — настоящее нарушение пола слышно ---")
    before = _floor_lines()
    res = cmd(drv, CHILD, "config.reload", {"observability": {"stats": {"aggregation_interval": 0.5}}, "ttl": 60})
    check(bool(res.get("success")), "правка с заведомо низким темпом принята", f"ответ: {str(res)[:150]}")
    time.sleep(3.0)
    after = _floor_lines()
    check(
        after > before,
        "нарушение пола предупредило вслух",
        f"строк «{FLOOR_MARK}»: было {before}, стало {after}",
    )
    cmd(drv, CHILD, "config.reload", {"observability_session_clear": True})


def _floor_lines() -> int:
    total = 0
    for path in LOG_DIR.rglob("*.log"):
        try:
            total += path.read_text(encoding="utf-8", errors="replace").count(FLOOR_MARK)
        except OSError:
            continue
    return total


def s3_the_diverging_measurement(drv) -> None:
    log("\n--- S3: различающий замер — пол темпа у ПМ против ребёнка ---")
    pm = stats_of(obs(drv, PM))
    child = stats_of(obs(drv, CHILD))
    log(f"         ПМ:     {pm}")
    log(f"         {CHILD}: {child}")
    check(
        pm.get("flush_interval") == DIVERGING["flush_interval"],
        "у оркестратора действует ПОЛ из рецепта, а не дефолт схемы",
        f"flush_interval ПМ = {pm.get('flush_interval')} (рецепт {DIVERGING['flush_interval']}, дефолт 10.0)",
    )
    check(
        child.get("flush_interval") != DIVERGING["flush_interval"],
        "ребёнок НЕ получил поимённую правку оркестратора",
        f"flush_interval {CHILD} = {child.get('flush_interval')}",
    )
    check(
        pm.get("aggregation_interval") == child.get("aggregation_interval"),
        "общий ключ system.yaml одинаков у обоих (контроль: замер не про него)",
        f"aggregation_interval ПМ={pm.get('aggregation_interval')} {CHILD}={child.get('aggregation_interval')}",
    )


# --------------------------------------------------------------------------
# S4 — задача 2.2
# --------------------------------------------------------------------------

#: (команда, поле, заведомо чужое значение, ожидаемый тип в отказе).
TYPE_CASES = [
    ("introspect.observability", "resolve", True, "str"),
    ("introspect.observability", "audit_limit", "не число", "int"),
    ("introspect.observability", "flush", "ага", "bool"),
    ("config.reload", "observability_reset", True, "List"),
    ("config.reload", "observability_session_clear", "нет", "bool"),
    ("config.reload", "observability", "не словарь", "Dict"),
    ("telemetry.reconfigure", "publish", "включи", "Dict"),
    ("telemetry.reconfigure", "throttle", "помедленнее", "Dict"),
    ("observability.sink.tail", "limit", "много", "int"),
    ("observability.sink.enable", "sink", True, "str"),
    ("observability.tail.subscribe", "level", True, "str"),
    ("log.tail.subscribe", "subscriber", True, "str"),
]


def s4_types_are_judged_before_the_handler(drv) -> None:
    log("\n--- S4: типы параметров судятся до хендлера, без Dispatch failed ---")
    dispatch_failures: List[str] = []
    unaddressed: List[str] = []
    accepted: List[str] = []
    for command, field, bad, expected in TYPE_CASES:
        res = cmd(drv, CHILD, command, {field: bad})
        reason = str(res.get("reason") or "")
        if res.get("success"):
            accepted.append(f"{command}.{field}")
            continue
        if "Dispatch failed" in reason or "not iterable" in reason:
            dispatch_failures.append(f"{command}.{field}: {reason[:110]}")
            continue
        if field not in reason or expected not in reason:
            unaddressed.append(f"{command}.{field}: {reason[:110]}")

    check(not accepted, "ни один чужой тип не принят", f"принято: {accepted or '—'} (всего случаев {len(TYPE_CASES)})")
    check(not dispatch_failures, "ни одного Dispatch failed на поверхности", f"падений: {dispatch_failures or '—'}")
    check(
        not unaddressed,
        "каждый отказ называет поле И ожидаемый тип",
        f"безадресных: {unaddressed or '—'}",
    )


# --------------------------------------------------------------------------
# S5 / S6 — задача 2.1 и гейт этапа
# --------------------------------------------------------------------------

#: (описание, команда, параметры, кусок адреса, который обязан быть в отказе).
PLANE_CASES = [
    ("logger", "config.reload", {"observability": {"log_level": "БОЛТОВНЯ"}}, "log_level"),
    ("error", "config.reload", {"observability": {"errors": {"level": "МУСОР"}}}, "level"),
    ("stats", "config.reload", {"observability": {"stats": {"aggregation_interval": "МУСОР"}}}, "aggregation_interval"),
    (
        "telemetry (дорога config.reload)",
        "config.reload",
        {"telemetry": {"publish": {"default_interval_sec": "быстро"}}},
        "telemetry.publish.default_interval_sec",
    ),
    (
        "telemetry (дорога команды)",
        "telemetry.reconfigure",
        {"publish": {"metrics": {"fps": {"enabled": "может быть"}}}},
        "telemetry.publish.metrics.fps.enabled",
    ),
    (
        "telemetry (троттл)",
        "telemetry.reconfigure",
        {"throttle": {"processes.**.state.fps": "часто"}},
        "telemetry.throttle",
    ),
]


def s5_four_planes_refuse_with_an_address(drv) -> None:
    log("\n--- S5: мусор на четырёх плоскостях → адресный отказ, слой не тронут ---")
    keys_before = session_keys(drv, CHILD)
    log(f"         session_keys до: {keys_before}")
    for title, command, payload, address in PLANE_CASES:
        res = cmd(drv, CHILD, command, dict(payload))
        reason = str(res.get("reason") or "")
        ok = res.get("success") is False and address in reason
        check(ok, f"плоскость {title}: отказ с адресом", f"success={res.get('success')}, reason={reason[:130]}")
    keys_after = session_keys(drv, CHILD)
    check(
        keys_after == keys_before,
        "слой L3 не тронут ни одним отказом",
        f"session_keys после: {keys_after}",
    )


def s6_the_neighbour_is_not_poisoned(drv) -> None:
    log("\n--- S6: сосед не отравлен отказом телеметрии ---")
    cmd(drv, CHILD, "telemetry.reconfigure", {"publish": {"default_interval_sec": "быстро"}})
    res = cmd(drv, CHILD, "config.reload", {"observability": {"log_level": "DEBUG"}, "ttl": 60})
    check(
        bool(res.get("success")),
        "смена уровня логов ПОСЛЕ отказа телеметрии проходит",
        f"success={res.get('success')}, reason={str(res.get('reason'))[:130]}",
    )
    level = (((obs(drv, CHILD).get("effective") or {}).get("logger") or {}).get("default_level")) or "?"
    check(level == "DEBUG", "и она ДЕЙСТВУЕТ, а не только принята", f"effective.logger.default_level={level}")
    cmd(drv, CHILD, "config.reload", {"observability_session_clear": True})


def s7_valid_forms_still_work(drv) -> None:
    log("\n--- S7: приёмная сторона — валидные формы действуют ---")
    cases = [
        ("resolve строкой", "introspect.observability", {"resolve": "messages_file"}),
        ("audit_limit числом", "introspect.observability", {"audit_limit": 2}),
        ("publish словарём", "telemetry.reconfigure", {"publish": {"metrics": {"fps": {"enabled": False}}}}),
        ("throttle числом", "telemetry.reconfigure", {"throttle": {"processes.**.state.fps": 2.0}}),
        ("уровень логов", "config.reload", {"observability": {"log_level": "WARNING"}, "ttl": 60}),
    ]
    for title, command, payload in cases:
        res = cmd(drv, CHILD, command, dict(payload))
        check(bool(res.get("success")), f"принято: {title}", f"reason={str(res.get('reason'))[:110]}")
    cmd(drv, CHILD, "config.reload", {"observability_session_clear": True})


# --------------------------------------------------------------------------


def main() -> int:
    log("=" * 78)
    log("Живой гейт этапа 2 (observability-roadmap) — стенд webcam_sketch")
    log(f"каталог прогона: {LOG_DIR}")
    log("=" * 78)

    make_stand_recipe()
    harness = BackendHarness(recipe=STAND_RECIPE, warmup=10.0)
    drv = harness.start()
    try:
        names = process_names(drv)
        check(bool(names), "список процессов стенда прочитан", f"процессы ({len(names)}): {names or 'НЕ ПРОЧИТАН'}")

        s1_boot_is_silent_about_its_own_config()
        s3_the_diverging_measurement(drv)
        s4_types_are_judged_before_the_handler(drv)
        s5_four_planes_refuse_with_an_address(drv)
        s6_the_neighbour_is_not_poisoned(drv)
        s7_valid_forms_still_work(drv)
        s2_the_detector_is_alive(drv)
    finally:
        harness.stop()
        STAND_RECIPE.unlink(missing_ok=True)

    log("\n" + "=" * 78)
    if FAILURES:
        log(f"ПРОВАЛЕНО проверок: {len(FAILURES)}")
        for f in FAILURES:
            log(f"  - {f}")
        return 1
    log("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
