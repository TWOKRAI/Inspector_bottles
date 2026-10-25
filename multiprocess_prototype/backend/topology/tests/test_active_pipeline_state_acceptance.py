"""Слепая приёмка C21.1 (прототип): активный pipeline живёт в ``<stem>.state.yaml``.

Линии A3, A8, A9, A12, A13, A14, A15 из плана ``plans/app-active-recipe-state.md``.
Написаны ДО реализации и по контракту (A-линиям); ожидаемые значения — литералы.

Все манифесты — в ``tmp_path`` (реальный ``multiprocess_prototype/app.yaml`` не трогается);
исключение — A12, он спрашивает ``git check-ignore`` у корня репозитория.
Всё, что может зависнуть (потоки, подпроцессы), идёт с дедлайном: зависание = красный тест.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest
import yaml

from multiprocess_framework.modules.app_module import ManifestStore
from multiprocess_framework.modules.app_module.manifest import load_manifest as framework_load_manifest
from multiprocess_prototype.backend.config.manifest import load_manifest as prototype_load_manifest
from multiprocess_prototype.backend.launch import _resolve_pipeline, persist_pipeline_choice

# tests/ -> topology/ -> backend/ -> multiprocess_prototype/ -> корень репозитория
REPO_ROOT = Path(__file__).resolve().parents[4]

# Прототипному парсеру обязательны ``system:`` и ``recipes:`` (иначе KeyError).
APP_YAML_TEXT = (
    "# комментарий владельца: не трогать\n"
    "system:   system.yaml\n"
    "pipeline:    recipes/a.yaml   # умолчание\n"
    "recipes: recipes\n"
)


def _write_app(directory: Path, name: str = "app.yaml") -> Path:
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


# ---------------------------------------------------------------------------
# A3 — оба парсера дают одно и то же
# ---------------------------------------------------------------------------


def test_a3_both_parsers_agree_on_pipeline_origin_and_note(tmp_path):
    # case -> (содержимое состояния | None, ожидаемый origin)
    cases = {
        "valid_state": (b"pipeline: recipes/b.yaml\n", "state"),
        "no_state": (None, "manifest"),
        "broken_state": (b"pipeline: [unclosed\n  : : {\n", "manifest"),
    }
    for case, (state_bytes, expected_origin) in cases.items():
        directory = tmp_path / case
        manifest = _write_app(directory)
        _make_recipe(directory, "b.yaml")
        if state_bytes is not None:
            (directory / "app.state.yaml").write_bytes(state_bytes)

        framework = framework_load_manifest(manifest)
        prototype = prototype_load_manifest(manifest)

        assert prototype.pipeline == framework.pipeline, case
        assert prototype.pipeline_origin == framework.pipeline_origin, case
        assert prototype.pipeline_note == framework.pipeline_note, case
        # Равенство двух None/одинаковых значений не должно быть пустышкой:
        assert prototype.pipeline_origin == expected_origin, case
        expected_pipeline = "b.yaml" if expected_origin == "state" else "a.yaml"
        assert prototype.pipeline == (directory / "recipes" / expected_pipeline).resolve(), case
        if case == "broken_state":
            assert prototype.pipeline_note, "для битого состояния примечание не должно быть пустым"
        else:
            assert prototype.pipeline_note is None, case


# ---------------------------------------------------------------------------
# A8 — persist_pipeline_choice пишет состояние, app.yaml не трогает
# ---------------------------------------------------------------------------


def test_a8_persist_pipeline_choice_writes_state_keeps_manifest(tmp_path):
    manifest = _write_app(tmp_path)
    _make_recipe(tmp_path, "b.yaml")
    before = manifest.read_bytes()

    persist_pipeline_choice(manifest, "b")

    assert manifest.read_bytes() == before
    state = tmp_path / "app.state.yaml"
    assert yaml.safe_load(state.read_text(encoding="utf-8")) == {"pipeline": "recipes/b.yaml"}


def test_a8_persist_pipeline_choice_missing_recipe_touches_nothing(tmp_path):
    manifest = _write_app(tmp_path)
    (tmp_path / "recipes").mkdir()  # recipes/ghost.yaml не создан
    before = manifest.read_bytes()

    with pytest.raises(FileNotFoundError):
        persist_pipeline_choice(manifest, "ghost")

    assert manifest.read_bytes() == before
    assert not (tmp_path / "app.state.yaml").exists()


# ---------------------------------------------------------------------------
# A9 — «headless-бэкенд + отдельно запущенный GUI»: два процесса подряд
# ---------------------------------------------------------------------------

_BACKEND_CODE = (
    "import sys\n"
    "from pathlib import Path\n"
    "from multiprocess_prototype.backend.launch import persist_pipeline_choice\n"
    "persist_pipeline_choice(Path(sys.argv[1]), 'b')\n"
)

_GUI_CODE = (
    "import json, sys\n"
    "from multiprocess_prototype.backend.config.manifest import load_manifest\n"
    "m = load_manifest(sys.argv[1])\n"
    "print(json.dumps({'pipeline': str(m.pipeline), 'origin': m.pipeline_origin}))\n"
)


def _run_process(code: str, manifest: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT), "PYTHONUTF8": "1"}
    try:
        return subprocess.run(
            [sys.executable, "-c", code, str(manifest)],
            cwd=REPO_ROOT,
            env=env,
            timeout=60,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        pytest.fail(f"подпроцесс упал, код {exc.returncode}:\n{exc.stderr.decode('utf-8', 'replace')}")


def test_a9_gui_process_sees_recipe_chosen_by_backend_process(tmp_path):
    manifest = _write_app(tmp_path)
    _make_recipe(tmp_path, "b.yaml")

    _run_process(_BACKEND_CODE, manifest)
    gui = _run_process(_GUI_CODE, manifest)

    result = json.loads(gui.stdout.decode("utf-8").strip().splitlines()[-1])
    assert result["pipeline"] == str((tmp_path / "recipes" / "b.yaml").resolve())
    assert result["origin"] == "state"


# ---------------------------------------------------------------------------
# A12 — файл состояния прототипа в .gitignore
# ---------------------------------------------------------------------------


def test_a12_prototype_state_file_is_git_ignored():
    result = subprocess.run(
        ["git", "check-ignore", "-q", "multiprocess_prototype/app.state.yaml"],
        cwd=REPO_ROOT,
        timeout=30,
    )

    assert result.returncode == 0


# ---------------------------------------------------------------------------
# A13 — писатель и читатель одновременно
# ---------------------------------------------------------------------------


def test_a13_concurrent_writer_and_reader_never_see_torn_state(tmp_path):
    manifest = _write_app(tmp_path)
    b = _make_recipe(tmp_path, "b.yaml").resolve()
    c = _make_recipe(tmp_path, "c.yaml").resolve()
    default = (tmp_path / "recipes" / "a.yaml").resolve()
    allowed = {b, c, default}

    stop = threading.Event()
    errors: list[tuple[str, BaseException]] = []
    reads: list[tuple[Path, str]] = []

    def writer():
        store = ManifestStore(manifest)
        values = ["recipes/b.yaml", "recipes/c.yaml"]
        i = 0
        try:
            while not stop.is_set():
                store.set_pipeline(values[i % 2])
                i += 1
        except BaseException as exc:  # noqa: BLE001 — любое исключение = находка
            errors.append(("writer", exc))

    def reader():
        try:
            while not stop.is_set():
                loaded = prototype_load_manifest(manifest)
                reads.append((loaded.pipeline, loaded.pipeline_origin))
        except BaseException as exc:  # noqa: BLE001
            errors.append(("reader", exc))

    threads = [threading.Thread(target=writer, daemon=True), threading.Thread(target=reader, daemon=True)]
    for t in threads:
        t.start()
    time.sleep(2.0)
    stop.set()
    for t in threads:
        t.join(15)
    assert not any(t.is_alive() for t in threads), "поток-писатель или читатель завис (join-дедлайн 15 с)"

    assert errors == []
    assert reads, "читатель не сделал ни одного чтения"
    assert {pipeline for pipeline, _ in reads} <= allowed
    assert any(origin == "state" for _, origin in reads), "за 2 с не было ни одного чтения с origin == 'state'"


# ---------------------------------------------------------------------------
# A14 — голое имя рецепта резолвится рядом с состоянием, а не рядом с умолчанием
# ---------------------------------------------------------------------------


def test_a14_bare_recipe_name_resolves_into_recipes_dir_even_if_state_is_elsewhere(tmp_path):
    manifest = _write_app(tmp_path)
    topology = tmp_path / "backend" / "topology"
    topology.mkdir(parents=True)
    (topology / "x.yaml").write_text("name: stub\n", encoding="utf-8")
    (tmp_path / "app.state.yaml").write_bytes(b"pipeline: backend/topology/x.yaml\n")

    app = prototype_load_manifest(manifest)

    # Предусловие: состояние действительно активно (иначе проверка ниже — пустышка:
    # у умолчания recipes/a.yaml родитель и так совпадает с recipes).
    assert app.pipeline_origin == "state"
    assert app.pipeline == (topology / "x.yaml").resolve()
    assert _resolve_pipeline(app, "phone_sketch") == app.recipes / "phone_sketch.yaml"


# ---------------------------------------------------------------------------
# A15 — фабрика запуска сообщает об источнике pipeline в stderr
# ---------------------------------------------------------------------------


def _call_factory(manifest: Path, monkeypatch):
    monkeypatch.setattr("multiprocess_prototype.main.build_launcher", lambda *a, **k: None)
    from multiprocess_prototype.main import _prototype_launcher_factory

    _prototype_launcher_factory(types.SimpleNamespace(source=manifest), None, headless=True)


def test_a15_factory_reports_broken_state_on_stderr(tmp_path, monkeypatch, capsys):
    manifest = _write_app(tmp_path)
    (tmp_path / "app.state.yaml").write_bytes(b"pipeline: [unclosed\n  : : {\n")
    capsys.readouterr()

    _call_factory(manifest, monkeypatch)

    err = capsys.readouterr().err
    assert "[run]" in err
    assert "app.state.yaml" in err


def test_a15_factory_reports_valid_state_source_on_stderr(tmp_path, monkeypatch, capsys):
    manifest = _write_app(tmp_path)
    _make_recipe(tmp_path, "b.yaml")
    (tmp_path / "app.state.yaml").write_bytes(b"pipeline: recipes/b.yaml\n")
    capsys.readouterr()

    _call_factory(manifest, monkeypatch)

    assert "источник: состояние" in capsys.readouterr().err


def test_a15_factory_is_silent_without_state(tmp_path, monkeypatch, capsys):
    manifest = _write_app(tmp_path)
    capsys.readouterr()

    _call_factory(manifest, monkeypatch)

    err = capsys.readouterr().err
    assert "[run]" not in err
    assert "app.state.yaml" not in err
    assert "источник: состояние" not in err
