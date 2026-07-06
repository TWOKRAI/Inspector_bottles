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
        [MM:SS] embedded N/~EST (X%) · R ч/с · ETA ~M:SS
     EST — оценка числа чанков из строки qex «Detected changes: A added … M modified»
     (файлы × средних чанков/файл из текущего индекса). Без оценки — только N·R·elapsed.

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
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent

IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
MODEL = "qwen3-embedding:4b"  # macOS переведён на 4b 2026-07-05 (было 8b) — см. qex-launcher.py
OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
KEEP_ALIVE = os.environ.get("QEX_KEEP_ALIVE", "60m")
REWARM_EVERY = 180
POLL_EVERY = 3
AVG_CHUNKS_FALLBACK = float(os.environ.get("QEX_AVG_CHUNKS", "15"))

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
    body = json.dumps({"model": MODEL, "input": "warmup", "keep_alive": KEEP_ALIVE}).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/embed", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.load(r)
        ok = bool(d.get("embeddings"))
        print(f"[warm] {MODEL} за {time.monotonic()-t0:.1f}s "
              f"(keep_alive={KEEP_ALIVE}, dim={len(d['embeddings'][0]) if ok else '?'})", flush=True)
        return ok
    except Exception as e:  # noqa: BLE001
        print(f"[warm] WARN {MODEL}: {e}", flush=True)
        return False


def avg_chunks_per_file() -> float:
    """Средних чанков/файл из закоммиченного индекса (для оценки total)."""
    try:
        meta = next(iter((Path.home() / ".qex" / "projects").glob("*/meta.json")), None)
        # meta.json у tantivy не хранит наши счётчики надёжно → используем fallback.
    except Exception:  # noqa: BLE001
        pass
    return AVG_CHUNKS_FALLBACK


def count_embeds(log: Path, start_offset: int) -> int:
    try:
        with log.open("rb") as f:
            f.seek(start_offset)
            data = f.read()
        c = data.count(b'POST     "/v1/embeddings"')
        return c if c else data.count(b'/v1/embeddings')
    except Exception:  # noqa: BLE001
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
            print(f"[scope] к переиндексации: {added} added + {modified} modified = {files} файлов", flush=True)
            continue
        if not raw and any(n in line for n in _NOISE):
            continue
        if line.strip():
            print(line, flush=True)


def progress_loop(log: Path | None, start_offset: int, cli_total: int | None,
                  stop: threading.Event) -> None:
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
                print(f"  [{fmt(elapsed)}] embedded {n}/{cli_total} ({pct:.0f}%) · "
                      f"{rate:.1f} ч/с · ETA ~{fmt(eta)}", flush=True)
            else:
                sc = f" · scope ~{_state['detected']} файлов" if _state["detected"] else ""
                print(f"  [{fmt(elapsed)}] embedded {n} чанков · {rate:.1f} ч/с{sc}", flush=True)
        else:
            print(f"  [{fmt(elapsed)}] индексация идёт (ollama-лог недоступен)", flush=True)
        stop.wait(POLL_EVERY)


def main() -> int:
    args = sys.argv[1:]
    cli_total = None
    raw = "--raw" in args
    if raw:
        args.remove("--raw")
    if "--total" in args:
        i = args.index("--total")
        cli_total = int(args[i + 1])
        del args[i:i + 2]

    print("=" * 60)
    print("qex reindex + progress")
    print("=" * 60)
    warm_model()  # прогрев ДО старта — иначе первый embed словит cold-timeout

    log = _ollama_log_path()
    start_offset = log.stat().st_size if (log and log.exists()) else 0
    if not (log and log.exists()):
        print(f"[progress] ollama-лог не найден ({log}) — только elapsed. "
              f"Задай OLLAMA_LOG=/path для per-chunk прогресса.", flush=True)

    stop = threading.Event()
    mon = threading.Thread(target=progress_loop, args=(log, start_offset, cli_total, stop), daemon=True)
    mon.start()

    proc = subprocess.Popen([sys.executable, str(REINDEX), *args],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    pump_reindex(proc, raw)
    rc = proc.wait()

    stop.set()
    mon.join(timeout=2)
    if log and log.exists():
        print(f"\n[итог] embedded ~{count_embeds(log, start_offset)} чанков за прогон, exit={rc}", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
