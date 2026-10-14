"""Хранилище данных робота на диске: оптимистичная ревизия и атомарная запись (T5.2).

Purpose:
    Документы робота по ``device_id``: ``<root>/<device_id>/{params,points,frames,calibration}.yaml`` и
    ``<root>/<device_id>/programs/<имя>.yaml``. Запись принимает ревизию, с которой клиент читал, и при
    расхождении отказывает (``RevisionConflict``), а не затирает чужую правку (образец —
    ``recipe.save``). Файл заменяется атомарно: временный файл в том же каталоге + замена.
    Библиотека: процессов, IPC, команд хаба и GUI здесь нет. Схемы содержимого хранилище не знает.

Public API:
    ``DOCS``, ``StoredDoc(body, rev)``, ``compute_rev(raw)``,
    ``RobotDataStore(root)``: ``read``, ``write``, ``read_program``, ``write_program``, ``list_programs``.
    Ошибки — ``Services.robot_comm.errors``: ``RevisionConflict``, ``InvalidStoreKey``, ``StoreDocumentInvalid``.

Stability: lite (новый модуль без Protocol-интерфейса; контракт держат ``Pre:``/``Post:`` методов и тесты).

Test seam:
    Модульная функция ``_replace_file(src, dst)``. Хранилище зовёт её ТОЛЬКО по имени модуля в момент
    вызова (каждая попытка — новый поиск имени): тест подменяет ``monkeypatch.setattr(store, "_replace_file", fake)``.
    Раннюю привязку (поле экземпляра, умолчание аргумента, ``from os import replace``) делать нельзя.

Гарантии потоков:
    ОДИН экземпляр ``RobotDataStore`` в одном процессе, любое число потоков. Два экземпляра на один ``root``
    и два процесса-писателя НЕ поддерживаются (решение владельца В2). Потоков хранилище не создаёт.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from Services.robot_comm.errors import InvalidStoreKey, RevisionConflict, StoreDocumentInvalid

__all__ = ["DOCS", "RobotDataStore", "StoredDoc", "compute_rev"]

log = logging.getLogger(__name__)

DOCS = ("params", "points", "frames", "calibration")

_DEVICE_RE = re.compile(r"[a-z0-9_]{1,64}")
_PROGRAM_RE = re.compile(r"\w(?:[\w.\- ]*\w)?")
_PROGRAM_MAX_LEN = 64
_SUFFIX = ".yaml"
# Зарезервированные имена устройств Windows (как ``ntpath.isreserved`` в 3.13; в 3.12 его нет).
# ``Path.resolve()`` устройства не распознаёт, поэтому вторая линия защиты их НЕ ловит.
_RESERVED = frozenset({"con", "prn", "aux", "nul"} | {p + c for p in ("com", "lpt") for c in "123456789¹²³"})
# Паузы повтора замены при PermissionError (Windows: цель открыта антивирусом/редактором), сумма 1.55 с.
_REPLACE_PAUSES = (0.05, 0.1, 0.2, 0.4, 0.8)


def compute_rev(raw: bytes) -> str:
    """Ревизия документа: ``sha256(байты).hexdigest()``. Клиент сравнивает её только на равенство."""
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class StoredDoc:
    """Прочитанный документ: ``body`` и ``rev`` равны None, когда файла нет."""

    body: dict | None
    rev: str | None


def _replace_file(src: str, dst: str) -> None:
    """Шов теста: атомарная замена ``dst`` файлом ``src``."""
    os.replace(src, dst)


def _replace_with_retry(src: str, dst: str) -> None:
    """Заменить ``dst`` на ``src``; ``PermissionError`` повторяется по ``_REPLACE_PAUSES``.

    Каждая попытка — новый вызов ``_replace_file`` по имени модуля. После последней паузы — одна попытка
    без перехвата: стойкая блокировка поднимает исходный ``PermissionError``. Прочие ``OSError`` не повторяются.
    """
    for pause in _REPLACE_PAUSES:
        try:
            _replace_file(src, dst)
            return
        except PermissionError:
            log.warning("robot_comm.store: замена %s отклонена (PermissionError), повтор через %s с", dst, pause)
            time.sleep(pause)
    _replace_file(src, dst)


def _atomic_write(path: Path, data: bytes) -> None:
    """Записать ``data`` в ``path``: tmp рядом с целью -> fsync -> замена. При сбое tmp удаляется, ошибка — наружу."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        _replace_with_retry(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            log.warning("robot_comm.store: не удалось удалить временный файл %s", tmp, exc_info=True)
        raise


