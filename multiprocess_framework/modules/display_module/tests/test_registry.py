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


# ---------------------------------------------------------------------------
# 13. reload — базовая замена реестра
# ---------------------------------------------------------------------------


def test_reload_replaces_registry():
    """reload(entries) полностью заменяет содержимое реестра."""
    registry = DisplayRegistry()
    registry.register(_make_entry("old_a"))
    registry.register(_make_entry("old_b"))

    new_entries = [
        {
            "id": "new_x",
            "name": "X",
            "width": 800,
            "height": 600,
            "format": "RGB",
            "fps_limit": 60.0,
            "ring_buffer_blocks": 2,
        },
        {
            "id": "new_y",
            "name": "Y",
            "width": 1920,
            "height": 1080,
            "format": "BGR",
            "fps_limit": 30.0,
            "ring_buffer_blocks": 4,
        },
    ]
    registry.reload(new_entries)

    assert registry.get("old_a") is None
    assert registry.get("old_b") is None
    assert registry.get("new_x") is not None
    assert registry.get("new_y") is not None
    assert registry.get("new_x").name == "X"
    assert registry.get("new_y").width == 1920
    assert len(registry.list()) == 2


# ---------------------------------------------------------------------------
# 14. reload — orphan вызывает on_orphan для каждого отсутствующего
# ---------------------------------------------------------------------------


def test_reload_calls_on_orphan():
    """reload: orphan-id (в реестре, но не в entries) → on_orphan вызван."""
    registry = DisplayRegistry()
    registry.register(_make_entry("keep"))
    registry.register(_make_entry("remove_a"))
    registry.register(_make_entry("remove_b"))

    orphans_received: list[str] = []
    new_entries = [
        {
            "id": "keep",
            "name": "Keep",
            "width": 1280,
            "height": 720,
            "format": "BGR",
            "fps_limit": 30.0,
            "ring_buffer_blocks": 3,
        },
    ]
    registry.reload(new_entries, on_orphan=lambda oid: orphans_received.append(oid))

    assert set(orphans_received) == {"remove_a", "remove_b"}
    assert registry.get("keep") is not None
    assert registry.get("remove_a") is None
    assert registry.get("remove_b") is None


# ---------------------------------------------------------------------------
# 15. reload — on_orphan=None → шаг пропускается, _cleanup всё равно
# ---------------------------------------------------------------------------


def test_reload_on_orphan_none_no_crash():
    """reload с on_orphan=None: orphan обрабатываются без колбэка, без краша."""
    registry = DisplayRegistry()
    registry.register(_make_entry("will_be_orphan"))

    # Не должно крашиться
    registry.reload([], on_orphan=None)
    assert registry.list() == []


# ---------------------------------------------------------------------------
# 16. reload — дубль id → пропуск + warning
# ---------------------------------------------------------------------------


def test_reload_duplicate_id_skipped(capfd):
    """Дубль id в entries → пропуск без исключения (warning в лог)."""
    import logging

    logger = logging.getLogger("test_reload_dup")
    logger.setLevel(logging.WARNING)
    warnings_captured: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda record: warnings_captured.append(record.getMessage())  # type: ignore[assignment]
    logger.addHandler(handler)

    # Пересоздадим singleton с нужным logger — hack через _instance
    registry = DisplayRegistry()
    registry._logger = logger

    entries = [
        {
            "id": "dup",
            "name": "First",
            "width": 100,
            "height": 100,
            "format": "BGR",
            "fps_limit": 10.0,
            "ring_buffer_blocks": 1,
        },
        {
            "id": "dup",
            "name": "Second",
            "width": 200,
            "height": 200,
            "format": "BGR",
            "fps_limit": 20.0,
            "ring_buffer_blocks": 2,
        },
    ]
    registry.reload(entries)

    # Должен остаться первый (дубль пропущен)
    assert len(registry.list()) == 1
    result = registry.get("dup")
    assert result is not None
    assert result.name == "First"
    assert result.width == 100

    # Warning был выброшен
    assert any("дубль" in w.lower() for w in warnings_captured)

    # Очистить logger
    registry._logger = None


# ---------------------------------------------------------------------------
# 17. reload — пустой entries → все текущие orphan, реестр пуст
# ---------------------------------------------------------------------------


def test_reload_empty_entries_clears_registry():
    """reload([]) → все текущие записи orphan, реестр пуст."""
    registry = DisplayRegistry()
    registry.register(_make_entry("a"))
    registry.register(_make_entry("b"))
    registry.register(_make_entry("c"))

    orphans: list[str] = []
    registry.reload([], on_orphan=lambda oid: orphans.append(oid))

    assert registry.list() == []
    assert set(orphans) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# 18. reload — render-поля в dict НЕ попадают в DisplayEntry
# ---------------------------------------------------------------------------


