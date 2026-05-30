"""Тесты для PluginPalette и PipelineDropTarget."""

from __future__ import annotations


from multiprocess_prototype.frontend.widgets.tabs.pipeline.palette import (
    PluginPalette,
)
from multiprocess_prototype.frontend.widgets.tabs.pipeline.palette.palette_widget import (
    CATEGORY_ORDER,
)

# ---------------------------------------------------------------------------
# Тестовые данные
# ---------------------------------------------------------------------------

SAMPLE_PLUGINS = [
    {"name": "capture", "category": "source", "description": "Захват кадра с камеры"},
    {"name": "color_mask", "category": "processing", "description": "Цветовая маска"},
    {"name": "blur", "category": "processing", "description": "Размытие"},
    {"name": "display", "category": "output", "description": "Отображение"},
    {"name": "logger", "category": "utility", "description": "Логирование"},
]


# ---------------------------------------------------------------------------
# TestPluginPalette
# ---------------------------------------------------------------------------


class TestPluginPalette:
    def test_create_palette(self, qtbot):
        """PluginPalette создаётся без ошибок."""
        palette = PluginPalette()
        qtbot.addWidget(palette)
        assert palette is not None
        assert palette.tree is not None

    def test_load_plugins(self, qtbot):
        """После load_plugins дерево содержит верное количество узлов."""
        palette = PluginPalette()
        qtbot.addWidget(palette)
        palette.load_plugins(SAMPLE_PLUGINS)

        # 4 категории: source, processing, output, utility
        # Всего листьев: 5 (capture, color_mask, blur, display, logger)
        total_leaves = sum(palette.tree.topLevelItem(i).childCount() for i in range(palette.tree.topLevelItemCount()))
        assert total_leaves == len(SAMPLE_PLUGINS)

    def test_plugins_grouped_by_category(self, qtbot):
        """Плагины сгруппированы по своей категории."""
        palette = PluginPalette()
        qtbot.addWidget(palette)
        palette.load_plugins(SAMPLE_PLUGINS)

        # processing содержит blur и color_mask
        processing_names = palette.plugin_names_in_category("processing")
        assert set(processing_names) == {"color_mask", "blur"}

        # source содержит capture
        source_names = palette.plugin_names_in_category("source")
        assert source_names == ["capture"]

    def test_category_order(self, qtbot):
        """Категории отображаются в порядке CATEGORY_ORDER."""
        palette = PluginPalette()
        qtbot.addWidget(palette)
        palette.load_plugins(SAMPLE_PLUGINS)

        # Собрать реально присутствующие категории из CATEGORY_ORDER
        expected_present = [c for c in CATEGORY_ORDER if palette._category_items.get(c)]

        # Порядок top-level items должен совпадать с expected_present
        actual_order = []
        for i in range(palette.tree.topLevelItemCount()):
            item = palette.tree.topLevelItem(i)
            # Найти ключ категории по объекту item
            for key, cat_item in palette._category_items.items():
                if cat_item is item:
                    actual_order.append(key)
                    break

        assert actual_order == expected_present

    def test_filter_by_name(self, qtbot):
        """Поиск по имени плагина скрывает несовпадающие."""
        palette = PluginPalette()
        qtbot.addWidget(palette)
        palette.load_plugins(SAMPLE_PLUGINS)

        # Поиск "blur" — должен оставить только blur
        palette._search.setText("blur")

        # blur не скрыт
        processing_item = palette._category_items.get("processing")
        assert processing_item is not None

        # Найти child blur
        blur_visible = False
        color_mask_visible = False
        for i in range(processing_item.childCount()):
            child = processing_item.child(i)
            name = child.data(0, __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.ItemDataRole.UserRole)
            if name == "blur":
                blur_visible = not child.isHidden()
            elif name == "color_mask":
                color_mask_visible = not child.isHidden()

        assert blur_visible is True
        assert color_mask_visible is False

    def test_filter_by_category(self, qtbot):
        """Поиск по названию категории показывает все плагины категории."""
        palette = PluginPalette()
        qtbot.addWidget(palette)
        palette.load_plugins(SAMPLE_PLUGINS)

        # "источники" входит в CATEGORY_LABELS["source"] = "Source — источники"
        palette._search.setText("источники")

        source_item = palette._category_items.get("source")
        assert source_item is not None

        # Категория source должна быть видима
        assert not source_item.isHidden()

        # Плагин capture внутри source — виден
        capture_visible = False
        for i in range(source_item.childCount()):
            child = source_item.child(i)
            from PySide6.QtCore import Qt

            name = child.data(0, Qt.ItemDataRole.UserRole)
            if name == "capture":
                capture_visible = not child.isHidden()

        assert capture_visible is True

        # Остальные категории должны быть скрыты (нет совпадения)
        processing_item = palette._category_items.get("processing")
        assert processing_item is not None
        assert processing_item.isHidden()

    def test_filter_clears(self, qtbot):
        """Очистка фильтра восстанавливает все элементы."""
        palette = PluginPalette()
        qtbot.addWidget(palette)
        palette.load_plugins(SAMPLE_PLUGINS)

        # Применить фильтр
        palette._search.setText("nonexistent_xyz")

        # Все категории должны быть скрыты
        for cat_item in palette._category_items.values():
            assert cat_item.isHidden()

        # Очистить фильтр
        palette._search.setText("")

        # Все категории видны
        for cat_item in palette._category_items.values():
            assert not cat_item.isHidden()

    def test_plugin_names_in_category(self, qtbot):
        """plugin_names_in_category возвращает отсортированные имена плагинов."""
        palette = PluginPalette()
        qtbot.addWidget(palette)
        palette.load_plugins(SAMPLE_PLUGINS)

        names = palette.plugin_names_in_category("processing")
        # Ожидаем отсортированный список
        assert names == sorted(names)
        assert set(names) == {"blur", "color_mask"}

    def test_reload_clears_previous(self, qtbot):
        """Повторный вызов load_plugins очищает предыдущие данные."""
        palette = PluginPalette()
        qtbot.addWidget(palette)

        palette.load_plugins(SAMPLE_PLUGINS)
        first_count = palette.tree.topLevelItemCount()

        # Загрузить только один плагин
        palette.load_plugins([{"name": "only_one", "category": "utility"}])
        second_count = palette.tree.topLevelItemCount()

        assert second_count < first_count
        names = palette.plugin_names_in_category("utility")
        assert names == ["only_one"]

    def test_unknown_category_added_after_known(self, qtbot):
        """Плагины с неизвестной категорией добавляются после стандартных."""
        plugins = SAMPLE_PLUGINS + [
            {"name": "custom_plugin", "category": "custom_cat", "description": "Кастом"},
        ]
        palette = PluginPalette()
        qtbot.addWidget(palette)
        palette.load_plugins(plugins)

        # Кастомная категория присутствует
        assert "custom_cat" in palette._category_items

        # Она стоит последней в top-level
        last_item = palette.tree.topLevelItem(palette.tree.topLevelItemCount() - 1)
        custom_item = palette._category_items["custom_cat"]
        assert last_item is custom_item


