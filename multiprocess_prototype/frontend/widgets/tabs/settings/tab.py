"""SettingsTab — таб Settings на основе DiffScrollTabLayout.

Layout (дифференциальный скролл):

    ┌──────────────┬──────────────┬────────────────────┬───┐
    │  [scroll]    │ ┌──────────┐ │  [scroll]          │ █ │
    │  Actions     │ │Настройки │ │  Content           │ █ │
    │  (120px)     │ └──────────┘ │  (QStackedWidget)  │   │
    │  QStacked    │  [scroll]    │                    │   │
    │  Widget      │  ▾ Админ     │                    │   │
    │  (кнопки     │    Users...  │                    │   │
    │  меняются    │  Настр.сист. │                    │   │
    │  по секции)  │  Интерфейс   │                    │   │
    ├──────────────┤  Оформление  │                    │   │
    │ [static]     │  История     │                    │   │
    │  [◀]  [▶]   │              │                    │   │
    └──────────────┴──────────────┴────────────────────┴───┘

Action-колонка содержит QStackedWidget: каждая секция регистрирует
свою «страницу» кнопок через _register_action_page(). При переключении
секции в дереве навигации action_stack переключается автоматически.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pydantic
from datetime import datetime

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class _CurrentPageStack(QStackedWidget):
    """QStackedWidget, чей размер определяется только текущей страницей.

    Стандартный QStackedLayout.minimumSize() = max всех дочерних виджетов,
    даже скрытых. Из-за этого scroll area выделяет место под самую большую
    страницу, и мастер-скроллбар показывает диапазон даже на маленькой.

    Решение: при смене страницы ставим неактивным виджетам
    QSizePolicy.Ignored — QStackedLayout пропустит их в расчёте
    minimumSize. Активной странице возвращаем Preferred.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(QSize(0, 0))
        self.currentChanged.connect(self._apply_size_policies)

    def sizeHint(self) -> QSize:  # noqa: N802
        w = self.currentWidget()
        if w is not None:
            return w.sizeHint()
        return super().sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        w = self.currentWidget()
        if w is not None:
            return w.minimumSizeHint()
        return super().minimumSizeHint()

    def _apply_size_policies(self, index: int) -> None:
        """Ignored на неактивных страницах → layout не считает их размер."""
        for i in range(self.count()):
            w = self.widget(i)
            if w is None:
                continue
            if i == index:
                w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            else:
                w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.updateGeometry()

from multiprocess_prototype.frontend.forms import RegisterView, ViewMode
from multiprocess_prototype.frontend.forms.field_editor import FieldEditor
from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewModeToggle
from multiprocess_prototype.frontend.prefs.store import UiPrefsStore
from multiprocess_prototype.frontend.widgets.primitives.diff_scroll_tab_layout import (
    DiffScrollTabLayout,
)

from .yaml_io import SETTINGS_PATH, load_settings, save_settings, schema_to_field_infos

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext

logger = logging.getLogger(__name__)

# Русские названия секций для group-box (RegisterView)
_SECTION_TITLES: dict[str, str] = {
    "system": "Система",
    "camera": "Камера",
    "processing": "Обработка",
    "display": "Дисплей",
    "storage": "Хранение",
}

# Ширины колонок
_ACTION_WIDTH = 160
_NAV_WIDTH = 230
_NAV_ITEM_HEIGHT = 36


