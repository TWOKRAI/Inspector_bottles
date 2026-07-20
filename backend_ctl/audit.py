# -*- coding: utf-8 -*-
"""audit.py — аудит-журнал мутаций сессии backend_ctl (E.1, Phase E «доверие»).

Каждый write/escalated-вызов сессии оседает записью в JSONL (кто/что/когда/аргументы/
результат/исход), чтобы владелец мог доверять автономным агентским сессиям и иметь
вход для откатов (D.5). Read/subscribe-инструменты в журнал НЕ шумят — только мутации.

Два уровня хранения:
  * durable JSONL-файл (append-only, best-effort) — переживает процесс, кросс-сессионный;
  * in-memory кольцо (последние N этой сессии) — источник для ``session_log()`` без
    парсинга файла и без протечки чужих сессий (важно для HTTP-мультиклиента D.2).

Best-effort по контракту: сбой записи журнала НЕ должен ронять сам инструмент —
аудит наблюдает, а не мешает.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

#: Сериализует дозапись в durable-файл в пределах процесса: несколько сессий D.2
#: (HTTP-мультиклиент) пишут в ОДИН дефолтный файл — без блокировки строки >PIPE_BUF
#: интерливятся и бьют JSONL. Кросс-процессную гонку не покрывает (обычно record-dir
#: свой на бэкенд), но реальный кейс «много сессий в одном сервере» — да.
_FILE_LOCK = threading.Lock()

#: Переменная окружения с явным путём файла журнала. Опущено → путь в каталоге записей.
AUDIT_PATH_ENV = "BACKEND_CTL_AUDIT"
#: Каталог записей (общий с flight recorder), если путь не задан явно.
_RECORD_DIR_ENV = "BACKEND_CTL_RECORD_DIR"
_DEFAULT_RECORD_DIR = "./backend_ctl_records"
_DEFAULT_AUDIT_FILE = "audit.jsonl"

#: Глубина in-memory кольца (сколько последних мутаций доступно session_log()).
DEFAULT_RING = 200
#: Потолок сериализации args/result в записи (защита журнала от гигантских payload'ов).
_FIELD_BYTE_CAP = 4096


def resolve_audit_path() -> str:
    """Путь файла журнала: явный ``BACKEND_CTL_AUDIT`` или ``<record_dir>/audit.jsonl``."""
    explicit = os.environ.get(AUDIT_PATH_ENV)
    if explicit:
        return os.path.abspath(explicit)
    base = os.environ.get(_RECORD_DIR_ENV) or _DEFAULT_RECORD_DIR
    return os.path.abspath(os.path.join(base, _DEFAULT_AUDIT_FILE))


def _clip(value: Any) -> Any:
    """Сжать значение до безопасного размера: длинная сериализация → усечённая строка-маркер."""
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001 — несериализуемое → repr
        text = repr(value)
    if len(text) <= _FIELD_BYTE_CAP:
        return value
    return {"_truncated": True, "size": len(text), "head": text[:_FIELD_BYTE_CAP]}


def _outcome(result: Any, error: Optional[BaseException]) -> Dict[str, Any]:
    """Извлечь ``ok``/``error`` из результата инструмента или исключения.

    Мягкий отказ бэкенда (``{"success": False, ...}``) — тоже ``ok=False``, но без
    исключения: журнал различает «упало исключением» и «бэкенд вернул неуспех».
    """
    if error is not None:
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}
    if isinstance(result, dict) and "success" in result:
        ok = bool(result["success"])
        out: Dict[str, Any] = {"ok": ok}
        if not ok and result.get("error"):
            out["error"] = str(result["error"])
        return out
    return {"ok": True}


class AuditLog:
    """Аудит-журнал одной сессии: durable JSONL + in-memory кольцо последних записей.

    Не бросает наружу: любая ошибка записи проглатывается (best-effort). ``records()``
    отдаёт только записи ЭТОЙ сессии (кольцо), не смешивая чужие из общего файла.
    """

    def __init__(
        self,
        *,
        path: Optional[str] = None,
        ring: int = DEFAULT_RING,
        clock: Any = time.time,
    ) -> None:
        self._path = path if path is not None else resolve_audit_path()
        self._ring: Deque[Dict[str, Any]] = deque(maxlen=ring)
        self._clock = clock
        self._seq = 0
        # Task 2.2: SDK гоняет tools/call в параллельных потоках (anyio.to_thread +
        # tg.start_soon), а один DriverSession отдаёт ОДИН AuditLog всем вызовам сессии
        # (см. _audit_log() в mcp_driver_session.py). Без лока «инкремент _seq → append
        # в кольцо» — не атомарная пара: два потока читают одно и то же старое значение
        # _seq → дубли номеров в журнале, либо один append перекрывает другой в узком
        # окне между чтением deque и записью (в CPython это не потерять сам append, но
        # порядок seq↔запись гарантированно рвётся под настоящей ОС-конкуренцией).
        self._lock = threading.Lock()

    @property
    def path(self) -> str:
        return self._path

    def record(
        self,
        tool: str,
        safety: str,
        args: Any,
        *,
        result: Any = None,
        error: Optional[BaseException] = None,
    ) -> Dict[str, Any]:
        """Записать один write/escalated-вызов. Best-effort: сбой файла не бросается.

        Возвращает записанную запись (для тестов/инлайна). ``result`` ИЛИ ``error`` —
        одно из двух: успешный/мягко-неуспешный ответ либо перехваченное исключение.
        """
        # Инкремент seq и append в кольцо — одна атомарная операция (Task 2.2): иначе
        # два потока читают одно старое значение _seq (дубль номера) либо расходятся
        # в порядке seq↔запись. Сериализация файла (_append_file, отдельный _FILE_LOCK)
        # сознательно вынесена за пределы этого лока — I/O не должен держать сессию.
        with self._lock:
            self._seq += 1
            entry: Dict[str, Any] = {
                "seq": self._seq,
                "ts": self._clock(),
                "tool": tool,
                "safety": safety,
                "args": _clip(args),
            }
            entry.update(_outcome(result, error))
            self._ring.append(entry)
        self._append_file(entry)
        return entry

    def records(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Последние записи ЭТОЙ сессии (кольцо), новейшие в конце. ``limit`` — хвост.

        ``limit=None`` → весь журнал (кольцо). ``limit=0`` → пустой список (а не весь
        журнал: срез ``items[-0:]`` == ``items[0:]``, поэтому 0 — особый случай).
        ``limit<0`` (бессмыслица — «последние минус N») → тоже пустой список, зеркало
        контракта :meth:`driver.BackendDriver.telemetry_history` (driver.py:1156-1160).
        """
        # list(deque) под тем же локом, что append (Task 2.2): без него параллельный
        # record() меняет размер кольца прямо во время итерации list() и деке кидает
        # «deque mutated during iteration» (RuntimeError) вместо тихой гонки.
        with self._lock:
            items = list(self._ring)
        if limit is not None:
            items = items[-limit:] if limit > 0 else []
        return items

    def _append_file(self, entry: Dict[str, Any]) -> None:
        """Дописать строку JSONL в durable-файл. Проглатывает любые ошибки (best-effort)."""
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            line = json.dumps(entry, ensure_ascii=False, default=str)
            # Лок сериализует открытие+запись строки между сессиями одного процесса —
            # иначе конкурентные append'ы в общий файл интерливятся (строка > PIPE_BUF).
            with _FILE_LOCK, open(self._path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:  # noqa: BLE001 — журнал не должен ронять инструмент
            pass


__all__ = ["AuditLog", "resolve_audit_path", "AUDIT_PATH_ENV", "DEFAULT_RING"]
