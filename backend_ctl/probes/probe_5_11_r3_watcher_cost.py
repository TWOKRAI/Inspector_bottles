# -*- coding: utf-8 -*-
"""Живой замер резидуала 5.11-R3 — цена раздачи из watcher'а всем детям.

**Что спрашивает резидуал.** Раздача правки спутника будит пересборку слоёв у
ВСЕХ детей на каждое срабатывание watcher'а. Дебаунс есть у watchdog'а, но не у
самой рассылки. Вопрос не «плохо ли это», а **сколько это стоит** — и ответ
обязан быть числом, иначе дебаунс рассылки заводится по ощущению.

Замеряется три вещи:

1. **Сколько раздач реально уходит** на серию быстрых правок файла. Если дебаунс
   watchdog'а их схлопывает, у рассылки своего дебаунса может и не быть — и тогда
   резидуал закрывается числом, а не кодом.
2. **Цена одной раздачи** — просадка FPS конвейера в окне вокруг неё.
3. **Цена серии** — та же просадка на пачке правок подряд (оператор тянет
   ползунок, каждое движение пишет спутник).

Признак раздачи — строка PM `[observability] правка (…) роздана детям: reached=N`
в его логе. Считаем ПО ЛОГУ, а не по ответу команды: раздача идёт из потока
watchdog'а и никому не отвечает.

Запуск: ``python -m backend_ctl.probes.probe_5_11_r3_watcher_cost`` (~2 мин).
Числа печатаются json — в план вручную (живой документ).
"""

from __future__ import annotations

import json
import os
import re
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
PROCS = ["devices", "camera_0", "camera_1", "consumer_0", "consumer_1"]
PM_LOG = PROJECT_ROOT / "logs" / "ProcessManager" / "system.log"

PORT = 8793
FANOUT_RE = re.compile(r"правка \(([^)]*)\) роздана детям: reached=(\d+)")


def log(msg: str) -> None:
    print(msg, flush=True)


def _pm_tail(chars: int = 4000) -> str:
    """Хвост лога PM — чтобы отличить «раздач не было» от «наблюдателя не было»."""
    if not PM_LOG.exists():
        return ""
    return PM_LOG.read_text(encoding="utf-8", errors="replace")[-chars:]


def fanout_count() -> int:
    """Сколько раздач зафиксировано в логе PM на данный момент."""
    if not PM_LOG.exists():
        return 0
    text = PM_LOG.read_text(encoding="utf-8", errors="replace")
    return len(FANOUT_RE.findall(text))


def sample_fps(drv) -> dict:
    """Мгновенный снимок effective_hz всех воркеров всех процессов."""
    out: dict[str, float] = {}
    for name in PROCS:
        status = _leaf_result(drv.send_command(name, "introspect.status", timeout=8.0))
        workers = status.get("workers") if isinstance(status, dict) else None
        if not isinstance(workers, dict):
            continue
        for wname, metrics in workers.items():
            if not isinstance(metrics, dict):
                continue
            hz = metrics.get("effective_hz")
            if isinstance(hz, (int, float)) and hz > 0:
                out[f"{name}.{wname}"] = float(hz)
    return out


def measure_fps(drv, seconds: float, label: str) -> dict:
    """Среднее по нескольким снимкам — одна точка ничего не значит на живом конвейере."""
    samples: list[dict] = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        samples.append(sample_fps(drv))
        time.sleep(0.8)
    keys = sorted({k for s in samples for k in s})
    avg = {k: round(sum(s.get(k, 0.0) for s in samples) / max(1, len([s for s in samples if k in s])), 2) for k in keys}
    total = round(sum(avg.values()), 2)
    log(f"  FPS [{label}]: сумма={total} по {len(keys)} воркерам, снимков={len(samples)}")
    return {"per_worker": avg, "total": total, "samples": len(samples)}


def edit_companion(recipe: Path, level: str, seq: int) -> None:
    """Правка спутника — ровно то, что делает `observability.persist` из пульта.

    Принимает путь РЕЦЕПТА: ``write_companion`` сам выводит из него имя спутника.
    Передача сюда уже готового пути спутника (первая редакция зонда) дописывала
    суффикс второй раз и создавала файл-призрак ``…observability.observability.yaml``
    рядом с рецептом — watcher его, разумеется, не ждал.
    """
    write_companion(recipe, {"processes": {"camera_0": {"log_level": level, "_probe_seq": seq}}})


