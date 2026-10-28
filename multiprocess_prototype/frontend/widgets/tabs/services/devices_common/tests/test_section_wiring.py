# -*- coding: utf-8 -*-
"""Проводка ``session=`` в секциях Робот/ПЧ: настоящая секция + настоящая цепочка + настоящий TopologySession.

Без ``session=getattr(runtime, "topology_session", None)`` в ``section.py`` запись Устройств не двигает
базу редактора, и следующий Save редактора получает ложный конфликт (F1 ревью 1.8, C-30 Task 1.9).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

_SLUG = "letter_robot_sim"


@pytest.mark.parametrize("which", ["robot", "vfd"])
def test_section_writes_devices_with_runtime_session(qtbot, tmp_path: Path, which: str) -> None:
    """upsert через ``section._recipe_store`` двигает базу сессии runtime на rev файла после записи."""
    from multiprocess_prototype.domain.topology_session import TopologySession
    from multiprocess_prototype.frontend.runtime_deps import RuntimeDeps
    from multiprocess_prototype.recipes.tests.test_save_noise_store import _put, build_chain, fixture_a_lf

    _put(tmp_path, _SLUG, fixture_a_lf())
    store = build_chain(tmp_path, _SLUG)
    session = TopologySession()
    session.capture_base(_SLUG, store.read_raw_with_rev(_SLUG)[1])
    base_before = session.base_rev_for(_SLUG)
    assert base_before is not None
    services = SimpleNamespace(recipes=store)
    # Настоящий RuntimeDeps: переименование поля topology_session без правки секции краснит тест.
    runtime = RuntimeDeps(topology_session=session)
    if which == "robot":
        from multiprocess_prototype.frontend.widgets.tabs.services.robot.section import _RobotSection as Section
    else:
        from multiprocess_prototype.frontend.widgets.tabs.services.vfd.section import _VfdSection as Section
    section = Section(services, runtime)
    qtbot.addWidget(section.widget())

    section._recipe_store.upsert({"id": "probe_dev", "name": "Проба", "kind": which})

    assert session.base_rev_for(_SLUG) != base_before
    assert session.base_rev_for(_SLUG) == store.read_raw_with_rev(_SLUG)[1]
