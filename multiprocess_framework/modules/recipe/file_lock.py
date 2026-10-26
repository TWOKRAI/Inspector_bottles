"""Межпроцессный лок файла рецепта (Task 1.1h).

Purpose
-------
Сериализовать «чтение байтов → сверка ``rev`` → запись/удаление» рецепта между ПРОЦЕССАМИ
(хаб, ``backend_ctl``, второй экземпляр приложения). Потоковый лок внутри процесса это не
покрывает: два процесса с одним ``base_rev`` иначе оба проходят сверку и последний молча
затирает первого.

Public API
----------
``recipe_file_lock(path, *, timeout=5.0)`` — контекстный менеджер.
    Pre: ``path`` — путь файла рецепта; сам файл может не существовать (новый рецепт).
    Post (вход): эксклюзивный лок на ``<path>.lock`` (``letter_robot_sim.yaml.lock``) рядом с
    рецептом взят этим процессом; lock-файл создан при отсутствии. Файл рецепта не трогается.
    Post (выход): лок снят, lock-файл ОСТАЁТСЯ на диске (никогда не удаляется: ``unlink`` —
    гонка по inode; лок умершего держателя снимает ОС).
    Ошибка: лок не взят за ``timeout`` секунд → ``RecipeLockTimeout``, дескриптор закрыт.
    Нереентерабелен: второй вход того же процесса на тот же путь ждёт сам себя до таймаута —
    брать лок один раз, на внешнем публичном методе.
``RecipeLockTimeout(TimeoutError)`` — поля ``path`` (lock-файл), ``timeout``; подкласс
    ``OSError``, сервис рецептов отдаёт его как ``io_error``.

Механизм: stdlib, без зависимостей. Windows — ``msvcrt.locking(LK_NBLCK)`` на байте 0;
POSIX — ``fcntl.flock(LOCK_EX | LOCK_NB)``. Обе ветки — неблокирующие попытки в цикле до
дедлайна по ``time.monotonic()``.

Stability
---------
lite-контракт, внутренний для ``recipe``: сигнатура и имя lock-файла стабильны (``*.yaml.lock``
в ``.gitignore``). Общий лок-утиль фреймворка — открытый вопрос (Task 1.3).
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

__all__ = ["RecipeLockTimeout", "recipe_file_lock"]

_POLL_S = 0.02


class RecipeLockTimeout(TimeoutError):
    """Межпроцессный лок рецепта не взят за ``timeout`` секунд."""

    def __init__(self, path: Path, timeout: float) -> None:
        super().__init__(f"межпроцессный лок рецепта '{path}' не взят за {timeout} с")
        self.path = path
        self.timeout = timeout


def _try_lock(fd: int) -> bool:
    """Одна неблокирующая попытка; ``True`` — лок взят."""
    try:
        if sys.platform == "win32":
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(fd: int) -> None:
    if sys.platform == "win32":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def recipe_file_lock(path: str | Path, *, timeout: float = 5.0) -> Iterator[None]:
    """Эксклюзивный межпроцессный лок рецепта ``path`` — см. докстринг модуля."""
    lock_path = Path(path).with_name(Path(path).name + ".lock")
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        deadline = time.monotonic() + timeout
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                raise RecipeLockTimeout(lock_path, timeout)
            time.sleep(_POLL_S)
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)
