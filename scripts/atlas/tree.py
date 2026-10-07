"""Дерево ревизии git: список файлов, чтение, распаковка во временный каталог (Task 1.2).

Purpose: сборка читает ревизию (ref), а не рабочий каталог; git вызывается подпроцессом.
Public API: AtlasError, Tree, git, git_z, resolve, run_git.
Stability: lite
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

__all__ = ["AtlasError", "Tree", "git", "git_z", "resolve", "run_git"]


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


def git_z(root: str | Path, *args: str) -> list[str]:
    """Stdout git с разделителем NUL (`-z`), без хвостовой пустой записи."""
    proc = run_git(root, *args)
    if proc.returncode != 0:
        raise AtlasError(f"atlas: git {' '.join(args)} failed: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return [item.decode("utf-8") for item in proc.stdout.split(b"\0") if item]


def resolve(root: str | Path, ref: str) -> str:
    """SHA коммита по пользовательскому ref; нет такого коммита, опция или диапазон -> AtlasError."""
    proc = run_git(root, "rev-parse", "--verify", "-q", "--end-of-options", f"{ref}^{{commit}}")
    if proc.returncode != 0:
        raise AtlasError(f"atlas: ref not found: {ref}")
    return proc.stdout.decode("utf-8").strip()


class Tree:
    """Дерево коммита `ref` репозитория `root`."""

    def __init__(self, root: str | Path, ref: str) -> None:
        self.root = Path(root)
        self.ref = ref
        self._files: list[str] | None = None

    def files(self) -> list[str]:
        if self._files is None:
            self._files = git_z(self.root, "ls-tree", "-r", "--name-only", "-z", self.ref)
        return list(self._files)

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
