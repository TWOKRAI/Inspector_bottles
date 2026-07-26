# -*- coding: utf-8 -*-
"""ErrorFloor — гарантированный пол для error/critical (Ф0.9, вариант B).

Задача 0.9 плана ``observability-unified-routing``. Решение владельца
2026-07-26: «лучше в одном месте, но с подробностями».

Инвариант, который держит этот модуль:

    error/critical пишутся СИНХРОННО, в ОДНО место, БЕЗ дублей,
    и этот путь НЕ зависит от конфигурации приёмников.

Как это достигается:

  * **Синхронно** — запись идёт напрямую в канал, минуя ``BatchBuffer``
    (см. ``LoggerCore.log`` / ``ErrorManager.log``). Временная мера Ф0.1
    (``priority="urgent"``) этим снята: она сбрасывала всю пачку, чтобы
    вытолкнуть одну запись, — теперь запись просто не попадает в пачку.
  * **Без дублей** — floor пишет ТОЛЬКО когда обычный маршрут записал ноль
    каналов. Это и есть отличие варианта B от отклонённого варианта A
    (отдельный аварийный файл ПОВЕРХ обычного маршрута, вторая копия каждой
    ошибки).
  * **Конфиго-независимо** — путь floor'а не берётся из ``config.channels``,
    поэтому ни ``enabled: false``, ни ``logger.sink.disable`` его не гасят.
    Каталог берётся оттуда же, откуда обычные логи (``log_directory`` / env),
    но сам приёмник не описан в конфиге и не может быть из него снят.
  * **Полная запись** — строка JSON со ВСЕМИ полями записи, включая ``extra``
    и многострочный traceback. Усечение запрещено требованием владельца:
    «упало» без «где и с чем» не отлаживается.

Формат — JSON Lines: одна запись = одна строка. Так многострочный traceback
не ломает разбор, а поля не теряются. Читается глазами и машиной.

Файл открывается ЛЕНИВО — на первой реальной ошибке. У здорового процесса
floor.log не появляется вовсе, и это осмысленный сигнал: floor непустой
означает, что штатный маршрут ошибок сломан.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional

#: Имя файла-пола. Одно на процесс, рядом с остальными логами.
FLOOR_FILE_NAME = "errors_floor.jsonl"

#: Процесс-wide реестр полов по абсолютному пути. Два менеджера одного процесса
#: (LoggerManager и ErrorManager) обязаны писать в ОДИН файл через ОДИН
#: дескриптор — иначе на Windows два хендла на один путь дают WinError 32,
#: тот же класс, ради которого в log_channel.py живёт _shared_handlers.
_floors: Dict[str, "ErrorFloor"] = {}
_floors_lock = threading.Lock()


class ErrorFloor:
    """Синхронный приёмник последней инстанции для error/critical.

    Потокобезопасен: запись под локом, файл открыт в режиме дозаписи и
    сбрасывается на диск после каждой строки (``flush``). ``fsync`` НЕ зовём —
    он стоит миллисекунды и не нужен: SIGKILL не забирает данные, уже отданные
    ядру, а от потери питания floor не защищает и не обязан.
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._fh: Optional[Any] = None
        self._written: int = 0
        self._failures: int = 0

    @property
    def path(self) -> str:
        return self._path

    @property
    def stats(self) -> Dict[str, Any]:
        """Счётчики пола.

        ``written`` > 0 — диагностический сигнал сам по себе: штатный маршрут
        ошибок не сработал столько-то раз. ``failures`` — не смогли записать
        даже в пол (дальше падать некуда, поэтому только счётчик).
        """
        return {"path": self._path, "written": self._written, "failures": self._failures}

    def write(self, record: Dict[str, Any]) -> bool:
        """Записать запись целиком. Возвращает True, если строка легла на диск."""
        with self._lock:
            try:
                if self._fh is None:
                    Path(self._path).parent.mkdir(parents=True, exist_ok=True)
                    self._fh = open(self._path, "a", encoding="utf-8")  # noqa: SIM115 — живёт до close()
                line = json.dumps(record, ensure_ascii=False, default=str)
                self._fh.write(line + "\n")
                self._fh.flush()
                self._written += 1
                return True
            except Exception:  # noqa: BLE001 — пол не имеет права ронять вызывающий код
                self._failures += 1
                return False

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.close()
                except Exception:  # nosec B110 — teardown best-effort
                    pass
                self._fh = None


def get_error_floor(path: str) -> ErrorFloor:
    """Пол по пути — один инстанс на путь в рамках процесса (см. ``_floors``)."""
    key = str(Path(path).resolve())
    with _floors_lock:
        floor = _floors.get(key)
        if floor is None:
            floor = ErrorFloor(key)
            _floors[key] = floor
        return floor


def reset_error_floors() -> None:
    """Закрыть и забыть все полы процесса. Только для тестов и teardown."""
    with _floors_lock:
        for floor in _floors.values():
            floor.close()
        _floors.clear()
