"""ManifestStore — единственная точка read/write app.yaml + регресс гонки (NEW-1, Ф5.11)."""

from __future__ import annotations

import multiprocessing as mp
import os
import threading
from pathlib import Path

import pytest
import yaml

from multiprocess_framework.modules.app_module import ManifestStore, resolve_active_pipeline
from multiprocess_framework.modules.app_module import store as store_mod

_HEADER = "# app.yaml — заголовок-комментарий (должен пережить запись)\n"


def _seed(tmp_path: Path) -> Path:
    p = tmp_path / "app.yaml"
    p.write_text(_HEADER + "name: App\npipeline: recipes/a.yaml\n", encoding="utf-8")
    return p


def _mp_writer(path_str: str, keys: list[tuple[str, int]]) -> None:
    """Top-level (picklable для spawn) writer: свой ManifestStore-инстанс на процесс."""
    store = ManifestStore(path_str)
    for k, v in keys:
        store.update({k: v})


def test_read_raw_returns_dict(tmp_path: Path) -> None:
    store = ManifestStore(_seed(tmp_path))
    raw = store.read_raw()
    assert raw["name"] == "App"
    assert raw["pipeline"] == "recipes/a.yaml"


def test_update_preserves_comments(tmp_path: Path) -> None:
    path = _seed(tmp_path)
    store = ManifestStore(path)
    store.update({"pipeline": "recipes/b.yaml"})
    text = path.read_text(encoding="utf-8")
    assert "заголовок-комментарий" in text  # комментарий пережил запись
    assert yaml.safe_load(text)["pipeline"] == "recipes/b.yaml"


def test_set_pipeline_noop_when_unchanged(tmp_path: Path) -> None:
    """Повторный set_pipeline тем же значением не переписывает файл состояния (A7)."""
    path = _seed(tmp_path)
    state_path = path.with_name("app.state.yaml")
    store = ManifestStore(path)

    assert store.set_pipeline("recipes/b.yaml") == "recipes/b.yaml"
    assert yaml.safe_load(state_path.read_text(encoding="utf-8")) == {"pipeline": "recipes/b.yaml"}

    t0 = 1_000_000_000_000_000_000  # заведомо в прошлом: любая перезапись сдвинет mtime
    os.utime(state_path, ns=(t0, t0))
    assert store.set_pipeline("recipes/b.yaml") == "recipes/b.yaml"  # уже такое значение
    assert state_path.stat().st_mtime_ns == t0  # файл состояния не тронут


def _seed_state_with_recipe(tmp_path: Path) -> tuple[Path, Path]:
    """Валидное состояние: app.state.yaml -> recipes/b.yaml, файл рецепта создан."""
    path = _seed(tmp_path)
    (tmp_path / "recipes").mkdir()
    recipe = tmp_path / "recipes" / "b.yaml"
    recipe.write_text("processes: []\n", encoding="utf-8")
    path.with_name("app.state.yaml").write_text("pipeline: recipes/b.yaml\n", encoding="utf-8")
    return path, recipe


def _patch_read_text(monkeypatch: pytest.MonkeyPatch, *, fail_first_n: int | None) -> list[Path]:
    """Path.read_text падает ``PermissionError`` на файле состояния.

    ``fail_first_n=N`` — первые N обращений к ``app.state.yaml``; ``None`` — все.
    Возвращает список обращений к файлу состояния (по нему видно число повторов).
    """
    real = Path.read_text
    calls: list[Path] = []

    def fake(self: Path, *args, **kwargs):
        if self.name == "app.state.yaml":
            calls.append(self)
            if fail_first_n is None or len(calls) <= fail_first_n:
                raise PermissionError(13, "файл занят писателем (имитация WinError 5)")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake)
    return calls


