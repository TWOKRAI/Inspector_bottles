# multiprocess_prototype_v3/tests/unit/test_recipes_auto_save.py
"""Unit-тесты `RecipeAutoSave` — debounce + ротация версий (Phase 1, Task 1.3)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
import yaml

from multiprocess_prototype_v3.frontend.widgets.recipes_widget.auto_save import (
    AutoSaveConfig,
    RecipeAutoSave,
)


class FakeRecipeManager:
    """Мок RecipeManager: пишет slot → `_data_path`, учитывает вызовы."""

    def __init__(self, data_path: Path) -> None:
        self._data_path = data_path
        self.saves: list[tuple[str, dict[str, Any]]] = []

    def save_slot(self, slot_id: str, snapshot: dict[str, Any]) -> bool:
        self.saves.append((slot_id, snapshot))
        self._data_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {slot_id: snapshot}
        # Читаем текущее содержимое (если есть) и мерджим, как делает реальный RecipeManager.
        if self._data_path.is_file():
            existing = yaml.safe_load(self._data_path.read_text(encoding="utf-8")) or {}
            if isinstance(existing, dict):
                existing.update(payload)
                payload = existing
        self._data_path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        return True


@pytest.fixture()
def data_path(tmp_path: Path) -> Path:
    return tmp_path / "recipes.yaml"


@pytest.fixture()
def mgr(data_path: Path) -> FakeRecipeManager:
    return FakeRecipeManager(data_path)


def _builder(mgr: FakeRecipeManager, slot: str, snapshot: dict[str, Any], config: AutoSaveConfig | None = None):
    return RecipeAutoSave(
        recipe_manager=mgr,
        slot_getter=lambda: slot,
        rm_snapshot_fn=lambda: dict(snapshot),
        config=config,
    )


class TestFlush:
    def test_flush_writes_snapshot_immediately(self, mgr: FakeRecipeManager) -> None:
        auto = _builder(mgr, "1", {"a": 1})
        assert auto.flush() is True
        assert mgr.saves == [("1", {"a": 1})]

    def test_snapshot_is_deep_copied_before_write(self, mgr: FakeRecipeManager) -> None:
        snapshot = {"nested": {"k": 42}}
        auto = RecipeAutoSave(
            recipe_manager=mgr,
            slot_getter=lambda: "x",
            rm_snapshot_fn=lambda: snapshot,
        )
        auto.flush()
        snapshot["nested"]["k"] = 999
        assert mgr.saves[0][1]["nested"]["k"] == 42


class TestScheduleDebounce:
    def test_schedule_fires_after_debounce(self, mgr: FakeRecipeManager) -> None:
        auto = _builder(mgr, "1", {"v": 1}, AutoSaveConfig(debounce_sec=0.05))
        auto.schedule()
        time.sleep(0.15)
        assert len(mgr.saves) == 1

    def test_double_schedule_in_window_produces_single_save(self, mgr: FakeRecipeManager) -> None:
        auto = _builder(mgr, "1", {"v": 1}, AutoSaveConfig(debounce_sec=0.1))
        auto.schedule()
        time.sleep(0.03)
        auto.schedule()
        time.sleep(0.2)
        assert len(mgr.saves) == 1

    def test_cancel_prevents_save(self, mgr: FakeRecipeManager) -> None:
        auto = _builder(mgr, "1", {"v": 1}, AutoSaveConfig(debounce_sec=0.2))
        auto.schedule()
        time.sleep(0.05)
        auto.cancel()
        time.sleep(0.3)
        assert mgr.saves == []


class TestVersioning:
    def test_first_save_creates_v1(self, mgr: FakeRecipeManager, data_path: Path) -> None:
        # Первый вызов: файла ещё нет → архивация пропускается.
        auto = _builder(mgr, "prod", {"value": 1})
        assert auto.flush() is True
        versions = data_path.parent / "versions"
        assert not versions.exists() or not list(versions.iterdir())

        # Второй вызов: файл уже есть → копия становится prod.v1.yaml
        auto_b = _builder(mgr, "prod", {"value": 2})
        auto_b.flush()
        files = sorted((data_path.parent / "versions").iterdir())
        assert [f.name for f in files] == ["prod.v1.yaml"]

    def test_rotation_trims_to_max_versions(self, mgr: FakeRecipeManager, data_path: Path) -> None:
        config = AutoSaveConfig(max_versions=2)
        # 1-й save: создаёт файл (без архивации).
        _builder(mgr, "prod", {"v": 1}, config).flush()
        # Последующие 4 save'а — 4 архива, но храним только последние 2.
        for i in range(2, 6):
            _builder(mgr, "prod", {"v": i}, config).flush()
        versions = sorted((data_path.parent / "versions").iterdir(), key=lambda p: p.name)
        names = [f.name for f in versions]
        assert len(names) == 2
        assert names == ["prod.v3.yaml", "prod.v4.yaml"]

    def test_sanitized_slot_id_in_filename(self, mgr: FakeRecipeManager, data_path: Path) -> None:
        _builder(mgr, "A/B C", {"x": 1}).flush()  # создать файл
        _builder(mgr, "A/B C", {"x": 2}).flush()  # + v1
        versions = list((data_path.parent / "versions").iterdir())
        assert len(versions) == 1
        assert versions[0].name == "A_B_C.v1.yaml"


class TestNoDataPath:
    def test_without_data_path_attr_rotation_skipped(self, tmp_path: Path) -> None:
        class MinimalMgr:
            def save_slot(self, slot_id: str, snapshot: dict[str, Any]) -> bool:
                return True

        auto = RecipeAutoSave(
            recipe_manager=MinimalMgr(),
            slot_getter=lambda: "x",
            rm_snapshot_fn=lambda: {"k": 1},
        )
        # Не должен упасть, даже если _data_path отсутствует.
        assert auto.flush() is True
