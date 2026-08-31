# -*- coding: utf-8 -*-
"""Живая приёмка 3.1 — под-секция без получателя отвергается, а не занимает слот.

Дефект живьём (снят на стенде 2026-08-14, ДО правки, процесс ``camera_0``)::

    telemetry.reconfigure {"throttle": {"processes.**.state.fps": 2}}
    → success=true, applied={'throttle': false}, ttl_sec=300.0, survives_reload=true

Три обещания в одном ответе, и все три ложные: команда «прошла», слот L3 занят на
пять минут, и правка якобы «переживёт reload» — правка, которая не действовала ни
секунды. Центральный store-троттл живёт только на оркестраторе; на ребёнке
применять его некому. Оператор читает ``success``.

Контрольная пара — обязательна: тот же вход на ``ProcessManager`` обязан
ПРИМЕНИТЬСЯ. Без второй половины зонд доказал бы лишь, что команда сломана
везде, а не что она стала честной.

**Зачем живьём при 60 зелёных.** Тесты судят механику границы на харнессе. Здесь
судится ПРОВОДКА: команда идёт боевой дорогой ``сокет → ПМ → роутер → процесс``,
через receive-мидлварь получателя, а не мимо неё. И судится ЧИСЛАМИ состояние
слоя после отказа — ``session_keys`` живого процесса, а не мнение фикстуры.

**Стенд зондом не поднимается** (решение владельца 2026-08-11 — у GUI-стенда одна
дорога подъёма, боевая)::

    BACKEND_CTL=1 INSPECTOR_GUI_UNATTENDED=1 INSPECTOR_LOG_DIR=logs_live/stage6_3_1 \\
        .venv/Scripts/python.exe multiprocess_prototype/frontend/run.py

Проверки — одиннадцать, перечислены ВСЕ (не сокращать до «P1…P6»: пропущенная в
списке ``P4b`` оказалась ровно той, что первой редакцией была написана вакуумной,
и её никто не искал, потому что в оглавлении её не было):

    P1   ребёнок, дверь ``telemetry.reconfigure`` → отказ;
    P1b  и reason называет АДРЕС (куда слать), а не только «здесь нельзя»;
    P2   ребёнок, дверь ``config.reload`` с той же секцией → тот же отказ. Дефект,
         починенный на одной двери из двух, воскресает на второй;
    P3   слот L3 не занят: ``telemetry.throttle`` нет в ``session_keys`` после
         ОБОИХ отказов;
    P3b  и состав слоя не изменился ни на ключ;
    P4   оркестратор: тот же вход → ``success=true``, ``applied.throttle=true``;
    P4b  и правило ДЕЙСТВУЕТ — в readback лежит присланное ЗНАЧЕНИЕ, а не просто
         присутствует ключ (ключ там есть и без всякой правки: он загрузочный);
    P5   сосед не отравлен: после двух отказов законная правка ``publish`` на том
         же ребёнке принята;
    P5b  и держится сессией;
    P6a  уборка: получатель откатился к загрузочному правилу;
    P6   и ключи прогона сняты из L3 — стенд как был.

Запуск: ``python -m backend_ctl.probes.probe_3_1_no_receiver_live``
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

from backend_ctl.driver import BackendDriver, _leaf_result  # noqa: E402
from backend_ctl.endpoint_config import resolve_endpoint  # noqa: E402

#: Ребёнок без получателя и оркестратор, у которого получатель есть. Пара, а не
#: один адресат: отказ, пришедший ОТОВСЮДУ, — это сломанная команда, а не
#: починенная.
CHILD = "camera_0"
ORCHESTRATOR = "ProcessManager"

#: Паттерн намеренно содержит точки: у троттла они часть ИМЕНИ правила, а не
#: разделитель пути слоя, и лист кладётся непрозрачным целиком.
THROTTLE_PATTERN = "processes.**.state.fps"
#: Значение обязано РАСХОДИТЬСЯ с загрузочным (0.05 у всех правил этой семьи):
#: совпади они — и P4b мерил бы дефолт, а не применение.
THROTTLE_VALUE = 2
THROTTLE_DELTA: Dict[str, Any] = {THROTTLE_PATTERN: THROTTLE_VALUE}

FAILURES: List[str] = []


def log(message: str) -> None:
    print(message, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


def session_keys(drv: BackendDriver, target: str) -> List[str]:
    res = _leaf_result(drv.send_command(target, "introspect.observability", {}, timeout=25.0)) or {}
    return sorted(((res.get("layers") or {}).get("session_keys")) or [])


def throttle_rules(drv: BackendDriver, target: str) -> Any:
    """Правила центрального троттла из readback — доказательство ДЕЙСТВИЯ, не ответа.

    Ключ ответа — плоский ``throttle_rules``, а не вложенный ``throttle.rules``:
    первая редакция зонда читала второй, получала ``None`` и обвиняла систему в
    том, чего та не делала. Промах зонда неотличим от дефекта, пока не посмотришь
    в ответ целиком, — поэтому путь читается из ОДНОГО места и здесь назван.
    """
    res = _leaf_result(drv.send_command(target, "introspect.telemetry", {}, timeout=25.0)) or {}
    return res.get("throttle_rules")


def judge_child(drv: BackendDriver) -> None:
    log(f"\n=== ребёнок {CHILD} (получателя троттла нет) ===")
    before = session_keys(drv, CHILD)
    log(f"  session_keys до прогона: {before}")

    res1 = (
        _leaf_result(drv.send_command(CHILD, "telemetry.reconfigure", {"throttle": THROTTLE_DELTA}, timeout=30.0)) or {}
    )
    reason1 = str(res1.get("reason", ""))
    check(
        res1.get("success") is False,
        "P1 дверь telemetry.reconfigure отказала",
        f"success={res1.get('success')}, applied={res1.get('applied')}, ttl_sec={res1.get('ttl_sec')}",
    )
    # Два признака в одном ассерте намеренно: «отказ» без адреса сообщает о
    # проблеме, но не о выходе, а адрес при success=true — это прежний дефект с
    # вежливым текстом.
    check(
        "throttle" in reason1 and ORCHESTRATOR in reason1,
        "P1b отказ называет адрес получателя",
        f"reason={reason1[:200]}",
    )

    res2 = (
        _leaf_result(
            drv.send_command(CHILD, "config.reload", {"telemetry": {"throttle": THROTTLE_DELTA}}, timeout=30.0)
        )
        or {}
    )
    reason2 = str(res2.get("reason", ""))
    check(
        res2.get("success") is False and ORCHESTRATOR in reason2,
        "P2 вторая дверь (config.reload) отказала так же",
        f"success={res2.get('success')}, reason={reason2[:200]}",
    )

    after = session_keys(drv, CHILD)
    check(
        not [k for k in after if k.startswith("telemetry.throttle")],
        "P3 слот L3 не занят: telemetry.throttle отсутствует",
        f"session_keys={after}",
    )
    check(
        after == before,
        "P3b состав L3 не изменился двумя отказами",
        f"до={before}, после={after}",
    )


def judge_orchestrator(drv: BackendDriver) -> Any:
    """Возвращает загрузочное значение правила ДО правки — базу для уборки (P6)."""
    log(f"\n=== оркестратор {ORCHESTRATOR} (получатель есть) ===")
    boot_value = (throttle_rules(drv, ORCHESTRATOR) or {}).get(THROTTLE_PATTERN)
    log(f"  загрузочное {THROTTLE_PATTERN} = {boot_value}")
    res = (
        _leaf_result(
            drv.send_command(
                ORCHESTRATOR,
                "telemetry.reconfigure",
                {"throttle": THROTTLE_DELTA, "telemetry_mode": "merge"},
                timeout=30.0,
            )
        )
        or {}
    )
    check(
        res.get("success") is True and (res.get("applied") or {}).get("throttle") is True,
        "P4 та же секция на оркестраторе ПРИМЕНЕНА",
        f"success={res.get('success')}, applied={res.get('applied')}",
    )
    rules = throttle_rules(drv, ORCHESTRATOR)
    # Судится ЗНАЧЕНИЕ, а не наличие ключа. Первая редакция проверяла
    # `"processes.**.state.fps" in rules` — и была зелена при нулевом применении:
    # этот паттерн есть в ЗАГРУЗОЧНЫХ правилах всегда, то есть ассерт мерил
    # дефолт, а заголовок обещал «действует». Дельта (2) и загрузочное (0.05)
    # расходятся, поэтому различение настоящее.
    check(
        isinstance(rules, dict) and rules.get(THROTTLE_PATTERN) == THROTTLE_VALUE,
        "P4b правило ДЕЙСТВУЕТ: значение в readback = присланное",
        f"{THROTTLE_PATTERN}={(rules or {}).get(THROTTLE_PATTERN)!r} "
        f"(прислано {THROTTLE_VALUE!r}, загрузочное было {boot_value!r})",
    )
    return boot_value


def judge_neighbour(drv: BackendDriver) -> None:
    log(f"\n=== сосед на {CHILD} (класс «отказ отравил следующую правку») ===")
    res = (
        _leaf_result(
            drv.send_command(
                CHILD,
                "telemetry.reconfigure",
                {"publish": {"metrics": {"fps": {"enabled": True, "interval_sec": 1}}}},
                timeout=30.0,
            )
        )
        or {}
    )
    check(
        res.get("success") is True and (res.get("applied") or {}).get("publish") is True,
        "P5 законная правка после двух отказов принята",
        f"success={res.get('success')}, applied={res.get('applied')}",
    )
    keys = session_keys(drv, CHILD)
    check(
        any(k.startswith("telemetry.publish") for k in keys),
        "P5b и она держится сессией",
        f"session_keys={keys}",
    )


def cleanup(drv: BackendDriver, boot_value: Any) -> None:
    log("\n=== уборка ===")
    # Сброс ключа, а не присвоение прежнего значения: присвоение порвало бы связь
    # с нижним слоем навсегда (см. докстринг `observability_reset`).
    for target, key in ((CHILD, "telemetry.publish"), (ORCHESTRATOR, "telemetry.throttle")):
        drv.send_command(target, "config.reload", {"observability_reset": [key]}, timeout=30.0)
    # Пустой L3 — не то же самое, что вернувшийся получатель: сброс ключа обязан
    # ещё и ОТКАТИТЬ правило к загрузочному. Судить только `session_keys` значило
    # бы сторожить учётную книгу вместо состояния — и правка семантики
    # `observability_reset` прошла бы мимо зонда зелёной.
    back = (throttle_rules(drv, ORCHESTRATOR) or {}).get(THROTTLE_PATTERN)
    check(
        back == boot_value,
        "P6a получатель откатился к загрузочному правилу",
        f"{THROTTLE_PATTERN}={back!r}, было до прогона {boot_value!r}",
    )
    left_child = [k for k in session_keys(drv, CHILD) if k.startswith("telemetry.")]
    left_pm = [k for k in session_keys(drv, ORCHESTRATOR) if k.startswith("telemetry.")]
    check(
        not left_child and not left_pm,
        "P6 ключи прогона сняты, стенд остался как был",
        f"{CHILD}={left_child}, {ORCHESTRATOR}={left_pm}",
    )


def main() -> int:
    host, port = resolve_endpoint()
    log("=" * 78)
    log("Живая приёмка 3.1 — «нет получателя» отвечает отказом с адресом")
    log(f"эндпоинт: {host}:{port}")
    log("=" * 78)

    drv = BackendDriver(host=host, port=port)
    try:
        drv.connect()
    except Exception as exc:  # noqa: BLE001 — отсутствие стенда объясняем командой запуска
        log(f"стенд недоступен ({exc}). Подними его так:")
        log("  BACKEND_CTL=1 INSPECTOR_GUI_UNATTENDED=1 INSPECTOR_LOG_DIR=logs_live/stage6_3_1 \\")
        log("      .venv/Scripts/python.exe multiprocess_prototype/frontend/run.py")
        return 2

    try:
        judge_child(drv)
        boot_value = judge_orchestrator(drv)
        judge_neighbour(drv)
        cleanup(drv, boot_value)
    finally:
        close = getattr(drv, "close", None)
        if callable(close):
            close()

    log("\n" + "=" * 78)
    if FAILURES:
        log(f"ПРОВАЛЕНО проверок: {len(FAILURES)}")
        for item in FAILURES:
            log(f"  - {item}")
        return 1
    log("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
