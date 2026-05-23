"""EntityTreeWidget — универсальный виджет дерева-таблицы, параметризованный конфигом.

Иерархия в дереве (одинаковая для всех вкладок):
  ■ Parent_0                 | значение | комментарий | сводка
    □ Параметры
      ⚙ Param_1             | value    | описание    |
      ⚙ Param_2             | value    | описание    |
    □ Child_0                | значение | комментарий | сводка
      □ Параметры
        ⚙ Param_A           | value    | описание    |

Визуальные правила (единые):
- Родитель: bold (если EntityLevel.bold), иконка ■
- Группа «Параметры»: □ серый, non-selectable
- Параметр: ⚙, серый шрифт
- Bool: ✓/✗
- Дочерний: □, обычный шрифт
- Значение «—» если None/отсутствует
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QStandardItem

from .base_editor_tree import BaseEditorTreeView
from .entity_tree_config import (
    EntityTreeConfig,
    ParamDef,
)

logger = logging.getLogger(__name__)

# Универсальные роли для EntityTreeWidget
ROLE_TYPE = Qt.ItemDataRole.UserRole + 1  # "parent"|"child"|"param_group"|"parent_param"|"child_param"
ROLE_PARENT = Qt.ItemDataRole.UserRole + 2  # ключ родительского элемента
ROLE_CHILD = Qt.ItemDataRole.UserRole + 3  # ключ дочернего элемента
ROLE_PARAM = Qt.ItemDataRole.UserRole + 4  # ключ параметра

# Цвета
_COLOR_GRAY = QColor(140, 140, 140)
_COLOR_GROUP = QColor(150, 150, 150)


class EntityTreeWidget(BaseEditorTreeView):
    """Универсальное дерево сущностей, параметризованное EntityTreeConfig.

    Подклассы могут переопределять:
    - _populate() — для кастомной логики загрузки данных (напр. merge двух моделей)
    - _build_parent_row() — для кастомного визуального оформления родителей
    - _build_child_row() — для кастомного визуального оформления дочерних элементов
    - _get_children_for_parent() — для кастомной фильтрации дочерних элементов

    Signals (наследуются от BaseEditorTreeView):
        item_selected(str): ключ выбранного элемента.
        selection_cleared(): ничего не выбрано.
    """

    def __init__(
        self,
        config: EntityTreeConfig,
        *,
        parent=None,
    ) -> None:
        """Инициализировать дерево с заданным конфигом.

        Args:
            config: Декларативный конфиг дерева (колонки, уровни, параметры).
            parent: Родительский виджет.
        """
        super().__init__(config.columns, parent=parent)
        self._config = config

        # Данные: {key: dict} для родителей и дочерних
        self._parents: dict[str, dict] = {}
        self._children: dict[str, dict] = {}

        # Применить ширины колонок из конфига
        if config.column_widths:
            for i, width in enumerate(config.column_widths):
                if i < len(config.columns):
                    self._tree.setColumnWidth(i, width)

        # Минимальная высота дерева
        self._tree.setMinimumHeight(350)

    # ------------------------------------------------------------------
    # Публичное API: загрузка данных
    # ------------------------------------------------------------------

    def set_data(
        self,
        parents: dict[str, dict],
        children: dict[str, dict],
    ) -> None:
        """Загрузить данные и обновить дерево.

        Args:
            parents:  Словарь {parent_key: parent_data_dict}.
            children: Словарь {child_key: child_data_dict}.
                      Каждый child_data_dict должен содержать ключ «parent_ref»
                      для привязки к родителю.
        """
        self._parents = parents
        self._children = children
        self.refresh()

    # ------------------------------------------------------------------
    # Переопределение save/restore selection
    # ------------------------------------------------------------------

    def _save_selection(self) -> Any:
        """Сохранить выделение как tuple (ROLE_TYPE, ROLE_PARENT, ROLE_CHILD, ROLE_PARAM).

        Позволяет точно восстановить позицию для всех уровней дерева.
        """
        index = self._tree.selectionModel().currentIndex()
        if not index.isValid():
            return None
        item = self._model.itemFromIndex(self._model.index(index.row(), 0, index.parent()))
        if item is None:
            return None
        return (
            item.data(ROLE_TYPE),
            item.data(ROLE_PARENT),
            item.data(ROLE_CHILD),
            item.data(ROLE_PARAM),
        )

    def _restore_selection(self, state: Any) -> None:
        """Восстановить выделение по tuple (type, parent, child, param).

        Args:
            state: Кортеж, сохранённый в _save_selection(), или None.
        """
        if state is None:
            return
        if not isinstance(state, tuple) or len(state) != 4:
            return

        role_type, role_parent, role_child, role_param = state
        item = self._find_item_by_roles(role_type, role_parent, role_child, role_param)
        if item is None:
            return

        with self._block():
            index = self._model.indexFromItem(item)
            self._tree.selectionModel().setCurrentIndex(
                index,
                self._tree.selectionModel().SelectionFlag.ClearAndSelect,
            )
            self._tree.scrollTo(index)

    # ------------------------------------------------------------------
    # Заполнение дерева
    # ------------------------------------------------------------------

    def _populate(self, root: QStandardItem) -> None:
        """Заполнить дерево из загруженных данных по конфигу.

        Строит иерархию: Parent → Параметры + Children → Параметры.

        Args:
            root: Корневой элемент модели (invisibleRootItem).
        """
        if not self._parents:
            placeholder = QStandardItem("Нет данных")
            placeholder.setFlags(Qt.ItemFlag.ItemIsEnabled)
            root.appendRow([placeholder])
            return

        for parent_key in self._sorted_parent_keys():
            parent_data = self._parents[parent_key]
            parent_row = self._build_parent_row(parent_key, parent_data)
            root.appendRow(parent_row)

            parent_item = parent_row[0]

            # Группа параметров родителя
            params_group = self._make_group_item("Параметры", "parent_param_group", parent_key)
            parent_item.appendRow(self._make_full_row(params_group))
            self._build_param_rows(
                params_group,
                parent_key,
                parent_data,
                self._config.parent_level.params,
                "parent_param",
            )

            # Дочерние элементы
            children = self._get_children_for_parent(parent_key)
            for child_key in self._sorted_child_keys(children):
                child_data = children[child_key]
                child_row = self._build_child_row(parent_key, child_key, child_data)
                parent_item.appendRow(child_row)

                child_item = child_row[0]

                # Группа параметров дочернего
                child_params_group = self._make_group_item("Параметры", "child_param_group", parent_key, child_key)
                child_item.appendRow(self._make_full_row(child_params_group))
                self._build_param_rows(
                    child_params_group,
                    parent_key,
                    child_data,
                    self._config.child_level.params,
                    "child_param",
                    child_key=child_key,
                )

    # ------------------------------------------------------------------
    # Построители строк
    # ------------------------------------------------------------------

    def _build_level_row(
        self,
        level,
        display_key: str,
        role_type: str,
        data: dict,
        *,
        user_role_value: str,
        role_parent: str,
        role_child: str | None = None,
    ) -> list[QStandardItem]:
        """Построить строку дерева для parent- или child-уровня (общая логика).

        role_child=None означает parent-строку; ROLE_CHILD не устанавливается.
        """
        # Сводка через опциональный builder
        try:
            summary = level.summary_builder(data) if level.summary_builder else ""
        except Exception:
            summary = ""

        name_item = QStandardItem(f"{level.icon} {display_key}")
        if level.bold:
            font = QFont()
            font.setBold(True)
            name_item.setFont(font)
        name_item.setData(user_role_value, Qt.ItemDataRole.UserRole)
        name_item.setData(role_type, ROLE_TYPE)
        name_item.setData(role_parent, ROLE_PARENT)
        if role_child is not None:  # ROLE_CHILD — только для дочерних строк
            name_item.setData(role_child, ROLE_CHILD)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        # Вспомогательная функция — создать non-editable item
        def _ro(text: str = "") -> QStandardItem:
            it = QStandardItem(text)
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            return it

        return self._pad_row([name_item, _ro(), _ro(), _ro(summary)])

    def _build_parent_row(self, key: str, data: dict) -> list[QStandardItem]:  # noqa: D102
        return self._build_level_row(
            self._config.parent_level,
            key,
            "parent",
            data,
            user_role_value=key,
            role_parent=key,
        )

    def _build_child_row(self, parent_key: str, child_key: str, data: dict) -> list[QStandardItem]:  # noqa: D102
        return self._build_level_row(
            self._config.child_level,
            child_key,
            "child",
            data,
            user_role_value=f"{parent_key}/{child_key}",
            role_parent=parent_key,
            role_child=child_key,
        )

    def _build_param_rows(
        self,
        parent_item: QStandardItem,
        parent_key: str,
        data: dict,
        params: list[ParamDef],
        role_type_str: str,
        *,
        child_key: str | None = None,
    ) -> None:
        """Добавить строки параметров в группу «Параметры».

        Args:
            parent_item:   Родительский item (группа «Параметры»).
            parent_key:    Ключ родителя верхнего уровня.
            data:          Данные для извлечения значений параметров.
            params:        Список определений параметров (ParamDef).
            role_type_str: Строка для ROLE_TYPE ("parent_param" или "child_param").
            child_key:     Ключ дочернего элемента (если параметры — child-уровня).
        """
        for param_def in params:
            raw_value = data.get(param_def.key)
            display_value = self._format_param_value(raw_value, param_def)

            row = self._make_param_row(f"⚙ {param_def.label}", display_value, param_def.comment)

            # Установить роли
            item = row[0]
            item.setData(role_type_str, ROLE_TYPE)
            item.setData(parent_key, ROLE_PARENT)
            if child_key is not None:
                item.setData(child_key, ROLE_CHILD)
            item.setData(param_def.key, ROLE_PARAM)

            # Editable: устанавливаем/снимаем флаг на COL_VAL
            val_item = row[1]
            if not param_def.editable:
                val_item.setFlags(val_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            parent_item.appendRow(row)

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    @staticmethod
    def _format_param_value(raw_value: Any, param_def: ParamDef) -> str:
        """Отформатировать значение параметра для отображения.

        Args:
            raw_value: Сырое значение из данных.
            param_def: Определение параметра.

        Returns:
            Строковое представление для отображения в дереве.
        """
        if raw_value is None:
            return "—"

        # Кастомный formatter имеет приоритет
        if param_def.formatter is not None:
            try:
                return param_def.formatter(raw_value)
            except Exception:
                return str(raw_value)

        # Bool → ✓/✗
        if param_def.is_bool or isinstance(raw_value, bool):
            return "✓" if raw_value else "✗"

        return str(raw_value)

    def _make_group_item(
        self,
        label: str,
        type_str: str,
        parent_key: str,
        child_key: str | None = None,
    ) -> QStandardItem:
        """Создать item-группу (серый, не редактируется).

        Args:
            label:      Текст группы.
            type_str:   Значение ROLE_TYPE.
            parent_key: Ключ родителя.
            child_key:  Ключ дочернего элемента (опционально).

        Returns:
            Настроенный QStandardItem.
        """
        item = QStandardItem(f"□ {label}")
        item.setForeground(_COLOR_GROUP)
        item.setData(type_str, ROLE_TYPE)
        item.setData(parent_key, ROLE_PARENT)
        if child_key is not None:
            item.setData(child_key, ROLE_CHILD)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _make_param_row(self, name: str, value: str, desc: str) -> list[QStandardItem]:
        """Создать строку параметра с серым шрифтом.

        Args:
            name:  Имя параметра (COL_NAME).
            value: Значение (COL_VAL).
            desc:  Описание (COL_COMMENT).

        Returns:
            Список из 4 QStandardItem.
        """
        name_item = QStandardItem(name)
        name_item.setForeground(_COLOR_GRAY)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        val_item = QStandardItem(value)
        val_item.setForeground(_COLOR_GRAY)
        # Флаг editable по умолчанию присутствует; снимается в _build_param_rows если нужно

        desc_item = QStandardItem(desc)
        desc_item.setForeground(_COLOR_GRAY)
        desc_item.setFlags(desc_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        summary_item = QStandardItem("")
        summary_item.setFlags(summary_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        return self._pad_row([name_item, val_item, desc_item, summary_item])

    @staticmethod
    def _make_full_row(first_item: QStandardItem) -> list[QStandardItem]:
        """Создать полную строку: первый item + пустые для остальных колонок.

        Args:
            first_item: QStandardItem для COL_NAME.

        Returns:
            Список из 4 QStandardItem.
        """
        return [
            first_item,
            QStandardItem(""),
            QStandardItem(""),
            QStandardItem(""),
        ]

    def _pad_row(self, items: list[QStandardItem]) -> list[QStandardItem]:
        """Дополнить строку пустыми элементами до количества колонок.

        Args:
            items: Список QStandardItem (может быть короче числа колонок).

        Returns:
            Список QStandardItem длиной == количество колонок.
        """
        col_count = len(self._config.columns)
        while len(items) < col_count:
            empty = QStandardItem("")
            empty.setFlags(empty.flags() & ~Qt.ItemFlag.ItemIsEditable)
            items.append(empty)
        return items[:col_count]

    def _get_children_for_parent(self, parent_key: str) -> dict[str, dict]:
        """Отфильтровать дочерние элементы по parent_ref.

        Args:
            parent_key: Ключ родителя для фильтрации.

        Returns:
            Словарь {child_key: child_data} для данного родителя.
        """
        return {k: v for k, v in self._children.items() if v.get("parent_ref") == parent_key}

    def _sorted_parent_keys(self) -> list[str]:
        """Вернуть ключи родителей, отсортированные по sort_order и имени.

        Returns:
            Отсортированный список ключей.
        """
        return sorted(
            self._parents.keys(),
            key=lambda k: (self._parents[k].get("sort_order", 9999), k),
        )

    @staticmethod
    def _sorted_child_keys(children: dict[str, dict]) -> list[str]:
        """Вернуть ключи дочерних элементов, отсортированные по sort_order и имени.

        Args:
            children: Словарь дочерних элементов.

        Returns:
            Отсортированный список ключей.
        """
        return sorted(
            children.keys(),
            key=lambda k: (children[k].get("sort_order", 9999), k),
        )

    # ------------------------------------------------------------------
    # Рекурсивный поиск по ролям
    # ------------------------------------------------------------------

    def _find_item_by_roles(
        self,
        role_type: str | None,
        role_parent: str | None,
        role_child: str | None,
        role_param: str | None,
        parent: QStandardItem | None = None,
    ) -> QStandardItem | None:
        """Рекурсивно найти item, у которого все четыре роли совпадают.

        Args:
            role_type:   Ожидаемый ROLE_TYPE.
            role_parent: Ожидаемый ROLE_PARENT.
            role_child:  Ожидаемый ROLE_CHILD.
            role_param:  Ожидаемый ROLE_PARAM.
            parent:      Узел поиска (по умолчанию — invisibleRootItem).

        Returns:
            Найденный QStandardItem или None.
        """
        if parent is None:
            parent = self._model.invisibleRootItem()

        for row in range(parent.rowCount()):
            item = parent.child(row, 0)
            if item is None:
                continue
            if (
                item.data(ROLE_TYPE) == role_type
                and item.data(ROLE_PARENT) == role_parent
                and item.data(ROLE_CHILD) == role_child
                and item.data(ROLE_PARAM) == role_param
            ):
                return item
            # Рекурсия в дочерние узлы
            found = self._find_item_by_roles(role_type, role_parent, role_child, role_param, item)
            if found is not None:
                return found

        return None


__all__ = [
    "EntityTreeWidget",
    "ROLE_TYPE",
    "ROLE_PARENT",
    "ROLE_CHILD",
    "ROLE_PARAM",
]
