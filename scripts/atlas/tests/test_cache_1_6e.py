"""Слепые приёмочные тесты кэша ref/card по ревизии и LF в выводе CLI (Task 1.6e, RED до кода).

Purpose: `ref` и `card` считаются лениво на первом вызове ревизии и кладутся в SQLite Атласа; повторный вызов
    читает кэш: ни checkout (tar -> диск), ни grimp.build_graph. Кэш сбрасывается сменой ревизии и кода Атласа
    (build.CORE_VERSION), не смешивает модули, не хранит ошибки. `build` кэш ref/card не считает. Вывод CLI с LF.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Счётчики стоят только на сторонних/stdlib вызовах: grimp.build_graph, tarfile.open, TarFile.extractall,
subprocess.run с `git archive`. Это наблюдаемый эффект «работа не сделана». Каждый счётчик проверяется и с
другой стороны: первый вызов на холодной ревизии обязан дать build_graph >= 1 и checkout >= 1 (иначе перехват
не сработал и нули повторных вызовов ничего не доказывали). Вызовы main() идут через conftest.atlas (дедлайн-поток),
процессы CLI — через run_with_deadline. Ожидаемые значения — литералы.

Окружение: тесты ref/card требуют griffe (в pyproject.toml он есть). Если в .venv его нет, ВСЕ тесты ref/card
красные по ModuleNotFoundError, а не по отсутствию кэша — сначала поставь griffe.
"""

from __future__ import annotations

import os
import sqlite3
import statistics
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, RepoFactory, run_with_deadline

__all__: list[str] = []

_ROOT = Path(__file__).resolve().parents[3]
_REFS = ("--ref", "main", "--main-ref", "main")
_MODULES_YAML = """\
version: 1
modules:
  - id: m
    paths: ["m/"]
    layer: scripts
    tier: core
    docs: []
    parent: null
  - id: n
    paths: ["n/"]
    layer: scripts
    tier: null
    docs: []
    parent: null
"""
_IFACE_M = '''\
"""Интерфейсы m."""


class Alpha:
    """Контракт альфа. Второе предложение не показывается."""

    def send(self, message: str, priority: str = "normal") -> None:
        """Отправить сообщение.

        Pre:
          - message не пустое.
        """
'''
_IFACE_N = '''\
"""Интерфейсы n."""


class Beta:
    """Контракт бета."""

    def receive(self, key: str) -> str:
        """Принять ключ."""
'''
_CORE = '''\
"""Реализация."""


def helper(x: int) -> int:
    return x + 1
'''


# ---------------------------------------------------------------- хелперы


def _new_repo(factory: RepoFactory, name: str, extra_files: int = 0) -> GitRepo:
    repo = factory.create(name)
    exclude = repo.path / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("data/\n", encoding="utf-8")
    repo.write("modules.yaml", _MODULES_YAML)
    repo.write("m/__init__.py", "")
    repo.write("m/interfaces.py", _IFACE_M)
    repo.write("m/core.py", _CORE)
    repo.write("n/__init__.py", "")
    repo.write("n/interfaces.py", _IFACE_N)
    repo.write("n/core.py", _CORE)
    for i in range(extra_files):
        repo.write(
            f"m/part_{i:02d}.py",
            f'"""Часть {i}."""\n\nfrom m.core import helper\n\n\ndef f_{i}(x: int) -> int:\n    return helper(x)\n',
        )
    repo.commit("init")
    return repo


class _Spy:
    """Счётчики стороннего/stdlib «тяжёлого» кода."""

    def __init__(self) -> None:
        self.build_graph = 0
        self.tar_open = 0
        self.extract = 0
        self.archive = 0

    @property
    def checkout(self) -> int:
        return self.tar_open + self.extract + self.archive

    def reset(self) -> None:
        self.build_graph = self.tar_open = self.extract = self.archive = 0