class SettingsTab(QWidget):
    """Таб Settings — DiffScrollTabLayout с дифференциальным скроллом.

    Сигналы:
        settings_saved(dict): эмитится при успешном сохранении system.yaml
        dirty_changed(bool): эмитится при смене dirty-флага (для statusBar)
    """

    settings_saved = Signal(dict)
    dirty_changed = Signal(bool)

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx

        # Загрузить конфиг и предпочтения
        self._cfg = load_settings()
        self._prefs = UiPrefsStore()
        self._dirty = False

        # Подготовить RegisterView для секции «Настройки системы»
        field_infos = schema_to_field_infos(self._cfg)
        try:
            initial_mode = ViewMode(self._prefs.get("settings.view_mode", "cards"))
        except ValueError:
            initial_mode = ViewMode.CARDS

        self._view = RegisterView(
            field_infos,
            initial_mode=initial_mode,
            category_titles=_SECTION_TITLES,
        )
        self._init_editor_values(field_infos)

        for key, editor in self._view.editors().items():
            editor.change_signal.connect(self._on_field_changed)
        self._view.field_changed.connect(self._on_field_changed_action_bus)
        self._view.mode_changed.connect(
            lambda mode_str: self._prefs.set("settings.view_mode", mode_str)
        )

        # Маппинг ключ → индекс в content stack
        self._page_index: dict[str, int] = {}

        # Построить UI
        self._setup_ui()

    # ------------------------------------------------------------------
    # Фабричный метод
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, ctx: "AppContext") -> "SettingsTab":
        """Фабричный метод для TabFactory.custom_factories."""
        return cls(ctx)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """Перечитать system.yaml и сбросить все изменения."""
        self._cfg = load_settings()
        field_infos = schema_to_field_infos(self._cfg)
        self._sync_editors_to_cfg(field_infos)
        self._clear_validation_errors()
        self._set_dirty(False)

    def save(self) -> bool:
        """Собрать значения из виджетов, валидировать и сохранить в YAML."""
        dict_form: dict[str, Any] = {}
        for key, editor in self._view.editors().items():
            parts = key.split(".", 1)
            if len(parts) != 2:
                continue
            section, field_name = parts
            if section not in dict_form:
                dict_form[section] = {}
            dict_form[section][field_name] = editor.getter()

        try:
            from multiprocess_prototype.config.schemas import SystemConfig
            validated = SystemConfig.model_validate(dict_form)
        except pydantic.ValidationError as exc:
            self._show_validation_errors(exc)
            return False

        self._clear_validation_errors()
        save_settings(validated)
        self._cfg = validated
        self.settings_saved.emit(dict_form)
        self._set_dirty(False)
        return True

    def is_dirty(self) -> bool:
        return self._dirty

    def field_editors(self) -> dict[str, FieldEditor]:
        return self._view.editors()

    def view_mode(self) -> ViewMode:
        return self._view.mode()

    # ------------------------------------------------------------------
    # UI Build
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Построить UI на основе DiffScrollTabLayout."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # === DiffScrollTabLayout ===
        self._diff_layout = DiffScrollTabLayout(
            title="Настройки",
            action_width=_ACTION_WIDTH,
            nav_width=_NAV_WIDTH,
        )

        # --- Левая колонка: action widget (QStackedWidget для кнопок секций) ---
        action_widget = QWidget()
        action_layout = QVBoxLayout(action_widget)
        action_layout.setContentsMargins(4, 4, 4, 4)
        action_layout.setSpacing(0)

        self._action_stack = QStackedWidget()
        action_layout.addWidget(self._action_stack, 1)

        # Маппинг ключ секции → индекс страницы в action_stack
        self._action_page_index: dict[str, int] = {}

        # Пустая страница (для секций без кнопок)
        self._action_page_index["_empty"] = self._action_stack.addWidget(QWidget())

        # Страница «Настройки системы»: тумблер + сбросить + сохранить
        self._view._toggle.hide()
        self._external_toggle = ViewModeToggle(initial_mode=self._view.mode())
        self._external_toggle.mode_changed.connect(
            lambda mode_str: self._view.set_mode(ViewMode(mode_str))
        )
        self._btn_reset = QPushButton("Сбросить")
        self._btn_reset.setToolTip("Сбросить изменения и загрузить данные с диска")
        self._btn_reset.clicked.connect(self.reload)
        self._btn_save = QPushButton("Сохранить")
        self._btn_save.setToolTip("Сохранить изменения в config/system.yaml")
        self._btn_save.clicked.connect(self.save)
        self._register_action_page(
            "system_settings",
            [self._external_toggle, self._btn_reset, self._btn_save],
        )

        self._diff_layout.set_action_widget(action_widget)

        # PR3: edit-кнопки — permission gate
        from multiprocess_prototype.frontend.widgets.access import gate_edit_widgets
        _auth = self._ctx.auth
        gate_edit_widgets(
            [self._btn_reset, self._btn_save],
            "tabs.settings.edit",
            _auth.state if _auth is not None else None,
        )

        # --- Средняя колонка: tree nav ---
        self._tree_nav = QTreeWidget()
        self._tree_nav.setObjectName("SettingsTreeNav")
        self._tree_nav.setHeaderHidden(True)
        self._tree_nav.setRootIsDecorated(True)
        self._tree_nav.setIndentation(16)
        # Отключаем встроенный скролл QTreeWidget
        self._tree_nav.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self._tree_nav.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self._tree_nav.currentItemChanged.connect(self._on_tree_item_changed)
        self._diff_layout.set_nav_widget(self._tree_nav)

        # --- Правая колонка: content stack ---
        # _CurrentPageStack — sizeHint учитывает только текущую страницу,
        # иначе скролл раздувается из-за больших страниц (напр. История)
        self._content_stack = _CurrentPageStack()
        self._content_stack.currentChanged.connect(self._on_content_page_changed)
        self._diff_layout.set_content_widget(self._content_stack)

        # --- Undo/Redo (статичная зона) ---
        bus = self._ctx.action_bus()
        self._diff_layout.enable_undo_redo(bus)
        # Сохраняем ссылки для _refresh_undo_redo_state
        self._btn_undo = self._diff_layout.undo_button
        self._btn_redo = self._diff_layout.redo_button

        main_layout.addWidget(self._diff_layout, stretch=1)

        # === Заполнить дерево и стек контента ===
        self._populate_tree_and_stack()

        # Спрятать скроллбар у внутреннего QScrollArea в RegisterView —
        # скроллом управляет мастер-скроллбар DiffScrollTabLayout
        cards_scroll = self._view._cards_widget
        if hasattr(cards_scroll, "setVerticalScrollBarPolicy"):
            cards_scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
            )

        # === Подписка ActionBus ===
        if bus is not None:
            bus.add_change_callback(self._refresh_history)
            bus.add_change_callback(self._on_bus_undo_redo_sync)
            bus.add_change_callback(self._refresh_undo_redo_state)

    # ------------------------------------------------------------------
    # Дерево навигации + стек контента
    # ------------------------------------------------------------------

    def _populate_tree_and_stack(self) -> None:
        """Заполнить QTreeWidget и QStackedWidget."""
        auth = self._ctx.auth
        auth_state = auth.state if auth is not None else None

        # --- Администрация (разворачиваемый узел) ---
        admin_root = QTreeWidgetItem(self._tree_nav, ["Администрация"])
        admin_root.setData(0, Qt.ItemDataRole.UserRole, "admin_dashboard")
        admin_root.setSizeHint(0, QSize(0, _NAV_ITEM_HEIGHT))
        admin_root.setExpanded(True)

        # AdminDashboard
        from .administration.dashboard import AdminDashboard
        dashboard = AdminDashboard(auth_state)
        dashboard.navigate_to.connect(self._navigate_to_admin_section)
        self._add_page("admin_dashboard", dashboard)

        # Подразделы администрации
        admin_children = [
            ("users", "Пользователи"),
            ("roles", "Роли"),
            ("sessions", "Сессии"),
            ("audit_log", "Audit log"),
        ]
        for key, title in admin_children:
            child = QTreeWidgetItem(admin_root, [title])
            child.setData(0, Qt.ItemDataRole.UserRole, key)
            child.setSizeHint(0, QSize(0, _NAV_ITEM_HEIGHT))

        # Лениво создаём панели при первом переходе
        self._lazy_admin_panels: dict[str, QWidget | None] = {
            "users": None,
            "roles": None,
            "sessions": None,
            "audit_log": None,
        }

        # --- Настройки системы ---
        self._add_tree_item("system_settings", "Настройки системы")
        self._add_page("system_settings", self._view)

        # --- Настройка интерфейса ---
        self._add_tree_item("interface_settings", "Настройка интерфейса")
        from .interface_section import InterfaceSection
        self._add_page("interface_settings", InterfaceSection(self._ctx))

        # --- Оформление ---
        self._add_tree_item("appearance", "Оформление")
        self._add_page("appearance", self._build_appearance_widget())

        # --- История ---
        self._add_tree_item("history", "История")
        self._add_page("history", self._build_history_widget())

        # Выбрать начальную секцию
        self._select_tree_key("system_settings")

    def _add_tree_item(self, key: str, title: str) -> QTreeWidgetItem:
        """Добавить top-level элемент в дерево."""
        item = QTreeWidgetItem(self._tree_nav, [title])
        item.setData(0, Qt.ItemDataRole.UserRole, key)
        item.setSizeHint(0, QSize(0, _NAV_ITEM_HEIGHT))
        return item

    def _add_page(self, key: str, widget: QWidget) -> int:
        """Добавить виджет в content stack и запомнить индекс."""
        idx = self._content_stack.addWidget(widget)
        self._page_index[key] = idx
        return idx

    def _select_tree_key(self, key: str) -> None:
        """Выбрать элемент дерева по ключу."""
        iterator = self._tree_nav.invisibleRootItem()
        item = self._find_tree_item(iterator, key)
        if item is not None:
            self._tree_nav.setCurrentItem(item)

    def _find_tree_item(self, parent: QTreeWidgetItem, key: str) -> QTreeWidgetItem | None:
        """Рекурсивный поиск элемента дерева по ключу в UserRole."""
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.data(0, Qt.ItemDataRole.UserRole) == key:
                return child
            found = self._find_tree_item(child, key)
            if found is not None:
                return found
        return None

    def _on_tree_item_changed(self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None) -> None:
        """Смена текущего элемента дерева → переключить контент."""
        if current is None:
            return
        key = current.data(0, Qt.ItemDataRole.UserRole)
        if not key:
            return

        # Ленивое создание панелей администрации
        if key in self._lazy_admin_panels and key not in self._page_index:
            widget = self._create_admin_panel(key)
            if widget is not None:
                self._add_page(key, widget)
                self._lazy_admin_panels[key] = widget

        idx = self._page_index.get(key)
        if idx is not None:
            self._content_stack.setCurrentIndex(idx)

        # Переключить кнопки в action-колонке
        self._switch_action_buttons(key)

    def _navigate_to_admin_section(self, key: str) -> None:
        """Навигация из AdminDashboard → выбор дочернего узла в дереве."""
        self._select_tree_key(key)

    def _create_admin_panel(self, key: str) -> QWidget | None:
        """Создать панель администрации по ключу (ленивая инициализация).

        Панель создаётся, её action_buttons() регистрируются в action-колонке.
        """
        auth = self._ctx.auth
        bus = self._ctx.action_bus()

        panel: QWidget | None = None
        if key == "users":
            from .administration.users_panel import UsersPanel
            panel = UsersPanel(auth)
        elif key == "roles":
            from .administration.roles_panel import RolesPanel
            panel = RolesPanel(auth, bus)
        elif key == "sessions":
            from .administration.sessions_panel import SessionsPanel
            panel = SessionsPanel(auth)
        elif key == "audit_log":
            from .administration.audit_log_panel import AuditLogPanel
            panel = AuditLogPanel(auth)

        # Зарегистрировать кнопки панели в action-колонке
        if panel is not None and hasattr(panel, "action_buttons"):
            self._register_action_page(key, panel.action_buttons())

        return panel

    # ------------------------------------------------------------------
    # Action-колонка (левая): переключение кнопок по секциям
    # ------------------------------------------------------------------

    def _register_action_page(self, key: str, widgets: list[QWidget]) -> None:
        """Создать страницу в action_stack с виджетами и запомнить индекс."""
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(12)
        for w in widgets:
            page_layout.addWidget(w)
        page_layout.addStretch(1)
        self._action_page_index[key] = self._action_stack.addWidget(page)

    def _switch_action_buttons(self, key: str) -> None:
        """Переключить action_stack на страницу текущей секции."""
        idx = self._action_page_index.get(key, self._action_page_index["_empty"])
        self._action_stack.setCurrentIndex(idx)

    def _on_content_page_changed(self, _index: int) -> None:
        """При смене страницы — принудительно пересчитать scroll area.

        _CurrentPageStack уже переключил size policies в _apply_size_policies.
        Toggle widgetResizable заставляет QScrollArea пересчитать
        размер виджета и диапазон скроллбара.
        """
        sa = self._diff_layout._content_scroll
        sa.setWidgetResizable(False)
        sa.setWidgetResizable(True)
        self._diff_layout._update_master_range()

    # ------------------------------------------------------------------
    # Builders для секций-контентов
    # ------------------------------------------------------------------

    def _build_appearance_widget(self) -> QWidget:
        """Виджет секции «Оформление» — редактор темы с таблицей тем и деревом переменных."""
        from multiprocess_prototype.frontend.styles.theme_loader import create_theme_manager
        from multiprocess_prototype.frontend.managers.theme_presets_manager import ThemePresetsManager
        from .theme_editor_section import ThemeEditorSection

        section = ThemeEditorSection(create_theme_manager(), ThemePresetsManager())
        # Зарегистрировать кнопки секции в action-колонке
        self._register_action_page("appearance", section.action_buttons())
        return section

    def _build_history_widget(self) -> QWidget:
        """Виджет секции «История» — таблица действий ActionBus."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        _HISTORY_COLUMNS = ["Время", "Вкладка", "Параметр", "Значение"]
        self._history_table = QTableWidget(0, len(_HISTORY_COLUMNS))
        self._history_table.setHorizontalHeaderLabels(_HISTORY_COLUMNS)
        self._history_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows,
        )
        self._history_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers,
        )
        self._history_table.verticalHeader().setVisible(False)

        h = self._history_table.horizontalHeader()
        if h:
            h.setStretchLastSection(False)

            h.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
            h.resizeSection(0, 140)   # Время — пошире

            h.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
            h.resizeSection(1, 150)   # Вкладка — пошире

            h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

            h.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)    
            h.resizeSection(3, 120)   # Значение — поуже

        layout.addWidget(self._history_table)

        # Кнопки — в левую action-колонку (как у других секций)
        self._btn_save_history = QPushButton("Сохранить в файл")
        self._btn_save_history.setToolTip("Экспортировать историю в CSV-файл")
        self._btn_save_history.setEnabled(False)
        self._btn_save_history.clicked.connect(self._on_history_save)

        self._btn_clear_history = QPushButton("Очистить историю")
        self._btn_clear_history.setToolTip("Очистить всю историю действий")
        self._btn_clear_history.setEnabled(False)
        self._btn_clear_history.clicked.connect(self._on_history_clear)

        self._register_action_page(
            "history",
            [self._btn_save_history, self._btn_clear_history],
        )

        return container

    # ------------------------------------------------------------------
    # Editors / Field sync
    # ------------------------------------------------------------------

    def _init_editor_values(self, field_infos: list) -> None:
        self._sync_editors_to_cfg(field_infos)

    def _sync_editors_to_cfg(self, field_infos: list) -> None:
        editors = self._view.editors()
        for fi in field_infos:
            section_name = fi.plugin_name
            field_name = fi.field_name
            key = f"{section_name}.{field_name}"
            section_obj = getattr(self._cfg, section_name, None)
            if section_obj is None:
                continue
            value = getattr(section_obj, field_name, None)
            if value is None:
                continue
            editor = editors.get(key)
            if editor is None:
                continue
            try:
                editor.setter(value)
            except Exception:
                pass

    def _on_field_changed(self) -> None:
        self._set_dirty(True)

    def _on_field_changed_action_bus(
        self, register_name: str, field_name: str, old_value: object, new_value: object,
    ) -> None:
        bus = self._ctx.action_bus()
        if bus is None:
            return
        from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder
        action = V2ActionBuilder.field_set_timed(
            register_name, field_name, new_value, old_value,
            description=f"{register_name}.{field_name} = {new_value}",
        )
        bus.record(action)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        self.dirty_changed.emit(dirty)

    def _show_validation_errors(self, exc: pydantic.ValidationError) -> None:
        editors = self._view.editors()
        for error in exc.errors():
            loc = error.get("loc", ())
            if len(loc) >= 2:
                key = f"{loc[0]}.{loc[1]}"
                editor = editors.get(key)
                if editor is not None:
                    editor.widget.setProperty("hasError", True)
                    editor.widget.style().unpolish(editor.widget)
                    editor.widget.style().polish(editor.widget)
                    editor.widget.setToolTip(f"Ошибка: {error['msg']}")

    def _clear_validation_errors(self) -> None:
        for editor in self._view.editors().values():
            editor.widget.setProperty("hasError", False)
            editor.widget.style().unpolish(editor.widget)
            editor.widget.style().polish(editor.widget)
            editor.widget.setToolTip("")

    # ------------------------------------------------------------------
    # History + Undo/Redo
    # ------------------------------------------------------------------

    def _refresh_history(self) -> None:
        bus = self._ctx.action_bus()
        if bus is None:
            return
        actions = bus.history(n=50)
        self._history_table.setRowCount(len(actions))
        for row, action in enumerate(actions):
            ts = datetime.fromtimestamp(action.timestamp).strftime("%H:%M:%S")
            self._history_table.setItem(row, 0, QTableWidgetItem(ts))
            tab_name = action.register_name or action.action_type
            self._history_table.setItem(row, 1, QTableWidgetItem(tab_name))
            param = action.field_name or action.description
            self._history_table.setItem(row, 2, QTableWidgetItem(param))
            value = action.forward_patch.get("value", "")
            if action.action_type == "recipe_apply":
                value = action.forward_patch.get("recipe_name", "recipe")
            self._history_table.setItem(row, 3, QTableWidgetItem(str(value)))
        if actions:
            self._history_table.scrollToBottom()
        has_history = len(actions) > 0
        self._btn_clear_history.setEnabled(bus.can_undo() or bus.can_redo())
        self._btn_save_history.setEnabled(has_history)

    def _refresh_undo_redo_state(self) -> None:
        bus = self._ctx.action_bus()
        if bus is None:
            return
        if self._btn_undo is not None:
            self._btn_undo.setEnabled(bus.can_undo())
        if self._btn_redo is not None:
            self._btn_redo.setEnabled(bus.can_redo())

    def _on_history_undo(self) -> None:
        bus = self._ctx.action_bus()
        if bus is not None:
            bus.undo()

    def _on_history_redo(self) -> None:
        bus = self._ctx.action_bus()
        if bus is not None:
            bus.redo()

    def _on_history_clear(self) -> None:
        bus = self._ctx.action_bus()
        if bus is not None:
            bus.clear()

    def _on_history_save(self) -> None:
        """Экспорт истории действий в CSV-файл."""
        from PySide6.QtWidgets import QFileDialog

        bus = self._ctx.action_bus()
        if bus is None:
            return
        actions = bus.history(n=0)  # все записи
        if not actions:
            return
        path, _ = QFileDialog.getSaveFileName(
            self._view.root_widget(),
            "Сохранить историю",
            "history.csv",
            "CSV (*.csv);;Все файлы (*)",
        )
        if not path:
            return
        import csv

        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["Время", "Вкладка", "Параметр", "Значение"])
            for action in actions:
                ts = datetime.fromtimestamp(action.timestamp).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                tab = action.register_name or action.action_type
                param = action.field_name or action.description
                value = action.forward_patch.get("value", "")
                if action.action_type == "recipe_apply":
                    value = action.forward_patch.get("recipe_name", "recipe")
                writer.writerow([ts, tab, param, str(value)])

    def _on_bus_undo_redo_sync(self) -> None:
        bus = self._ctx.action_bus()
        if bus is None:
            return
        event = bus.last_event
        if event is None:
            return
        event_type, action = event
        if event_type not in ("undo", "redo"):
            return
        if action.action_type != "field_set":
            return
        register_name = action.register_name or ""
        value = (
            action.backward_patch.get("value")
            if event_type == "undo"
            else action.forward_patch.get("value")
        )
        key = f"{register_name}.{action.field_name}"
        if key in self._view.editors():
            self._view.set_editor_value(key, value)
