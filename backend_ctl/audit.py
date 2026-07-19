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
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

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
        """Последние записи ЭТОЙ сессии (кольцо), новейшие в конце. ``limit`` — хвост."""
        items = list(self._ring)
        if limit is not None and limit >= 0:
            items = items[-limit:]
        return items

    def _append_file(self, entry: Dict[str, Any]) -> None:
        """Дописать строку JSONL в durable-файл. Проглатывает любые ошибки (best-effort)."""
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            line = json.dumps(entry, ensure_ascii=False, default=str)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:  # noqa: BLE001 — журнал не должен ронять инструмент
            pass


__all__ = ["AuditLog", "resolve_audit_path", "AUDIT_PATH_ENV", "DEFAULT_RING"]