def test_resolver_retries_transient_read_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Писатель подменяет файл в момент чтения: первое чтение падает, повтор успешен."""
    path, recipe = _seed_state_with_recipe(tmp_path)
    calls = _patch_read_text(monkeypatch, fail_first_n=1)

    active = resolve_active_pipeline(path, "recipes/a.yaml")

    assert active.origin == "state"
    assert active.path == recipe.resolve()
    assert active.note is None
    assert len(calls) >= 2  # было повторное чтение, а не сдача с первой ошибки


def test_resolver_persistent_read_error_falls_back_with_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Чтение падает всегда: умолчание + note с путём состояния, исключения нет."""
    path, _recipe = _seed_state_with_recipe(tmp_path)
    _patch_read_text(monkeypatch, fail_first_n=None)

    active = resolve_active_pipeline(path, "recipes/a.yaml")

    assert active.origin == "manifest"
    assert active.path == (tmp_path / "recipes" / "a.yaml").resolve()
    assert active.note
    assert "app.state.yaml" in active.note


def test_atomic_write_no_leftover_tmp(tmp_path: Path) -> None:
    path = _seed(tmp_path)
    ManifestStore(path).update({"pipeline": "recipes/c.yaml"})
    leftovers = list(tmp_path.glob("app.yaml.tmp*"))
    assert leftovers == []  # temp-файл убран после атомарной подмены


def test_concurrent_writes_no_lost_update(tmp_path: Path) -> None:
    """Регресс гонки backend↔GUI: N параллельных писателей разных ключей.

    Без сериализации read-modify-write часть ключей терялась бы (last-writer-wins
    на уровне всего файла). ManifestStore под EX-локом гарантирует, что итоговый
    файл содержит ВСЕ записанные ключи и остаётся валидным YAML.
    """
    path = _seed(tmp_path)
    store = ManifestStore(path)
    n = 24
    barrier = threading.Barrier(n)

    def writer(i: int) -> None:
        barrier.wait()  # максимизировать конкуренцию
        store.update({f"key_{i}": i})

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data is not None  # файл не побит (не torn)
    for i in range(n):
        assert data[f"key_{i}"] == i  # ни одно обновление не потеряно
    assert data["name"] == "App"  # исходные ключи целы
    assert "заголовок-комментарий" in path.read_text(encoding="utf-8")


def test_concurrent_writes_multiprocess_no_lost_update(tmp_path: Path) -> None:
    """Регресс МЕЖПРОЦЕССНОЙ гонки (spawn): in-process threading.Lock здесь бесполезен —
    ключи не теряются ТОЛЬКО благодаря flock. Threading-вариант выше зеленел бы и без
    flock (ловушка «параметры прячут дефект»); этот тест проверяет реальный контракт NEW-1.
    """
    path = _seed(tmp_path)
    ctx = mp.get_context("spawn")
    n_procs, per_proc = 6, 5
    procs = [
        ctx.Process(target=_mp_writer, args=(str(path), [(f"mp_{i}_{j}", i * 100 + j) for j in range(per_proc)]))
        for i in range(n_procs)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data is not None  # не torn между процессами (atomic replace)
    for i in range(n_procs):
        for j in range(per_proc):
            assert data[f"mp_{i}_{j}"] == i * 100 + j  # ни одно межпроцессное обновление не потеряно
    assert data["name"] == "App"  # исходный ключ цел
    assert "заголовок-комментарий" in path.read_text(encoding="utf-8")


@pytest.mark.skipif(not store_mod._HAVE_FCNTL, reason="flock-путь только на POSIX")
def test_lock_released_on_flock_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MAJOR-1: исключение в flock НЕ оставляет глобальный _PROCESS_LOCK захваченным.

    Иначе все последующие операции ManifestStore в процессе виснут. После падения
    лок должен быть свободен, а восстановленная операция — отработать без deadlock'а.
    """
    path = _seed(tmp_path)
    store = ManifestStore(path)
    real_flock = store_mod.fcntl.flock

    def boom(*_a, **_k):
        raise OSError("flock отказал (симуляция ro-FS/прав)")

    monkeypatch.setattr(store_mod.fcntl, "flock", boom)
    with pytest.raises(OSError):
        store.update({"x": 1})

    # Лок освобождён: можем взять его без блокировки (иначе — навсегда захвачен).
    assert store_mod._PROCESS_LOCK.acquire(blocking=False)
    store_mod._PROCESS_LOCK.release()

    # Восстановленная операция не виснет и пишет корректно.
    monkeypatch.setattr(store_mod.fcntl, "flock", real_flock)
    store.update({"y": 2})
    assert store.read_raw()["y"] == 2