def _install_spy(mp: pytest.MonkeyPatch) -> _Spy:
    import grimp

    spy = _Spy()
    orig_bg = grimp.build_graph

    def bg(*args: Any, **kwargs: Any) -> Any:
        spy.build_graph += 1
        return orig_bg(*args, **kwargs)

    mp.setattr(grimp, "build_graph", bg)
    # если Атлас сделал `from grimp import build_graph` — подменяем и там, где имя уже связано
    for name, mod in list(sys.modules.items()):
        if name.startswith("scripts.atlas") and getattr(mod, "build_graph", None) is orig_bg:
            mp.setattr(mod, "build_graph", bg)

    orig_open = tarfile.open

    def topen(*args: Any, **kwargs: Any) -> Any:
        spy.tar_open += 1
        return orig_open(*args, **kwargs)

    mp.setattr(tarfile, "open", topen)

    orig_extract = tarfile.TarFile.extractall

    def extract(self: Any, *args: Any, **kwargs: Any) -> Any:
        spy.extract += 1
        return orig_extract(self, *args, **kwargs)

    mp.setattr(tarfile.TarFile, "extractall", extract)

    orig_run = subprocess.run

    def run(cmd: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(cmd, (list, tuple)) and "archive" in cmd:
            spy.archive += 1
        return orig_run(cmd, *args, **kwargs)

    mp.setattr(subprocess, "run", run)
    return spy


def _call(atlas: Any, spy: _Spy, repo: GitRepo, *argv: str) -> tuple[Any, dict[str, int]]:
    """Вызов main() со сброшенными счётчиками; возвращает (Result, снимок счётчиков)."""
    spy.reset()
    res = atlas(repo, *argv)
    return res, {"build_graph": spy.build_graph, "checkout": spy.checkout}


def _rows(repo: GitRepo) -> int:
    """Суммарное число строк по ВСЕМ таблицам базы Атласа (кэш может лежать в любой, в том числе новой)."""
    db = repo.path / "data" / "atlas.sqlite"
    if not db.exists():
        return 0
    con = sqlite3.connect(db)
    try:
        tables = [
            r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        ]
        return sum(int(con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]) for t in tables)
    finally:
        con.close()


