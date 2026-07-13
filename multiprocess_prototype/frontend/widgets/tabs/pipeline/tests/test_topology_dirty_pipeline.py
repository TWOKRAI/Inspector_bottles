# -*- coding: utf-8 -*-
"""RS-4 (Fable #3/#4): dirty-контур на Pipeline-стороне.

#3: restart_topology (Apply editor→live) гасит diverged ТОЛЬКО при подтверждённом
    success apply — не по факту отправки (fire-and-forget возвращал optimistic-ack).
#4: load_topology_from_file → dirty=True (загруженный файл не в рецепте).

Refs: plans/2026-07-06_constructor-master/plan.md (RS-4)
"""

from __future__ import annotations

from pathlib import Path

from multiprocess_prototype.domain.topology_session import TopologySession
from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter

from ._helpers import make_pipeline_services
from .test_launch_recipe import _FakeAsyncProxy


def _presenter(session: TopologySession, proxy=None) -> PipelinePresenter:
    services = make_pipeline_services()
    return PipelinePresenter(
        services,
        notify=lambda _m: None,
        process_manager_proxy=proxy,
        topology_session=session,
    )


# ---------------------------------------------------------------------------
# #3 restart_topology: diverged только при подтверждённом success
# ---------------------------------------------------------------------------


def test_restart_confirmed_success_clears_diverged() -> None:
    """Подтверждённый success apply → diverged снят (граф == live)."""
    session = TopologySession()
    session.mark_edited()
    assert session.diverged is True
    proxy = _FakeAsyncProxy({"success": True, "result": {"success": True, "replaced": []}})
    presenter = _presenter(session, proxy)

    presenter.restart_topology(parent=None)

    assert session.diverged is False, "подтверждённый apply должен снять расхождение"


def test_restart_failure_keeps_diverged() -> None:
    """Ответ success=False → diverged НЕ снят (живая система не приняла граф)."""
    session = TopologySession()
    session.mark_edited()
    proxy = _FakeAsyncProxy({"success": False, "result": {"success": False, "error": "boom"}})
    presenter = _presenter(session, proxy)

    presenter.restart_topology(parent=None)

    assert session.diverged is True, "отказ apply не должен гасить индикатор расхождения"


def test_restart_rollback_keeps_diverged() -> None:
    """Ответ rolled_back=True → diverged НЕ снят (откат: граф редактора не применён)."""
    session = TopologySession()
    session.mark_edited()
    proxy = _FakeAsyncProxy(
        {"success": False, "result": {"success": False, "rolled_back": True, "error": "unstoppable"}}
    )
    presenter = _presenter(session, proxy)

    presenter.restart_topology(parent=None)

    assert session.diverged is True


def test_restart_no_proxy_does_not_clear() -> None:
    """Нет proxy (backend не запущен) → pre-flight, diverged не трогается."""
    session = TopologySession()
    session.mark_edited()
    presenter = _presenter(session, proxy=None)

    presenter.restart_topology(parent=None)

    assert session.diverged is True


# ---------------------------------------------------------------------------
# #4 load_topology_from_file → dirty=True
# ---------------------------------------------------------------------------


def test_load_from_file_marks_dirty() -> None:
    """Загрузка графа из внешнего файла → dirty=True (содержимое не в рецепте)."""
    session = TopologySession()
    presenter = _presenter(session)
    # Изолируем от реальной загрузки YAML — проверяем именно проводку dirty-контура.
    presenter._layout.load_topology_from_file = lambda _path: ([], [])  # type: ignore[assignment]

    presenter.load_topology_from_file(Path("whatever.yaml"))

    assert session.dirty is True
    assert session.diverged is True
