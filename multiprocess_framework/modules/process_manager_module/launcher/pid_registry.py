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

Путь к файлу — из env ``MULTIPROCESS_PID_FILE`` / ``INSPECTOR_PID_FILE`` (наследуется
детьми через spawn) или дефолт в системной temp-директории.

**Имя дефолтного файла зависит от приложения** (D4). До этого оно было прибито к
одному продукту (``inspector_system_pids.jsonl``), и это не косметика: два разных
приложения на фреймворке делили ОДИН реестр в общей temp-директории, поэтому старт
второго реапал живые процессы первого. Теперь имя — ``<app>_system_pids.jsonl`` по
``MPF_APP_NAME``, и приложения друг друга не видят.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import List, Tuple

from ...base_manager.utils import app_name_slug

#: Каноничное имя env-ручки и её легаси-алиас (де-брендинг, Ф5.11 + D4).
_ENV_KEYS = ("MULTIPROCESS_PID_FILE", "INSPECTOR_PID_FILE")

#: Реестр продукта, под которым фреймворк жил до D4. Осиротел бы молча — см.
#: :func:`legacy_pid_file_path` и реап в :func:`reap_and_reset`.
_LEGACY_DEFAULT_NAME = "inspector_system_pids.jsonl"


def default_pid_file_name(app_name: str | None = None) -> str:
    """Имя дефолтного файла-реестра для приложения (``<app>_system_pids.jsonl``)."""
    return f"{app_name_slug(app_name)}_system_pids.jsonl"


def pid_file_path() -> Path:
    """Путь к файлу-реестру PID (env-ручка или temp-дефолт по имени приложения)."""
    for key in _ENV_KEYS:
        env = (os.environ.get(key) or "").strip()
        if env:
            return Path(env)
    return Path(tempfile.gettempdir()) / default_pid_file_name()


def legacy_pid_file_path() -> Path | None:
    """Реестр прежнего продуктового имени, если он ещё лежит в temp и это НЕ текущий.

    Возвращает ``None``, когда легаси-файла нет либо когда текущий реестр — он же
    (приложение с ``MPF_APP_NAME=inspector``: файл не «чужой хвост», а свой рабочий).
    """
    legacy = Path(tempfile.gettempdir()) / _LEGACY_DEFAULT_NAME
    try:
        if not legacy.exists():
            return None
        if legacy.resolve() == pid_file_path().resolve():
            return None
    except Exception:  # noqa: BLE001 — недоступный путь = нечего реапать
        return None
    return legacy


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

    Дополнительно реапает **легаси-реестр** прежнего продуктового имени, если он
    остался в temp от запусков до D4, и удаляет его. Иначе после переименования его
    хвосты не убил бы никто и никогда — молча осиротевшие процессы копят память
    (тот же класс, что инцидент 2026-06-01). Считается в общее число убитых.
    """
    path = path or pid_file_path()
    killed = _reap_file(path, log=log)
    _reset_file(path)

    legacy = legacy_pid_file_path()
    if legacy is not None:
        legacy_killed = _reap_file(legacy, log=log)
        killed += legacy_killed
        if log is not None:
            try:
                log(
                    f"PID-реестр: подобран легаси-реестр {legacy} "
                    f"(убито {legacy_killed}), файл удалён — имя реестра теперь "
                    f"зависит от приложения (MPF_APP_NAME)"
                )
            except Exception:  # noqa: BLE001
                pass
        try:
            legacy.unlink()
        except Exception:  # noqa: BLE001 — не смогли удалить: реап уже отработал
            pass

    if killed and log is not None:
        try:
            log(f"PID-реестр: убито {killed} осиротевших процесс(ов) предыдущего запуска")
        except Exception:  # noqa: BLE001
            pass
    return killed


def _reap_file(path: Path, *, log=None) -> int:
    """Убить живые процессы, записанные в один файл-реестр. Файл не трогает."""
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

    return killed


def _reset_file(path: Path) -> None:
    """Очистить реестр под новый запуск (даже если что-то не убилось)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("")
    except Exception:  # noqa: BLE001
        pass


def clear(path: Path | None = None) -> None:
    """Очистить реестр (зовётся при штатной остановке)."""
    path = path or pid_file_path()
    try:
        if path.exists():
            with open(path, "w", encoding="utf-8") as f:
                f.write("")
    except Exception:  # noqa: BLE001
        pass
