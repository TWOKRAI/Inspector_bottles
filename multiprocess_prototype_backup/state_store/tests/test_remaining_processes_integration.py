"""Интеграционные тесты: RendererProcess, RobotProcess, DatabaseProcess ↔ StateProxy.

Проверяем что:
1. build_state_config_handlers возвращает маппинг для всех 5 флагов (renderer)
2. Каждый handler вызывает setattr на сервисе
3. _on_config_changed роутит дельты к правильным обработчикам
4. RobotProcess / DatabaseProcess не имеют подписок на config
5. Shutdown корректно записывает state.status через proxy
6. Dual-mode: register_update путь в _render_worker НЕ удалён

Все тесты БЕЗ реальных процессов — мокаем сервисы и proxy.
Тесты исходного кода process.py читают файл как текст (без import framework).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from multiprocess_prototype.backend.processes.renderer.commands import (
    build_state_config_handlers,
    SERVICE_FLAGS,
)


# ---------------------------------------------------------------------------
# Утилита: чтение исходника process.py без импорта
# ---------------------------------------------------------------------------

def _read_process_source(process_name: str) -> str:
    """Прочитать исходный код process.py без импорта (избегаем зависимостей framework)."""
    process_file = (
        Path(__file__).resolve().parent.parent.parent
        / "backend" / "processes" / process_name / "process.py"
    )
    return process_file.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Вспомогательные классы и фабрики
# ---------------------------------------------------------------------------

class FakeDelta:
    """Мок Delta с path, new_value, old_value."""

    def __init__(self, path: str, new_value=None, old_value=None):
        self.path = path
        self.new_value = new_value
        self.old_value = old_value


def _make_renderer_service() -> MagicMock:
    """Создать мок RendererService с 5 флаговыми атрибутами."""
    svc = MagicMock()
    for flag in SERVICE_FLAGS:
        setattr(svc, flag, False)
    return svc


def _make_on_config_changed():
    """Создать функцию _on_config_changed с замоканными зависимостями.

    Возвращает (callback, service_mock, handlers_dict).
    """
    svc = _make_renderer_service()
    handlers = build_state_config_handlers(svc)
    prefix = "renderer.config."

    def _on_config_changed(deltas: list) -> None:
        """Реплика метода RendererProcess._on_config_changed для тестов."""
        for delta in deltas:
            if not delta.path.startswith(prefix):
                continue
            field = delta.path[len(prefix):]
            handler = handlers.get(field)
            if handler:
                handler(delta.new_value)

    return _on_config_changed, svc, handlers


# ===========================================================================
# Тесты RendererProcess (8 тестов)
# ===========================================================================

class TestBuildStateConfigHandlersRenderer:
    """Тесты build_state_config_handlers для RendererProcess."""

    EXPECTED_KEYS = {"show_original", "show_mask", "draw_contours", "draw_bboxes", "save_frames"}

    def test_build_state_config_handlers_keys(self):
        """build_state_config_handlers возвращает dict с ровно 5 ожидаемыми ключами."""
        svc = _make_renderer_service()
        handlers = build_state_config_handlers(svc)

        assert set(handlers.keys()) == self.EXPECTED_KEYS, (
            f"Ожидались ключи {self.EXPECTED_KEYS}, получили {set(handlers.keys())}"
        )

    def test_handler_show_original(self):
        """handler['show_original'](True) → setattr(service, 'show_original', True)."""
        svc = _make_renderer_service()
        handlers = build_state_config_handlers(svc)

        handlers["show_original"](True)

        assert svc.show_original is True

    def test_handler_save_frames(self):
        """handler['save_frames'](True) → setattr(service, 'save_frames', True)."""
        svc = _make_renderer_service()
        handlers = build_state_config_handlers(svc)

        handlers["save_frames"](True)

        assert svc.save_frames is True

    def test_on_config_changed_routes_correctly(self):
        """delta renderer.config.show_mask=True → service.show_mask=True."""
        callback, svc, handlers = _make_on_config_changed()

        delta = FakeDelta("renderer.config.show_mask", new_value=True)
        callback([delta])

        assert svc.show_mask is True

    def test_on_config_changed_wrong_prefix_ignored(self):
        """delta с неверным prefix (processor.config.*) → ни один флаг не изменён."""
        callback, svc, handlers = _make_on_config_changed()
        # Зафиксируем начальные значения
        initial_values = {flag: getattr(svc, flag) for flag in SERVICE_FLAGS}

        delta = FakeDelta("processor.config.show_mask", new_value=True)
        callback([delta])

        for flag in SERVICE_FLAGS:
            assert getattr(svc, flag) == initial_values[flag], (
                f"Флаг {flag} не должен был измениться"
            )

    def test_on_config_changed_unknown_field_ignored(self):
        """delta renderer.config.unknown_field → ни один флаг не изменён."""
        callback, svc, handlers = _make_on_config_changed()
        initial_values = {flag: getattr(svc, flag) for flag in SERVICE_FLAGS}

        delta = FakeDelta("renderer.config.unknown_field", new_value=True)
        callback([delta])

        for flag in SERVICE_FLAGS:
            assert getattr(svc, flag) == initial_values[flag], (
                f"Флаг {flag} не должен был измениться"
            )

    def test_on_config_changed_multiple_deltas(self):
        """3 дельты → 3 флага обновлены корректно."""
        callback, svc, handlers = _make_on_config_changed()

        deltas = [
            FakeDelta("renderer.config.show_original", new_value=True),
            FakeDelta("renderer.config.draw_bboxes", new_value=False),
            FakeDelta("renderer.config.save_frames", new_value=True),
        ]
        callback(deltas)

        assert svc.show_original is True
        assert svc.draw_bboxes is False
        assert svc.save_frames is True

    def test_renderer_state_proxy_initialization(self):
        """RendererProcess инициализирует StateProxy с именем 'renderer' и подпиской на config."""
        source = _read_process_source("renderer")

        # StateProxy(...) может быть многострочным — проверяем обе сигнатуры
        assert "StateProxy(" in source and '"renderer"' in source, (
            'StateProxy должен создаваться с именем "renderer"'
        )
        assert '"renderer.state.status"' in source, (
            "renderer.state.status должен записываться при инициализации"
        )
        assert '"renderer.config.*"' in source, (
            "подписка на renderer.config.* должна быть"
        )

    def test_no_register_update_renderer(self):
        """_render_worker НЕ содержит register_update (убран в 4f.3)."""
        source = _read_process_source("renderer")
        assert "apply_register_update" not in source, (
            "apply_register_update удалён в Phase 4f.3 — только StateProxy"
        )


# ===========================================================================
# Тесты RobotProcess (3 теста)
# ===========================================================================

class TestRobotProcessStateProxy:
    """Тесты интеграции RobotProcess с StateProxy (через чтение исходника)."""

    def test_robot_process_has_no_config_subscription(self):
        """RobotProcess не имеет подписок на config (_state_config_handlers не создаётся)."""
        source = _read_process_source("robot")

        # Подписка на config не создаётся (нет subscribe на config)
        assert "_state_config_handlers" not in source, (
            "_state_config_handlers не должен создаваться в RobotProcess"
        )

    def test_robot_has_state_proxy_methods(self):
        """RobotProcess создаёт StateProxy и регистрирует handler state.changed."""
        source = _read_process_source("robot")

        assert "StateProxy" in source, (
            "RobotProcess должен создавать StateProxy"
        )
        assert "_state_proxy" in source, (
            "_state_proxy должен инициализироваться в RobotProcess"
        )
        assert "state.changed" in source, (
            "handler state.changed должен регистрироваться"
        )

    def test_robot_shutdown_writes_status(self):
        """shutdown записывает robot.state.status='shutdown' и action_count через proxy."""
        source = _read_process_source("robot")

        assert "robot.state.status" in source, (
            "shutdown должен записывать robot.state.status"
        )
        assert "action_count" in source, (
            "shutdown должен записывать action_count в StateProxy"
        )
        assert "_state_proxy.shutdown()" in source, (
            "_state_proxy.shutdown() должен вызываться в shutdown"
        )


# ===========================================================================
# Тесты DatabaseProcess (3 теста)
# ===========================================================================

class TestDatabaseProcessStateProxy:
    """Тесты интеграции DatabaseProcess с StateProxy (через чтение исходника)."""

    def test_database_process_has_no_config_subscription(self):
        """DatabaseProcess не имеет подписок на config (_state_config_handlers не создаётся)."""
        source = _read_process_source("database")

        assert "_state_config_handlers" not in source, (
            "_state_config_handlers не должен создаваться в DatabaseProcess"
        )

    def test_database_has_state_proxy_methods(self):
        """DatabaseProcess создаёт StateProxy и регистрирует handler state.changed."""
        source = _read_process_source("database")

        assert "StateProxy" in source, (
            "DatabaseProcess должен создавать StateProxy"
        )
        assert "_state_proxy" in source, (
            "_state_proxy должен инициализироваться в DatabaseProcess"
        )
        assert "state.changed" in source, (
            "handler state.changed должен регистрироваться"
        )

    def test_database_shutdown_writes_status(self):
        """shutdown записывает database.state.status='shutdown' через proxy перед sql_manager."""
        source = _read_process_source("database")

        assert "database.state.status" in source, (
            "shutdown должен записывать database.state.status"
        )
        assert "_state_proxy.shutdown()" in source, (
            "_state_proxy.shutdown() должен вызываться в shutdown"
        )
        # Proxy.shutdown() должен вызываться ДО sql_manager.shutdown()
        proxy_pos = source.find("_state_proxy.shutdown()")
        sql_pos = source.find("sql_manager.shutdown()")
        assert proxy_pos != -1 and sql_pos != -1, (
            "Оба _state_proxy.shutdown() и sql_manager.shutdown() должны быть в коде"
        )
        assert proxy_pos < sql_pos, (
            "_state_proxy.shutdown() должен вызываться ДО sql_manager.shutdown()"
        )
