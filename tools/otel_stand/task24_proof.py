# -*- coding: utf-8 -*-
"""Проба Task 2.4 — останов укладывается в бюджет 5 с, и исход назван числами.

**Предмет.** Task 2.2 отменила дожатие на останове, потому что держать дедлайн было
нечем: `export_timeout_ms` — это дедлайн расписания ретраев SDK, а не потолок вызова
(замер CTO: при «потолке» 3000 мс вызов жил 4.08 с, на чёрной дыре при 30 с — 42.08 с).
Task 2.4 вернула дожатие ОГРАНИЧЕННЫМ: дедлайн держит `BatchDrainWorker.flush(timeout)`,
честный против зависшего стока по построению.

**Мерить чёрной дырой, а не закрытым портом** — условие вердикта CTO 2026-09-07.
Отказ в соединении (`refused`) приходит мгновенно и ничего не проверяет; `10.255.255.1`
держит `connect` до таймаута, то есть воспроизводит именно «сток, который ЖДЁТ».

**Четыре утверждения и пара к каждому.**

1. *Останов на чёрной дыре укладывается в бюджет.* Пара — контрольный прогон с ЖИВЫМ
   приёмником: без него «уложился» неотличимо от «отправлять было нечего».
2. *Процесс остановился САМ*: в журнале нет строки фреймворка о принудительном
   завершении `otel_export` по истечении 5 с.
3. *Исход останова назван ЧИСЛАМИ* — строка `otel flush: N дожато, M потеряно`.
4. *Приём не встал за висящей отправкой*: `received` продолжает расти, пока сток висит.

**Отказ ИЗМЕРЕНИЯ отделён от отказа ПРЕДМЕТА** (правило, выведенное из семи ложных
опровержений на этом треке): недобор фактов даёт «НЕ ДОКАЗАНО», а не «ОПРОВЕРГНУТО».

**Запуск (стенд 8765 эксклюзивен — занять, объявить, освободить):**

    "$PWD/../../../.venv/Scripts/python.exe" tools/otel_stand/task24_proof.py

Выход: 0 — доказано всё; 1 — есть опровергнутое; 2 — отказало измерение.
"""

from __future__ import annotations

import http.server
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

PROCESS = "otel_export"
BASE_TOPOLOGY = Path("multiprocess_prototype/backend/topology/otel_export.yaml")
#: Временный фрагмент кладётся РЯДОМ с исходным: путь топологии резолвится
#: относительно дерева, и абсолютный путь из временного каталога сюда не годится.
TEMP_TOPOLOGY = BASE_TOPOLOGY.with_name("otel_export_stand_t24.yaml")

#: Адрес, который держит `connect` вместо мгновенного отказа. Именно он требуется
#: вердиктом CTO: `refused` на localhost отвечает за миллисекунды и дедлайн не проверяет.
BLACK_HOLE = "http://10.255.255.1:4318/v1/logs"
LIVE_ENDPOINT = "http://127.0.0.1:4318/v1/logs"
COLLECTOR_PORT = 4318

#: Бюджет останова фреймворка (`process_registry.stop_all`, `spawner.stop_timeout`).
#: Литерал, а не чтение конфига: проба сверяет РЕАЛЬНОСТЬ с обещанием, и обещание
#: обязано быть написано здесь, иначе она согласится с любым значением.
FRAMEWORK_STOP_BUDGET_SEC = 5.0
#: Запас на останов ОСТАЛЬНОЙ системы: измеряется `launcher.shutdown()` целиком,
#: а в нём после плагина ещё снятие намерений, гашение логгера и join процессов.
WHOLE_SHUTDOWN_SLACK_SEC = 6.0

_SETTLE_SEC = 12.0

#: Литералы, по которым читается исход. Меняются вместе с кодом — на то они и здесь.
FLUSH_LINE = "otel flush:"
STOPPED_LINE = f"{PROCESS}: остановлен"
FORCED_STOP_MARK = "did not stop in"


class _AcceptingCollector(http.server.BaseHTTPRequestHandler):
    """Живой приёмник для контрольного прогона: принимает и отвечает 200."""

    def do_POST(self) -> None:  # noqa: N802 — имя навязано BaseHTTPRequestHandler
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_args: Any) -> None:
        """Молчит: его шум мешал бы читать наш журнал."""


def _start_collector() -> http.server.HTTPServer:
    server = http.server.HTTPServer(("127.0.0.1", COLLECTOR_PORT), _AcceptingCollector)
    threading.Thread(target=server.serve_forever, daemon=True, name="stand-collector").start()
    return server


def _write_topology(endpoint: str) -> None:
    text = BASE_TOPOLOGY.read_text(encoding="utf-8")
    patched, count = re.subn(r"endpoint: \S+", f"endpoint: {endpoint}", text, count=1)
    if count != 1:
        raise RuntimeError(f"в {BASE_TOPOLOGY} не нашлось ровно одного ключа endpoint (нашлось {count})")
    TEMP_TOPOLOGY.write_text(patched, encoding="utf-8")