# ---------------------------------------------------------------------------
# TestPaletteDisplays — секция дисплеев (issue: дисплеи в списке Pipeline)
# ---------------------------------------------------------------------------

SAMPLE_DISPLAYS = [
    {"display_id": "main", "display_name": "Основной дисплей"},
    {"display_id": "debug", "display_name": "Debug дисплей"},
    {"display_id": "headless", "display_name": ""},  # без имени → label = id
]


class TestPaletteDisplays:
    def test_load_displays_adds_section(self, qtbot):
        """load_displays добавляет секцию «Displays — дисплеи» с элементами."""
        from multiprocess_prototype.frontend.widgets.tabs.pipeline.palette.palette_widget import (
            DISPLAY_SECTION_LABEL,
            PluginPalette as _PP,
        )

        palette = PluginPalette()
        qtbot.addWidget(palette)
        palette.load_plugins(SAMPLE_PLUGINS)
        palette.load_displays(SAMPLE_DISPLAYS)

        cat = palette._category_items.get(_PP._DISPLAY_KEY)
        assert cat is not None
        assert cat.text(0) == DISPLAY_SECTION_LABEL
        assert cat.childCount() == len(SAMPLE_DISPLAYS)

    def test_display_items_carry_id_and_kind(self, qtbot):
        """Элементы дисплеев несут display_id (UserRole) и kind='display'."""
        from PySide6.QtCore import Qt

        from multiprocess_prototype.frontend.widgets.tabs.pipeline.palette.palette_widget import (
            _KIND_ROLE,
            PluginPalette as _PP,
        )

        palette = PluginPalette()
        qtbot.addWidget(palette)
        palette.load_displays(SAMPLE_DISPLAYS)

        cat = palette._category_items[_PP._DISPLAY_KEY]
        ids = {cat.child(i).data(0, Qt.ItemDataRole.UserRole) for i in range(cat.childCount())}
        kinds = {cat.child(i).data(0, _KIND_ROLE) for i in range(cat.childCount())}
        assert ids == {"main", "debug", "headless"}
        assert kinds == {"display"}

    def test_load_displays_idempotent(self, qtbot):
        """Повторный load_displays не плодит дубль-секцию."""
        from multiprocess_prototype.frontend.widgets.tabs.pipeline.palette.palette_widget import (
            PluginPalette as _PP,
        )

        palette = PluginPalette()
        qtbot.addWidget(palette)
        palette.load_displays(SAMPLE_DISPLAYS)
        first = palette.tree.topLevelItemCount()
        palette.load_displays(SAMPLE_DISPLAYS)
        assert palette.tree.topLevelItemCount() == first
        assert palette._category_items[_PP._DISPLAY_KEY].childCount() == len(SAMPLE_DISPLAYS)

    def test_empty_displays_noop(self, qtbot):
        """Пустой список дисплеев — секция не добавляется."""
        from multiprocess_prototype.frontend.widgets.tabs.pipeline.palette.palette_widget import (
            PluginPalette as _PP,
        )

        palette = PluginPalette()
        qtbot.addWidget(palette)
        palette.load_displays([])
        assert _PP._DISPLAY_KEY not in palette._category_items


