"""test_persistence.py — Тесты PersistenceManager.

Покрывает:
    1. Базовое сохранение после debounce
    2. 10 изменений → один save (debounce работает)
    3. shutdown → save_now() → всё сохранено
    4. load() → dict для TreeStore.merge()
    5. state-ветви НЕ сохраняются
    6. system.* → немедленный save (без ожидания debounce)
    7. Файлы создаются корректно на диске (YAML)
    8. load() + merge() → данные восстанавливаются в TreeStore
    9. Неизвестный prefix → не сохраняется, нет ошибок
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
import yaml

from multiprocess_prototype.state_store.core.delta import Delta, MISSING
from multiprocess_prototype.state_store.core.tree_store import TreeStore
from multiprocess_prototype.state_store.persistence.persistence_manager import PersistenceManager


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Временная папка для YAML-файлов."""
    return tmp_path / "state_data"


@pytest.fixture
def store() -> TreeStore:
    """Пустой TreeStore."""
    return TreeStore()


@pytest.fixture
def pm(store: TreeStore, tmp_data_dir: Path) -> PersistenceManager:
    """PersistenceManager с коротким debounce для тестов."""
    return PersistenceManager(store=store, data_dir=tmp_data_dir, debounce_seconds=0.1)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _make_delta(path: str, value: object = 42) -> Delta:
    """Создать дельту для тестов."""
    return Delta(path=path, old_value=MISSING, new_value=value, source="test")


def _fire_after_set(pm: PersistenceManager, path: str, value: object = 42) -> None:
    """Имитация срабатывания after_set middleware."""
    pm.middleware.after_set(_make_delta(path, value), context={})


# ---------------------------------------------------------------------------
# Тест 1: Базовое сохранение после debounce
# ---------------------------------------------------------------------------


