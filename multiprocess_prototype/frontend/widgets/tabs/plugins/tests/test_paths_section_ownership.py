# -*- coding: utf-8 -*-
"""Владение секцией «Пути»: модуль состояния не копит, вкладка секцию держит.

История файла, чтобы следующий читатель не пошёл по тому же кругу.

Первую редакцию писал независимый тестер по критериям, которые я ему выдал, и
критерии были построены на НЕВЕРНОЙ посылке: будто ``refresh_catalog()``
пересоздаёт секции, а значит секцию надо специально сохранять в держателе,
иначе теряется подписка на ``catalog_updated``. Ревью опровергло это замером:
секция «Пути» объявлена НЕленивой, ``BaseTreeNavTab.__init__`` подключает её
один раз, а ``refresh_catalog()`` пересобирает только спеки — счётчик вызовов
фабрики показал 1 после ``__init__`` и 1 после двух ``refresh_catalog()``.
Контрольная инъекция (кэш убран полностью) не изменила поведение GUI.

Поэтому три теста той редакции — про держатель, отданный вызывающим, — сняты
вместе с самим держателем: они охраняли контракт, который решено не вводить.
Уцелел тест на отсутствие модульного состояния (настоящий дефект: словарь по
``id(services)`` не чистился никогда), а к нему добавлены два теста на живой
вкладке — они проверяют то, что раньше только утверждалось прозой.
"""

from __future__ import annotations

import gc
import weakref

import pytest
from PySide6.QtWidgets import QApplication

from multiprocess_prototype.domain.protocols.plugin_catalog import PluginSpec
from multiprocess_prototype.domain.tests._fakes import FakePluginCatalog
from multiprocess_prototype.domain.tests.conftest import make_test_app_services
from multiprocess_prototype.frontend.runtime_deps import RuntimeDeps
from multiprocess_prototype.frontend.widgets.tabs.plugins._sections import (
    build_plugin_sections,
)
from multiprocess_prototype.frontend.widgets.tabs.plugins.tab import PluginsTab

_PATHS_KEY = "__paths__"


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _services():
    specs = {
        "color_mask": PluginSpec(name="color_mask", category="processing", description="d", has_registers=False),
    }
    return make_test_app_services(plugins=FakePluginCatalog(specs=specs))


def _paths_widget(tab: PluginsTab):
    """Виджет, который вкладка показывает на странице «Пути» — то, что видит оператор."""
    return tab._content_stack.widget(tab.presenter._page_index[_PATHS_KEY])


def _make_section_and_forget(services) -> weakref.ref:
    """Собрать спеки, создать секцию «Пути» и уронить ВСЕ свои сильные ссылки.

    Отдельная функция, чтобы фрейм теста не удерживал ни спеки, ни секцию:
    локальные переменные умирают вместе с фреймом, и остаётся ровно то, что
    держит сам продукт.
    """
    specs = build_plugin_sections(services)
    spec = next(s for s in specs if s.key == _PATHS_KEY)
    section = spec.factory(None)
    ref = weakref.ref(section)
    del section, spec, specs
    return ref


def test_build_leaves_no_module_level_state() -> None:
    """Модуль сборки секций не удерживает созданную секцию.

    Свойство от независимого тестера — единственное из его набора, которое
    пережило ревью, и именно оно ловит настоящий дефект: словарь
    ``_PATHS_SECTION_CACHE`` по ``id(services)`` не удалял записи никогда.

    Если покраснеет — в модуле снова завёлся кэш: секции будут накапливаться на
    каждую пересозданную вкладку, а ``id`` умершего объекта, доставшийся новому,
    отдаст новой вкладке чужую секцию, подписанную на объекты прошлой.
    """
    services = _services()

    ref_first = _make_section_and_forget(services)
    ref_second = _make_section_and_forget(services)
    gc.collect()

    assert ref_first() is None
    assert ref_second() is None


def test_paths_section_survives_refresh_catalog(app: QApplication) -> None:
    """На ЖИВОЙ вкладке страница «Пути» переживает rescan плагинов.

    Раньше это свойство только утверждалось прозой («иначе теряется подписка
    catalog_updated»), а держалось оно совсем не тем механизмом, которому
    приписывалось: секция неленивая и подключается один раз, поэтому
    ``refresh_catalog()`` её не трогает.

    Если покраснеет — оператор после пересканирования каталога получит новый
    экземпляр ``PathsSubtabWidget`` на месте старого: введённые пути и подписка
    на ``catalog_updated`` уедут вместе с прежним виджетом.
    """
    tab = PluginsTab.create(_services(), RuntimeDeps(registers_manager=None))
    before = _paths_widget(tab)

    tab.refresh_catalog()
    app.processEvents()
    tab.refresh_catalog()
    app.processEvents()

    assert _paths_widget(tab) is before


def test_section_does_not_outlive_its_tab(app: QApplication) -> None:
    """Секция «Пути» умирает вместе со своей вкладкой — течи нет.

    Парный контроль к предыдущему тесту: там секция обязана ЖИТЬ, пока жива
    вкладка, здесь — обязана УМЕРЕТЬ, когда вкладки не стало. Без второй
    половины «переживает rescan» выполнил бы и вечный модульный кэш.

    Если покраснеет — каждая пересозданная вкладка оставляет за собой секцию с
    её виджетом и подписками: течь памяти плюс живые обработчики, слушающие
    сигналы от имени закрытой вкладки.
    """
    tab = PluginsTab.create(_services(), RuntimeDeps(registers_manager=None))
    ref = weakref.ref(_paths_widget(tab))

    del tab
    gc.collect()
    app.processEvents()
    gc.collect()

    assert ref() is None
