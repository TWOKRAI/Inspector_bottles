#!/usr/bin/env python3
"""qex reindex с прогревом embedding-модели и live-прогрессом.

Зачем: qex сам НЕ отдаёт прогресс индексации, а `get_indexing_status` показывает
только последний ЗАкоммиченный индекс (не растёт вживую). Надёжный live-сигнал —
счётчик embedding-запросов к ollama: qex шлёт ~1 `POST /v1/embeddings` на чанк.
Эта обёртка:

  1) ПРОГРЕВАЕТ embedding-модель с длинным keep_alive — устраняет главную причину
     падений (cold-load 8b-модели → HTTP timeout внутри qex);
  2) ПЕРИОДИЧЕСКИ ре-прогревает, чтобы модель не выгрузилась посреди прогона;
  3) запускает `reindex.py`, ГЛУШИТ tantivy-шум и показывает live-прогресс:
        [MM:SS] embedded N/TOTAL (X%) · R ч/с · ETA ~M:SS
     Проценты и ETA считаются ТОЛЬКО при явном --total: qex-«added» — это файлы,
     а не чанки, и оценка «файлы × средних чанков/файл» врёт. Без --total
     печатается честное N · R · elapsed, а строка «Detected changes» показывается
     отдельно как объём работ.

Использование:
    python reindex_progress.py                 # инкрементальная
    python reindex_progress.py --force          # полная
    python reindex_progress.py --total 4000     # явно задать число чанков для точных %/ETA
    python reindex_progress.py --clear --force  # очистка + полная
    python reindex_progress.py --raw            # не глушить логи qex (диагностика)
Флаги --total/--raw обрабатываются здесь; --force/--clear/прочее → в reindex.py.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REINDEX = SCRIPT_DIR / "reindex.py"
# .claude/plugins/mcp-qex → .claude/plugins → .claude → корень проекта.
# Сам скрипт корень не использует (всю работу делает reindex.py), константа
# оставлена якорем раскладки, одинаковым с reindex.py и reindex_retry.py.
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent

IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
# Источник истины — qex-launcher.py (Windows → 0.6b/dim 1024, иначе → 8b/dim 4096);
# здесь дубль нужен только для прогрева keep-alive и обязан совпадать с ним:
# греть не ту модель бесполезно — qex запросит свою и словит cold-load таймаут.
# QEX_EMBED_MODEL переопределяет выбор, не трогая шипнутый код (например
# qwen3-embedding:4b на машине с запасом VRAM) — но тогда и qex-launcher.py
# должен быть переключён на неё же вместе с dimensions.
# Тег-вариант (`-qex`), не базовый — должен совпадать с qex-launcher.py/reindex.py:
# базовый тег не несёт num_ctx/num_gpu, греть не тот тег бесполезно.
MODEL = os.environ.get(
    "QEX_EMBED_MODEL",
    "qwen3-embedding:0.6b-qex" if IS_WIN else "qwen3-embedding:8b-qex",
)
OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
KEEP_ALIVE = os.environ.get("QEX_KEEP_ALIVE", "60m")
REWARM_EVERY = 180
POLL_EVERY = 3
_DETECT_RE = re.compile(r"Detected changes:\s*(\d+)\s*added.*?(\d+)\s*modified")
# строки qex, которые НЕ показываем (tantivy-внутрянка) — глушим, если не --raw
_NOISE = ("tantivy::", "managed_directory", "segment_updater", "Garbage", "Deleted ")

# общее live-состояние (пишет монитор и парсер вывода reindex)
_state: dict = {"total_chunks": None, "detected": None}


def _ollama_log_path() -> Path | None:
    if os.environ.get("OLLAMA_LOG"):
        return Path(os.environ["OLLAMA_LOG"])
    if IS_MAC:
        return Path.home() / ".ollama" / "logs" / "server.log"
    if IS_WIN:
        la = os.environ.get("LOCALAPPDATA", "")
        return Path(la) / "Ollama" / "server.log" if la else None
    p = Path.home() / ".ollama" / "logs" / "server.log"
    return p if p.exists() else None


def warm_model() -> bool:
    body = json.dumps(
        {"model": MODEL, "input": "warmup", "keep_alive": KEEP_ALIVE}
    ).encode()
    req = urllib.request.Request(
        f"{OLLAMA}/api/embed", data=body, headers={"Content-Type": "application/json"}
    )
    try:
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.load(r)
        ok = bool(d.get("embeddings"))
        print(
            f"[warm] {MODEL} за {time.monotonic() - t0:.1f}s "
            f"(keep_alive={KEEP_ALIVE}, dim={len(d['embeddings'][0]) if ok else '?'})",
            flush=True,
        )
        return ok
    except Exception as e:
        print(f"[warm] WARN {MODEL}: {e}", flush=True)
        return False


def count_embeds(log: Path, start_offset: int) -> int:
    try:
        with log.open("rb") as f:
            f.seek(start_offset)
            data = f.read()
        c = data.count(b'POST     "/v1/embeddings"')
        return c if c else data.count(b"/v1/embeddings")
    except Exception:
        return 0


def fmt(sec: float) -> str:
    sec = int(max(0, sec))
    return f"{sec // 60}:{sec % 60:02d}"


def pump_reindex(proc: subprocess.Popen, raw: bool) -> None:
    """Читает вывод reindex.py: глушит tantivy-шум, ловит 'Detected changes' → total."""
    for line in proc.stdout:  # type: ignore[union-attr]
        line = line.rstrip("\n")
        m = _DETECT_RE.search(line)
        if m:
            added, modified = int(m.group(1)), int(m.group(2))
            files = added + modified
            _state["detected"] = files
            # НЕ выводим ETA-оценку из файлов: qex-«added» ≠ число чанков, оценка врёт.
            # Честный ETA только при явном --total. Здесь — лишь контекст объёма работ.
            print(
                f"[scope] к переиндексации: {added} added + {modified} modified = {files} файлов",
                flush=True,
            )
            continue
        if not raw and any(n in line for n in _NOISE):
            continue
        if line.strip():
            print(line, flush=True)


def progress_loop(
    log: Path | None, start_offset: int, cli_total: int | None, stop: threading.Event
) -> None:
    t0 = time.monotonic()
    last_warm = t0
    while not stop.is_set():
        elapsed = time.monotonic() - t0
        if time.monotonic() - last_warm > REWARM_EVERY:
            warm_model()
            last_warm = time.monotonic()
        if log and log.exists():
            n = count_embeds(log, start_offset)
            rate = n / elapsed if elapsed > 0 else 0
            if cli_total and cli_total > 0:
                pct = min(100.0, 100 * n / cli_total)
                eta = (cli_total - n) / rate if rate > 0 and n < cli_total else 0
                print(
                    f"  [{fmt(elapsed)}] embedded {n}/{cli_total} ({pct:.0f}%) · "
                    f"{rate:.1f} ч/с · ETA ~{fmt(eta)}",
                    flush=True,
                )
            else:
                sc = (
                    f" · scope ~{_state['detected']} файлов"
                    if _state["detected"]
                    else ""
                )
                print(
                    f"  [{fmt(elapsed)}] embedded {n} чанков · {rate:.1f} ч/с{sc}",
                    flush=True,
                )
        else:
            print(
                f"  [{fmt(elapsed)}] индексация идёт (ollama-лог недоступен)",
                flush=True,
            )
        stop.wait(POLL_EVERY)


def main() -> int:
    # Windows-консоль по умолчанию cp1251/cp866: без этого русский вывод и
    # символы вроде -> x -- роняют скрипт с UnicodeEncodeError ещё до работы.
    # Тот же приём, что в mcp-graphify/scripts/graph_slice.py.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        # Раньше всего остального: без этой ветки --help проваливался в reindex.py
        # и упирался в «Ollama не запущена», прогрев и трёхсекундный цикл прогресса.
        print(__doc__ or "", end="")
        return 0
    cli_total = None
    raw = "--raw" in args
    if raw:
        args.remove("--raw")
    if "--total" in args:
        i = args.index("--total")
        cli_total = int(args[i + 1])
        del args[i : i + 2]

    print("=" * 60)
    print("qex reindex + progress")
    print("=" * 60)
    warm_model()  # прогрев ДО старта — иначе первый embed словит cold-timeout

    log = _ollama_log_path()
    start_offset = log.stat().st_size if (log and log.exists()) else 0
    if not (log and log.exists()):
        print(
            f"[progress] ollama-лог не найден ({log}) — только elapsed. "
            f"Задай OLLAMA_LOG=/path для per-chunk прогресса.",
            flush=True,
        )

    stop = threading.Event()
    mon = threading.Thread(
        target=progress_loop, args=(log, start_offset, cli_total, stop), daemon=True
    )
    mon.start()

    proc = subprocess.Popen(
        [sys.executable, str(REINDEX), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    pump_reindex(proc, raw)
    rc = proc.wait()

    stop.set()
    mon.join(timeout=2)
    if log and log.exists():
        print(
            f"\n[итог] embedded ~{count_embeds(log, start_offset)} чанков за прогон, exit={rc}",
            flush=True,
        )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
