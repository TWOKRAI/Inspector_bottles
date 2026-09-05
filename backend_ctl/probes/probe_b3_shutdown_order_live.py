# -*- coding: utf-8 -*-
"""Живая приёмка B3 — записи уборки доезжают, обе младшие плоскости гасятся.

Зачем живьём. Свойство B3 наблюдаемо ТОЛЬКО в файлах после останова: тесты
судят порядок вызовов на дублях, а «запись доехала» — это байты в журнале
процесса, которого уже нет. Живой контрпример до правки (прогон B2, тот же
стенд, `logs/prototype_2/camera_0/messages.log` — INFO; см. Task 3.2, Р-7(а))::

    #193 ... [INFO] camera_0: All workers stopped
    #195 ... [INFO] logger_manager: LoggerManager shutting down
    (grep "shut down successfully" → 0)

То есть последняя запись процесса — про смерть логгера, а всё, что уборка
говорит после, теряется.

Измеряется **ДЕЛЬТА файла**, а не его размер: журнал стенда накапливается
прогонами, и «в файле есть строка» ничего не доказывает — она могла лежать там
с прошлого раза. Запоминаем смещения перед остановом и читаем только хвост,
дописанный в окне останова.

Проверки:

    S1  В хвосте останова есть «shut down successfully» — INFO уборки доехала
        (до правки её не было ни у одного процесса).
    S2  В хвосте НАЗВАНЫ погашенные плоскости («observability planes stopped:
        error, stats»): до правки `error_manager.shutdown` / `stats_manager.
        shutdown` не звались нигде. Строка нужна именно в журнале процесса —
        собственная запись плоскости ошибок идёт по ЕЁ маршруту, а INFO по нему
        не ездит (пороги severity), и «погасили» выглядело бы как «не погасили».
    S3  Логгер гасится ПОСЛЕДНИМ: его «shutting down» стоит в хвосте позже
        строк S1/S2.
    S4  Финальный flush статистики виден числом: снапшот метрик в хвосте
        `performance.log`.
    S5  Длительность останова — числом, для решения по долгу graceful-stop.

Молчавшие приёмники (`idle_sinks`) здесь НЕ проверяются: их детектор пишет
**аварийным выходом** (stdlib → консоль), а не через менеджер, и в журнале
процесса его нет по построению. Вывод виден в этом же файле прогона — консоль
стенда наследуется пробой.

Запуск: ``python -m backend_ctl.probes.probe_b3_shutdown_order_live``
Стенд одиночный — порт 8765 не терпит двух. Прогон ~1 минута.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["BACKEND_CTL"] = "1"

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

from backend_ctl.harness import BackendHarness  # noqa: E402

RECIPE = PROJECT_ROOT / "multiprocess_prototype" / "recipes" / "webcam_sketch.yaml"
LOG_DIR = PROJECT_ROOT / "logs" / "prototype_2"
#: Процессы стенда, у которых есть собственный каталог журналов.
WATCHED = ["camera_0", "seg", "points", "lines", "pult", "devices"]

FAILURES: list = []


def log(msg: str) -> None:
    print(msg, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


def offsets(files: List[Path]) -> Dict[Path, int]:
    return {path: (path.stat().st_size if path.exists() else 0) for path in files}


def tail_since(path: Path, offset: int) -> str:
    if not path.exists():
        return ""
    with open(path, "rb") as fh:
        fh.seek(min(offset, path.stat().st_size))
        return fh.read().decode("utf-8", errors="replace")


def main() -> int:
    log("=" * 78)
    log("Живая приёмка B3 — стенд webcam_sketch, порядок останова")
    log("=" * 78)

    if not LOG_DIR.exists():
        log(f"каталог журналов не найден: {LOG_DIR}")
        return 1

    # Task 3.2 (Р-7(а)): строки останова S1/S2 эмитятся через `_log_info`
    # (`process_lifecycle.py:216,223`), то есть уровень INFO -> скоуп BUSINESS ->
    # `messages.log`. До 3.2 BUSINESS писал ещё и в `system_file`, и проба читала
    # его. Имя переменной оставлено: смысл — «файл плоскости логов», а не
    # «файл с именем system».
    system_logs = [LOG_DIR / name / "messages.log" for name in WATCHED]
    perf_logs = [LOG_DIR / name / "performance.log" for name in WATCHED]

    harness = BackendHarness(recipe=RECIPE, warmup=8.0)
    harness.start()
    time.sleep(5.0)

    before_system = offsets(system_logs)
    before_perf = offsets(perf_logs)
    started = time.monotonic()
    harness.stop()
    stop_seconds = time.monotonic() - started
    time.sleep(1.5)  # дать ОС дописать хвосты

    tails = {path: tail_since(path, before_system[path]) for path in system_logs}
    perf_tails = {path: tail_since(path, before_perf[path]) for path in perf_logs}
    alive = {path: text for path, text in tails.items() if text.strip()}

    log(f"\nхвостов останова прочитано: {len(alive)} из {len(system_logs)}")
    check(
        len(alive) >= 2,
        "процессы дописали в журнал в окне останова",
        f"файлов с непустым хвостом: {sorted(p.parent.name for p in alive)}",
    )

    log("\n--- S1: INFO уборки доехала ---")
    with_final = {p.parent.name: t.count("shut down successfully") for p, t in alive.items()}
    check(
        any(count > 0 for count in with_final.values()),
        "«shut down successfully» есть в хвосте останова",
        f"по процессам: {with_final}",
    )

    log("\n--- S2: названы погашенные плоскости ---")
    named = {
        p.parent.name: t.split("observability planes stopped:")[1].splitlines()[0].strip()
        for p, t in alive.items()
        if "observability planes stopped:" in t
    }
    check(
        bool(named) and all("error" in v and "stats" in v for v in named.values()),
        "обе младшие плоскости названы погашенными",
        f"по процессам: {named}",
    )

    log("\n--- S3: логгер гасится последним ---")
    verdicts = {}
    for path, text in alive.items():
        logger_at = text.find("logger_manager: logger_manager shutting down")
        if logger_at < 0:
            logger_at = text.rfind("shutting down")
        final_at = text.find("shut down successfully")
        planes_at = text.find("observability planes stopped:")
        if logger_at < 0 or final_at < 0:
            continue
        verdicts[path.parent.name] = (final_at < logger_at) and (planes_at < 0 or planes_at < logger_at)
    check(
        bool(verdicts) and all(verdicts.values()),
        "итоговая запись и гашение stats стоят РАНЬШЕ смерти логгера",
        f"по процессам: {verdicts}",
    )

    log("\n--- S4: финальный flush статистики виден числом ---")
    snapshots = {p.parent.name: t.count("metrics snapshot") for p, t in perf_tails.items() if t.strip()}
    check(
        any(count > 0 for count in snapshots.values()),
        "снапшот метрик записан в окне останова",
        f"снапшотов в хвосте performance.log: {snapshots}",
    )

    log("\n--- S5: длительность останова ---")
    log(f"         останов занял {stop_seconds:.1f} с (долг graceful-stop — 5-секундный ханг ПМ)")

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
