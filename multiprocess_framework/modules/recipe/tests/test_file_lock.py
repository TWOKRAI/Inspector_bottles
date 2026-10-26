"""Межпроцессный лок рецепта (Task 1.1h): ``recipe_file_lock`` и его место в ``RecipeService``.

Схема: второй процесс — ``subprocess.Popen([sys.executable, "-c", _CHILD, ...])``; синхронизация
файлами-маркерами ``held``/``release`` в ``tmp_path``; каждое ожидание — с дедлайном. Вызов, который
может зависнуть, идёт в daemon-потоке с ``join(timeout=...)``, затем ``assert not t.is_alive()``.
Ребёнок убивается в ``finally``.

Доказана только Windows-ветка (машина разработки — Windows); POSIX-ветка тестами здесь не исполнялась.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.recipe.format import compute_rev
from multiprocess_framework.modules.recipe.service import RecipeService

_REPO_ROOT = Path(__file__).resolve().parents[4]

# Ребёнок: берёт лок на рецепт, ставит маркер held, ждёт маркер release (с дедлайном), при
# непустом argv[4] переписывает рецепт этими байтами ПОД локом, затем отпускает лок и выходит.
_CHILD = r"""
import sys, time, pathlib
from multiprocess_framework.modules.recipe.file_lock import recipe_file_lock
recipe, held, release, new_text = sys.argv[1:5]
with recipe_file_lock(recipe, timeout=10.0):
    pathlib.Path(held).write_text("1")
    end = time.monotonic() + 30.0
    while not pathlib.Path(release).exists():
        if time.monotonic() > end:
            sys.exit(3)
        time.sleep(0.01)
    if new_text:
        pathlib.Path(recipe).write_bytes(new_text.encode("utf-8"))
