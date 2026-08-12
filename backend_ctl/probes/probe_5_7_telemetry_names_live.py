# -*- coding: utf-8 -*-
"""Живая приёмка 5.7 — имена внутри `telemetry` судятся как у соседних плоскостей.

Основание — блокер Н2-4 переприёмки F2 раунд 2. Дефект живьём (до правки,
переснят исполнителем на боевом стенде)::

    config.reload {"telemetry": {"publish": {"нет_такой_метрики": {"interval_sec": 5.0}}}}
    → success=true, verified=None,
      session_keys=['telemetry.publish.нет_такой_метрики.interval_sec']   # срок 254 с
      попутно gate_active False→True — эффект, которого оператор не просил

Это прямой пробел задачи 5.4: её сверщик снимает ключ `telemetry` и отдаёт его
соседу (`validate_telemetry_section`), а сосед судил только имена ПОД-СЕКЦИЙ и
значения. «Фасад — белый список»: делегирование соседу не делает ключ проверенным.

Проверки:

    T1  незнакомое ПОЛЕ `publish` → адресный отказ, в L3 не оседает;
    T2  незнакомое поле ПРАВИЛА метрики (`metrics.<имя>.enabld`) → тот же отказ;
    T3  незнакомое ИМЯ МЕТРИКИ — ЗАКОННО (конфиг сужает набор, а не объявляет
        белый список) и озвучено полем `unknown_metrics` в ответе, а не отказом.
        Это единственная проверка, которую нельзя сделать юнитом: у фальшивки нет
        heartbeat'а, а голос считает живой гейт;
    T4  телеметрийная правка несёт ВЕРДИКТ вместо тишины (`unverifiable` с
        перечнем запрошенных путей — readback плоскости не отдаётся, значит
        подтверждать нечем, и это ответ);
    T5  отвергнутая правка не оставляет следа: L3 и `gate_active` как были.

Запуск: ``python -m backend_ctl.probes.probe_5_7_telemetry_names_live``
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

TARGETS = ("camera_0", "ProcessManager")
FAILURES: List[str] = []


def log(message: str) -> None:
    print(message, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


def introspect(drv: BackendDriver, target: str) -> Dict[str, Any]:
    return _leaf_result(drv.send_command(target, "introspect.observability", {}, timeout=25.0)) or {}


def session_keys(drv: BackendDriver, target: str) -> List[str]:
    return list(((introspect(drv, target).get("layers") or {}).get("session_keys")) or [])


def gate_active(drv: BackendDriver, target: str) -> Any:
    reply = _leaf_result(drv.send_command(target, "introspect.telemetry", {}, timeout=25.0)) or {}
    return reply.get("gate_active")


def reload_telemetry(drv: BackendDriver, target: str, section: Dict[str, Any]) -> Dict[str, Any]:
    return _leaf_result(drv.send_command(target, "config.reload", {"telemetry": section}, timeout=30.0)) or {}


def judge(drv: BackendDriver, target: str) -> None:
    log(f"\n=== адресат {target} ===")
    before_keys = session_keys(drv, target)
    before_gate = gate_active(drv, target)
    log(f"  L3 до: {before_keys} · gate_active до: {before_gate}")

    t1 = reload_telemetry(drv, target, {"publish": {"нет_такой_метрики": {"interval_sec": 5.0}}})
    reason1 = str(t1.get("reason", ""))
    check(
        t1.get("success") is False and "telemetry.publish.нет_такой_метрики" in reason1,
        "T1 незнакомое поле publish отвергнуто с адресом",
        f"success={t1.get('success')}, reason={reason1[:170]}",
    )

    t2 = reload_telemetry(drv, target, {"publish": {"metrics": {"fps": {"enabld": True}}}})
    reason2 = str(t2.get("reason", ""))
    check(
        t2.get("success") is False and "metrics.fps.enabld" in reason2,
        "T2 незнакомое поле правила метрики отвергнуто с адресом",
        f"success={t2.get('success')}, reason={reason2[:170]}",
    )

    t3 = reload_telemetry(drv, target, {"publish": {"metrics": {"нет_такой_метрики": {"enabled": True}}}})
    check(
        t3.get("success") is True,
        "T3 незнакомое ИМЯ метрики принято (конфиг сужает, а не объявляет)",
        f"success={t3.get('success')}, reason={str(t3.get('reason'))[:120]}",
    )
    check(
        "нет_такой_метрики" in (t3.get("unknown_metrics") or []),
        "T3b и озвучено полем unknown_metrics, а не проглочено",
        f"unknown_metrics={t3.get('unknown_metrics')}",
    )

    t4 = reload_telemetry(drv, target, {"publish": {"default_interval_sec": 2.0}})
    verified = t4.get("verified") or {}
    check(
        verified.get("verdict") == "unverifiable",
        "T4 телеметрийная правка несёт вердикт вместо тишины",
        f"verified={verified}",
    )
    check(
        "telemetry.publish.default_interval_sec" in (verified.get("unverifiable") or []),
        "T4b и вердикт называет запрошенные пути поимённо",
        f"unverifiable={verified.get('unverifiable')}",
    )

    # Уборка: снять всё, что положили законные T3/T4, и сверить след отказов.
    drv.send_command(target, "config.reload", {"observability_session_clear": True}, timeout=30.0)
    after_keys = session_keys(drv, target)
    check(
        not [k for k in after_keys if "нет_такой" in k or "enabld" in k],
        "T5 отвергнутые правки не оставили следа в L3",
        f"L3 после уборки: {after_keys}",
    )


def main() -> int:
    host, port = resolve_endpoint()
    log("=" * 78)
    log("Живая приёмка 5.7 — имена внутри telemetry (блокер Н2-4)")
    log(f"эндпоинт: {host}:{port}")
    log("=" * 78)

    drv = BackendDriver(host=host, port=port)
    try:
        drv.connect()
    except Exception as exc:  # noqa: BLE001
        log(f"стенд недоступен ({exc}). Подними его так:")
        log("  BACKEND_CTL=1 INSPECTOR_GUI_UNATTENDED=1 INSPECTOR_LOG_DIR=logs_live/f2_5_7 \\")
        log("      .venv/Scripts/python.exe multiprocess_prototype/frontend/run.py")
        return 2

    try:
        for target in TARGETS:
            judge(drv, target)
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
