# -*- coding: utf-8 -*-
"""Тесты кнопки «Запустить активный рецепт» — PipelinePresenter.launch_active_recipe.

Task E.1 -> F.4: мигрировано на RecipeStore Protocol (FakeRecipeStore).
command-result-bridge P3: async request/response + НЕ-модальный feedback через
notify-callback (статус-строка + лог), без блокирующих QMessageBox.

Запуск:
    python -m pytest multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_launch_recipe.py -v
"""

from __future__ import annotations

from multiprocess_prototype.domain.tests._fakes import FakeRecipeStore
from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import (
    PipelinePresenter,
)

from ._helpers import make_pipeline_services


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


_SENTINEL = object()


def _make_recipe_store(
    active_slug: str | None = "my_recipe",
    recipe_data=_SENTINEL,
) -> FakeRecipeStore:
    """Создать FakeRecipeStore с нужным поведением."""
    raw: dict[str, dict] = {}
    if active_slug is not None:
        if recipe_data is _SENTINEL:
            raw[active_slug] = {
                "meta": {"name": active_slug},
                "data": {
                    "blueprint": {
                        "processes": [{"process_name": "proc1"}],
                        "wires": [],
                    }
                },
            }
        elif recipe_data is not None:
            raw[active_slug] = recipe_data
        # recipe_data=None -> slug в active но raw пуст (read_raw вернёт None)
    return FakeRecipeStore(raw=raw, active=active_slug)


def _make_services(store: FakeRecipeStore, config_extra: dict | None = None):
    """Создать AppServices с FakeRecipeStore."""
    services = make_pipeline_services(config_extra=config_extra)
    object.__setattr__(services, "recipes", store)
    return services


def _make_presenter(store, proxy=None):
    """PipelinePresenter с notify-spy. Возвращает (presenter, messages)."""
    messages: list[str] = []
    services = _make_services(store)
    presenter = PipelinePresenter(services, notify=messages.append, process_manager_proxy=proxy)
    return presenter, messages


class _FakeAsyncProxy:
    """Fake ProcessManagerProxy с async request/response.

    Синхронно зовёт ``on_result`` заготовленным ответом — детерминизм в
    unit-тесте. Реальная доставка результата с worker-потока в main-thread
    покрыта тестами RequestRunner (P2), здесь проверяется только рендеринг
    результата презентером.

    Task 4.1: использует apply_topology(source, on_result=...) вместо
    replace_blueprint_async.
    """

    def __init__(self, response: dict | None = None, raise_exc: Exception | None = None) -> None:
        self._response = (
            response if response is not None else {"success": True, "result": {"success": True, "replaced": []}}
        )
        self._raise = raise_exc
        self.blueprints: list[dict] = []

    def apply_topology(self, source: dict, on_result=None) -> None:
        self.blueprints.append(source)
        if self._raise is not None:
            raise self._raise
        if on_result is not None:
            on_result(self._response)


# ---------------------------------------------------------------------------
# Pre-flight (НЕ-модальный feedback через notify)
# ---------------------------------------------------------------------------


class TestLaunchPreflight:
    """Pre-flight проверки → notify-сообщение + return False (без модалок)."""

    def test_launch_no_active_recipe(self) -> None:
        presenter, messages = _make_presenter(_make_recipe_store(active_slug=None))

        result = presenter.launch_active_recipe(parent=None)

        assert result is False
        assert any("активный рецепт" in m.lower() for m in messages)

    def test_launch_recipe_read_fails(self) -> None:
        presenter, messages = _make_presenter(_make_recipe_store(active_slug="broken", recipe_data=None))

        result = presenter.launch_active_recipe(parent=None)

        assert result is False
        assert any("прочитать" in m.lower() for m in messages)

    def test_launch_no_blueprint(self) -> None:
        presenter, messages = _make_presenter(
            _make_recipe_store(
                active_slug="empty_bp",
                recipe_data={"meta": {}, "data": {"active_services": []}},
            )
        )

        result = presenter.launch_active_recipe(parent=None)

        assert result is False
        assert any("blueprint" in m.lower() for m in messages)

    def test_launch_no_proxy(self) -> None:
        presenter, messages = _make_presenter(_make_recipe_store())  # proxy=None

        result = presenter.launch_active_recipe(parent=None)

        assert result is False
        assert any("proxy" in m.lower() for m in messages)


# ---------------------------------------------------------------------------
# Async request/response — GUI узнаёт реальный результат
# ---------------------------------------------------------------------------


class TestLaunchAsyncResult:
    """apply_topology(source, on_result=...) → реальный результат PM в notify."""

    def test_success_shows_replaced_count(self) -> None:
        """Успех PM → notify «запущен (заменено процессов: N)», return True."""
        expected_blueprint = {"processes": [{"process_name": "proc1"}], "wires": []}
        store = _make_recipe_store(
            active_slug="demo_recipe",
            recipe_data={"meta": {"name": "demo_recipe"}, "data": {"blueprint": expected_blueprint}},
        )
        proxy = _FakeAsyncProxy(response={"success": True, "result": {"success": True, "replaced": ["a", "b"]}})
        presenter, messages = _make_presenter(store, proxy)

        result = presenter.launch_active_recipe(parent=None)

        assert result is True  # запрос отправлен в работу
        assert proxy.blueprints == [expected_blueprint]
        assert any("запущен" in m and "2" in m for m in messages)

    def test_failure_shows_error(self) -> None:
        """PM success=False → notify ошибки с текстом, return True (запрос ушёл)."""
        proxy = _FakeAsyncProxy(response={"success": False, "result": {"success": False, "error": "boom"}})
        presenter, messages = _make_presenter(_make_recipe_store(), proxy)

        result = presenter.launch_active_recipe(parent=None)

        assert result is True
        assert any("ошибка" in m.lower() and "boom" in m for m in messages)

    def test_rollback_shows_rollback(self) -> None:
        """PM rolled_back=True → notify помечает откат."""
        proxy = _FakeAsyncProxy(
            response={
                "success": False,
                "result": {
                    "success": False,
                    "error": "Ошибка старта процесса 'cam'",
                    "rolled_back": True,
                },
            }
        )
        presenter, messages = _make_presenter(_make_recipe_store(), proxy)

        result = presenter.launch_active_recipe(parent=None)

        assert result is True
        assert any("rollback" in m.lower() or "откач" in m.lower() for m in messages)

    def test_dispatch_exception(self) -> None:
        """Исключение при отправке → notify ошибки, return False (pre-flight провал)."""
        proxy = _FakeAsyncProxy(raise_exc=Exception("crash"))
        presenter, messages = _make_presenter(_make_recipe_store(), proxy)

        result = presenter.launch_active_recipe(parent=None)

        assert result is False
        assert any("crash" in m for m in messages)
