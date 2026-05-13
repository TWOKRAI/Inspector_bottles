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
свою «страницу» кнопок через register_action_page(). При переключении
секции в дереве навигации action_stack переключается автоматически.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype.frontend.widgets.primitives.diff_scroll_tab_layout import (
    DiffScrollTabLayout,
)

from ._nav_tree import (
    CurrentPageStack as _CurrentPageStack,
    build_nav_tree,
    select_tree_key as _select_tree_key,
)
from .presenter import SettingsPresenter

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext
    from multiprocess_prototype.frontend.forms.field_editor import FieldEditor
    from multiprocess_prototype.frontend.forms import ViewMode
    from .system import SystemSection

logger = logging.getLogger(__name__)

# Русские названия секций для group-box (RegisterView) — оставлены для обратной совместимости
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


class SettingsTab(QWidget):
    """Таб Settings — DiffScrollTabLayout с дифференциальным скроллом.

    Тонкая оболочка над SettingsPresenter: создаёт UI, делегирует
    навигацию presenter'у. Логика системных настроек вынесена в SystemSection.

    Сигналы:
        settings_saved(dict): эмитится при успешном сохранении system.yaml
        dirty_changed(bool): эмитится при смене dirty-флага (для statusBar)
    """

    settings_saved = Signal(dict)
    dirty_changed = Signal(bool)

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx

        # SystemSection создаётся в add_system_settings_page()
        self._system_section: "SystemSection | None" = None

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
    # Публичный API — делегация SystemSection
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """Перечитать system.yaml и сбросить все изменения."""
        if self._system_section is not None:
            self._system_section.presenter.reload()

    def save(self) -> bool:
        """Собрать значения из виджетов, валидировать и сохранить в YAML."""
        if self._system_section is not None:
            return self._system_section.presenter.save()
        return False

    def is_dirty(self) -> bool:
        """Вернуть текущий dirty-флаг системных настроек."""
        if self._system_section is not None:
            return self._system_section.presenter.is_dirty()
        return False

    def field_editors(self) -> "dict[str, FieldEditor]":
        """Вернуть словарь редакторов системных настроек."""
        if self._system_section is not None:
            return self._system_section.field_editors()
        return {}

    def view_mode(self) -> "ViewMode":
        """Вернуть текущий режим отображения."""
        if self._system_section is not None:
            return self._system_section.view_mode()
        from multiprocess_prototype.frontend.forms import ViewMode
        return ViewMode.CARDS

    # ------------------------------------------------------------------
    # SettingsView Protocol — реализация (для presenter)
    # ------------------------------------------------------------------

    def set_content_index(self, index: int) -> None:
        """Переключить content stack на указанный индекс."""
        self._content_stack.setCurrentIndex(index)

    def set_action_index(self, index: int) -> None:
        """Переключить action stack на указанный индекс."""
        self._action_stack.setCurrentIndex(index)

    def register_action_page(self, key: str, widgets: list) -> int:
        """Создать страницу в action stack с виджетами, вернуть индекс."""
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(12)
        for w in widgets:
            page_layout.addWidget(w)
        page_layout.addStretch(1)
        idx = self._action_stack.addWidget(page)
        self._presenter.register_action_page(key, idx)
        return idx

    def add_content_page(self, key: str, widget: object) -> int:
        """Добавить виджет в content stack, вернуть индекс."""
        idx = self._content_stack.addWidget(widget)
        self._presenter.register_content_page(key, idx)
        return idx

    def select_tree_key(self, key: str) -> None:
        """Выбрать элемент nav-дерева по ключу."""
        _select_tree_key(self._tree_nav, key)

    def set_undo_enabled(self, enabled: bool) -> None:
        """Установить доступность кнопки Undo."""
        if self._btn_undo is not None:
            self._btn_undo.setEnabled(enabled)

    def set_redo_enabled(self, enabled: bool) -> None:
        """Установить доступность кнопки Redo."""
        if self._btn_redo is not None:
            self._btn_redo.setEnabled(enabled)

    def build_nav_tree(
        self,
        sections: list[tuple[str, str]],
        admin_children: list[tuple[str, str]],
    ) -> None:
        """Заполнить QTreeWidget секциями навигации."""
        build_nav_tree(self._tree_nav, sections, admin_children)

    def add_admin_dashboard_page(self, admin_children: list[tuple[str, str]]) -> None:
        """Создать AdminDashboard и зарегистрировать в content stack."""
        from .administration.dashboard import AdminDashboard
        auth = self._ctx.auth
        auth_state = auth.state if auth is not None else None
        dashboard = AdminDashboard(auth_state)
        dashboard.navigate_to.connect(self._navigate_to_admin_section)
        self.add_content_page("admin_dashboard", dashboard)

    def add_system_settings_page(self) -> None:
        """Создать SystemSection и зарегистрировать как страницу «Настройки системы»."""
        from .system import SystemSection
        section = SystemSection(self._ctx)
        # Подключить колбэки для проброса сигналов на SettingsTab
        section.presenter.on_settings_saved = lambda data: self.settings_saved.emit(data)
        section.presenter.on_dirty_changed = lambda dirty: self.dirty_changed.emit(dirty)
        # Зарегистрировать кнопки секции в action-колонке
        self.register_action_page("system_settings", section.action_buttons())
        # Зарегистрировать content-страницу
        self.add_content_page("system_settings", section)
        # Подписать presenter секции на undo/redo ActionBus
        bus = self._ctx.action_bus()
        if bus is not None:
            bus.add_change_callback(section.presenter.on_bus_undo_redo_sync)
        # Зарегистрировать секцию в presenter'е
        self._presenter.register_section(section)
        # Сохранить ссылку для делегации публичных методов
        self._system_section = section
        # Для обратной совместимости с тестами: _view указывает на register_view секции
        self._view = section.register_view

    def add_interface_settings_page(self) -> None:
        """Создать InterfaceSection и зарегистрировать в content stack."""
        from .interface import InterfaceSection
        section = InterfaceSection(self._ctx)
        self.add_content_page("interface_settings", section)
        self._presenter.register_section(section)

    def add_appearance_page(self) -> None:
        """Создать AppearanceSection и зарегистрировать в content stack."""
        from multiprocess_prototype.frontend.styles.theme_loader import create_theme_manager
        from multiprocess_prototype.frontend.managers.theme_presets_manager import ThemePresetsManager
        from .appearance import AppearanceSection
        section = AppearanceSection(
            theme_manager=create_theme_manager(),
            presets_manager=ThemePresetsManager(),
        )
        # Зарегистрировать кнопки секции в action-колонке
        self.register_action_page("appearance", section.action_buttons())
        self.add_content_page("appearance", section)

    def add_history_page(self) -> None:
        """Создать HistorySection и зарегистрировать в content stack."""
        from .history import HistorySection
        section = HistorySection(self._ctx)
        # Кнопки секции регистрируются в action-колонке
        self.register_action_page("history", section.action_buttons())
        self.add_content_page("history", section)
        # Подписать presenter секции на обновления ActionBus
        bus = self._ctx.action_bus()
        if bus is not None:
            bus.add_change_callback(section.presenter.refresh)
        # Зарегистрировать секцию в presenter'е для on_activated / on_deactivated
        self._presenter.register_section(section)

    def create_admin_panel(self, key: str) -> None:
        """Создать admin-панель и уведомить presenter (ленивая инициализация).

        Presenter вызывает этот метод, когда панель ещё не была создана.
        View создаёт Qt-виджет и вызывает notify_admin_panel_created().
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

        if panel is None:
            logger.warning("Неизвестный ключ admin-панели: %s", key)
            return

        # Зарегистрировать кнопки панели в action-колонке
        # TODO(Phase 5): заменить hasattr на isinstance(panel, SectionProtocol)
        action_idx = self._presenter.get_action_index("_empty")
        if hasattr(panel, "action_buttons"):
            action_idx = self.register_action_page(key, panel.action_buttons())

        content_idx = self._content_stack.addWidget(panel)
        self._presenter.notify_admin_panel_created(key, panel, action_idx, content_idx)

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

        # --- Создать presenter ---
        self._presenter = SettingsPresenter(view=self, rm=None, ui=None, ctx=self._ctx)

        # --- Левая колонка: action widget (QStackedWidget для кнопок секций) ---
        action_widget = QWidget()
        action_layout = QVBoxLayout(action_widget)
        action_layout.setContentsMargins(4, 4, 4, 4)
        action_layout.setSpacing(0)

        self._action_stack = QStackedWidget()
        action_layout.addWidget(self._action_stack, 1)

        # Пустая страница (для секций без кнопок)
        empty_idx = self._action_stack.addWidget(QWidget())
        self._presenter.register_action_page("_empty", empty_idx)

        # Кнопки system_settings регистрируются в add_system_settings_page()
        # через SystemSection.action_buttons() — см. ниже в populate()

        self._diff_layout.set_action_widget(action_widget)

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
        # Сохраняем ссылки для presenter.on_bus_change
        self._btn_undo = self._diff_layout.undo_button
        self._btn_redo = self._diff_layout.redo_button

        main_layout.addWidget(self._diff_layout, stretch=1)

        # === Presenter координирует заполнение дерева и стека контента ===
        # populate() вызывает add_system_settings_page() → создаётся SystemSection
        self._presenter.populate()

        # Спрятать скроллбар у внутреннего QScrollArea в SystemSection.RegisterView —
        # скроллом управляет мастер-скроллбар DiffScrollTabLayout
        if self._system_section is not None:
            cards_scroll = self._system_section.register_view._cards_widget
            if hasattr(cards_scroll, "setVerticalScrollBarPolicy"):
                cards_scroll.setVerticalScrollBarPolicy(
                    Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
                )

        # === Подписка ActionBus ===
        if bus is not None:
            bus.add_change_callback(self._presenter.on_bus_change)

    # ------------------------------------------------------------------
    # Обработчики навигации
    # ------------------------------------------------------------------

    def _on_tree_item_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        """Смена текущего элемента дерева → делегировать presenter'у."""
        if current is None:
            return
        key = current.data(0, Qt.ItemDataRole.UserRole)
        if not key:
            return
        # Вся логика (в т.ч. ленивое создание панелей) — в presenter
        self._presenter.on_tree_item_changed(key)

    def _navigate_to_admin_section(self, key: str) -> None:
        """Навигация из AdminDashboard → выбор дочернего узла в дереве."""
        self._presenter.navigate_to(key)

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