"""


def _fl() -> Any:
    """Модуль под тестом; импорт в тесте, чтобы его отсутствие было красным каждого теста, а не сбором."""
    return importlib.import_module("multiprocess_framework.modules.recipe.file_lock")


class _Child:
    def __init__(self, tmp_path: Path, recipe: Path, new_text: str = "") -> None:
        self.held = tmp_path / "held"
        self.release = tmp_path / "release"
        self._err = tmp_path / "child_stderr.txt"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(_REPO_ROOT)
        with open(self._err, "wb") as err:
            self.proc = subprocess.Popen(
                [sys.executable, "-c", _CHILD, str(recipe), str(self.held), str(self.release), new_text],
                cwd=str(_REPO_ROOT),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=err,
            )

    def wait_held(self, deadline_s: float = 60.0) -> None:
        end = time.monotonic() + deadline_s
        while not self.held.exists():
            if self.proc.poll() is not None:
                pytest.fail(
                    f"ребёнок вышел до held (код {self.proc.returncode}): {self._err.read_text(errors='replace')}"
                )
            if time.monotonic() > end:
                pytest.fail("ребёнок не взял лок за дедлайн")
            time.sleep(0.01)

    def let_go(self, deadline_s: float = 15.0) -> None:
        self.release.write_text("1")
        assert self.proc.wait(timeout=deadline_s) == 0, self._err.read_text(errors="replace")

    def kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=15)


def _in_thread(fn: Any) -> tuple[threading.Thread, dict[str, Any]]:
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — исключение проверяет тест
            box["exc"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, box


def _acquire_once(path: Path, timeout: float) -> str:
    with _fl().recipe_file_lock(path, timeout=timeout):
        return "taken"


class _Hook:
    def normalize(self, body: dict) -> dict:
        return dict(body)

    def validate(self, body: dict) -> list[dict]:
        return []

    def to_topology(self, body: dict) -> dict:
        return body


def _service(recipes_dir: Path) -> RecipeService:
    return RecipeService(
        recipes_dir,
        _Hook(),
        apply_topology=lambda args: {"success": True},
        persist_active=lambda path: None,
        read_active=lambda: None,
    )


# --- recipe_file_lock -------------------------------------------------------------------


def test_lock_excludes_other_process(tmp_path: Path) -> None:
    recipe = tmp_path / "r.yaml"
    recipe.write_bytes(b"a: 1\n")
    child = _Child(tmp_path, recipe)
    try:
        child.wait_held()
        t, box = _in_thread(lambda: _acquire_once(recipe, 0.3))
        t.join(timeout=10)
        assert not t.is_alive()
        assert isinstance(box.get("exc"), _fl().RecipeLockTimeout), box
        child.let_go()
        t, box = _in_thread(lambda: _acquire_once(recipe, 5.0))
        t.join(timeout=10)
        assert not t.is_alive()
        assert box == {"result": "taken"}
    finally:
        child.kill()


def test_lock_timeout_raises_within_deadline(tmp_path: Path) -> None:
    recipe = tmp_path / "r.yaml"
    child = _Child(tmp_path, recipe)
    try:
        child.wait_held()

        def timed() -> float:
            start = time.monotonic()
            try:
                _acquire_once(recipe, 0.5)
            except _fl().RecipeLockTimeout:
                return time.monotonic() - start
            raise AssertionError("лок взят при живом держателе")

        t, box = _in_thread(timed)
        t.join(timeout=5)
        assert not t.is_alive(), "лок ждёт дольше дедлайна (блокирующий вызов?)"
        assert "exc" not in box, box
        assert 0.5 <= box["result"] <= 2.5
    finally:
        child.kill()


def test_lock_released_when_holder_process_dies(tmp_path: Path) -> None:
    recipe = tmp_path / "r.yaml"
    child = _Child(tmp_path, recipe)
    try:
        child.wait_held()
        child.proc.kill()
        child.proc.wait(timeout=15)
        # Windows снимает лок убитого процесса асинхронно — ждём с дедлайном, а не сразу.
        t, box = _in_thread(lambda: _acquire_once(recipe, 5.0))
        t.join(timeout=10)
        assert not t.is_alive()
        assert box == {"result": "taken"}
    finally:
        child.kill()


def test_lock_file_next_to_recipe_and_left_after_release(tmp_path: Path) -> None:
    recipe = tmp_path / "letter_robot_sim.yaml"
    recipe.write_bytes(b"a: 1\n")
    lock = tmp_path / "letter_robot_sim.yaml.lock"
    with _fl().recipe_file_lock(recipe):
        assert lock.is_file()
    assert lock.is_file()


def test_lock_on_absent_recipe_file(tmp_path: Path) -> None:
    recipe = tmp_path / "new_recipe.yaml"
    t, box = _in_thread(lambda: _acquire_once(recipe, 1.0))
    t.join(timeout=5)
    assert not t.is_alive()
    assert box == {"result": "taken"}
    assert not recipe.exists()


# --- RecipeService под межпроцессным локом -----------------------------------------------


def test_service_save_rev_check_inside_interprocess_lock(tmp_path: Path) -> None:
    recipe = tmp_path / "r.yaml"
    recipe.write_bytes(b"a: 1\n")
    rev0 = compute_rev(b"a: 1\n")
    svc = _service(tmp_path)
    child = _Child(tmp_path, recipe, new_text="a: 2\n")
    try:
        child.wait_held()
        t, box = _in_thread(lambda: svc.save({"name": "r", "base_rev": rev0, "body": {"a": 3}}))
        t.join(timeout=0.3)
        assert t.is_alive(), f"save не ждал межпроцессный лок: {box}"
        child.let_go()
        t.join(timeout=10)
        assert not t.is_alive()
        assert box["result"]["success"] is False
        assert box["result"]["error"] == "conflict"
        assert recipe.read_bytes() == b"a: 2\n"
    finally:
        child.kill()


def test_service_delete_under_interprocess_lock(tmp_path: Path) -> None:
    recipe = tmp_path / "r.yaml"
    recipe.write_bytes(b"a: 1\n")
    rev0 = compute_rev(b"a: 1\n")
    svc = _service(tmp_path)
    child = _Child(tmp_path, recipe, new_text="a: 2\n")
    try:
        child.wait_held()
        t, box = _in_thread(lambda: svc.delete({"name": "r", "base_rev": rev0}))
        t.join(timeout=0.3)
        assert t.is_alive(), f"delete не ждал межпроцессный лок: {box}"
        child.let_go()
        t.join(timeout=10)
        assert not t.is_alive()
        assert box["result"]["error"] == "conflict"
        assert recipe.read_bytes() == b"a: 2\n"
    finally:
        child.kill()


# --- _atomic_write: повтор os.replace при открытом читателе -----------------------------


def _write_with_reader(
    monkeypatch: pytest.MonkeyPatch, recipe: Path, data: bytes, close_on_failure: int | None
) -> tuple[list[str], BaseException | None]:
    """``_atomic_write`` при открытом читателе, без времени: ``os.replace`` обёрнут счётчиком
    (настоящая PermissionError от читателя сохраняется), пауза между попытками — пустышка.
    Читатель закрывается на ``close_on_failure``-й отказавшей попытке (``None`` — не закрывается).
    Возврат: исходы попыток (``"fail"``/``"ok"``) и исключение записи."""
    from multiprocess_framework.modules.recipe import service

    outcomes: list[str] = []
    real_replace = os.replace
    reader = open(recipe, "rb")  # open() Python не даёт FILE_SHARE_DELETE → os.replace падает

    def counting_replace(src: Any, dst: Any) -> None:
        try:
            real_replace(src, dst)
        except PermissionError:
            outcomes.append("fail")
            if outcomes.count("fail") == close_on_failure:
                reader.close()
            raise
        outcomes.append("ok")

    monkeypatch.setattr(service.os, "replace", counting_replace)
    monkeypatch.setattr(service.time, "sleep", lambda _s: None)
    try:
        service._atomic_write(recipe, data)
    except BaseException as exc:  # noqa: BLE001 — исключение проверяет тест
        return outcomes, exc
    finally:
        reader.close()
    return outcomes, None


@pytest.mark.skipif(sys.platform != "win32", reason="PermissionError при открытом читателе — только Windows")
def test_atomic_write_retries_until_reader_closes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Читатель закрылся на 2-й отказавшей попытке: запись прошла с 3-й попытки."""
    recipe = tmp_path / "r.yaml"
    recipe.write_bytes(b"old\n")

    outcomes, exc = _write_with_reader(monkeypatch, recipe, b"new\n", close_on_failure=2)

    assert exc is None
    assert outcomes == ["fail", "fail", "ok"]
    assert recipe.read_bytes() == b"new\n"


