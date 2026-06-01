"""Реестр PID процессов системы — надёжная чистка «хвостов» при старте/перезапуске.

Проблема: при штатной остановке (`SystemLauncher.run()` → `finally: stop()`) дерево
процессов гасится через ``_kill_orphan_children``. Но если главный процесс убит ЖЁСТКО
(закрытие окна терминала крестиком, kill -9, падение до входа в loop), ``finally`` не
отрабатывает — дочерние OS-процессы остаются сиротами и копят память (см. инцидент
2026-06-01: 53 осиротевших python-процесса → OpenBLAS/MemoryError при спавне).

Решение: каждый процесс системы (PM + дети) дописывает свой ``(pid, create_time)`` в
общий jsonl-файл. При следующем старте ``reap_and_reset`` убивает все ещё живые записи
предыдущего запуска и очищает файл. Сверка ``create_time`` защищает от переиспользования
PID операционной системой (не убьём чужой процесс, занявший старый PID).

Путь к файлу — из env ``INSPECTOR_PID_FILE`` (наследуется детьми через spawn) или дефолт
в системной temp-директории.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import List, Tuple

_ENV_KEY = "INSPECTOR_PID_FILE"
_DEFAULT_NAME = "inspector_system_pids.jsonl"


def pid_file_path() -> Path:
    """Путь к файлу-реестру PID (env ``INSPECTOR_PID_FILE`` или temp-дефолт)."""
    env = os.environ.get(_ENV_KEY)
    if env:
        return Path(env)
    return Path(tempfile.gettempdir()) / _DEFAULT_NAME


def _safe_create_time(pid: int) -> float | None:
    """create_time процесса или None, если процесса нет / нет доступа."""
    try:
        import psutil

        return psutil.Process(pid).create_time()
    except Exception:  # noqa: BLE001 — нет процесса/нет psutil/нет доступа
        return None


def register_self(path: Path | None = None) -> None:
    """Дописать ``(pid, create_time)`` текущего процесса в реестр (append, best-effort)."""
    path = path or pid_file_path()
    try:
        ct = _safe_create_time(os.getpid())
        line = json.dumps({"pid": os.getpid(), "ct": ct}) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:  # noqa: BLE001 — реестр не критичен, не должен ронять процесс
        pass


def _read_entries(path: Path) -> List[Tuple[int, float | None]]:
    out: List[Tuple[int, float | None]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    d = json.loads(raw)
                    out.append((int(d["pid"]), d.get("ct")))
                except Exception:  # noqa: BLE001 — битая строка → пропускаем  # nosec B112
                    continue
    except FileNotFoundError:
        return out
    except Exception:  # noqa: BLE001
        return out
    return out


def reap_and_reset(path: Path | None = None, *, log=None) -> int:
    """Убить ещё живые процессы из реестра прошлого запуска и очистить файл.

    Убивает PID, только если процесс жив И его ``create_time`` совпадает с записанным
    (защита от переиспользования PID). Не трогает текущий процесс. Возвращает число убитых.
    """
    path = path or pid_file_path()
    entries = _read_entries(path)
    me = os.getpid()
    killed = 0

    if entries:
        try:
            import psutil
        except Exception:  # noqa: BLE001 — без psutil не можем безопасно убивать
            psutil = None  # type: ignore[assignment]

        if psutil is not None:
            victims = []
            for pid, ct in entries:
                if pid == me:
                    continue
                try:
                    p = psutil.Process(pid)
                    if not p.is_running():
                        continue
                    # Сверка create_time — иначе можем убить чужой переиспользованный PID
                    if ct is not None and abs(p.create_time() - ct) > 1.0:
                        continue
                    victims.append(p)
                except Exception:  # noqa: BLE001 — процесса нет / нет доступа  # nosec B112
                    continue
            for p in victims:
                try:
                    p.kill()
                    killed += 1
                except Exception:  # noqa: BLE001
                    pass
            if victims:
                psutil.wait_procs(victims, timeout=3.0)

    # Очистить реестр под новый запуск (даже если что-то не убилось)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("")
    except Exception:  # noqa: BLE001
        pass

    if killed and log is not None:
        try:
            log(f"PID-реестр: убито {killed} осиротевших процесс(ов) предыдущего запуска")
        except Exception:  # noqa: BLE001
            pass
    return killed


def clear(path: Path | None = None) -> None:
    """Очистить реестр (зовётся при штатной остановке)."""
    path = path or pid_file_path()
    try:
        if path.exists():
            with open(path, "w", encoding="utf-8") as f:
                f.write("")
    except Exception:  # noqa: BLE001
        pass
