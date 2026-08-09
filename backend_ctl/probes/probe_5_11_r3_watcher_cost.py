# -*- coding: utf-8 -*-
"""Живой замер резидуала 5.11-R3 — доходит ли правка спутника до детей и чего стоит.

**Что спрашивает резидуал.** Раздача правки спутника будит пересборку слоёв у
ВСЕХ детей на каждое срабатывание watcher'а. Дебаунс есть у watchdog'а, но не у
самой рассылки. Вопрос не «плохо ли это», а **сколько это стоит**.

**Чем этот зонд отличается от первой редакции.** Первая считала строки
``правка (…) роздана детям`` в логе PM и намерила ноль при нулевой просадке FPS.
Ноль оказался ложным трижды подряд: сперва спутника не было на boot (watcher не
поднимался), потом зонд писал файл-призрак с двойным суффиксом, потом сам
детектор читал лог раньше, чем PM успевал в него написать. Молчание сломанного
детектора неотличимо от «дёшево», поэтому теперь меряется **эффект, а не
сигнал**: изменился ли ДЕЙСТВУЮЩИЙ уровень логирования у ребёнка.

Порядок проверок — от факта к цене:

    P0  спутник задаёт camera_0 уровень INFO, стенд стартует → читаем эффективный
    P1  правка спутника на DEBUG → дошло ли до ребёнка и за сколько (это и есть
        главный вопрос: раздача работает или нет)
    P2  серия правок → сколько применений реально случилось (дебаунс?)
    P3  FPS до/во время/после — цена, но ТОЛЬКО если P1 подтвердил доставку

Запуск: ``python -m backend_ctl.probes.probe_5_11_r3_watcher_cost`` (~2 мин).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["BACKEND_CTL"] = "1"

for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")

from backend_ctl.driver import _leaf_result  # noqa: E402
from backend_ctl.harness import BackendHarness  # noqa: E402
from multiprocess_framework.modules.process_module.configs.observability_companion import (  # noqa: E402
    companion_path,
    write_companion,
)

RECIPE = PROJECT_ROOT / "multiprocess_prototype" / "recipes" / "dualcam_synth.yaml"
TARGET = "camera_0"
PROCS = ["devices", "camera_0", "camera_1", "consumer_0", "consumer_1"]

PORT = 8793
FAILURES: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


def edit_companion(level: str, seq: int) -> None:
    """Правка спутника — ровно то, что делает ``observability.persist`` из пульта.

    Принимает уровень, путь выводится из РЕЦЕПТА: ``write_companion`` сам
    дописывает суффикс. Передача сюда готового пути спутника (первая редакция)
    дописывала суффикс второй раз и создавала файл-призрак рядом с рецептом.
    """
    write_companion(RECIPE, {"processes": {TARGET: {"log_level": level, "_probe_seq": seq}}})


def effective_level(drv, process: str) -> str | None:
    """Действующий уровень логирования процесса — наблюдаемый ЭФФЕКТ правки.

    Читается из readback'а самого процесса, а не из лога оркестратора: доказывать
    доставку по строке отправителя — то же самое, что верить накладной вместо
    товара.
    """
    snap = _leaf_result(drv.send_command(process, "introspect.observability", timeout=10.0))
    if not isinstance(snap, dict):
        return None
    eff = snap.get("effective")
    if not isinstance(eff, dict):
        return None
    # Ключ слоя и ключ readback'а называются ПО-РАЗНОМУ: в спутник пишется
    # `log_level`, а действующее значение отдаётся как `logger.default_level`.
    # Первая редакция искала `log_level` и получала None — то есть «не дошло»
    # и «не умею прочитать» выглядели одинаково.
    logger = eff.get("logger")
    if isinstance(logger, dict):
        for key in ("default_level", "log_level", "level", "min_level"):
            value = logger.get(key)
            if value is not None:
                return str(value)
    return None


def wait_for_level(drv, process: str, expected: str, timeout: float) -> tuple[bool, float]:
    """Дождаться, пока действующий уровень станет ожидаемым. Возвращает (дошло, секунды)."""
    t0 = time.monotonic()
    deadline = t0 + timeout
    while time.monotonic() < deadline:
        if (effective_level(drv, process) or "").upper() == expected.upper():
            return True, round(time.monotonic() - t0, 2)
        time.sleep(0.25)
    return False, round(time.monotonic() - t0, 2)


def sample_fps(drv) -> float:
    """Сумма effective_hz по всем воркерам всех процессов."""
    total = 0.0
    for name in PROCS:
        status = _leaf_result(drv.send_command(name, "introspect.status", timeout=8.0))
        workers = status.get("workers") if isinstance(status, dict) else None
        if not isinstance(workers, dict):
            continue
        for metrics in workers.values():
            hz = metrics.get("effective_hz") if isinstance(metrics, dict) else None
            if isinstance(hz, (int, float)) and hz > 0:
                total += float(hz)
    return round(total, 2)


def measure_fps(drv, seconds: float, label: str) -> float:
    samples = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        samples.append(sample_fps(drv))
        time.sleep(0.8)
    avg = round(sum(samples) / max(1, len(samples)), 2)
    log(f"  FPS [{label}]: {avg} (снимков {len(samples)})")
    return avg


def main() -> int:
    report: dict = {"recipe": RECIPE.name, "processes": len(PROCS), "target": TARGET}

    # Спутник обязан существовать ДО старта: L2-watcher поднимается на boot и
    # честно пишет «спутник отсутствует, L2-watcher не поднят», если файла нет.
    comp = companion_path(RECIPE)
    existed = comp.exists()
    backup = comp.read_text(encoding="utf-8") if existed else None
    edit_companion("INFO", 0)

    harness = BackendHarness(recipe=RECIPE, with_base=True, port=PORT, ready_timeout=60.0)
    drv = harness.start()
    log(f"\n=== стенд поднят: {RECIPE.name} + base, спутник задаёт {TARGET}=INFO ===")

    try:
        time.sleep(8.0)

        # ---------------- P0: слой спутника вообще применён? -------------------
        log("\n--- P0: спутник действует на boot ---")
        boot_level = effective_level(drv, TARGET)
        report["boot_level"] = boot_level
        check(
            (boot_level or "").upper() == "INFO",
            "уровень из спутника действует после старта",
            f"эффективный уровень {TARGET}: {boot_level}",
        )
        base_fps = measure_fps(drv, 6.0, "базовый")
        report["fps_baseline"] = base_fps

        # ---------------- P1: правка доходит до ребёнка? -----------------------
        log("\n--- P1: правка спутника INFO → DEBUG ---")
        edit_companion("DEBUG", 1)
        arrived, latency = wait_for_level(drv, TARGET, "DEBUG", timeout=25.0)
        report["single_edit"] = {"arrived": arrived, "latency_s": latency}
        check(
            arrived,
            "правка спутника дошла до ребёнка",
            f"уровень стал DEBUG за {latency}s" if arrived else f"за {latency}s уровень не изменился — раздачи нет",
        )
        report["fps_after_single"] = measure_fps(drv, 6.0, "после одной правки")

        # ---------------- P2: серия правок --------------------------------------
        if arrived:
            log("\n--- P2: серия из 8 правок по 150мс (оператор тянет ползунок) ---")
            t0 = time.monotonic()
            for i in range(8):
                edit_companion("WARNING" if i % 2 else "ERROR", 100 + i)
                time.sleep(0.15)
            write_window = round(time.monotonic() - t0, 2)
            fps_during = measure_fps(drv, 5.0, "во время серии")
            # Последняя правка — WARNING (i=7 нечётное), её и ждём.
            settled, settle_s = wait_for_level(drv, TARGET, "WARNING", timeout=25.0)
            report["burst"] = {
                "edits": 8,
                "write_window_s": write_window,
                "final_level_applied": settled,
                "settle_s": settle_s,
            }
            check(
                settled,
                "после серии действует ПОСЛЕДНЯЯ правка",
                f"уровень WARNING установился за {settle_s}s" if settled else f"за {settle_s}s не установился",
            )
            report["fps_during_burst"] = fps_during
            report["fps_after_burst"] = measure_fps(drv, 6.0, "после серии")
            if base_fps:
                report["drop_during_burst_pct"] = round(100.0 * (1 - fps_during / base_fps), 1)
                report["drop_after_burst_pct"] = round(100.0 * (1 - report["fps_after_burst"] / base_fps), 1)
        else:
            log("\n--- P2 пропущен: раздача не подтверждена, мерить цену нечего ---")
            report["burst"] = {"skipped": "доставка не подтверждена в P1"}

    finally:
        try:
            if backup is not None:
                comp.write_text(backup, encoding="utf-8")
            elif comp.exists():
                comp.unlink()
        except OSError as exc:
            log(f"ВНИМАНИЕ: спутник не восстановлен: {exc}")
        harness.stop()

    log("\n" + "=" * 70)
    log(json.dumps(report, ensure_ascii=False, indent=2))
    if FAILURES:
        log(f"\nИТОГ: {len(FAILURES)} провал(ов)")
        for f in FAILURES:
            log(f"  - {f}")
        return 1
    log("\nИТОГ: все проверки зелёные")
    return 0


if __name__ == "__main__":
    sys.exit(main())