def test_save_after_debounce(pm: PersistenceManager, store: TreeStore, tmp_data_dir: Path) -> None:
    """Изменение fps → через debounce → state_cameras.yaml обновлён."""
    store.set("cameras.0.config.fps", 30, source="test")
    _fire_after_set(pm, "cameras.0.config.fps", 30)

    # ждём debounce
    time.sleep(0.3)

    yaml_file = tmp_data_dir / "state_cameras.yaml"
    assert yaml_file.exists(), "state_cameras.yaml должен быть создан"

    with open(yaml_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert data is not None
    assert "cameras" in data
    assert data["cameras"]["0"]["config"]["fps"] == 30


# ---------------------------------------------------------------------------
# Тест 2: 10 изменений за 1с → один save (debounce)
# ---------------------------------------------------------------------------


def test_debounce_coalesces_multiple_changes(
    pm: PersistenceManager, store: TreeStore, tmp_data_dir: Path
) -> None:
    """Множественные изменения → debounce сбрасывается → один save в конце."""
    save_count = [0]

    # Патчим _save_file для подсчёта вызовов
    original_save = pm._save_file

    def counting_save(filename: str) -> None:
        save_count[0] += 1
        original_save(filename)

    pm._save_file = counting_save  # type: ignore[method-assign]

    # 10 изменений подряд с минимальной задержкой
    for i in range(10):
        store.set("cameras.0.config.fps", i, source="test")
        _fire_after_set(pm, "cameras.0.config.fps", i)
        time.sleep(0.01)  # 10мс между изменениями (меньше debounce 100мс)

    # ждём debounce
    time.sleep(0.3)

    # должен быть ровно 1 save для cameras
    assert save_count[0] == 1, (
        f"Ожидался 1 save, получено {save_count[0]} — debounce не работает"
    )


# ---------------------------------------------------------------------------
# Тест 3: shutdown → save_now() → всё сохранено
# ---------------------------------------------------------------------------


def test_shutdown_saves_dirty(
    pm: PersistenceManager, store: TreeStore, tmp_data_dir: Path
) -> None:
    """При shutdown → save_now() вызывается → файл сохраняется немедленно."""
    store.set("renderer.config.width", 1920, source="test")
    _fire_after_set(pm, "renderer.config.width", 1920)

    assert pm.is_dirty, "Должен быть dirty до shutdown"

    pm.shutdown()

    assert not pm.is_dirty, "После shutdown не должно быть dirty"

    yaml_file = tmp_data_dir / "state_renderer.yaml"
    assert yaml_file.exists(), "state_renderer.yaml должен быть создан"

    with open(yaml_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert data["renderer"]["config"]["width"] == 1920


# ---------------------------------------------------------------------------
# Тест 4: load() → dict для TreeStore.merge()
# ---------------------------------------------------------------------------


def test_load_returns_merged_dict(
    store: TreeStore, tmp_data_dir: Path
) -> None:
    """load() возвращает dict со всеми данными из YAML-файлов."""
    # Записываем данные вручную в YAML
    (tmp_data_dir).mkdir(parents=True, exist_ok=True)
    cameras_data = {"cameras": {"0": {"config": {"fps": 25, "type": "usb"}}}}
    robot_data = {"robot": {"config": {"speed": 100}}}

    with open(tmp_data_dir / "state_cameras.yaml", "w") as f:
        yaml.dump(cameras_data, f)
    with open(tmp_data_dir / "state_robot.yaml", "w") as f:
        yaml.dump(robot_data, f)

    pm = PersistenceManager(store=store, data_dir=tmp_data_dir, debounce_seconds=0.1)
    loaded = pm.load()

    assert "cameras" in loaded
    assert loaded["cameras"]["0"]["config"]["fps"] == 25
    assert "robot" in loaded
    assert loaded["robot"]["config"]["speed"] == 100


# ---------------------------------------------------------------------------
# Тест 5: state-ветви НЕ сохраняются
# ---------------------------------------------------------------------------


def test_state_branch_not_saved(
    pm: PersistenceManager, store: TreeStore, tmp_data_dir: Path
) -> None:
    """Изменения в *.state.* не должны приводить к сохранению."""
    store.set("cameras.0.state.status", "running", source="test")
    _fire_after_set(pm, "cameras.0.state.status", "running")

    # ждём дольше debounce
    time.sleep(0.3)

    assert not pm.is_dirty, "state-ветвь не должна быть dirty"

    yaml_file = tmp_data_dir / "state_cameras.yaml"
    assert not yaml_file.exists(), "state_cameras.yaml не должен быть создан для state-ветви"


# ---------------------------------------------------------------------------
# Тест 6: system.* → немедленный save (без debounce)
# ---------------------------------------------------------------------------


def test_system_saves_immediately(
    pm: PersistenceManager, store: TreeStore, tmp_data_dir: Path
) -> None:
    """Изменения system.* сохраняются немедленно, без ожидания debounce."""
    store.set("system.profile", "production", source="test")
    _fire_after_set(pm, "system.profile", "production")

    # НЕ ждём debounce — save должен быть уже сделан
    # небольшая пауза для выполнения save_now в том же потоке
    time.sleep(0.05)

    yaml_file = tmp_data_dir / "state_system.yaml"
    assert yaml_file.exists(), "state_system.yaml должен быть создан немедленно"

    with open(yaml_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert data["system"]["profile"] == "production"
    assert not pm.is_dirty, "После немедленного save не должно быть dirty"


# ---------------------------------------------------------------------------
# Тест 7: Корректный формат YAML-файлов на диске
# ---------------------------------------------------------------------------


def test_yaml_file_format(
    pm: PersistenceManager, store: TreeStore, tmp_data_dir: Path
) -> None:
    """Сохранённый YAML содержит валидный формат с prefix-ключом."""
    store.set("database.config.host", "localhost", source="test")
    store.set("database.config.port", 5432, source="test")
    _fire_after_set(pm, "database.config.host", "localhost")

    time.sleep(0.3)

    yaml_file = tmp_data_dir / "state_database.yaml"
    assert yaml_file.exists()

    with open(yaml_file, "r", encoding="utf-8") as f:
        content = f.read()
        f.seek(0)
        data = yaml.safe_load(f)

    # файл должен быть валидным YAML
    assert data is not None
    # должен содержать корневой ключ 'database'
    assert "database" in data
    # данные должны присутствовать
    assert data["database"]["config"]["host"] == "localhost"
    assert data["database"]["config"]["port"] == 5432


# ---------------------------------------------------------------------------
# Тест 8: load() + merge() восстанавливает данные в TreeStore
# ---------------------------------------------------------------------------


def test_load_and_merge_restores_state(
    tmp_data_dir: Path
) -> None:
    """Полный цикл: save → load() → merge() → данные в новом TreeStore."""
    store1 = TreeStore()
    pm1 = PersistenceManager(store=store1, data_dir=tmp_data_dir, debounce_seconds=0.1)

    # записываем данные
    store1.set("robot.config.speed", 150, source="test")
    store1.set("robot.config.enabled", True, source="test")
    _fire_after_set(pm1, "robot.config.speed", 150)
    _fire_after_set(pm1, "robot.config.enabled", True)

    # принудительный save
    pm1.save_now()

    # новый store + загрузка
    store2 = TreeStore()
    pm2 = PersistenceManager(store=store2, data_dir=tmp_data_dir, debounce_seconds=0.1)
    loaded = pm2.load()
    store2.merge("", loaded, source="load")

    assert store2.get("robot.config.speed") == 150
    assert store2.get("robot.config.enabled") is True


# ---------------------------------------------------------------------------
# Тест 9: Неизвестный prefix → не сохраняется, нет ошибок
# ---------------------------------------------------------------------------


def test_unknown_prefix_ignored(
    pm: PersistenceManager, store: TreeStore, tmp_data_dir: Path
) -> None:
    """Пути с неизвестным prefix не вызывают ошибок и не создают файлов."""
    _fire_after_set(pm, "unknown_module.config.value", 99)

    time.sleep(0.3)

    assert not pm.is_dirty, "Неизвестный prefix не должен быть dirty"

    # никакие новые файлы не должны появиться (папка может быть пустой)
    files = list(tmp_data_dir.glob("state_unknown*.yaml"))
    assert len(files) == 0, "Файл для неизвестного prefix не должен создаваться"


# ---------------------------------------------------------------------------
# Тест 10: regions-ветвь сохраняется
# ---------------------------------------------------------------------------


def test_regions_branch_saved(
    pm: PersistenceManager, store: TreeStore, tmp_data_dir: Path
) -> None:
    """cameras.*.regions.* сохраняются как часть конфигурации."""
    store.set("cameras.0.regions.zone1.x", 100, source="test")
    _fire_after_set(pm, "cameras.0.regions.zone1.x", 100)

    time.sleep(0.3)

    yaml_file = tmp_data_dir / "state_cameras.yaml"
    assert yaml_file.exists(), "state_cameras.yaml должен содержать regions"

    with open(yaml_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert data["cameras"]["0"]["regions"]["zone1"]["x"] == 100


# ---------------------------------------------------------------------------
# Тест 11: is_dirty — состояние флага
# ---------------------------------------------------------------------------


def test_is_dirty_flag(
    pm: PersistenceManager, store: TreeStore, tmp_data_dir: Path
) -> None:
    """is_dirty корректно отражает наличие несохранённых изменений."""
    assert not pm.is_dirty, "Изначально не dirty"

    _fire_after_set(pm, "cameras.0.config.fps", 30)
    assert pm.is_dirty, "После изменения должен быть dirty"

    pm.save_now()
    assert not pm.is_dirty, "После save_now не должен быть dirty"


# ---------------------------------------------------------------------------
# Тест 12: Несколько секций одновременно
# ---------------------------------------------------------------------------


def test_multiple_sections_saved(
    pm: PersistenceManager, store: TreeStore, tmp_data_dir: Path
) -> None:
    """Изменения в разных секциях → каждая секция сохраняется в свой файл."""
    store.set("cameras.0.config.fps", 30, source="test")
    store.set("renderer.config.width", 1280, source="test")
    store.set("robot.config.speed", 200, source="test")

    _fire_after_set(pm, "cameras.0.config.fps", 30)
    _fire_after_set(pm, "renderer.config.width", 1280)
    _fire_after_set(pm, "robot.config.speed", 200)

    pm.save_now()

    assert (tmp_data_dir / "state_cameras.yaml").exists()
    assert (tmp_data_dir / "state_renderer.yaml").exists()
    assert (tmp_data_dir / "state_robot.yaml").exists()
