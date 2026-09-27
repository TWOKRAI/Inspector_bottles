# -*- coding: utf-8 -*-
"""Тесты yaml_io.update_yaml_preserving — запись YAML с сохранением комментариев.

Home-тест generic-writer'а модуля `recipe` (C3, ADR-RCP-005). Покрывает:
  - persist scalar `pipeline:` в app.yaml без потери комментариев;
  - обновление top-level `blueprint` с сохранением заголовка;
  - точечный persist `blueprint.metadata.*` без порчи per-node комментариев.
"""

from __future__ import annotations

import textwrap

import yaml

from multiprocess_framework.modules.recipe.yaml_io import (
    update_blueprint_metadata_preserving,
    update_yaml_preserving,
)


def test_creates_new_file_from_updates(tmp_path):
    """Несуществующий файл создаётся из updates."""
    path = tmp_path / "new.yaml"
    update_yaml_preserving(path, {"name": "demo", "version": 3})

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data == {"name": "demo", "version": 3}


def test_preserves_header_comment_on_scalar_update(tmp_path):
    """persist: обновление pipeline: сохраняет комментарии и прочие ключи."""
    path = tmp_path / "app.yaml"
    path.write_text(
        textwrap.dedent(
            """\
            # Главный конфиг — комментарий-заголовок.
            system: backend/config/system.yaml
            # Активный pipeline (рецепт).
            pipeline: recipes/old.yaml
            recipes: recipes
            """
        ),
        encoding="utf-8",
    )

    update_yaml_preserving(path, {"pipeline": "recipes/color_inspect.yaml"})

    text = path.read_text(encoding="utf-8")
    assert "# Главный конфиг — комментарий-заголовок." in text
    assert "# Активный pipeline (рецепт)." in text
    assert "pipeline: recipes/color_inspect.yaml" in text
    assert "recipes: recipes" in text  # прочие ключи не тронуты
    assert "old.yaml" not in text  # старое значение заменено


def test_updates_only_named_keys(tmp_path):
    """Обновляются только переданные top-level ключи; остальные сохраняются."""
    path = tmp_path / "recipe.yaml"
    path.write_text(
        textwrap.dedent(
            """\
            # Рецепт-заголовок.
            name: demo
            version: 3
            description: "Описание"
            blueprint:
              processes: []
              wires: []
            active_services:
              - svc_a
            """
        ),
        encoding="utf-8",
    )

    update_yaml_preserving(
        path,
        {"blueprint": {"processes": [{"process_name": "p1"}], "wires": [], "displays": []}},
    )

    text = path.read_text(encoding="utf-8")
    assert "# Рецепт-заголовок." in text  # заголовок сохранён
    data = yaml.safe_load(text)
    assert data["name"] == "demo"  # не тронут
    assert data["version"] == 3
    assert data["active_services"] == ["svc_a"]  # не тронут
    assert data["blueprint"]["processes"][0]["process_name"] == "p1"  # обновлён


# ---------------------------------------------------------------------------
# update_blueprint_metadata_preserving — free-layout авто-персист
# ---------------------------------------------------------------------------


def _recipe_with_comments() -> str:
    return textwrap.dedent(
        """\
        # Рецепт-заголовок (free-layout).
        name: demo
        version: 3
        blueprint:
          name: demo
          # --- Камера ---
          processes:
            - process_name: camera_0
              plugins:
                - plugin_name: capture
          # --- Провода ---
          wires:
            - source: a
              target: b
        """
    )


def test_metadata_write_preserves_inner_comments(tmp_path):
    """free-layout: запись blueprint.metadata НЕ стирает комментарии внутри blueprint."""
    path = tmp_path / "recipe.yaml"
    path.write_text(_recipe_with_comments(), encoding="utf-8")

    update_blueprint_metadata_preserving(
        path,
        {"gui_positions": {"camera_0.capture": [10.0, 20.0]}, "locked_nodes": ["camera_0.capture"]},
    )

    text = path.read_text(encoding="utf-8")
    # Комментарии (заголовок + per-node ВНУТРИ blueprint) сохранены
    assert "# Рецепт-заголовок (free-layout)." in text
    assert "# --- Камера ---" in text
    assert "# --- Провода ---" in text
    data = yaml.safe_load(text)
    # processes/wires не тронуты
    assert data["blueprint"]["processes"][0]["process_name"] == "camera_0"
    assert data["blueprint"]["wires"][0] == {"source": "a", "target": "b"}
    # metadata записан
    assert data["blueprint"]["metadata"]["gui_positions"]["camera_0.capture"] == [10.0, 20.0]
    assert data["blueprint"]["metadata"]["locked_nodes"] == ["camera_0.capture"]