def _cli(repo: GitRepo, *argv: str) -> Any:
    """Процесс `python -m scripts.atlas` с захватом байтов; PYTHONUTF8 не задаём: LF и UTF-8 — дело самого CLI."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    env["PYTHONPATH"] = os.pathsep.join([str(_ROOT), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    return run_with_deadline(
        lambda: subprocess.run(
            [sys.executable, "-m", "scripts.atlas", *argv], cwd=repo.path, env=env, capture_output=True, check=False
        ),
        seconds=120,
    )


# ---------------------------------------------------------------- A1


def test_second_ref_and_card_do_no_checkout_and_no_build_graph(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _new_repo(repo_factory, "a1")
    spy = _install_spy(monkeypatch)
    for argv in (("ref", "m", *_REFS), ("card", "m", *_REFS)):
        first, cold = _call(atlas, spy, repo, *argv)
        assert first.code == 0, first.err
        # контроль перехвата: холодный вызов обязан делать работу (зелёный и до правки — это не дыра)
        assert cold["build_graph"] >= 1, f"{argv[0]}: перехват grimp.build_graph не сработал"
        assert cold["checkout"] >= 1, f"{argv[0]}: перехват checkout не сработал"
        second, warm = _call(atlas, spy, repo, *argv)
        assert second.code == 0, second.err
        # RED до кэша: сейчас каждый вызов заново выгружает ревизию и строит граф
        assert warm == {"build_graph": 0, "checkout": 0}, f"{argv[0]}: повторный вызов не из кэша: {warm}"


# ---------------------------------------------------------------- A2


@pytest.mark.parametrize(
    "argv",
    [("ref", "m"), ("card", "m"), ("ref", "m", "--symbol", "Alpha")],
    ids=["ref", "card", "ref-symbol"],
)
def test_cached_output_is_byte_equal_to_first(repo_factory: RepoFactory, atlas: Any, argv: tuple[str, ...]) -> None:
    # Может быть зелёным и до правки (оба вызова считают заново): ловит расхождение кэша с расчётом, не его отсутствие.
    repo = _new_repo(repo_factory, "a2")
    first = atlas(repo, *argv, *_REFS)
    assert first.code == 0, first.err
    assert first.out != ""
    second = atlas(repo, *argv, *_REFS)
    assert second.code == 0
    assert second.out.encode("utf-8") == first.out.encode("utf-8")
    assert second.err == first.err == ""


# ---------------------------------------------------------------- A3


def test_new_commit_invalidates_and_old_sha_stays_cached(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _new_repo(repo_factory, "a3")
    spy = _install_spy(monkeypatch)
    old_sha = repo.head
    old, _ = _call(atlas, spy, repo, "ref", "m", *_REFS)
    assert old.code == 0, old.err
    assert "Gamma" not in old.out
    _call(atlas, spy, repo, "ref", "m", *_REFS)  # прогрев кэша старой ревизии

    repo.write("m/interfaces.py", _IFACE_M + '\n\nclass Gamma:\n    """Контракт гамма."""\n')
    repo.commit("add Gamma")

    new, cold = _call(atlas, spy, repo, "ref", "m", *_REFS)
    assert new.code == 0, new.err
    assert cold["build_graph"] >= 1, "новая ревизия не должна браться из кэша старой"
    assert "Gamma" in new.out and new.out != old.out

    pinned, warm = _call(atlas, spy, repo, "ref", "m", "--ref", old_sha, "--main-ref", "main")
    assert pinned.code == 0, pinned.err
    assert pinned.out == old.out
    # RED до кэша: старая ревизия обязана читаться из кэша, а не пересчитываться
    assert warm == {"build_graph": 0, "checkout": 0}, f"старый sha не из кэша: {warm}"


# ---------------------------------------------------------------- A4


def test_core_version_change_invalidates_cache(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _new_repo(repo_factory, "a4")
    spy = _install_spy(monkeypatch)
    first, _ = _call(atlas, spy, repo, "ref", "m", *_REFS)
    assert first.code == 0, first.err
    _, warm = _call(atlas, spy, repo, "ref", "m", *_REFS)
    assert warm["build_graph"] == 0, "предусловие: до смены CORE_VERSION кэш должен работать"  # RED до кэша

    from scripts.atlas import build

    # build.fingerprint() читает глобал CORE_VERSION при каждом вызове (build.py: parts = [CORE_VERSION, ...])
    monkeypatch.setattr(build, "CORE_VERSION", "test-1.6e-other")
    again, cold = _call(atlas, spy, repo, "ref", "m", *_REFS)
    assert again.code == 0, again.err
    assert cold["build_graph"] >= 1, "смена кода Атласа обязана сбросить кэш"
    assert again.out == first.out


# ---------------------------------------------------------------- A5


def test_two_modules_on_one_revision_do_not_mix(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _new_repo(repo_factory, "a5")
    spy = _install_spy(monkeypatch)
    first = {}
    for mod in ("m", "n"):
        for cmd in ("ref", "card"):
            res, _ = _call(atlas, spy, repo, cmd, mod, *_REFS)
            assert res.code == 0, res.err
            first[cmd, mod] = res.out
    assert first["ref", "m"] != first["ref", "n"]
    assert first["card", "m"] != first["card", "n"]
    assert "Alpha" in first["ref", "m"] and "Beta" not in first["ref", "m"]
    assert "Beta" in first["ref", "n"] and "Alpha" not in first["ref", "n"]
    for mod in ("m", "n"):
        for cmd in ("ref", "card"):
            again, _ = _call(atlas, spy, repo, cmd, mod, *_REFS)
            assert again.out == first[cmd, mod], f"{cmd} {mod}: повтор отдал чужой или иной вывод"


# ---------------------------------------------------------------- A6


@pytest.mark.parametrize(
    "argv",
    [("ref", "m"), ("card", "m"), ("pack", "nosuch#1", "--module", "m"), ("index",), ("build",)],
    ids=["ref", "card", "pack", "index", "build"],
)
def test_cli_stdout_has_lf_only_and_utf8(repo_factory: RepoFactory, argv: tuple[str, ...]) -> None:
    # На Linux это зелёное и до правки: print уже пишет LF. Дыра ожидаемая — CRLF проявляется только на Windows
    # (stdout в текстовом режиме переводит \n в \r\n); здесь тест стережёт контракт, а не ловит текущий дефект.
    # Для pack задача заведомо не найдена: код выхода не проверяем, байты stdout (пусть пустые) — да.
    repo = _new_repo(repo_factory, "a6")
    proc = _cli(repo, *argv, *_REFS)
    assert b"\r\n" not in proc.stdout
    assert b"\r" not in proc.stdout
    if argv[0] in ("ref", "card"):
        assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
        text = proc.stdout.decode("utf-8")  # строгая декодировка: не UTF-8 -> UnicodeDecodeError
        assert "Контракт альфа" in text if argv[0] == "ref" else "m" in text


# ---------------------------------------------------------------- A7


def test_cached_ref_median_under_half_second(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "a7", extra_files=28)
    warmup = atlas(repo, "ref", "m", *_REFS)  # первый вызов считает и кладёт кэш; не измеряется
    assert warmup.code == 0, warmup.err
    samples = []
    for _ in range(5):
        start = time.perf_counter()
        res = atlas(repo, "ref", "m", *_REFS)
        samples.append(time.perf_counter() - start)
        assert res.code == 0, res.err
    median = statistics.median(samples)
    # Порог 0,5 с не ослаблять. ВНИМАНИЕ: на этом малом репо расчёт без кэша тоже укладывается в порог, поэтому
    # тест зелёный и до правки (красным быть не мог); отсутствие кэша ловят A1/A3/A4/A8, здесь страж скорости.
    assert median <= 0.5, f"медиана {median:.3f} с > 0,5 с; пробы: {[round(s, 3) for s in samples]}"


# ---------------------------------------------------------------- A8


def test_cache_lives_in_atlas_db_and_is_lazy(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "a8")
    built = atlas(repo, "build", *_REFS)
    assert built.code == 0, built.err
    after_build = _rows(repo)
    assert after_build > 0, "build должен записать реестр"

    first = atlas(repo, "ref", "m", *_REFS)
    assert first.code == 0, first.err
    after_ref = _rows(repo)
    # RED до кэша: холодный build кэш ref/card не считает, первый ref кладёт его в базу
    assert after_ref > after_build, f"кэш ref не появился в базе: {after_build} -> {after_ref}"

    again = atlas(repo, "ref", "m", *_REFS)
    assert again.code == 0, again.err
    assert _rows(repo) == after_ref, "повторный ref не должен добавлять строк"


# ---------------------------------------------------------------- A9


def test_error_is_not_cached(repo_factory: RepoFactory, atlas: Any) -> None:
    repo = _new_repo(repo_factory, "a9")
    bad1 = atlas(repo, "ref", "nosuch", *_REFS)
    assert (bad1.code, bad1.out, bad1.err) == (2, "", "atlas: module not found\n")
    rows_after_first_error = _rows(repo)
    bad2 = atlas(repo, "ref", "nosuch", *_REFS)
    assert (bad2.code, bad2.out, bad2.err) == (2, "", "atlas: module not found\n")
    assert _rows(repo) == rows_after_first_error, "ошибка не должна оставлять записей в базе"
    good = atlas(repo, "ref", "m", *_REFS)
    assert good.code == 0, good.err
    assert "Alpha" in good.out
    # ошибка card для неизвестного модуля тоже не ломает последующий валидный вызов
    bad_card = atlas(repo, "card", "nosuch", *_REFS)
    assert bad_card.code == 2 and bad_card.out == ""
    assert atlas(repo, "ref", "m", *_REFS).out == good.out
