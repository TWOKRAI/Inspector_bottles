"""ManifestStore — единственная точка read/write app.yaml + регресс гонки (NEW-1, Ф5.11)."""

from __future__ import annotations

import threading
from pathlib import Path

import yaml

from multiprocess_framework.modules.app_module import ManifestStore

_HEADER = "# app.yaml — заголовок-комментарий (должен пережить запись)\n"


def _seed(tmp_path: Path) -> Path:
    p = tmp_path / "app.yaml"
    p.write_text(_HEADER + "name: App\npipeline: recipes/a.yaml\n", encoding="utf-8")
    return p


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
    path = _seed(tmp_path)
    store = ManifestStore(path)
    before_mtime = path.stat().st_mtime_ns
    result = store.set_pipeline("recipes/a.yaml")  # уже такое значение
    assert result == "recipes/a.yaml"
    assert path.stat().st_mtime_ns == before_mtime  # файл не тронут (не дёргаем mtime)


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
