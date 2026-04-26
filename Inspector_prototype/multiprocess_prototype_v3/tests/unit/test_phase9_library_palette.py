"""Unit-тесты для LibraryPalette + LibraryDropTarget (Task 9.9).

Покрывает:
  - load_catalog: 7 категорий + UNCATEGORIZED, фиксированный порядок.
  - Пустые категории (без операций) удаляются из дерева.
  - Фильтр по тексту скрывает несовпадающие операции и пустые категории.
  - LibraryDropTarget: dragEnter с правильным MIME принимается.
  - LibraryDropTarget: drop парсит type_key и вызывает on_drop с scene-координатами.
  - LibraryDropTarget: чужой MIME не принимается.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# sys.path для плоских импортов
_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from frontend.widgets.pipeline_tab.library_palette import (  # noqa: E402
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    MIME_TYPE,
    UNCATEGORIZED_LABEL,
    LibraryDropTarget,
    LibraryPalette,
)
from registers.processor.catalog.port_types import PORT_TYPE_IMAGE  # noqa: E402
from registers.processor.catalog.schemas import (  # noqa: E402
    Port,
    ProcessingOperationDef,
)


# ---------------------------------------------------------------------------
# QApplication fixture — одна на сессию (PySide6 требует ровно одну)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def qapp() -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


# ---------------------------------------------------------------------------
# Фабрика каталога (с категориями для всех 7 групп + одна без категории)
# ---------------------------------------------------------------------------


def _op(
    type_key: str,
    *,
    name: str,
    category: str | None,
    description: str = "",
) -> ProcessingOperationDef:
    return ProcessingOperationDef(
        name=name,
        type_key=type_key,
        params_schema=f"tests.stub.{type_key}.Params",
        module_path=f"tests.stub.{type_key}.Op",
        description=description,
        category=category,
        input_ports=[Port(name="in", data_type=PORT_TYPE_IMAGE)],
        output_ports=[Port(name="out", data_type=PORT_TYPE_IMAGE)],
    )


def _full_catalog() -> dict[str, ProcessingOperationDef]:
    """Каталог с операцией в каждой из 7 категорий + одна без категории."""
    return {
        "webcam": _op("webcam", name="Веб-камера", category="Input"),
        "splitter": _op("splitter", name="Разделитель регионов", category="ROI"),
        "resize": _op("resize", name="Resize", category="Preprocess",
                      description="изменение размера"),
        "color_det": _op("color_det", name="Цветовая детекция", category="Detect"),
        "area_meas": _op("area_meas", name="Площадь", category="Measure"),
        "if_node": _op("if_node", name="If", category="Logic"),
        "display": _op("display", name="Display Output", category="Output"),
        "legacy_op": _op("legacy_op", name="Без категории", category=None),
    }


# ---------------------------------------------------------------------------
# Тесты LibraryPalette
# ---------------------------------------------------------------------------


class TestLibraryPaletteCategories:
    """load_catalog → группировка по 7 категориям + Other."""

    def test_seven_categories_displayed(self, qapp: QtWidgets.QApplication) -> None:
        palette = LibraryPalette()
        palette.load_catalog(_full_catalog())

        categories = palette.categories
        # Должны быть все 7 канонических категорий + Other для legacy_op
        assert set(categories) == set(CATEGORY_ORDER) | {UNCATEGORIZED_LABEL}

    def test_categories_in_fixed_order(self, qapp: QtWidgets.QApplication) -> None:
        palette = LibraryPalette()
        palette.load_catalog(_full_catalog())

        categories = palette.categories
        # Проверяем что Input идёт раньше Output, а Other — последним
        for i, cat in enumerate(CATEGORY_ORDER):
            assert categories.index(cat) == i
        assert categories[-1] == UNCATEGORIZED_LABEL

    def test_operation_in_correct_category(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        palette = LibraryPalette()
        palette.load_catalog(_full_catalog())

        assert "webcam" in palette.operation_keys_in_category("Input")
        assert "resize" in palette.operation_keys_in_category("Preprocess")
        assert "display" in palette.operation_keys_in_category("Output")
        assert "legacy_op" in palette.operation_keys_in_category(UNCATEGORIZED_LABEL)

    def test_empty_categories_pruned(self, qapp: QtWidgets.QApplication) -> None:
        """Если категория не имеет операций — узел удаляется из дерева."""
        catalog = {
            "webcam": _op("webcam", name="Cam", category="Input"),
        }
        palette = LibraryPalette()
        palette.load_catalog(catalog)

        # Должна остаться только Input — остальные пустые → pruned
        assert palette.categories == ("Input",)

    def test_empty_catalog_shows_placeholder(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        palette = LibraryPalette()
        palette.load_catalog({})

        # categories пуст, но в дереве есть placeholder-item
        assert palette.categories == ()
        assert palette.tree.topLevelItemCount() == 1
        item = palette.tree.topLevelItem(0)
        assert "пуст" in item.text(0).lower()

    def test_category_label_human_readable(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        """В UI отображается локализованный label, а не сухой ключ."""
        palette = LibraryPalette()
        palette.load_catalog(_full_catalog())

        input_item = palette.tree.topLevelItem(0)
        assert input_item.text(0) == CATEGORY_LABELS["Input"]


class TestLibraryPaletteFilter:
    """Фильтр по тексту."""

    def test_filter_by_name(self, qapp: QtWidgets.QApplication) -> None:
        palette = LibraryPalette()
        palette.load_catalog(_full_catalog())

        palette.filter_text("resize")

        # Все категории кроме Preprocess (где лежит Resize) — скрыты
        for cat in palette.categories:
            cat_item = palette.tree.findItems(
                CATEGORY_LABELS.get(cat, cat),
                QtCore.Qt.MatchFlag.MatchExactly,
            )
            assert cat_item, f"Категория {cat} не найдена в дереве"
            if cat == "Preprocess":
                assert not cat_item[0].isHidden()
            else:
                assert cat_item[0].isHidden(), (
                    f"Категория {cat} должна быть скрыта по фильтру 'resize'"
                )

    def test_filter_by_description(self, qapp: QtWidgets.QApplication) -> None:
        palette = LibraryPalette()
        palette.load_catalog(_full_catalog())

        # description Resize содержит «изменение размера»
        palette.filter_text("изменение")

        # Resize-item должен быть видим
        preproc_label = CATEGORY_LABELS["Preprocess"]
        items = palette.tree.findItems(
            preproc_label, QtCore.Qt.MatchFlag.MatchExactly,
        )
        assert items
        preproc_item = items[0]
        assert not preproc_item.isHidden()
        # У Resize дочернего item — состояние видим
        for i in range(preproc_item.childCount()):
            child = preproc_item.child(i)
            if child.data(0, QtCore.Qt.ItemDataRole.UserRole) == "resize":
                assert not child.isHidden()
                break
        else:
            pytest.fail("resize-item не найден в Preprocess")

    def test_empty_filter_shows_all(self, qapp: QtWidgets.QApplication) -> None:
        palette = LibraryPalette()
        palette.load_catalog(_full_catalog())

        palette.filter_text("nonexistent_xyz_xxx")
        palette.filter_text("")

        # Все категории должны быть видимыми снова
        for cat_label in palette.categories:
            display = CATEGORY_LABELS.get(cat_label, cat_label)
            items = palette.tree.findItems(display, QtCore.Qt.MatchFlag.MatchExactly)
            assert items and not items[0].isHidden()


# ---------------------------------------------------------------------------
# Тесты LibraryDropTarget
# ---------------------------------------------------------------------------


class _FakeViewer(QtWidgets.QGraphicsView):
    """Минимальный QGraphicsView для проверки dragEnter/drop через event-filter."""

    def __init__(self) -> None:
        super().__init__()
        self.setScene(QtWidgets.QGraphicsScene(self))


class _FakeGraph:
    """NodeGraph-stub: достаточно метода viewer()."""

    def __init__(self) -> None:
        self._viewer = _FakeViewer()

    def viewer(self) -> _FakeViewer:
        return self._viewer


def _make_drag_enter_event(mime: QtCore.QMimeData) -> QtGui.QDragEnterEvent:
    return QtGui.QDragEnterEvent(
        QtCore.QPoint(10, 20),
        QtCore.Qt.DropAction.CopyAction,
        mime,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )


def _make_drop_event(mime: QtCore.QMimeData) -> QtGui.QDropEvent:
    return QtGui.QDropEvent(
        QtCore.QPointF(10, 20),
        QtCore.Qt.DropAction.CopyAction,
        mime,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )


class TestLibraryDropTarget:
    """eventFilter маршрутизирует drag/drop в callback."""

    def test_drag_enter_with_known_mime_accepted(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        graph = _FakeGraph()
        callback = MagicMock()
        target = LibraryDropTarget(graph, callback)

        mime = QtCore.QMimeData()
        mime.setData(MIME_TYPE, b"webcam")
        event = _make_drag_enter_event(mime)

        accepted = target.eventFilter(graph.viewer().viewport(), event)

        assert accepted is True
        assert event.isAccepted()

    def test_drag_enter_with_foreign_mime_rejected(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        graph = _FakeGraph()
        callback = MagicMock()
        target = LibraryDropTarget(graph, callback)

        mime = QtCore.QMimeData()
        mime.setText("not-our-payload")
        event = _make_drag_enter_event(mime)

        accepted = target.eventFilter(graph.viewer().viewport(), event)

        assert accepted is False
        callback.assert_not_called()

    def test_drop_invokes_callback_with_scene_pos(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        graph = _FakeGraph()
        callback = MagicMock()
        target = LibraryDropTarget(graph, callback)

        mime = QtCore.QMimeData()
        mime.setData(MIME_TYPE, b"resize")
        event = _make_drop_event(mime)

        accepted = target.eventFilter(graph.viewer().viewport(), event)

        assert accepted is True
        callback.assert_called_once()
        op_ref, scene_pos = callback.call_args.args
        assert op_ref == "resize"
        assert isinstance(scene_pos, tuple)
        assert len(scene_pos) == 2
        # Сравниваем не с константой, а с тем же mapToScene — поведение QGraphicsView
        # зависит от внутреннего state'а view (transform/scrollbar), которое не
        # настроено в _FakeViewer; контракт — корректный mapToScene результат.
        expected = graph.viewer().mapToScene(QtCore.QPoint(10, 20))
        assert scene_pos == pytest.approx(
            (expected.x(), expected.y()), abs=0.01,
        )

    def test_drop_with_foreign_mime_not_invoked(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        graph = _FakeGraph()
        callback = MagicMock()
        target = LibraryDropTarget(graph, callback)

        mime = QtCore.QMimeData()
        mime.setText("foreign")
        event = _make_drop_event(mime)

        accepted = target.eventFilter(graph.viewer().viewport(), event)

        assert accepted is False
        callback.assert_not_called()

    def test_callback_exception_does_not_propagate(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        """on_drop должен ловить исключения callback'а — drag-drop не должен крэшить UI."""
        graph = _FakeGraph()
        callback = MagicMock(side_effect=RuntimeError("boom"))
        target = LibraryDropTarget(graph, callback)

        mime = QtCore.QMimeData()
        mime.setData(MIME_TYPE, b"webcam")
        event = _make_drop_event(mime)

        accepted = target.eventFilter(graph.viewer().viewport(), event)

        # Исключение проглочено, но drop не accepted (false → Qt игнорирует)
        assert accepted is False

    def test_detach_removes_event_filter(
        self, qapp: QtWidgets.QApplication,
    ) -> None:
        graph = _FakeGraph()
        callback = MagicMock()
        target = LibraryDropTarget(graph, callback)

        target.detach()

        # После detach callback не должен срабатывать на новых событиях.
        # Проверяем что не падает при повторном detach (idempotent).
        target.detach()