def _lines(log_dir: Path, needle: str) -> list[str]:
    out: list[str] = []
    for path in sorted(log_dir.rglob("*.log")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out.extend(line for line in text.splitlines() if needle in line)
    return out


def _await_lines(log_dir: Path, needle: str, deadline_sec: float = 10.0) -> list[str]:
    """Дождаться строки: журнал пишется ПОЗЖЕ возврата вызова, между ними конвейер."""
    deadline = time.monotonic() + deadline_sec
    found = _lines(log_dir, needle)
    while not found and time.monotonic() < deadline:
        time.sleep(0.3)
        found = _lines(log_dir, needle)
    return found


def _received(drv: Any) -> int:
    raw = drv.send_command(PROCESS, "otel_export.status") or {}
    payload = raw.get("result", raw.get("data", raw))
    counters = (payload if isinstance(payload, dict) else {}).get("counters", {}) or {}
    return int(counters.get("received", 0) or 0)


def _last_number(lines: list[str], pattern: str) -> int:
    """Число по образцу из ПОСЛЕДНЕЙ строки, где оно нашлось. -1 — не нашлось нигде."""
    for line in reversed(lines):
        match = re.search(pattern, line)
        if match:
            return int(match.group(1))
    return -1


def _verdict(name: str, ok: bool | None, detail: str) -> tuple[str, bool | None]:
    label = {True: "ДОКАЗАНО   ", False: "ОПРОВЕРГНУТО", None: "НЕ ДОКАЗАНО"}[ok]
    print(f"[{label}] {name}\n              {detail}")
    return name, ok


def _mark(log_dir: Path) -> dict[str, set[str]]:
    """Засечка: какие строки уже лежат в журнале ДО фазы.

    **Почему множество, а не счётчик, и почему не второй каталог — два урока подряд.**

    Первая редакция переключала `INSPECTOR_LOG_DIR` между фазами внутри одного
    процесса: не сработало, обе фазы писали в каталог первой, проба читала пустой
    второй и выдала ОПРОВЕРГНУТО на исправном механизме.

    Вторая редакция резала строки по КОЛИЧЕСТВУ, снятому до фазы. Тоже не сработало:
    строки разных прогонов ложатся в РАЗНЫЕ файлы каталога, `rglob` отдаёт их в
    порядке имён, и вторая фаза сдвинула индексы — обе фазы отчитались одними и теми
    же числами (`потеряно 21` дважды), хотя в журнале лежали разные: 21 у чёрной
    дыры и 0 у живого приёмника.

    Общая форма обеих ошибок одна и та же и повторяет весь этот трек: **утверждение
    выведено из догадки о форме данных, а не измерено рядом.** Множество строк от
    порядка файлов не зависит вовсе — строки несут номер и время, то есть уникальны.
    """
    return {needle: set(_lines(log_dir, needle)) for needle in (FLUSH_LINE, STOPPED_LINE, FORCED_STOP_MARK)}


def _run_phase(endpoint: str, log_dir: Path, *, measure_reception: bool) -> dict[str, Any]:
    """Поднять систему на заданном адресе, померить останов, вернуть факты."""
    from backend_ctl.driver import BackendDriver

    from multiprocess_prototype.main import bootstrap

    _write_topology(endpoint)
    mark = _mark(log_dir)
    print(f"[proof] поднимаю топологию, endpoint={endpoint}")
    launcher = bootstrap(str(TEMP_TOPOLOGY).replace("\\", "/"))
    launcher.start()
    if not launcher.wait_until_ready(timeout=45.0):
        launcher.shutdown()
        return {"measurement_failed": "система не готова за 45 с"}

    facts: dict[str, Any] = {}
    try:
        print(f"[proof] даю хвосту натечь {_SETTLE_SEC} с...")
        time.sleep(_SETTLE_SEC)
        if measure_reception:
            with BackendDriver(port=8765) as drv:
                first = _received(drv)
                time.sleep(6.0)
                second = _received(drv)
            facts["received_before"] = first
            facts["received_after"] = second
    finally:
        print("[proof] останавливаю систему, засекаю...")
        started = time.monotonic()
        launcher.shutdown()
        facts["shutdown_sec"] = time.monotonic() - started
        print(f"[proof]   launcher.shutdown() занял {facts['shutdown_sec']:.2f} с")

    # Срез ПОСЛЕ засечки: иначе вторая фаза читала бы строки первой.
    _await_lines(log_dir, STOPPED_LINE, deadline_sec=10.0)
    facts["flush_lines"] = [ln for ln in _lines(log_dir, FLUSH_LINE) if ln not in mark[FLUSH_LINE]]
    facts["stopped_lines"] = [ln for ln in _lines(log_dir, STOPPED_LINE) if ln not in mark[STOPPED_LINE]]
    facts["forced"] = [
        ln for ln in _lines(log_dir, FORCED_STOP_MARK) if ln not in mark[FORCED_STOP_MARK] and PROCESS in ln
    ]
    return facts


def main() -> int:
    os.environ.setdefault("BACKEND_CTL", "1")
    results: list[tuple[str, bool | None]] = []
    collector: http.server.HTTPServer | None = None

    try:
        # ------------------------------------------------------------------ #
        # Фаза А: ЧЁРНАЯ ДЫРА — сток, который ЖДЁТ
        # ------------------------------------------------------------------ #
        log_dir = Path(os.environ.get("INSPECTOR_LOG_DIR") or "logs_t24").resolve()
        os.environ["INSPECTOR_LOG_DIR"] = str(log_dir)
        dark = _run_phase(BLACK_HOLE, log_dir, measure_reception=True)
        if "measurement_failed" in dark:
            print(f"[proof] ОТКАЗ ИЗМЕРЕНИЯ: {dark['measurement_failed']}")
            return 2

        budget = FRAMEWORK_STOP_BUDGET_SEC + WHOLE_SHUTDOWN_SLACK_SEC
        results.append(
            _verdict(
                "останов на ЧЁРНОЙ ДЫРЕ укладывается в бюджет",
                dark["shutdown_sec"] <= budget,
                f"launcher.shutdown() {dark['shutdown_sec']:.2f} с при потолке {budget:.1f} с "
                f"(бюджет фреймворка {FRAMEWORK_STOP_BUDGET_SEC} с + {WHOLE_SHUTDOWN_SLACK_SEC} с на "
                "останов остальной системы). До Task 2.4 синхронное дожатие жило 23-42 с",
            )
        )
        results.append(
            _verdict(
                f"процесс {PROCESS} остановился САМ, а не был добит по таймауту",
                not dark["forced"],
                f"строк «{FORCED_STOP_MARK}» про {PROCESS}: {len(dark['forced'])}"
                + (f"; первая: {dark['forced'][0].strip()}" if dark["forced"] else ""),
            )
        )
        numbered = [ln for ln in dark["flush_lines"] if re.search(r"\d+ дожато", ln)]
        results.append(
            _verdict(
                "исход останова назван ЧИСЛАМИ",
                bool(numbered),
                f"строк «{FLUSH_LINE}» с числами: {len(numbered)}"
                + (f"; последняя: {numbered[-1].strip()}" if numbered else " — исход не назван"),
            )
        )
        grew = dark.get("received_after", 0) - dark.get("received_before", 0)
        results.append(
            _verdict(
                "приём НЕ встал за висящей отправкой",
                grew > 0,
                f"received за 6 с при висящем стоке: +{grew} "
                f"({dark.get('received_before')} -> {dark.get('received_after')}). "
                "Синхронная отправка держала бы поток команды и прирост был бы нулевым",
            )
        )

        # ------------------------------------------------------------------ #
        # Фаза Б (ПАРА): живой приёмник — иначе «уложился» ничего не значит
        # ------------------------------------------------------------------ #
        collector = _start_collector()
        live = _run_phase(LIVE_ENDPOINT, log_dir, measure_reception=False)
        if "measurement_failed" in live:
            print(f"[proof] ОТКАЗ ИЗМЕРЕНИЯ в контрольной фазе: {live['measurement_failed']}")
            return 2

        # ПАРА переписана: «с живым приёмником дожимается больше нуля» — посылка,
        # которую сама асинхронность делает ложной. Фоновый дренаж отправляет
        # непрерывно, поэтому к останову очередь ПУСТА и дожимать нечего; первая
        # редакция получила «0 дожато» на исправном механизме. Наблюдаемое
        # различие фаз другое: на чёрной дыре останов ТЕРЯЕТ записи числом (значит
        # работа у него была), с живым приёмником не теряет и они доехали.
        dark_lost = _last_number(dark["stopped_lines"], r"не дожато за [\d.]+ с\) (\d+)")
        live_lost = _last_number(live["stopped_lines"], r"не дожато за [\d.]+ с\) (\d+)")
        dark_exported = _last_number(dark["stopped_lines"], r"'exported': (\d+)")
        live_exported = _last_number(live["stopped_lines"], r"'exported': (\d+)")
        results.append(
            _verdict(
                "ПАРА: фазы различаются числами — потеря есть только у чёрной дыры",
                dark_lost > 0 and live_lost == 0 and live_exported > 0,
                f"чёрная дыра: потеряно {dark_lost}, exported {dark_exported}; "
                f"живой приёмник: потеряно {live_lost}, exported {live_exported}. "
                "Потеря>0 у чёрной дыры доказывает, что у останова БЫЛА работа, а не пустая очередь",
            )
        )
    finally:
        if collector is not None:
            collector.shutdown()
            collector.server_close()
        TEMP_TOPOLOGY.unlink(missing_ok=True)

    proven = sum(1 for _n, ok in results if ok is True)
    refuted = [n for n, ok in results if ok is False]
    unknown = [n for n, ok in results if ok is None]
    print(f"\n[proof] ИТОГ: доказано {proven} из {len(results)}")
    for name in refuted:
        print(f"[proof]   ОПРОВЕРГНУТО: {name}")
    for name in unknown:
        print(f"[proof]   НЕ ДОКАЗАНО: {name}")
    return 1 if refuted else (2 if unknown else 0)


if __name__ == "__main__":
    sys.exit(main())