def test_metadata_write_replaces_gui_positions_wholesale(tmp_path):
    """Повторная запись заменяет gui_positions целиком (не копит устаревшие ноды)."""
    path = tmp_path / "recipe.yaml"
    path.write_text(_recipe_with_comments(), encoding="utf-8")

    update_blueprint_metadata_preserving(path, {"gui_positions": {"old.node": [1.0, 2.0]}, "locked_nodes": []})
    update_blueprint_metadata_preserving(path, {"gui_positions": {"new.node": [3.0, 4.0]}, "locked_nodes": []})

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    gp = data["blueprint"]["metadata"]["gui_positions"]
    assert "old.node" not in gp  # устаревшая нода не осталась
    assert gp["new.node"] == [3.0, 4.0]


def test_metadata_write_noop_without_blueprint(tmp_path):
    """raw-topology без вложенного blueprint — no-op (layout писать некуда)."""
    path = tmp_path / "raw.yaml"
    path.write_text("processes: []\nwires: []\n", encoding="utf-8")

    update_blueprint_metadata_preserving(path, {"gui_positions": {"x": [1.0, 2.0]}, "locked_nodes": []})

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "metadata" not in data  # ничего не добавлено
    assert data == {"processes": [], "wires": []}


def test_metadata_write_noop_missing_file(tmp_path):
    """Несуществующий файл — no-op без исключения."""
    update_blueprint_metadata_preserving(tmp_path / "ghost.yaml", {"gui_positions": {}, "locked_nodes": []})
    assert not (tmp_path / "ghost.yaml").exists()


# ---------------------------------------------------------------------------
# AU-1 граница: update_yaml_preserving НЕ удаляет отсутствующие ключи
# ---------------------------------------------------------------------------


def test_update_yaml_preserving_keeps_legacy_top_level_gui_positions(tmp_path):
    """Честная фиксация границы AU-1: writer НЕ удаляет legacy top-level gui_positions.

    normalize_recipe_v3_raw возвращает dict БЕЗ top-level gui_positions, но
    update_yaml_preserving мержит только присутствующие в updates ключи и НЕ трёт
    отсутствующие (сохранность комментариев). Значит на диске уже лежащий legacy-дубль
    ПЕРЕЖИВАЕТ Save — его удаляет только миграция canonicalize_gui_positions, а не Save.
    """
    from multiprocess_framework.modules.recipe.format import normalize_recipe_v3_raw

    path = tmp_path / "legacy.yaml"
    path.write_text(
        textwrap.dedent(
            """\
            name: legacy
            version: 3
            blueprint:
              processes: []
            gui_positions:
              stale.node: [1.0, 2.0]
            """
        ),
        encoding="utf-8",
    )

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    normalized = normalize_recipe_v3_raw(raw, {"processes": [], "wires": [], "displays": []})
    assert "gui_positions" not in normalized  # pure-функция дубль не возвращает

    update_yaml_preserving(path, normalized)

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    # Фактическое поведение: top-level дубль на диске ОСТАЛСЯ (writer не удаляет).
    assert data["gui_positions"] == {"stale.node": [1.0, 2.0]}


# ---------------------------------------------------------------------------
# Атомарность записи (line-sim-layer-editor, Task 1.2a, ревью it.1): запись идёт
# через service._atomic_write — сбой посреди записи оставляет старый файл и не
# оставляет tmp рядом; права файла не меняются; комментарии нетронутых ключей живы.
# ---------------------------------------------------------------------------

_COMMENTED = textwrap.dedent(
    """\
    # заголовок файла
    name: demo  # имя
    # комментарий перед version
    version: 3
    """
)


