"""Дерево ревизии git: список файлов, чтение, распаковка во временный каталог (Task 1.2).

Purpose: сборка читает ревизию (ref), а не рабочий каталог; git вызывается подпроцессом.
Public API: AtlasError, Tree, git, git_z, read_blobs, resolve, run_git.
    read_blobs — пакетное чтение блобов одним `git cat-file --batch`; Tree.oids() — oid блобов дерева,
    Tree.read_many() — то же чтение без исключения на отсутствующем файле. files() и oids() делят один `ls-tree`.
Stability: lite
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

__all__ = ["AtlasError", "Tree", "git", "git_z", "read_blobs", "resolve", "run_git"]


class AtlasError(Exception):
    """Ошибка окружения или ввода; CLI печатает текст в stderr и выходит с кодом 2."""


def run_git(root: str | Path, *args: str, input: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(root), *args], input=input, capture_output=True, check=False)


def git(root: str | Path, *args: str) -> str:
    """Stdout git без хвостовых пробелов; ненулевой код -> AtlasError."""
    proc = run_git(root, *args)
    if proc.returncode != 0:
        raise AtlasError(f"atlas: git {' '.join(args)} failed: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc.stdout.decode("utf-8").strip()


def git_z(root: str | Path, *args: str, skip_undecodable: bool = False) -> list[str]:
    """Stdout git с разделителем NUL (`-z`), без хвостовой пустой записи.

    Запись не в UTF-8 -> UnicodeDecodeError; `skip_undecodable=True` — запись пропускается, одна строка в stderr
    `atlas: пропущено N путей не в UTF-8`. Годится только там, где запись — целая строка (`ls-tree -r -z`):
    позиционный разбор токенов (`diff --name-status -z`) от пропуска сдвинулся бы.
    """
    proc = run_git(root, *args)
    if proc.returncode != 0:
        raise AtlasError(f"atlas: git {' '.join(args)} failed: {proc.stderr.decode('utf-8', 'replace').strip()}")
    items: list[str] = []
    skipped = 0
    for raw in filter(None, proc.stdout.split(b"\0")):
        try:
            items.append(raw.decode("utf-8"))
        except UnicodeDecodeError:
            if not skip_undecodable:
                raise
            skipped += 1
    if skipped:
        print(f"atlas: пропущено {skipped} путей не в UTF-8", file=sys.stderr)
    return items


def resolve(root: str | Path, ref: str) -> str:
    """SHA коммита по пользовательскому ref; нет такого коммита, опция или диапазон -> AtlasError."""
    proc = run_git(root, "rev-parse", "--verify", "-q", "--end-of-options", f"{ref}^{{commit}}")
    if proc.returncode != 0:
        raise AtlasError(f"atlas: ref not found: {ref}")
    return proc.stdout.decode("utf-8").strip()


def read_blobs(root: str | Path, ref: str, paths: list[str], strict: bool = True) -> dict[str, bytes | None]:
    """Содержимое `<ref>:<path>` одним `git cat-file --batch`; нет файла -> None (strict: AtlasError).

    Путь с переводом строки -> AtlasError: протокол cat-file построчный, перенос в пути сдвинул бы все
    следующие ответы. Усечённый вывод (длина блоба не равна заявленной) -> AtlasError. Пустой список -> {} без git.
    """
    if not paths:
        return {}
    if any("\n" in p for p in paths):
        raise AtlasError("atlas: path with a newline cannot be read by cat-file --batch")
    proc = run_git(root, "cat-file", "--batch", input="".join(f"{ref}:{p}\n" for p in paths).encode("utf-8"))
    out: dict[str, bytes | None] = {}
    pos = 0
    try:
        if proc.returncode != 0:
            raise ValueError
        for path in paths:
            end = proc.stdout.index(b"\n", pos)
            header, pos = proc.stdout[pos:end], end + 1
            out[path] = None
            if not header.endswith(b" missing"):  # путь с пробелом даёт заголовок из 3+ частей
                _, kind, size = header.split(b" ")
                if kind == b"blob":
                    blob = proc.stdout[pos : pos + int(size)]
                    if len(blob) != int(size):  # усечённый вывод при коде 0
                        raise ValueError
                    out[path] = blob
                pos += int(size) + 1
            if strict and out[path] is None:
                raise ValueError
    except ValueError:
        raise AtlasError("atlas: git cat-file failed") from None
    return out


class Tree:
    """Дерево коммита `ref` репозитория `root`."""

    def __init__(self, root: str | Path, ref: str) -> None:
        self.root = Path(root)
        self.ref = ref
        self._entries: list[tuple[str, str, str]] | None = None  # (режим, oid, путь) одного `ls-tree -r -z`

    def _ls(self) -> list[tuple[str, str, str]]:
        if self._entries is None:
            entries = []
            for item in git_z(self.root, "ls-tree", "-r", "-z", self.ref, skip_undecodable=True):
                meta, _, path = item.partition("\t")
                mode, _, oid = meta.split(" ")
                entries.append((mode, oid, path))
            self._entries = entries
        return self._entries

    def files(self) -> list[str]:
        """Все записи дерева, включая символьные ссылки и gitlink."""
        return [path for _, _, path in self._ls()]

    def oids(self) -> dict[str, str]:
        """{путь: oid блоба} только для обычных файлов (режим 100644/100755)."""
        return {path: oid for mode, oid, path in self._ls() if mode in ("100644", "100755")}

    def read_many(self, paths: Iterable[str]) -> dict[str, bytes | None]:
        """Содержимое файлов одним git-процессом; нет файла -> None, не исключение."""
        return read_blobs(self.root, self.ref, list(paths), strict=False)

    def read(self, path: str) -> bytes:
        """Содержимое файла в ревизии; нет файла -> FileNotFoundError."""
        proc = run_git(self.root, "cat-file", "--batch", input=f"{self.ref}:{path}\n".encode())
        header, _, rest = proc.stdout.partition(b"\n")
        parts = header.split(b" ")
        if len(parts) != 3 or parts[1] != b"blob":
            raise FileNotFoundError(f"{self.ref}:{path}")
        return rest[: int(parts[2])]

    @contextmanager
    def materialize(self, *paths: str) -> Iterator[Path]:
        """Распаковать ревизию (или только `paths`) во временный каталог; удаляется при выходе и при исключении.

        С `paths` вызывающий сам проверяет, что в дереве есть файл под ними: `git archive` иначе упадёт.
        """
        target = Path(tempfile.mkdtemp(prefix="atlas-"))
        try:
            # autocrlf=false: на Windows `git archive` иначе отдаёт CRLF, а read() — байты объекта (LF).
            proc = run_git(
                self.root,
                "-c",
                "core.autocrlf=false",
                "archive",
                "--format=tar",
                self.ref,
                *(["--", *paths] if paths else []),
            )
            if proc.returncode != 0:
                raise AtlasError(f"atlas: git archive {self.ref} failed: {proc.stderr.decode('utf-8', 'replace')}")
            with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
                tar.extractall(target, filter="data")
            yield target
        finally:
            shutil.rmtree(target, ignore_errors=True)