@pytest.mark.skipif(sys.platform != "win32", reason="PermissionError при открытом читателе — только Windows")
def test_atomic_write_gives_up_after_five_attempts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Читатель не закрывается: PermissionError ровно после 5 попыток, файл прежний."""
    recipe = tmp_path / "r.yaml"
    recipe.write_bytes(b"old\n")

    outcomes, exc = _write_with_reader(monkeypatch, recipe, b"new\n", close_on_failure=None)

    assert isinstance(exc, PermissionError)
    assert outcomes == ["fail", "fail", "fail", "fail", "fail"]
    assert recipe.read_bytes() == b"old\n"


# --- 1.1h, ревью р2: лок не прячет чужие ошибки ------------------------------------------


def test_try_lock_on_closed_fd_raises_real_error(tmp_path: Path) -> None:
    """``_try_lock`` на закрытом дескрипторе (EBADF): настоящий OSError, а не «лок занят»/таймаут."""
    fl = _fl()
    fd = os.open(tmp_path / "x.lock", os.O_RDWR | os.O_CREAT, 0o644)
    os.close(fd)

    with pytest.raises(OSError) as info:
        fl._try_lock(fd)

    assert not isinstance(info.value, fl.RecipeLockTimeout)


def test_body_exception_survives_failing_unlock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Исключение внутри ``with recipe_file_lock(...)`` всплывает исходным, даже если ``_unlock`` бросает."""
    fl = _fl()

    def broken_unlock(fd: int) -> None:
        raise OSError("unlock failed")

    monkeypatch.setattr(fl, "_unlock", broken_unlock)

    with pytest.raises(ValueError, match="boom"):
        with fl.recipe_file_lock(tmp_path / "r.yaml", timeout=1.0):
            raise ValueError("boom")
