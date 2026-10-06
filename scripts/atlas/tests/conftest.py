"""Общие фикстуры приёмочных тестов ядра scripts/atlas (Task 1.2, RED).

Purpose: временный git-репозиторий, запуск main() в потоке с дедлайном,
    тестовые адаптеры (маркерный, счётчик, фиксированный). Ядро и схема
    импортируются ВНУТРИ функций, чтобы отсутствие кода давало красный на
    каждом тесте, а не одну ошибку сбора.
Public API: GitRepo, RepoFactory, Result, MarkerAdapter, CountingAdapter,
    FixedAdapter, run_with_deadline; фикстуры repo_factory, repo, atlas,
    set_adapters.
Stability: lite

Маркерный адаптер читает из дерева сборки строки `@@finding <severity> <code>
<node> [<detail>]` в файлах `.md` и `.py`; `{path}` в `<node>` заменяется путём
файла — так находка «переезжает» вместе с файлом при `git mv`.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest

__all__ = [
    "CountingAdapter",
    "FixedAdapter",
    "GitRepo",
    "MarkerAdapter",
    "RepoFactory",
    "Result",
    "run_with_deadline",
]

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DEADLINE_S = 60.0


def run_with_deadline(fn: Callable[[], Any], seconds: float = DEADLINE_S) -> Any:
    """Выполнить fn в daemon-потоке; не уложился в дедлайн — pytest.fail."""
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - пробрасываем в основной поток
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        pytest.fail(f"вызов завис: нет ответа за {seconds} с")
    if "error" in box:
        raise box["error"]
    return box.get("value")


class GitRepo:
    """Временный git-репозиторий; все вызовы git идут через дедлайн."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def git(self, *args: str) -> str:
        def call() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["git", *args],
                cwd=self.path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

        proc = run_with_deadline(call)
        assert proc.returncode == 0, f"git {' '.join(args)} -> {proc.returncode}: {proc.stderr}"
        return proc.stdout.strip()

    def write(self, rel: str, text: str) -> None:
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def commit(self, message: str) -> str:
        self.git("add", ".")
        self.git("commit", "-q", "-m", message)
        return self.head

    @property
    def head(self) -> str:
        return self.git("rev-parse", "HEAD")


class RepoFactory:
    """Создаёт репозитории под одним tmp_path."""

    def __init__(self, base: Path) -> None:
        self.base = base

    def create(self, name: str) -> GitRepo:
        path = self.base / name
        path.mkdir(parents=True)
        repo = GitRepo(path)
        repo.git("init", "-q", "-b", "main")
        repo.git("config", "user.name", "Atlas Test")
        repo.git("config", "user.email", "atlas@example.invalid")
        repo.git("config", "commit.gpgsign", "false")
        return repo

    def clone_shallow(self, src: GitRepo, name: str) -> GitRepo:
        dest = self.base / name
        # file:// — иначе локальный путь молча игнорирует --depth
        url = f"file://{src.path}"

        def call() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["git", "clone", "-q", "--depth", "1", url, str(dest)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

        proc = run_with_deadline(call)
        assert proc.returncode == 0, f"git clone --depth 1 -> {proc.returncode}: {proc.stderr}"
        return GitRepo(dest)


@dataclass(frozen=True)
class Result:
    code: Any
    out: str
    err: str


@pytest.fixture
def repo_factory(tmp_path: Path) -> RepoFactory:
    return RepoFactory(tmp_path)


@pytest.fixture
def repo(repo_factory: RepoFactory) -> GitRepo:
    return repo_factory.create("repo")


@pytest.fixture
def atlas(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    """atlas(repo, *argv, cwd=None) -> Result: main(argv) с cwd = репозиторий (или cwd), в потоке с дедлайном."""

    def run(target: GitRepo, *argv: str, cwd: Path | None = None) -> Result:
        monkeypatch.chdir(cwd or target.path)
        capsys.readouterr()

        def call() -> Any:
            from scripts.atlas.__main__ import main

            try:
                return main(list(argv))
            except SystemExit as exc:
                return exc.code if isinstance(exc.code, int) else 1

        code = run_with_deadline(call)
        captured = capsys.readouterr()
        return Result(code, captured.out, captured.err)

    return run


@pytest.fixture
def set_adapters(monkeypatch: pytest.MonkeyPatch):
    def apply(*adapters: Any) -> None:
        monkeypatch.setattr("scripts.atlas.build.ADAPTERS", tuple(adapters))

    return apply


class MarkerAdapter:
    """Находки по маркерам `@@finding` в файлах дерева сборки."""

    name = "marker"
    version = 1

    def collect(self, ctx: Any) -> Any:
        from scripts.atlas.schema import AdapterOutput, Finding, Node

        nodes: list[Any] = []
        findings: list[Any] = []
        for path in ctx.tree.files():
            if not path.endswith((".md", ".py")):
                continue
            for line in ctx.tree.read(path).decode("utf-8").splitlines():
                start = line.find("@@finding ")
                if start < 0:
                    continue
                parts = line[start:].split(" ", 4)
                severity, code, node = parts[1], parts[2], parts[3]
                detail = parts[4] if len(parts) > 4 else ""
                if "{path}" in node:
                    node = node.replace("{path}", path)
                    kind, _, ident = node.partition(":")
                    nodes.append(Node(kind=kind, id=ident, path=path, status=None, time=None))
                findings.append(
                    Finding(
                        code=code,
                        severity=severity,
                        node=node,
                        detail=detail,
                        message=f"{code} on {node}",
                        source=path,
                    )
                )
        return AdapterOutput(nodes=nodes, edges=[], findings=findings)


class CountingAdapter:
    """Считает вызовы collect(); отдаёт один узел модуля."""

    name = "counting"
    version = 1

    def __init__(self) -> None:
        self.calls = 0

    def collect(self, ctx: Any) -> Any:
        from scripts.atlas.schema import AdapterOutput, Node

        self.calls += 1
        node = Node(kind="module", id="m", path="m", status=None, time=None)
        return AdapterOutput(nodes=[node], edges=[], findings=[])


class FixedAdapter:
    """Отдаёт заранее заданный AdapterOutput (фабрика вызывается внутри collect)."""

    def __init__(self, factory: Callable[[], Any], name: str = "fixed", version: int = 1) -> None:
        self.name = name
        self.version = version
        self._factory = factory

    def collect(self, ctx: Any) -> Any:
        return self._factory()
