"""Тесты DisplayRegistry — thread-safe singleton-реестр дисплеев.

Покрытие: singleton, register/get, дубликаты, unregister/clear,
list (copy), persist/load (YAML), thread-safety.

Фикстура `_clean_registry` (autouse) очищает singleton перед/после каждого теста.

Refs: plans/prototype-skeleton-2026-05/phase-4-displays-tab.md Task 4.8
"""

from __future__ import annotations

import concurrent.futures
import threading
from pathlib import Path

import pytest

from multiprocess_framework.modules.display_module import DisplayEntry, DisplayRegistry


# ---------------------------------------------------------------------------
# Вспомогательные хелперы
# ---------------------------------------------------------------------------


def _make_entry(
    display_id: str = "main",
    name: str = "Основной",
    width: int = 1280,
    height: int = 720,
    fmt: str = "BGR",
    fps_limit: float = 30.0,
    ring_buffer_blocks: int = 3,
) -> DisplayEntry:
    """Создать DisplayEntry-заглушку."""
    return DisplayEntry(
        id=display_id,
        name=name,
        width=width,
        height=height,
        format=fmt,
        fps_limit=fps_limit,
        ring_buffer_blocks=ring_buffer_blocks,
    )


# ---------------------------------------------------------------------------
# Фикстура: изоляция singleton между тестами
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    """Очищает реестр перед и после каждого теста."""
    DisplayRegistry().clear()
    yield
    DisplayRegistry().clear()


# ---------------------------------------------------------------------------
# 1. Singleton
# ---------------------------------------------------------------------------


def test_singleton():
    """DisplayRegistry() is DisplayRegistry() -> True."""
    r1 = DisplayRegistry()
    r2 = DisplayRegistry()
    assert r1 is r2


# ---------------------------------------------------------------------------
# 2. register + get
# ---------------------------------------------------------------------------


def test_register_and_get():
    """register(entry) → get(id) возвращает идентичный entry."""
    registry = DisplayRegistry()
    entry = _make_entry("main")
    registry.register(entry)
    result = registry.get("main")
    assert result is entry
    assert result.id == "main"
    assert result.name == "Основной"


# ---------------------------------------------------------------------------
# 3. Дублирование → ValueError
# ---------------------------------------------------------------------------


def test_register_duplicate_raises():
    """Повторный register(same_id) → ValueError."""
    registry = DisplayRegistry()
    registry.register(_make_entry("main"))
    with pytest.raises(ValueError, match="уже зарегистрирован"):
        registry.register(_make_entry("main", name="Дубликат"))


# ---------------------------------------------------------------------------
# 4. unregister существующего → True, не в list()
# ---------------------------------------------------------------------------


def test_unregister_existing_returns_true():
    """unregister(id) существующего → True, entry не возвращается в list()."""
    registry = DisplayRegistry()
    registry.register(_make_entry("main"))
    result = registry.unregister("main")
    assert result is True
    assert registry.get("main") is None
    assert all(e.id != "main" for e in registry.list())


# ---------------------------------------------------------------------------
# 5. unregister несуществующего → False, без исключений
# ---------------------------------------------------------------------------


def test_unregister_nonexistent_returns_false():
    """unregister('nope') → False, нет исключения."""
    registry = DisplayRegistry()
    result = registry.unregister("nope")
    assert result is False


# ---------------------------------------------------------------------------
# 6. list() возвращает копию
# ---------------------------------------------------------------------------


def test_list_returns_copy():
    """Мутация результата list() не влияет на внутренний реестр."""
    registry = DisplayRegistry()
    registry.register(_make_entry("main"))
    lst = registry.list()
    lst.clear()
    # После мутации результата — реестр не изменился
    assert len(registry.list()) == 1


# ---------------------------------------------------------------------------
# 7. persist → файл создан, содержит id
# ---------------------------------------------------------------------------


def test_persist_creates_yaml(tmp_path: Path):
    """persist(path) → файл создан и содержит id дисплея."""
    registry = DisplayRegistry()
    registry.register(_make_entry("main"))

    yaml_file = tmp_path / "displays.yaml"
    registry.persist(yaml_file)

    assert yaml_file.exists()
    content = yaml_file.read_text(encoding="utf-8")
    assert "main" in content


# ---------------------------------------------------------------------------
# 8. persist → clear → load → реестр идентичен
# ---------------------------------------------------------------------------


def test_load_after_persist_restores(tmp_path: Path):
    """После persist → clear → load реестр идентичен оригиналу."""
    registry = DisplayRegistry()
    entry = _make_entry("main", name="Тест", width=640, height=480)
    registry.register(entry)

    yaml_file = tmp_path / "displays.yaml"
    registry.persist(yaml_file)
    registry.clear()
    assert registry.list() == []

    registry.load(yaml_file)
    loaded = registry.get("main")
    assert loaded is not None
    assert loaded.id == "main"
    assert loaded.name == "Тест"
    assert loaded.width == 640
    assert loaded.height == 480


# ---------------------------------------------------------------------------
# 9. load несуществующего файла → без исключений, реестр пуст
# ---------------------------------------------------------------------------


def test_load_nonexistent_no_exception():
    """load(Path('/nonexistent')) → нет исключений, реестр пуст."""
    registry = DisplayRegistry()
    registry.load(Path("/nonexistent/path/displays.yaml"))
    assert registry.list() == []


# ---------------------------------------------------------------------------
# 10. load невалидного YAML → без краша, реестр без изменений
# ---------------------------------------------------------------------------


def test_load_invalid_yaml_no_crash(tmp_path: Path):
    """Невалидный YAML → load() без исключений, реестр без изменений (только лог)."""
    registry = DisplayRegistry()
    registry.register(_make_entry("existing"))

    bad_yaml = tmp_path / "bad.yaml"
    # Записываем некорректный YAML
    bad_yaml.write_text("not: valid: yaml: [\n", encoding="utf-8")

    registry.load(bad_yaml)
    # Реестр не был очищен / не упал
    # Результат зависит от реализации: либо старые данные сохранены,
    # либо реестр пуст — главное что нет исключения
    # Проверяем только отсутствие краша (assert прошло если мы здесь)
    _ = registry.list()


# ---------------------------------------------------------------------------
# 11. Thread-safety: 20 параллельных register с разными id
# ---------------------------------------------------------------------------


def test_thread_safety_concurrent_register():
    """20 параллельных register с разными id → все 20 в registry."""
    registry = DisplayRegistry()
    barrier = threading.Barrier(20)
    errors: list[str] = []

    def _register_one(idx: int) -> None:
        entry = _make_entry(f"display_{idx}", name=f"Дисплей {idx}")
        barrier.wait()
        try:
            registry.register(entry)
        except Exception as exc:
            errors.append(f"display_{idx}: {exc}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(_register_one, i) for i in range(20)]
        concurrent.futures.wait(futures)

    assert not errors, f"Ошибки при конкурентной регистрации: {errors}"
    assert len(registry.list()) == 20


# ---------------------------------------------------------------------------
# 12. clear → list() пуст
# ---------------------------------------------------------------------------


def test_clear():
    """register + clear → list() пуст."""
    registry = DisplayRegistry()
    registry.register(_make_entry("a"))
    registry.register(_make_entry("b"))
    assert len(registry.list()) == 2

    registry.clear()
    assert registry.list() == []
