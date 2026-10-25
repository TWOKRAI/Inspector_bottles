"""Слепая приёмка C21.1 (framework): активный pipeline живёт в ``<stem>.state.yaml``.

Линии A1, A1b, A2, A2b, A4, A5, A6, A7, A10, A10b, A11, A16, A17, A19 из плана
``plans/app-active-recipe-state.md``. Тесты написаны ДО реализации и по контракту
(A-линиям), а не по коду; ожидаемые значения — литералы.

Слой: только framework — ``multiprocess_prototype`` здесь не импортируется.
Все манифесты — в ``tmp_path`` (реальный ``app.yaml`` не трогается).
Всё, что может зависнуть (потоки, процессы), идёт с дедлайном: зависание = красный тест.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import threading
from pathlib import Path

import pytest
import yaml

from multiprocess_framework.modules.app_module import ManifestStore
from multiprocess_framework.modules.app_module.builder import AppSpec, SystemBuilder
from multiprocess_framework.modules.app_module.manifest import load_manifest

# Манифест с комментариями и нестандартным форматированием: сравнение байт
# ловит любую перезапись app.yaml (ruamel round-trip тоже могла бы его «причесать»).
APP_YAML_TEXT = (
    "# комментарий владельца: не трогать\n"
    "name:   demo_app\n"
    "version: 1\n"
    "pipeline:    recipes/a.yaml   # умолчание\n"
    "\n"
    "recipes: recipes\n"
)


def _write_app(directory: Path, name: str = "app.yaml") -> Path:
    """Создать манифест-умолчание ``recipes/a.yaml`` и вернуть его путь."""
    directory.mkdir(parents=True, exist_ok=True)
    manifest = directory / name
    manifest.write_bytes(APP_YAML_TEXT.encode("utf-8"))
    return manifest


def _make_recipe(directory: Path, name: str) -> Path:
    recipes = directory / "recipes"
    recipes.mkdir(parents=True, exist_ok=True)
    recipe = recipes / name
    recipe.write_text("name: stub\n", encoding="utf-8")
    return recipe


def _run_with_deadline(fn, timeout: float):
    """Выполнить ``fn`` в daemon-потоке; вернуть (результат, исключение). Не завершился → fail."""
    box: dict = {}

    def target():
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — тест фиксирует любое исключение
            box["error"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)
    assert not t.is_alive(), f"вызов не завершился за {timeout} с (зависание)"
    return box.get("result"), box.get("error")


# ---------------------------------------------------------------------------
# A1 / A1b — set_pipeline пишет состояние, app.yaml не трогает
# ---------------------------------------------------------------------------


def test_a1_set_pipeline_writes_state_and_keeps_manifest_bytes(tmp_path):
    manifest = _write_app(tmp_path)
    before = manifest.read_bytes()

    ManifestStore(manifest).set_pipeline("recipes/b.yaml")

    assert manifest.read_bytes() == before
    state = tmp_path / "app.state.yaml"
    assert state.is_file()
    assert yaml.safe_load(state.read_text(encoding="utf-8")) == {"pipeline": "recipes/b.yaml"}


def test_a1b_set_pipeline_to_default_value_still_creates_state(tmp_path):
    manifest = _write_app(tmp_path)
    assert not (tmp_path / "app.state.yaml").exists()

    ManifestStore(manifest).set_pipeline("recipes/a.yaml")

    state = tmp_path / "app.state.yaml"
    assert state.is_file()
    assert yaml.safe_load(state.read_text(encoding="utf-8")) == {"pipeline": "recipes/a.yaml"}


# ---------------------------------------------------------------------------
# A2 / A2b — load_manifest и ManifestStore.load берут pipeline из состояния
# ---------------------------------------------------------------------------


def test_a2_load_manifest_takes_pipeline_from_state(tmp_path):
    manifest = _write_app(tmp_path)
    _make_recipe(tmp_path, "b.yaml")
    ManifestStore(manifest).set_pipeline("recipes/b.yaml")

    loaded = load_manifest(manifest)

    assert loaded.pipeline == (tmp_path / "recipes" / "b.yaml").resolve()
    assert loaded.pipeline_origin == "state"


def test_a2b_store_load_in_thread_returns_state_pipeline(tmp_path):
    manifest = _write_app(tmp_path)
    _make_recipe(tmp_path, "b.yaml")
    ManifestStore(manifest).set_pipeline("recipes/b.yaml")

    # load() идёт под shared-локом манифеста; чтение состояния не должно взаимно
    # блокироваться с ним — дедлайн 10 с отличает зависание от результата.
    loaded, error = _run_with_deadline(lambda: ManifestStore(manifest).load(), timeout=10)

    assert error is None, f"load() упал: {error!r}"
    assert loaded.pipeline == (tmp_path / "recipes" / "b.yaml").resolve()
    assert loaded.pipeline_origin == "state"


# ---------------------------------------------------------------------------
# A4 / A5 / A6 — откат к умолчанию
# ---------------------------------------------------------------------------


def test_a4_no_state_file_uses_manifest_default(tmp_path):
    manifest = _write_app(tmp_path)
    assert not (tmp_path / "app.state.yaml").exists()

    loaded = load_manifest(manifest)

    assert loaded.pipeline == (tmp_path / "recipes" / "a.yaml").resolve()
    assert loaded.pipeline_origin == "manifest"
    assert loaded.pipeline_note is None


def test_a5_missing_recipe_falls_back_to_default(tmp_path):
    manifest = _write_app(tmp_path)
    state = tmp_path / "app.state.yaml"
    state.write_bytes(b"pipeline: recipes/ghost.yaml\n")  # recipes/ghost.yaml не создан
    os.utime(state, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))
    bytes_before = state.read_bytes()
    mtime_before = state.stat().st_mtime_ns

    loaded = load_manifest(manifest)  # исключения нет

    assert loaded.pipeline == (tmp_path / "recipes" / "a.yaml").resolve()
    assert loaded.pipeline_origin == "manifest"
    assert loaded.pipeline_note is not None
    assert "app.state.yaml" in loaded.pipeline_note
    assert state.read_bytes() == bytes_before
    assert state.stat().st_mtime_ns == mtime_before


# Содержимое состояния -> всегда умолчание и непустое примечание, без исключения.
_BAD_STATES = {
    "broken_yaml": b"pipeline: [unclosed\n  : : {\n",
    "empty_file": b"",
    "list": b"- recipes/b.yaml\n",
    "int": b"pipeline: 5\n",
    "empty_string": b'pipeline: ""\n',
    "blank_string": b'pipeline: "   "\n',
    "null": b"pipeline: null\n",
    # В YAML-тексте — escape-последовательность \0 в двойных кавычках, не NUL-байт.
    "nul_escape": b'pipeline: "a\\0b.yaml"\n',
    "directory": b"pipeline: recipes/dir\n",
}


@pytest.mark.parametrize("case", sorted(_BAD_STATES))
def test_a6_bad_state_falls_back_with_note(tmp_path, case):
    manifest = _write_app(tmp_path)
    _make_recipe(tmp_path, "b.yaml")
    (tmp_path / "recipes" / "dir").mkdir()  # для случая «pipeline указывает на каталог»
    (tmp_path / "app.state.yaml").write_bytes(_BAD_STATES[case])

    loaded = load_manifest(manifest)  # исключения нет

    assert loaded.pipeline == (tmp_path / "recipes" / "a.yaml").resolve()
    assert loaded.pipeline_origin == "manifest"
    assert loaded.pipeline_note, f"примечание пусто для случая {case}"


# ---------------------------------------------------------------------------
# A7 — идемпотентность записи: то же значение не трогает mtime
# ---------------------------------------------------------------------------


def test_a7_same_value_does_not_touch_state_mtime(tmp_path):
    manifest = _write_app(tmp_path)
    store = ManifestStore(manifest)
    store.set_pipeline("recipes/b.yaml")
    state = tmp_path / "app.state.yaml"
    t0 = 1_000_000_000_000_000_000  # 2001 год — заведомо в прошлом
    os.utime(state, ns=(t0, t0))
    assert state.stat().st_mtime_ns == t0

    store.set_pipeline("recipes/b.yaml")

    assert state.stat().st_mtime_ns == t0


# ---------------------------------------------------------------------------
# A10 / A10b — изоляция состояний
# ---------------------------------------------------------------------------


def test_a10_write_via_one_manifest_keeps_other_dir_state(tmp_path):
    manifest_a = _write_app(tmp_path / "dir_a")
    manifest_b = _write_app(tmp_path / "dir_b")
    ManifestStore(manifest_b).set_pipeline("recipes/b.yaml")
    state_b = tmp_path / "dir_b" / "app.state.yaml"
    t0 = 1_000_000_000_000_000_000
    os.utime(state_b, ns=(t0, t0))
    bytes_b = state_b.read_bytes()

    ManifestStore(manifest_a).set_pipeline("recipes/c.yaml")

    assert yaml.safe_load((tmp_path / "dir_a" / "app.state.yaml").read_text(encoding="utf-8")) == {
        "pipeline": "recipes/c.yaml"
    }
    assert state_b.read_bytes() == bytes_b
    assert state_b.stat().st_mtime_ns == t0


def test_a10_write_via_one_manifest_does_not_create_state_in_other_dir(tmp_path):
    manifest_a = _write_app(tmp_path / "dir_a")
    _write_app(tmp_path / "dir_b")

    ManifestStore(manifest_a).set_pipeline("recipes/c.yaml")

    assert (tmp_path / "dir_a" / "app.state.yaml").is_file()
    assert not (tmp_path / "dir_b" / "app.state.yaml").exists()


def test_a10b_same_dir_manifests_have_independent_states(tmp_path):
    app = _write_app(tmp_path, "app.yaml")
    stand = _write_app(tmp_path, "stand.yaml")

    ManifestStore(app).set_pipeline("recipes/b.yaml")
    assert (tmp_path / "app.state.yaml").is_file()
    assert not (tmp_path / "stand.state.yaml").exists()

    ManifestStore(stand).set_pipeline("recipes/c.yaml")
    assert yaml.safe_load((tmp_path / "app.state.yaml").read_text(encoding="utf-8")) == {"pipeline": "recipes/b.yaml"}
    assert yaml.safe_load((tmp_path / "stand.state.yaml").read_text(encoding="utf-8")) == {"pipeline": "recipes/c.yaml"}


# ---------------------------------------------------------------------------
# A11 — два процесса пишут состояние одновременно
# ---------------------------------------------------------------------------


def _a11_worker(manifest_path: str, start_event, values: list) -> None:
    """Дочерний процесс (spawn): ждёт общий старт и 30 раз зовёт set_pipeline."""
    from multiprocess_framework.modules.app_module import ManifestStore as _Store

    assert start_event.wait(60), "общий старт не пришёл"
    store = _Store(manifest_path)
    for value in values:
        store.set_pipeline(value)


def test_a11_two_spawn_processes_write_state_without_corruption(tmp_path):
    manifest = _write_app(tmp_path)
    ctx = mp.get_context("spawn")
    start = ctx.Event()
    values = {pid: [f"recipes/p{pid}_{i}.yaml" for i in range(30)] for pid in (1, 2)}
    all_values = {v for vs in values.values() for v in vs}
    assert len(all_values) == 60

    procs = [ctx.Process(target=_a11_worker, args=(str(manifest), start, values[pid])) for pid in (1, 2)]
    for p in procs:
        p.start()
    try:
        start.set()
        for p in procs:
            p.join(150)
        hung = [p for p in procs if p.is_alive()]
        assert not hung, "процесс-писатель завис (join-дедлайн 150 с)"
    finally:
        for p in procs:
            if p.is_alive():
                p.terminate()
                p.join(10)

    assert [p.exitcode for p in procs] == [0, 0]
    state = tmp_path / "app.state.yaml"
    assert yaml.safe_load(state.read_text(encoding="utf-8"))["pipeline"] in all_values
    assert list(tmp_path.rglob("*.tmp.*")) == []


# ---------------------------------------------------------------------------
# A16 — относительный и абсолютный путь манифеста дают одно состояние
# ---------------------------------------------------------------------------


def test_a16_relative_and_absolute_manifest_path_share_one_state(tmp_path, monkeypatch):
    manifest = _write_app(tmp_path)
    monkeypatch.chdir(tmp_path)

    ManifestStore(Path("app.yaml")).set_pipeline("recipes/x.yaml")
    ManifestStore(manifest).set_pipeline("recipes/y.yaml")

    assert [p.name for p in tmp_path.glob("*.state.yaml")] == ["app.state.yaml"]
    state = tmp_path / "app.state.yaml"
    assert yaml.safe_load(state.read_text(encoding="utf-8"))["pipeline"] == "recipes/y.yaml"


# ---------------------------------------------------------------------------
# A17 — store.update({"pipeline": ...}) меняет умолчание, состояние приоритетнее
# ---------------------------------------------------------------------------


def test_a17_update_pipeline_with_state_keeps_state_active(tmp_path):
    manifest = _write_app(tmp_path)
    _make_recipe(tmp_path, "b.yaml")
    _make_recipe(tmp_path, "c.yaml")
    (tmp_path / "app.state.yaml").write_bytes(b"pipeline: recipes/b.yaml\n")
    store = ManifestStore(manifest)

    store.update({"pipeline": "recipes/c.yaml"})

    loaded = load_manifest(manifest)
    assert loaded.pipeline == (tmp_path / "recipes" / "b.yaml").resolve()
    assert loaded.pipeline_origin == "state"
    assert store.read_raw()["pipeline"] == "recipes/c.yaml"


def test_a17_update_pipeline_without_state_changes_default(tmp_path):
    manifest = _write_app(tmp_path)
    _make_recipe(tmp_path, "c.yaml")
    store = ManifestStore(manifest)

    store.update({"pipeline": "recipes/c.yaml"})

    loaded = load_manifest(manifest)
    assert loaded.pipeline == (tmp_path / "recipes" / "c.yaml").resolve()
    assert loaded.pipeline_origin == "manifest"
    assert store.read_raw()["pipeline"] == "recipes/c.yaml"


# ---------------------------------------------------------------------------
# A19 — баннер показывает источник pipeline
# ---------------------------------------------------------------------------


def test_a19_banner_marks_pipeline_from_state(tmp_path, capsys):
    manifest = _write_app(tmp_path)
    _make_recipe(tmp_path, "b.yaml")
    ManifestStore(manifest).set_pipeline("recipes/b.yaml")

    SystemBuilder(AppSpec(manifest_path=manifest))._print_banner(
        load_manifest(manifest), n_plugins=0, n_services=0, n_processes=0
    )

    assert "pipeline : b.yaml (state)" in capsys.readouterr().out


def test_a19_banner_without_state_has_no_state_mark(tmp_path, capsys):
    manifest = _write_app(tmp_path)

    SystemBuilder(AppSpec(manifest_path=manifest))._print_banner(
        load_manifest(manifest), n_plugins=0, n_services=0, n_processes=0
    )

    out = capsys.readouterr().out
    assert "pipeline : a.yaml" in out
    assert "(state)" not in out