def _is_reserved(name: str) -> bool:
    return name.partition(".")[0].rstrip(" ").lower() in _RESERVED


def _dump(body: object) -> bytes:
    """Сериализовать тело записи; не словарь или не сериализуется -> ``StoreDocumentInvalid(rev=None)``."""
    if not isinstance(body, dict):
        raise StoreDocumentInvalid(None)
    try:
        return yaml.safe_dump(body, sort_keys=False, allow_unicode=True).encode("utf-8")
    except yaml.YAMLError as exc:
        raise StoreDocumentInvalid(None) from exc


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


class RobotDataStore:
    """Документы робота по ``device_id`` с ревизией байтов и атомарной заменой файла.

    ``root`` — каталог ``data/robot`` целиком. Конструктор только запоминает путь: env не читает, ничего не создаёт.
    Раскладка: ``root/<device_id>/<doc>.yaml``, ``root/<device_id>/programs/<имя>.yaml``.

    Потоки: один экземпляр на ``root`` в одном процессе, любое число потоков (замок на документ). Два экземпляра
    на один ``root`` или два процесса НЕ гарантируются. ``read``/``read_program`` берут замок документа, поэтому
    могут ждать до ~1.6 с, пока запись повторяет замену при ``PermissionError``.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root)
        self._locks: dict[tuple[str, str], threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ------------------------------------------------------------------ #
    # ключи и пути
    # ------------------------------------------------------------------ #

    def _doc_lock(self, device_id: str, rel: str) -> threading.Lock:
        """Замок документа; ключ по ``casefold``: на Windows ``Prog.yaml`` и ``prog.yaml`` — один файл."""
        key = (device_id, rel.casefold())
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = self._locks[key] = threading.Lock()
            return lock

    def _check_device(self, device_id: object) -> str:
        if not isinstance(device_id, str) or not _DEVICE_RE.fullmatch(device_id) or _is_reserved(device_id):
            raise InvalidStoreKey(device_id)
        root = self._root.resolve()
        if (root / device_id).resolve().parent != root:
            raise InvalidStoreKey(device_id)
        return device_id

    def _doc_path(self, device_id: object, doc: object) -> tuple[str, str, Path]:
        """``(device_id, rel, путь)`` документа; отказ — ``InvalidStoreKey`` до обращения к диску."""
        dev = self._check_device(device_id)
        if not isinstance(doc, str) or doc not in DOCS:
            raise InvalidStoreKey(doc)
        rel = f"{doc}{_SUFFIX}"
        return dev, rel, self._root / dev / rel

    def _program_path(self, device_id: object, name: object) -> tuple[str, str, Path]:
        """``(device_id, rel, путь)`` программы; отказ — ``InvalidStoreKey`` до обращения к диску."""
        dev = self._check_device(device_id)
        if (
            not isinstance(name, str)
            or len(name) > _PROGRAM_MAX_LEN
            or not _PROGRAM_RE.fullmatch(name)
            or _is_reserved(name)
        ):
            raise InvalidStoreKey(name)
        expected_dir = self._root.resolve() / dev / "programs"
        if (expected_dir / f"{name}{_SUFFIX}").resolve().parent != expected_dir:
            raise InvalidStoreKey(name)
        rel = f"programs/{name}{_SUFFIX}"
        return dev, rel, self._root / dev / "programs" / f"{name}{_SUFFIX}"

    # ------------------------------------------------------------------ #
    # чтение и запись одного файла
    # ------------------------------------------------------------------ #

    def _read(self, dev: str, rel: str, path: Path) -> StoredDoc:
        with self._doc_lock(dev, rel):
            raw = _read_bytes(path)
        if raw is None:
            return StoredDoc(None, None)
        rev = compute_rev(raw)
        try:
            body = yaml.safe_load(raw)
        except (yaml.YAMLError, ValueError) as exc:
            raise StoreDocumentInvalid(rev) from exc
        if not isinstance(body, dict):
            raise StoreDocumentInvalid(rev)
        return StoredDoc(body, rev)

    def _write(self, dev: str, rel: str, path: Path, body: dict[str, Any], base_rev: str | None) -> str:
        data = _dump(body)  # до замка: сериализация не держит документ
        with self._doc_lock(dev, rel):
            raw = _read_bytes(path)
            current_rev = None if raw is None else compute_rev(raw)
            if base_rev != current_rev:
                raise RevisionConflict(current_rev)
            _atomic_write(path, data)
        return compute_rev(data)

    # ------------------------------------------------------------------ #
    # публичный API
    # ------------------------------------------------------------------ #

    def read(self, device_id: str, doc: str) -> StoredDoc:
        """Прочитать документ устройства.

        Pre: ``device_id`` — ``[a-z0-9_]{1,64}``, не имя устройства Windows; ``doc`` ∈ ``DOCS``.
        Post: диск не меняется (каталоги не создаются); файла нет -> ``StoredDoc(None, None)``; иначе
        ``StoredDoc(body, rev)``, ``rev`` — sha256 байтов на диске сейчас. Может ждать до ~1.6 с, пока запись
        этого же документа повторяет замену (``read`` берёт замок документа).
        Raises: ``InvalidStoreKey`` (до обращения к диску); ``StoreDocumentInvalid(rev)`` — файл не YAML-словарь
        (пустой тоже), ``rev`` — ревизия этих байтов.
        """
        return self._read(*self._doc_path(device_id, doc))

    def write(self, device_id: str, doc: str, body: dict[str, Any], *, base_rev: str | None) -> str:
        """Записать документ, если на диске всё ещё ревизия ``base_rev``.

        Pre: ключи как у ``read``; ``body`` — ``dict``, сериализуемый ``yaml.safe_dump``; ``base_rev`` — ревизия,
        с которой клиент читал, либо None (создание: файла быть не должно). Из двух ``write`` с одной ``base_rev``
        успешен ровно один. Экземпляр один на ``root`` в процессе (иначе гарантия не действует).
        Post: успех -> файл заменён атомарно, возвращена ``compute_rev`` новых байтов, временных файлов нет.
        Отказ -> старые байты на месте и временных файлов нет; при ``RevisionConflict`` каталоги не создаются.
        Raises: ``InvalidStoreKey``; ``StoreDocumentInvalid(None)`` — ``body`` не словарь или не сериализуется
        (диск не тронут); ``RevisionConflict(current_rev)`` — ``base_rev`` не равна текущей ревизии (None, если
        файла нет); ``OSError`` — сбой записи/замены, не оборачивается (``PermissionError`` на замене
        повторяется ~1.6 с).
        """
        dev, rel, path = self._doc_path(device_id, doc)
        return self._write(dev, rel, path, body, base_rev)

    def read_program(self, device_id: str, name: str) -> StoredDoc:
        """Прочитать программу устройства.

        Pre: ``device_id`` как у ``read``; ``name`` — ``\\w(?:[\\w.\\- ]*\\w)?`` длиной ≤ 64, не имя устройства
        Windows. Регистр не нормализуется: на Windows ``Prog`` и ``prog`` — один файл.
        Post: как у ``read``. Raises: ``InvalidStoreKey``, ``StoreDocumentInvalid(rev)``.
        """
        return self._read(*self._program_path(device_id, name))

    def write_program(self, device_id: str, name: str, body: dict[str, Any], *, base_rev: str | None) -> str:
        """Записать программу устройства (семантика ``write``).

        Pre: ключи как у ``read_program``, остальное как у ``write``. Замок общий для имён, равных по
        ``casefold``: два одновременных создания ``Prog``/``prog`` -> успешно одно, второе ``RevisionConflict``.
        Post/Raises: как у ``write``; каталог ``programs`` создаётся при успешной записи.
        """
        dev, rel, path = self._program_path(device_id, name)
        return self._write(dev, rel, path, body, base_rev)

    def list_programs(self, device_id: str) -> list[str]:
        """Имена программ устройства по возрастанию.

        Pre: ``device_id`` как у ``read``. Замка документа не берёт.
        Post: диск не меняется; только ``*.yaml``-файлы, имя которых проходит проверку ``read_program``
        (что перечислено, то открывается); застрявшие ``.<файл>.<случайное>.tmp`` и прочие файлы не видны;
        нет каталога -> ``[]``. Raises: ``InvalidStoreKey``.
        """
        dev = self._check_device(device_id)
        directory = self._root / dev / "programs"
        if not directory.is_dir():
            return []
        names: list[str] = []
        for entry in directory.iterdir():
            if not entry.name.endswith(_SUFFIX) or not entry.is_file():
                continue
            name = entry.name[: -len(_SUFFIX)]
            try:
                self._program_path(dev, name)
            except InvalidStoreKey:
                continue
            names.append(name)
        return sorted(names)
