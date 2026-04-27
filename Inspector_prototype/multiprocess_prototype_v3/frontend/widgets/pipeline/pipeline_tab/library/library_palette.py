"""LibraryPalette — палитра операций Pipeline-tab с группировкой по категориям.

Task 9.9 — миграция CatalogPalette из graph_editor с добавлением:
- Группировки операций по полю ProcessingOperationDef.category (Task 9.2);
- Drag-drop в NodeGraphQt-viewer вместо собственного GraphScene;
- Текстового фильтра — операции, чьё имя/категория содержат подстроку, остаются видимыми.

Drop-target (LibraryDropTarget) — отдельный helper, ставит eventFilter
на viewport NodeGraphQt-viewer'а: парсит MIME-payload, конвертирует viewport-
координаты в scene-координаты и зовёт callback (как правило —
`adapter.add_node_from_catalog(op_ref, position)`).

# TODO(framework): паттерн «палитра + MIME-drop + scene-position маппинг»
# универсален для любых Qt-канвасов (GraphScene, NodeGraphQt, custom QGraphicsView).
# Кандидат на вынесение в multiprocess_framework/modules/frontend_module/widgets/.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, Iterable

from PySide6 import QtCore, QtGui, QtWidgets

if TYPE_CHECKING:
    from NodeGraphQt import NodeGraph

logger = logging.getLogger(__name__)


# Единый MIME-тип для перетаскивания операции из палитры на canvas.
# Тот же ключ, что использовал старый CatalogPalette — удобно для постепенной миграции.
MIME_TYPE = "application/x-inspector-operation"

# Фиксированный порядок категорий в палитре (Task 9.2 / Task 9.9).
# Совпадает с Literal в ProcessingOperationDef.category.
CATEGORY_ORDER: tuple[str, ...] = (
    "Input",
    "ROI",
    "Preprocess",
    "Detect",
    "Measure",
    "Logic",
    "Output",
)

# Для операций без category — кладём в группу "Other".
UNCATEGORIZED_LABEL = "Other"

# Локализованные подписи категорий для UI.
CATEGORY_LABELS: dict[str, str] = {
    "Input": "Input — источники",
    "ROI": "ROI — регионы интереса",
    "Preprocess": "Preprocess — предобработка",
    "Detect": "Detect — детекторы",
    "Measure": "Measure — измерения",
    "Logic": "Logic — логика",
    "Output": "Output — приёмники",
    UNCATEGORIZED_LABEL: "Other — прочее",
}


# ---------------------------------------------------------------------------
# QTreeWidget с поддержкой drag-drop из категорий
# ---------------------------------------------------------------------------


class _LibraryTree(QtWidgets.QTreeWidget):
    """Дерево с категориями и операциями. Поддерживает drag для операций.

    UserRole-данные:
      - На category-item (top-level): None (drag запрещён).
      - На operation-item (child):    type_key (str) — payload для MIME.
    """

    def startDrag(self, supported_actions: QtCore.Qt.DropAction) -> None:  # noqa: N802
        """Инициировать drag только для operation-item, не для категории."""
        item = self.currentItem()
        if item is None or item.parent() is None:
            # Это category-item (top-level) — drag не делаем.
            return

        type_key = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if not isinstance(type_key, str) or not type_key:
            return

        drag = QtGui.QDrag(self)
        mime = QtCore.QMimeData()
        mime.setData(MIME_TYPE, type_key.encode("utf-8"))
        drag.setMimeData(mime)

        drag.exec(QtCore.Qt.DropAction.CopyAction)


# ---------------------------------------------------------------------------
# LibraryPalette — публичный виджет
# ---------------------------------------------------------------------------


class LibraryPalette(QtWidgets.QWidget):
    """Палитра операций с группировкой по category и текстовым фильтром.

    Использование::

        palette = LibraryPalette()
        palette.load_catalog(catalog)  # dict[type_key, ProcessingOperationDef]
        # И смонтировать drop-target на NodeGraphQt-viewer:
        target = install_palette_drop_target(graph, adapter.add_node_from_catalog)

    Сигналы:
        operation_drag_started(str): type_key — испускается на старте drag
            (вспомогательный сигнал для UX, обычно не нужен).
    """

    operation_drag_started = QtCore.Signal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)

        self.setMinimumWidth(220)

        # ─── Layout ────────────────────────────────────────────────────────
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Заголовок
        title = QtWidgets.QLabel("Библиотека операций")
        title.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(title)

        # Поле поиска
        self._search = QtWidgets.QLineEdit()
        self._search.setPlaceholderText("Поиск операций…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)
        layout.addWidget(self._search)

        # Дерево категорий
        self._tree = _LibraryTree()
        self._tree.setHeaderHidden(True)
        self._tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection,
        )
        self._tree.setDragEnabled(True)
        self._tree.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.DragOnly)
        self._tree.setIndentation(12)
        self._tree.setUniformRowHeights(True)
        layout.addWidget(self._tree)

        # Внутреннее состояние
        self._catalog: dict[str, Any] = {}
        # category_label -> QTreeWidgetItem (top-level)
        self._category_items: dict[str, QtWidgets.QTreeWidgetItem] = {}

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def load_catalog(self, catalog: dict[str, Any]) -> None:
        """Перезаполнить дерево операциями из каталога.

        Args:
            catalog: словарь type_key → ProcessingOperationDef. ProcessingOperationDef
                должен иметь поля name, description, category (опционально).
        """
        self._catalog = catalog
        self._tree.clear()
        self._category_items.clear()

        if not catalog:
            placeholder = QtWidgets.QTreeWidgetItem([
                "Каталог пуст — добавьте операции в processing_catalog.yaml",
            ])
            placeholder.setFlags(
                placeholder.flags() & ~QtCore.Qt.ItemFlag.ItemIsEnabled,
            )
            placeholder.setForeground(0, QtGui.QBrush(QtCore.Qt.GlobalColor.gray))
            self._tree.addTopLevelItem(placeholder)
            return

        # 1) Создаём узлы категорий в фиксированном порядке
        for cat in (*CATEGORY_ORDER, UNCATEGORIZED_LABEL):
            self._ensure_category_item(cat)

        # 2) Добавляем операции в соответствующие категории
        for type_key, op_def in catalog.items():
            cat_label = self._category_for(op_def)
            cat_item = self._ensure_category_item(cat_label)

            display_name = getattr(op_def, "name", type_key) or type_key
            description = getattr(op_def, "description", "") or type_key

            op_item = QtWidgets.QTreeWidgetItem([display_name])
            op_item.setData(0, QtCore.Qt.ItemDataRole.UserRole, type_key)
            op_item.setToolTip(0, description)
            cat_item.addChild(op_item)

        # 3) Удаляем пустые категории (нет операций)
        self._prune_empty_categories()

        # 4) Раскрываем все категории
        self._tree.expandAll()

    def filter_text(self, text: str) -> None:
        """Программно установить значение фильтра."""
        self._search.setText(text)

    # ------------------------------------------------------------------
    # Read-only properties (для тестов и интеграции)
    # ------------------------------------------------------------------

    @property
    def tree(self) -> QtWidgets.QTreeWidget:
        """QTreeWidget — для интеграционных тестов."""
        return self._tree

    @property
    def categories(self) -> tuple[str, ...]:
        """Список меток непустых категорий, отображаемых в палитре."""
        return tuple(self._category_items.keys())

    def operation_keys_in_category(self, label: str) -> list[str]:
        """type_key операций, лежащих в категории `label` (для тестов)."""
        item = self._category_items.get(label)
        if item is None:
            return []
        return [
            item.child(i).data(0, QtCore.Qt.ItemDataRole.UserRole)
            for i in range(item.childCount())
        ]

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _category_for(self, op_def: Any) -> str:
        """Определить метку категории для операции."""
        cat = getattr(op_def, "category", None)
        if cat in CATEGORY_ORDER:
            return cat
        return UNCATEGORIZED_LABEL

    def _ensure_category_item(self, label: str) -> QtWidgets.QTreeWidgetItem:
        """Получить (или создать) top-level item для категории."""
        if label in self._category_items:
            return self._category_items[label]

        display = CATEGORY_LABELS.get(label, label)
        item = QtWidgets.QTreeWidgetItem([display])
        # Категория — не draggable: помечаем её тем, что UserRole = None.
        item.setData(0, QtCore.Qt.ItemDataRole.UserRole, None)
        # Категории отображаем жирным
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)

        self._tree.addTopLevelItem(item)
        self._category_items[label] = item
        return item

    def _prune_empty_categories(self) -> None:
        """Удалить категории без дочерних операций."""
        for label in list(self._category_items.keys()):
            item = self._category_items[label]
            if item.childCount() == 0:
                idx = self._tree.indexOfTopLevelItem(item)
                if idx >= 0:
                    self._tree.takeTopLevelItem(idx)
                self._category_items.pop(label, None)

    def _apply_filter(self, text: str) -> None:
        """Скрыть операции/категории, не подходящие под подстроку."""
        needle = text.strip().lower()

        for cat_label, cat_item in self._category_items.items():
            visible_children = 0
            cat_label_lower = cat_label.lower()
            cat_display_lower = CATEGORY_LABELS.get(cat_label, cat_label).lower()
            cat_matches = (
                not needle
                or needle in cat_label_lower
                or needle in cat_display_lower
            )

            for i in range(cat_item.childCount()):
                child = cat_item.child(i)
                if not needle:
                    child.setHidden(False)
                    visible_children += 1
                    continue
                # Сравниваем имя + tooltip + type_key
                name = child.text(0).lower()
                tooltip = child.toolTip(0).lower()
                type_key = (
                    child.data(0, QtCore.Qt.ItemDataRole.UserRole) or ""
                ).lower()
                hit = (
                    cat_matches
                    or needle in name
                    or needle in tooltip
                    or needle in type_key
                )
                child.setHidden(not hit)
                if hit:
                    visible_children += 1

            cat_item.setHidden(visible_children == 0 and not cat_matches)


# ---------------------------------------------------------------------------
# Drop-target для NodeGraphQt viewer
# ---------------------------------------------------------------------------


class LibraryDropTarget(QtCore.QObject):
    """Event-filter для viewport NodeGraphQt-viewer'а.

    Перехватывает DragEnter/DragMove/Drop события, проверяет MIME_TYPE и зовёт
    `on_drop(operation_ref, scene_pos)` при успешном дропе.

    Архитектурное замечание: ставим eventFilter на viewport (а не на сам viewer),
    т.к. QGraphicsView пересылает drag-события именно через viewport-widget.
    `setAcceptDrops(True)` обязателен — без него viewport не получает события.

    # TODO(framework): паттерн универсален для любых QGraphicsView-канвасов;
    # вынести в frontend_module/widgets/ при появлении 2-го клиента.
    """

    def __init__(
        self,
        graph: NodeGraph,
        on_drop: Callable[[str, tuple[float, float]], Any],
        *,
        accepted_mime: Iterable[str] = (MIME_TYPE,),
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self._graph = graph
        self._on_drop = on_drop
        self._accepted_mime = tuple(accepted_mime)

        viewer = graph.viewer()
        viewport = viewer.viewport()

        # Включаем приём drop-событий на viewport
        viewport.setAcceptDrops(True)
        viewport.installEventFilter(self)

        self._viewer = viewer
        self._viewport = viewport

    # ------------------------------------------------------------------
    # QObject API
    # ------------------------------------------------------------------

    def eventFilter(  # noqa: N802 — Qt API
        self,
        obj: QtCore.QObject,
        event: QtCore.QEvent,
    ) -> bool:
        if obj is not self._viewport:
            return False

        etype = event.type()
        if etype == QtCore.QEvent.Type.DragEnter:
            return self._handle_drag_enter(event)
        if etype == QtCore.QEvent.Type.DragMove:
            return self._handle_drag_move(event)
        if etype == QtCore.QEvent.Type.Drop:
            return self._handle_drop(event)
        return False

    def detach(self) -> None:
        """Снять eventFilter — вызывать при dispose."""
        try:
            self._viewport.removeEventFilter(self)
        except RuntimeError:
            # Viewport уже удалён — игнорируем
            pass

    # ------------------------------------------------------------------
    # Внутренние обработчики
    # ------------------------------------------------------------------

    def _has_accepted_mime(self, event: QtGui.QDragMoveEvent) -> bool:
        mime = event.mimeData()
        if mime is None:
            return False
        return any(mime.hasFormat(fmt) for fmt in self._accepted_mime)

    def _handle_drag_enter(self, event: QtGui.QDragEnterEvent) -> bool:
        if self._has_accepted_mime(event):
            event.acceptProposedAction()
            return True
        return False

    def _handle_drag_move(self, event: QtGui.QDragMoveEvent) -> bool:
        if self._has_accepted_mime(event):
            event.acceptProposedAction()
            return True
        return False

    def _handle_drop(self, event: QtGui.QDropEvent) -> bool:
        mime = event.mimeData()
        if mime is None:
            return False

        type_key: str | None = None
        for fmt in self._accepted_mime:
            if mime.hasFormat(fmt):
                raw = bytes(mime.data(fmt))
                try:
                    type_key = raw.decode("utf-8")
                except UnicodeDecodeError:
                    type_key = None
                break

        if not type_key:
            return False

        # Конвертируем viewport-координаты → scene-координаты
        try:
            position = event.position().toPoint()  # PySide6 ≥ 6.0 (QPointF)
        except AttributeError:
            position = event.pos()  # Совместимость на случай старого API

        scene_point = self._viewer.mapToScene(position)
        scene_pos = (scene_point.x(), scene_point.y())

        try:
            self._on_drop(type_key, scene_pos)
        except Exception:
            logger.exception(
                "LibraryDropTarget: on_drop failed (op=%s, pos=%s)",
                type_key,
                scene_pos,
            )
            return False

        event.acceptProposedAction()
        return True


def install_palette_drop_target(
    graph: NodeGraph,
    on_drop: Callable[[str, tuple[float, float]], Any],
) -> LibraryDropTarget:
    """Удобный конструктор: смонтировать drop-target на graph.viewer().

    Args:
        graph: NodeGraphQt.NodeGraph (уже создан с QApplication).
        on_drop: callback(operation_ref, scene_pos). Обычно —
            ``adapter.add_node_from_catalog``.

    Returns:
        LibraryDropTarget — держите ссылку, иначе GC снимет eventFilter.
    """
    return LibraryDropTarget(graph, on_drop)


__all__ = [
    "MIME_TYPE",
    "CATEGORY_ORDER",
    "CATEGORY_LABELS",
    "UNCATEGORIZED_LABEL",
    "LibraryPalette",
    "LibraryDropTarget",
    "install_palette_drop_target",
]
