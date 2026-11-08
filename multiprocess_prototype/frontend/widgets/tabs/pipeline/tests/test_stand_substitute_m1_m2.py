# -*- coding: utf-8 -*-
"""ЗАМЕНА живого стенда M1/M2 (не стенд): настоящие Qt-виджеты offscreen, кнопка «Сохранить» нажимается ``click()``.

Живой стенд даёт два замера C-30, которые нельзя снять без экрана:

* **M1** — Save редактора без правок = ``0/0`` строк диффа; вторая запись тоже; ``mtime`` прежний;
* **M2** — файл рецепта правят руками при «открытом» редакторе -> Save показывает диалог конфликта
  «Рецепт изменён снаружи — перезагрузите его» и ничего не затирает (байты файла == ручная правка).

Здесь это снимается на настоящих объектах: ``PipelineTab`` / ``RecipesTab`` (QApplication offscreen, поиск и клик
по кнопке «Сохранить»), ``TopologySession`` с базой и ``capture_foundation(["devices"])``,
``RecipeStoreFromManager`` + ``RecipeManager`` + ``InspectorRecipeFormatHook`` на tmp-копии рецепта
``bridge_synth`` (байты HEAD из ``recipes/tests/fixtures``), живой граф = ``base.yaml`` ⊕ рецепт. ``QMessageBox``
подменяется на захват (вид, заголовок, текст) без блокировки; число вызовов проверяется.

Чего это НЕ доказывает (остаётся стенду):

* нет ProcessManager и живых процессов: рецепт не запускался, граф не приходил из бэкенда;
* нет ``run_gui`` и настоящего ``capture_foundation`` из ``app.py``: имена фундамента заданы тестом;
* нет настоящего окна и хуков ``MainWindow`` (``closeEvent``, подписка на активацию рецепта, индикатор dirty);
* нет настоящего показа диалога: проверен вызов ``QMessageBox`` с точным текстом, а не пиксели на экране;
* нет живой камеры и реальной раскладки узлов на экране (M3/M5 ждут камеры).

Ожидаемые значения — литералы. Реальные рецепты только копируются.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QMessageBox, QPushButton, QWidget

from multiprocess_prototype.frontend.widgets.tabs.pipeline.tests.test_save_conflict_rev import (
    _OLD_MTIME_NS,
    _bridge_synth_setup,
    _Repo,
)

_SLUG = "bridge_synth"
_CONFLICT_TEXT = "Рецепт изменён снаружи — перезагрузите его"
_EXTERNAL_EDIT = b"# external edit\n"
_SAVE_TITLE = "Сохранение рецепта"
_SAVED_TEXT = "Рецепт сохранён: bridge_synth"

# Раскладка, которую Pipeline-вкладка пишет при первом Save (узел один; ``devices`` — фундамент, ``gui`` без плагинов).
_POSITIONS_BLOCK = (
    b"  metadata:\n"
    b"    gui_positions:\n"
    b"      synthetic_source.synthetic_frame_source:\n"
    b"        - 400.0\n"
    b"        - 100.0\n"
)

type Dialog = tuple[str, str, str]


@pytest.fixture()
def dialogs(monkeypatch: pytest.MonkeyPatch) -> list[Dialog]:
    """QMessageBox подменён до клика: список (вид окна, заголовок, текст); ничего не блокирует."""
    shown: list[Dialog] = []

    def make_static(kind: str, result: Any) -> Any:
        def fake(parent: Any, title: str, text: str, *args: Any, **kwargs: Any) -> Any:
            shown.append((kind, title, text))
            return result

        return staticmethod(fake)

    for kind in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, kind, make_static(kind, QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "question", make_static("question", QMessageBox.StandardButton.No))

    def fake_exec(self: QMessageBox) -> Any:
        shown.append(("exec", self.windowTitle(), self.text()))
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    return shown


def _settled_setup(tmp_path: Path) -> tuple[Path, bytes, Any, Any, dict]:
    """``bridge_synth`` в состоянии «раскладка уже сохранена редактором»: HEAD-байты + блок ``gui_positions``.

    В HEAD у рецепта раскладки нет, и первый Save Pipeline-вкладки дописывает её (см. тест характеризации ниже);
    рабочий файл стенда раскладку уже имеет, поэтому M1 снимается с ней. База сессии берётся после подмены файла.
    """
    path, head, store, session, live = _bridge_synth_setup(tmp_path)
    settled = head + _POSITIONS_BLOCK
    path.write_bytes(settled)
    os.utime(path, ns=(_OLD_MTIME_NS, _OLD_MTIME_NS))
    session.capture_base(_SLUG, store.read_raw_with_rev(_SLUG)[1])
    return path, settled, store, session, live


def _save_button(tab: QWidget) -> QPushButton:
    """Единственная живая кнопка «Сохранить» вкладки; отключённая кнопка молча проглотила бы click()."""
    buttons = [b for b in tab.findChildren(QPushButton) if b.text() == "Сохранить"]
    assert len(buttons) == 1
    assert buttons[0].isEnabled()
    return buttons[0]


def _pipeline_tab(qtbot: Any, store: Any, session: Any, live: dict) -> QWidget:
    """Настоящий PipelineTab на живом графе, с настоящим стором и сессией."""
    from multiprocess_prototype.frontend.widgets.tabs.pipeline.tab import PipelineTab
    from multiprocess_prototype.frontend.widgets.tabs.pipeline.tests._helpers import make_pipeline_services

    services = make_pipeline_services(topology=live)
    object.__setattr__(services, "recipes", store)
    tab = PipelineTab(services, topology_session=session)
    qtbot.addWidget(tab)
    return tab


def _recipes_tab(qtbot: Any, store: Any, session: Any, live: dict) -> QWidget:
    """Настоящий RecipesTab с выбранным рецептом ``bridge_synth``; источник графа — живая топология."""
    from multiprocess_prototype.domain.tests.conftest import make_test_app_services
    from multiprocess_prototype.frontend.widgets.tabs.recipes.tab import RecipesTab

    services = make_test_app_services(recipes=store, topology=_Repo(live))
    tab = RecipesTab(services, topology_session=session)
    qtbot.addWidget(tab)
    tab.select_item(_SLUG)
    return tab


_TAB_BUILDERS = {"pipeline": _pipeline_tab, "recipes": _recipes_tab}


def _click(button: QPushButton) -> None:
    """Клик в потоке теста: виджеты Qt живут в главном потоке, daemon-поток с дедлайном здесь не годится."""
    button.click()


@pytest.mark.parametrize("tab_kind", ["pipeline", "recipes"])
def test_m1_save_click_without_edits_is_zero_diff_twice(
    qtbot: Any, tmp_path: Path, dialogs: list[Dialog], tab_kind: str
) -> None:
    """M1: клик «Сохранить» без правок — байты и mtime прежние; второй клик тоже; диалог «сохранён» дважды."""
    path, src, store, session, live = _settled_setup(tmp_path)
    assert path.stat().st_mtime_ns == _OLD_MTIME_NS
    tab = _TAB_BUILDERS[tab_kind](qtbot, store, session, live)
    button = _save_button(tab)

    _click(button)

    assert dialogs == [("information", _SAVE_TITLE, _SAVED_TEXT)]
    assert path.read_bytes() == src
    assert path.stat().st_mtime_ns == _OLD_MTIME_NS

    _click(button)

    assert dialogs == [("information", _SAVE_TITLE, _SAVED_TEXT)] * 2
    assert path.read_bytes() == src
    assert path.stat().st_mtime_ns == _OLD_MTIME_NS


def test_pipeline_first_save_of_recipe_without_layout_adds_default_positions(
    qtbot: Any, tmp_path: Path, dialogs: list[Dialog]
) -> None:
    """Характеризация (не требование C-30): HEAD-рецепт без раскладки, первый Save Pipeline-вкладки дописывает её.

    Поэтому M1 для Pipeline снимается с «осевшим» рецептом (``_settled_setup``): ``0/0`` верно, когда раскладка уже
    в файле.
    """
    path, head, store, session, live = _bridge_synth_setup(tmp_path)
    tab = _pipeline_tab(qtbot, store, session, live)

    _click(_save_button(tab))

    assert dialogs == [("information", _SAVE_TITLE, _SAVED_TEXT)]
    assert path.read_bytes() == head + _POSITIONS_BLOCK


@pytest.mark.parametrize(
    ("tab_kind", "kind", "title"),
    [("pipeline", "critical", _SAVE_TITLE), ("recipes", "warning", "Ошибка")],
)
def test_m2_external_edit_then_save_click_shows_conflict_and_keeps_bytes(
    qtbot: Any, tmp_path: Path, dialogs: list[Dialog], tab_kind: str, kind: str, title: str
) -> None:
    """M2: после первого Save файл дописан снаружи -> клик «Сохранить» даёт диалог конфликта, файл не затёрт."""
    path, src, store, session, live = _settled_setup(tmp_path)
    tab = _TAB_BUILDERS[tab_kind](qtbot, store, session, live)
    button = _save_button(tab)
    _click(button)
    assert dialogs == [("information", _SAVE_TITLE, _SAVED_TEXT)]
    assert path.read_bytes() == src

    path.write_bytes(src + _EXTERNAL_EDIT)
    edited = path.read_bytes()
    assert edited == src + b"# external edit\n"
    mtime_after_edit = path.stat().st_mtime_ns

    _click(button)

    assert dialogs == [("information", _SAVE_TITLE, _SAVED_TEXT), (kind, title, _CONFLICT_TEXT)]
    assert path.read_bytes() == edited
    assert path.stat().st_mtime_ns == mtime_after_edit