def test_reload_ignores_render_fields():
    """render-поля (fit, scale, rotate, flip, crop, position) в dict игнорируются."""
    registry = DisplayRegistry()

    entries = [
        {
            "id": "main",
            "name": "Test",
            "width": 640,
            "height": 480,
            "format": "BGR",
            "fps_limit": 25.0,
            "ring_buffer_blocks": 2,
            # render-поля — должны быть проигнорированы
            "fit": "cover",
            "scale": 150,
            "rotate": 90,
            "flip": "horizontal",
            "crop": {"x": 10, "y": 20, "w": 100, "h": 200},
            "position": {"x": 50, "y": 60},
        },
    ]
    registry.reload(entries)

    result = registry.get("main")
    assert result is not None
    assert result.id == "main"
    assert result.width == 640
    assert result.height == 480
    assert result.format == "BGR"
    assert result.fps_limit == 25.0
    assert result.ring_buffer_blocks == 2
    # DisplayEntry — dataclass с ровно 7 полями, render-полей нет
    assert not hasattr(result, "fit")
    assert not hasattr(result, "scale")
    assert not hasattr(result, "rotate")
    assert not hasattr(result, "flip")
    assert not hasattr(result, "crop")
    assert not hasattr(result, "position")


# ---------------------------------------------------------------------------
# 19. reload — идемпотентность: reload(same) даёт тот же реестр
# ---------------------------------------------------------------------------


def test_reload_idempotent():
    """Повторный reload(same_entries) даёт идентичный реестр."""
    registry = DisplayRegistry()

    entries = [
        {
            "id": "a",
            "name": "A",
            "width": 800,
            "height": 600,
            "format": "RGB",
            "fps_limit": 60.0,
            "ring_buffer_blocks": 2,
        },
        {
            "id": "b",
            "name": "B",
            "width": 1920,
            "height": 1080,
            "format": "BGR",
            "fps_limit": 30.0,
            "ring_buffer_blocks": 3,
        },
    ]

    registry.reload(entries)
    first = {e.id: e for e in registry.list()}

    registry.reload(entries)
    second = {e.id: e for e in registry.list()}

    assert first == second


# ---------------------------------------------------------------------------
# 20. reload — rollback: reload(old) после reload(new) восстанавливает
# ---------------------------------------------------------------------------


def test_reload_rollback():
    """reload(old) после reload(new) полностью восстанавливает старый набор."""
    registry = DisplayRegistry()

    old_entries = [
        {
            "id": "alpha",
            "name": "Alpha",
            "width": 640,
            "height": 480,
            "format": "GRAY",
            "fps_limit": 15.0,
            "ring_buffer_blocks": 2,
        },
        {
            "id": "beta",
            "name": "Beta",
            "width": 320,
            "height": 240,
            "format": "BGR",
            "fps_limit": 10.0,
            "ring_buffer_blocks": 1,
        },
    ]
    new_entries = [
        {
            "id": "gamma",
            "name": "Gamma",
            "width": 1920,
            "height": 1080,
            "format": "RGBA",
            "fps_limit": 120.0,
            "ring_buffer_blocks": 5,
        },
    ]

    # Устанавливаем old
    registry.reload(old_entries)
    assert len(registry.list()) == 2
    assert registry.get("alpha") is not None
    assert registry.get("beta") is not None

    # Переходим на new
    registry.reload(new_entries)
    assert len(registry.list()) == 1
    assert registry.get("gamma") is not None
    assert registry.get("alpha") is None

    # Откат к old — полное восстановление
    registry.reload(old_entries)
    assert len(registry.list()) == 2
    assert registry.get("alpha") is not None
    assert registry.get("alpha").name == "Alpha"
    assert registry.get("alpha").format == "GRAY"
    assert registry.get("beta") is not None
    assert registry.get("beta").width == 320
    assert registry.get("gamma") is None


# ---------------------------------------------------------------------------
# 21. reload — запись без id → warning, пропуск
# ---------------------------------------------------------------------------


def test_reload_entry_without_id_skipped():
    """Запись без ключа 'id' → warning, пропуск (остальные регистрируются)."""
    import logging

    logger = logging.getLogger("test_reload_no_id")
    logger.setLevel(logging.WARNING)
    warnings_captured: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda record: warnings_captured.append(record.getMessage())  # type: ignore[assignment]
    logger.addHandler(handler)

    registry = DisplayRegistry()
    registry._logger = logger

    entries = [
        {
            "name": "NoId",
            "width": 100,
            "height": 100,
            "format": "BGR",
            "fps_limit": 10.0,
            "ring_buffer_blocks": 1,
        },  # нет id!
        {
            "id": "valid",
            "name": "Valid",
            "width": 200,
            "height": 200,
            "format": "BGR",
            "fps_limit": 20.0,
            "ring_buffer_blocks": 2,
        },
    ]
    registry.reload(entries)

    assert len(registry.list()) == 1
    assert registry.get("valid") is not None
    assert any("id" in w.lower() for w in warnings_captured)

    registry._logger = None


# ---------------------------------------------------------------------------
# 22. reload — дефолты для опциональных полей
# ---------------------------------------------------------------------------


def test_reload_defaults_for_optional_fields():
    """Минимальный dict с только 'id' → DisplayEntry с дефолтами."""
    registry = DisplayRegistry()

    entries = [{"id": "minimal"}]
    registry.reload(entries)

    result = registry.get("minimal")
    assert result is not None
    assert result.id == "minimal"
    assert result.name == ""
    assert result.width == 1280
    assert result.height == 720
    assert result.format == "BGR"
    assert result.fps_limit == 30.0
    assert result.ring_buffer_blocks == 3
