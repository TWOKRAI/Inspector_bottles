"""Слепые приёмочные тесты скорости ref/card: tar, checkout на диске, Code в процессе (Task 1.6g, RED до кода).

Purpose: `atlas ref|card` распаковывает `.py` ревизии системным `tar` в `<repo>/data/atlas/checkout/<ключ>/` и
    оставляет каталог после процесса; хранится не более 3 каталогов (имена с `.` во временных не считаются,
    остаются новейшие). `tar` не подменяется `tarfile`, пока `tar` работает; нет `tar` или он упал -> `tarfile` и
    в stderr строка `fallback to tarfile` (плюс `rc=<n>`, если `tar` запускался и упал). Второй модуль той же
    ревизии в одном процессе берёт разобранную ревизию из памяти: ни `git archive`, ни `tarfile`, ни
    `grimp.build_graph`. `codemap.forget()` сбрасывает эту память (имитация нового процесса). Вывод `ref`/`card`
    байт-в-байт одинаков для тёплой и холодной ревизии.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Фикстуры и перехватчики общие с 1.6e (`_new_repo`, `_install_spy`, `_call`, `_REFS`), не переписаны. `checkout` в
снимке счётчиков = запуски `git archive` + `tarfile.open` + `TarFile.extractall`. Вызовы main() идут через
conftest.atlas (дедлайн-поток), процессы CLI — через run_with_deadline. Ожидаемые значения — литералы. Время не
проверяется (его меряет лид на живом дереве).

Причины RED до кода (`codemap.forget` ещё нет, `AttributeError` по нему — принятая причина):
  - test_tar_unpacks_without_tarfile_fallback: AssertionError("tarfile fallback used") (только Windows; на Linux
    GNU tar читает stdin с -C и тест зелёный по природе);
  - test_tar_failure_falls_back_with_warning: нет строки `fallback to tarfile` в stderr (AssertionError);
  - test_checkout_survives_the_process: нет каталога `data/atlas/checkout` (AssertionError);
  - test_checkout_keeps_three_revisions: нет нового каталога после первого вызова (AssertionError);
  - test_second_module_in_process_reuses_code: `card n` снова строит граф и выгружает ревизию (AssertionError);
  - test_warm_output_is_byte_equal_to_cold: ЗАЩИТА, зелёная до кода; до кода `codemap.forget()` в ней не нужен.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, RepoFactory, run_with_deadline
from scripts.atlas.tests.test_cache_1_6e import _REFS, _call, _install_spy, _new_repo

__all__: list[str] = []

_ROOT = Path(__file__).resolve().parents[3]
_NEW_CORE_VERSION = "test-1.6g"


# ---------------------------------------------------------------- хелперы


def _forget_if_present() -> None:
    """Сбросить память процесса, если `forget` уже есть: изоляция тестов без маскировки причины RED."""
    from scripts.atlas import codemap

    fn = getattr(codemap, "forget", None)
    if fn is not None:
        fn()


@pytest.fixture(autouse=True)
def _isolated_process_memory():
    _forget_if_present()
    yield
    _forget_if_present()


def _checkout_dir(repo: GitRepo) -> Path:
    return repo.path / "data" / "atlas" / "checkout"


def _entries(repo: GitRepo) -> list[str]:
    """Имена каталогов checkout без временных (с точки в начале); нет каталога -> пусто."""
    root = _checkout_dir(repo)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if not p.name.startswith("."))


def _proc(repo: GitRepo, *argv: str) -> Any:
    """Процесс `python -m scripts.atlas` с байтами в stdout/stderr; UTF-8 включён явно (как просил лид)."""
    env = dict(os.environ, PYTHONPATH=str(_ROOT), PYTHONUTF8="1")
    return run_with_deadline(
        lambda: subprocess.run(
            [sys.executable, "-m", "scripts.atlas", *argv], cwd=repo.path, env=env, capture_output=True, check=False
        ),
        seconds=120,
    )


def _fake_failing_tar(directory: Path) -> None:
    """Подделка `tar`, которая сразу завершается с кодом 3."""
    directory.mkdir()
    if sys.platform == "win32":
        (directory / "tar.bat").write_text("@exit /b 3\r\n", encoding="ascii")
    else:
        script = directory / "tar"
        script.write_text("#!/bin/sh\nexit 3\n", encoding="ascii")
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# ---------------------------------------------------------------- tar без запасного пути


@pytest.mark.skipif(shutil.which("tar") is None, reason="системного tar нет: проверять нечего")
def test_tar_unpacks_without_tarfile_fallback(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("tarfile fallback used")

    monkeypatch.setattr(tarfile, "open", forbidden)
    # два репозитория: во втором `card` не должен получить готовый checkout первого
    for cmd, name in (("ref", "tar_ref"), ("card", "tar_card")):
        repo = _new_repo(repo_factory, name)
        _forget_if_present()
        res = atlas(repo, cmd, "m", *_REFS)
        assert res.code == 0, f"{cmd}: {res.err}"
        assert res.err == "", f"{cmd}: непустой stderr: {res.err!r}"


def test_tar_failure_falls_back_with_warning(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    control_repo = _new_repo(repo_factory, "tarfail_ctl")
    control = atlas(control_repo, "ref", "m", *_REFS)
    assert control.code == 0, control.err
    _forget_if_present()

    fake = tmp_path / "faketar"
    _fake_failing_tar(fake)
    monkeypatch.setenv("PATH", str(fake) + os.pathsep + os.environ.get("PATH", ""))
    repo = _new_repo(repo_factory, "tarfail")
    res = atlas(repo, "ref", "m", *_REFS)
    assert res.code == 0, res.err
    assert "fallback to tarfile" in res.err, f"нет предупреждения в stderr: {res.err!r}"
    assert "rc=3" in res.err, f"нет кода возврата tar в stderr: {res.err!r}"
    assert res.out == control.out  # запасной путь даёт тот же вывод, что и tar


# ---------------------------------------------------------------- checkout на диске


def test_checkout_survives_the_process(repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.atlas import codemap

    repo = _new_repo(repo_factory, "survive")
    first = _proc(repo, "card", "m", "--ref", "main", "--main-ref", "main")
    assert first.returncode == 0, first.stderr.decode("utf-8", "replace")
    entries = _entries(repo)
    assert len(entries) == 1, f"ожидался один каталог ревизии в {_checkout_dir(repo)}: {entries}"
    entry = _checkout_dir(repo) / entries[0]
    assert (entry / "m" / "interfaces.py").is_file(), "в каталоге ревизии нет m/interfaces.py"
    ino = entry.stat().st_ino
    assert ino != 0, "st_ino == 0: проверка «каталог не пересоздан» была бы пустой"

    codemap.forget()  # новый процесс: память пуста, остался только диск
    spy = _install_spy(monkeypatch)
    res, counts = _call(atlas, spy, repo, "ref", "m", *_REFS)
    assert res.code == 0, res.err
    assert counts["checkout"] == 0, f"вторая ревизия распакована заново: {counts}"
    assert _entries(repo) == entries
    assert (_checkout_dir(repo) / entries[0]).stat().st_ino == ino, "каталог ревизии пересоздан"


def test_checkout_keeps_three_revisions(repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.atlas import build, codemap

    repo = _new_repo(repo_factory, "three")
    shas = [repo.head]
    for i in range(3):
        repo.write("m/core.py", f'"""Реализация."""\n\n\ndef helper(x: int) -> int:\n    return x + {i + 2}\n')
        shas.append(repo.commit(f"edit {i}"))
    assert len(set(shas)) == 4

    names: list[str] = []
    first_out = ""
    for i, sha in enumerate(shas):
        res = atlas(repo, "ref", "m", "--ref", sha, "--main-ref", "main")
        assert res.code == 0, res.err
        if i == 0:
            first_out = res.out
        new = sorted(set(_entries(repo)) - set(names))
        assert len(new) == 1, f"после ревизии {i} ожидался ровно один новый каталог, есть: {new}"
        names.append(new[0])

    kept = _entries(repo)
    assert len(kept) == 3, f"хранится не 3 каталога: {kept}"
    assert names[0] not in kept, "самый старый каталог не вытеснен"
    assert set(kept) == set(names[1:]), "остались не новейшие три"

    codemap.forget()
    monkeypatch.setattr(build, "CORE_VERSION", _NEW_CORE_VERSION)  # иначе кэш видов 1.6e ответит мимо checkout
    spy = _install_spy(monkeypatch)
    again, counts = _call(atlas, spy, repo, "ref", "m", "--ref", shas[0], "--main-ref", "main")
    assert again.code == 0, again.err
    assert counts["checkout"] >= 1, f"старая ревизия не распаковывалась заново: {counts}"
    back = _entries(repo)
    assert names[0] in back, "каталог старой ревизии не вернулся"
    assert len(back) == 3, f"после возврата хранится не 3 каталога: {back}"
    assert names[1] not in back, "вытеснен не самый старый из оставшихся"
    assert again.out == first_out


# ---------------------------------------------------------------- разобранная ревизия в процессе


def test_second_module_in_process_reuses_code(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _new_repo(repo_factory, "reuse")
    spy = _install_spy(monkeypatch)
    first, cold = _call(atlas, spy, repo, "card", "m", *_REFS)
    assert first.code == 0, first.err
    # контроль перехвата: холодный вызов обязан делать работу, иначе нули ниже ничего не доказывают
    assert cold["build_graph"] >= 1, "перехват grimp.build_graph не сработал"
    assert cold["checkout"] >= 1, "перехват checkout не сработал"
    second, warm = _call(atlas, spy, repo, "card", "n", *_REFS)
    assert second.code == 0, second.err
    assert warm == {"build_graph": 0, "checkout": 0}, f"второй модуль той же ревизии не из памяти: {warm}"


# ---------------------------------------------------------------- ЗАЩИТА: тёплый вывод == холодному


def test_warm_output_is_byte_equal_to_cold(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.atlas import build

    repo = _new_repo(repo_factory, "warm")
    cold_ref = atlas(repo, "ref", "m", *_REFS)
    cold_card = atlas(repo, "card", "m", *_REFS)
    assert (cold_ref.code, cold_ref.err) == (0, "")
    assert (cold_card.code, cold_card.err) == (0, "")

    # тёплая ревизия, но промах кэша видов (приём из 1.6e A4)
    monkeypatch.setattr(build, "CORE_VERSION", _NEW_CORE_VERSION)
    warm_ref = atlas(repo, "ref", "m", *_REFS)
    warm_card = atlas(repo, "card", "m", *_REFS)
    assert (warm_ref.code, warm_ref.err) == (0, "")
    assert (warm_card.code, warm_card.err) == (0, "")
    assert warm_ref.out == cold_ref.out
    assert warm_card.out == cold_card.out

    # новый процесс: checkout и кэш grimp с диска; кэш видов стираем, иначе ответ придёт из него
    con = sqlite3.connect(repo.path / "data" / "atlas.sqlite")
    try:
        con.execute("DELETE FROM view_cache")
        con.commit()
    finally:
        con.close()
    for cmd, cold in (("ref", cold_ref), ("card", cold_card)):
        proc = _proc(repo, cmd, "m", "--ref", "main", "--main-ref", "main")
        assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
        assert proc.stdout.decode("utf-8") == cold.out, f"{cmd}: вывод нового процесса отличается от холодного"