def main() -> int:
    report: dict = {"recipe": RECIPE.name, "processes": len(PROCS)}

    # Спутник обязан существовать ДО старта: L2-watcher поднимается на boot и
    # честно пишет «спутник отсутствует, L2-watcher не поднят», если файла нет.
    # Первый прогон зонда создавал файл ПОСЛЕ старта и намерил ноль раздач при
    # нулевой просадке FPS — ровно тот случай, когда молчание сломанного
    # детектора неотличимо от «дёшево». Наблюдатель, вооружённый позже (после
    # первого `observability.persist`), — отдельный путь; здесь мерится штатный.
    comp = companion_path(RECIPE)
    existed = comp.exists()
    backup = comp.read_text(encoding="utf-8") if existed else None
    edit_companion(RECIPE, "INFO", 0)

    harness = BackendHarness(recipe=RECIPE, with_base=True, port=PORT, ready_timeout=60.0)
    drv = harness.start()
    log(f"\n=== стенд поднят: {RECIPE.name} + base, процессов {len(PROCS)} ===")

    # Ждём, пока PM допишет boot-строки: первая редакция читала лог сразу и
    # объявляла watcher поднятым, когда строки «не поднят» там ещё просто не было.
    time.sleep(2.0)
    watcher_up = "L2-watcher не поднят" not in _pm_tail()
    report["watcher_up"] = watcher_up
    log(f"  L2-watcher поднят: {watcher_up}")
    if not watcher_up:
        log("  ВНИМАНИЕ: наблюдателя нет — числа ниже НЕ означают «дёшево»")

    try:
        log("\n--- P0: прогрев и базовый FPS ---")
        time.sleep(8.0)
        report["fps_baseline"] = measure_fps(drv, 6.0, "базовый")

        # ---------------- P1: ОДНА правка ------------------------------------
        log("\n--- P1: одна правка спутника ---")
        before = fanout_count()
        t0 = time.monotonic()
        edit_companion(RECIPE, "DEBUG", 1)
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline and fanout_count() == before:
            time.sleep(0.1)
        latency = round(time.monotonic() - t0, 2)
        single = fanout_count() - before
        log(f"  раздач на одну правку: {single}, задержка от записи файла: {latency}s")
        report["single_edit"] = {"fanouts": single, "latency_s": latency}
        report["fps_after_single"] = measure_fps(drv, 6.0, "после одной правки")

        # ---------------- P2: серия правок ------------------------------------
        log("\n--- P2: серия из 10 правок по 150мс (оператор тянет ползунок) ---")
        before = fanout_count()
        burst_start = time.monotonic()
        for i in range(10):
            edit_companion(RECIPE, "DEBUG" if i % 2 else "INFO", 100 + i)
            time.sleep(0.15)
        burst_write_s = round(time.monotonic() - burst_start, 2)
        fps_during = measure_fps(drv, 5.0, "во время серии")
        time.sleep(8.0)  # дать watchdog'у осесть
        burst = fanout_count() - before
        log(f"  правок записано: 10 за {burst_write_s}s → раздач: {burst}")
        report["burst"] = {
            "edits": 10,
            "write_window_s": burst_write_s,
            "fanouts": burst,
            "collapsed": burst < 10,
        }
        report["fps_during_burst"] = fps_during
        report["fps_after_burst"] = measure_fps(drv, 6.0, "после серии")

        # ---------------- Вывод ------------------------------------------------
        base = report["fps_baseline"]["total"] or 1.0
        report["drop_during_burst_pct"] = round(100.0 * (1 - fps_during["total"] / base), 1)
        report["drop_after_burst_pct"] = round(100.0 * (1 - report["fps_after_burst"]["total"] / base), 1)

    finally:
        # Вернуть спутник в исходное состояние: зонд не имеет права оставить
        # рабочий рецепт с машинными правками.
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
