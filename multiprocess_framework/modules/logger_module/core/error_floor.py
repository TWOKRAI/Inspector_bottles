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
  * **Конфиго-независимо** — но только ФАКТ записи, не её местоположение, и
    путать эти два утверждения нельзя (находка ревью Ф0.9). Приёмник не описан
    в ``config.channels``, поэтому ни ``enabled: false``, ни
    ``logger.sink.disable`` его не гасят. А вот КАТАЛОГ резолвится в том числе
    по каналам конфига (см. ``LoggerCore._resolve_floor_path``): floor должен
    лежать там же, где обычные логи, иначе его будут искать не там.
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

    #: Потолок файла-пола. Ретеншен (Ф0.7) пол НЕ подметает намеренно — он
    #: последнее свидетельство о падении, и политика дискового места не имеет
    #: права отменять политику сохранности улик. Но «не подметаем» не значит
    #: «пусть растёт без предела»: при долгоживущем ``logger.sink.disable``
    #: КАЖДАЯ ошибка идёт сюда, и файл, который никто не ротирует, повторил бы
    #: историю ``messages.log`` (645 МБ незамеченными). Поэтому пол ротирует
    #: себя сам, одним бэкапом.
    _MAX_BYTES = 32 * 1024 * 1024

    def __init__(self, path: str, max_bytes: int = _MAX_BYTES) -> None:
        self._path = path
        self._max_bytes = max_bytes
        self._lock = threading.Lock()
        self._fh: Optional[Any] = None
        self._written: int = 0
        self._failures: int = 0
        self._rotations: int = 0

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
        return {
            "path": self._path,
            "written": self._written,
            "failures": self._failures,
            "rotations": self._rotations,
        }

    def write(self, record: Dict[str, Any]) -> bool:
        """Записать запись целиком. Возвращает True, если строка легла на диск."""
        with self._lock:
            try:
                if self._fh is None:
                    Path(self._path).parent.mkdir(parents=True, exist_ok=True)
                    self._fh = open(self._path, "a", encoding="utf-8")  # noqa: SIM115 — живёт до close()
                line = json.dumps(record, ensure_ascii=False, default=str)
                self._rotate_if_needed(len(line) + 1)
                self._fh.write(line + "\n")
                self._fh.flush()
                self._written += 1
                return True
            except Exception:  # noqa: BLE001 — пол не имеет права ронять вызывающий код
                self._failures += 1
                return False

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        """Сдвинуть файл в ``.1``, если следующая строка перевалит за потолок.

        Один бэкап, а не пять: пол — аварийный приёмник, и его ценность в
        СВЕЖИХ записях о том, что маршрут сломан прямо сейчас. Держать
        глубокую историю отказов ценой гигабайтов незачем.

        Вызывается ПОД локом записи и только при открытом дескрипторе.
        Любая ошибка ротации проглатывается сознательно: не сумели
        подвинуть — продолжаем писать в текущий файл (fail-open). Потерять
        запись об ошибке из-за неудавшейся уборки было бы хуже, чем
        превысить потолок.
        """
        if self._max_bytes <= 0 or self._fh is None:
            return
        try:
            if self._fh.tell() + incoming_bytes <= self._max_bytes:
                return
            self._fh.close()
            self._fh = None
            backup = Path(self._path).with_suffix(Path(self._path).suffix + ".1")
            backup.unlink(missing_ok=True)
            Path(self._path).rename(backup)
            self._rotations += 1
        except OSError:
            pass  # nosec B110 — fail-open: пишем дальше в текущий файл
        finally:
            if self._fh is None:
                # И после успешной ротации, и после сбоя нужен живой дескриптор.
                self._fh = open(self._path, "a", encoding="utf-8")  # noqa: SIM115 — живёт до close()

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