# ---------------------------------------------------------------------------
# TestPipelineDropTarget — маршрутизация drop по типу MIME
# ---------------------------------------------------------------------------


def _make_drop_event(mime_type: str, payload: str):
    """Сконструировать QDropEvent с одним MIME-форматом.

    Возвращает (event, mime). QDropEvent НЕ владеет QMimeData (PySide6) — её
    нужно держать живой на стороне вызывающего, иначе mimeData() станет dangling.
    """
    from PySide6.QtCore import QMimeData, QPointF, Qt
    from PySide6.QtGui import QDropEvent

    mime = QMimeData()
    mime.setData(mime_type, payload.encode("utf-8"))
    event = QDropEvent(
        QPointF(10.0, 10.0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    return event, mime


class TestPipelineDropTarget:
    def _make_view(self, qtbot):
        from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene import GraphScene
        from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_view import GraphView

        view = GraphView(GraphScene())
        qtbot.addWidget(view)
        return view

    def test_plugin_drop_routed_to_on_drop(self, qtbot):
        from multiprocess_prototype.frontend.widgets.tabs.pipeline.palette import PipelineDropTarget
        from multiprocess_prototype.frontend.widgets.tabs.pipeline.palette.palette_widget import MIME_TYPE

        view = self._make_view(qtbot)
        plugin_calls, display_calls = [], []
        target = PipelineDropTarget(
            view,
            lambda name, pos: plugin_calls.append(name),
            on_display_drop=lambda did, pos: display_calls.append(did),
        )

        event, _mime = _make_drop_event(MIME_TYPE, "blur")
        handled = target.eventFilter(view.viewport(), event)

        assert handled is True
        assert plugin_calls == ["blur"]
        assert display_calls == []

    def test_display_drop_routed_to_on_display_drop(self, qtbot):
        from multiprocess_prototype.frontend.widgets.tabs.pipeline.palette import PipelineDropTarget
        from multiprocess_prototype.frontend.widgets.tabs.pipeline.palette.palette_widget import (
            MIME_TYPE_DISPLAY,
        )

        view = self._make_view(qtbot)
        plugin_calls, display_calls = [], []
        target = PipelineDropTarget(
            view,
            lambda name, pos: plugin_calls.append(name),
            on_display_drop=lambda did, pos: display_calls.append(did),
        )

        event, _mime = _make_drop_event(MIME_TYPE_DISPLAY, "main")
        handled = target.eventFilter(view.viewport(), event)

        assert handled is True
        assert display_calls == ["main"]
        assert plugin_calls == []

    def test_display_drop_ignored_without_callback(self, qtbot):
        """Без on_display_drop display-MIME не принимается (формат не в _accepted_formats)."""
        from multiprocess_prototype.frontend.widgets.tabs.pipeline.palette import PipelineDropTarget
        from multiprocess_prototype.frontend.widgets.tabs.pipeline.palette.palette_widget import (
            MIME_TYPE_DISPLAY,
        )

        view = self._make_view(qtbot)
        target = PipelineDropTarget(view, lambda name, pos: None)  # on_display_drop=None

        event, _mime = _make_drop_event(MIME_TYPE_DISPLAY, "main")
        handled = target.eventFilter(view.viewport(), event)

        assert handled is not True  # событие не обработано фильтром