def test_update_yaml_preserving_is_atomic_on_failure(tmp_path, monkeypatch):
    """Сбой ПОСЛЕ записи байт во tmp (fsync / replace): файл побайтно прежний, в каталоге
    только он сам. Прежняя запись ``open("w")`` усекала файл до сериализации — здесь было бы
    пусто/полфайла или (при сбое replace) прежний файл, но без гарантии на fsync-сбое."""
    import os

    path = tmp_path / "r.yaml"
    path.write_text(_COMMENTED, encoding="utf-8")
    before = path.read_bytes()

    for target in ("fsync", "replace"):

        def boom(*_a, _t=target, **_k):
            raise OSError(f"injected {_t}")

        with monkeypatch.context() as m:
            m.setattr(os, target, boom)
            try:
                update_yaml_preserving(path, {"version": 4})
            except OSError as exc:
                assert f"injected {target}" in str(exc)
            else:
                raise AssertionError(f"сбой {target} не дошёл до вызывающего")
        assert path.read_bytes() == before, target
        assert sorted(p.name for p in tmp_path.iterdir()) == ["r.yaml"], target


def test_update_yaml_preserving_serialization_failure_leaves_file_untouched(tmp_path):
    """Непредставимое значение (ruamel RepresenterError) — до открытия файла: файл цел."""
    path = tmp_path / "r.yaml"
    path.write_text(_COMMENTED, encoding="utf-8")
    before = path.read_bytes()
    try:
        update_yaml_preserving(path, {"version": object()})
    except Exception:  # noqa: BLE001 — тип ошибки ruamel не контракт; контракт — файл цел
        pass
    else:
        raise AssertionError("object() неожиданно сериализовался")
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["r.yaml"]


def test_update_yaml_preserving_keeps_file_mode(tmp_path):
    """mkstemp создаёт tmp с 0600 — после записи mode файла прежний (0644 и 0640)."""
    import os
    import stat

    path = tmp_path / "r.yaml"
    for mode in (0o644, 0o640):
        path.write_text(_COMMENTED, encoding="utf-8")
        os.chmod(path, mode)
        update_yaml_preserving(path, {"version": 4})
        assert stat.S_IMODE(path.stat().st_mode) == mode
        assert yaml.safe_load(path.read_text(encoding="utf-8"))["version"] == 4


def test_update_yaml_preserving_new_file_mode_follows_umask(tmp_path):
    """Новый файл — mode как у обычного ``open("w")`` (0666 & ~umask), не 0600 от mkstemp."""
    import stat

    probe = tmp_path / "probe"
    probe.write_text("x", encoding="utf-8")
    expected = stat.S_IMODE(probe.stat().st_mode)
    path = tmp_path / "new.yaml"
    update_yaml_preserving(path, {"name": "n"})
    assert stat.S_IMODE(path.stat().st_mode) == expected


def test_update_yaml_preserving_keeps_comments_through_atomic_path(tmp_path):
    """Комментарии нетронутых ключей переживают атомарную запись (буфер -> tmp -> replace)."""
    path = tmp_path / "r.yaml"
    path.write_text(_COMMENTED, encoding="utf-8")
    update_yaml_preserving(path, {"version": 4})
    text = path.read_text(encoding="utf-8")
    for comment in ("# заголовок файла", "# имя", "# комментарий перед version"):
        assert comment in text
    assert "version: 4" in text


def test_update_yaml_preserving_writes_through_symlink(tmp_path):
    """Ревью 1.2a it.2, F1: симлинк остаётся симлинком, обновляется его цель (как прежний open("w"))."""
    target = tmp_path / "real.yaml"
    target.write_text(_COMMENTED, encoding="utf-8")
    link = tmp_path / "link.yaml"
    link.symlink_to(target)
    update_yaml_preserving(link, {"version": 4})
    assert link.is_symlink()
    assert yaml.safe_load(target.read_text(encoding="utf-8"))["version"] == 4


def test_update_yaml_preserving_read_only_file_raises_and_keeps_bytes(tmp_path):
    """Ревью 1.2a it.2, F1: файл 0444 — PermissionError, байты те же (атомарная замена
    иначе перезаписала бы его молча — прав на каталог ей достаточно)."""
    import os

    import pytest

    path = tmp_path / "r.yaml"
    path.write_text(_COMMENTED, encoding="utf-8")
    before = path.read_bytes()
    os.chmod(path, 0o444)
    try:
        with pytest.raises(PermissionError):
            update_yaml_preserving(path, {"version": 4})
        assert path.read_bytes() == before
    finally:
        os.chmod(path, 0o644)
