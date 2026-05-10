"""ProcessPluginPanel — правая панель конструктора для управления плагинами процесса.

При клике на ноду процесса на канвасе показывает:
  - Заголовок с именем процесса
  - PluginChainEditor — текущая цепочка плагинов
  - PluginCatalogWidget — каталог для добавления плагинов
  - PluginConfigPanel — форма конфига выбранного плагина

Публичный API:
    show_process(proc_key, proc_data) — отобразить процесс
    clear()                           — сбросить все дочерние виджеты
    current_proc_key()                — вернуть текущий ключ процесса

Сигнал process_changed(str, dict) — эмитируется при любом изменении plugins.

Правило Dict at Boundary: proc_data и plugins — dict/list[dict], Pydantic внутри процесса.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QLabel,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

# Импорт напрямую из модулей — избегаем circular imports через __init__.py
from multiprocess_prototype.frontend.widgets.tabs_setting.processes_tab.plugin_chain_editor import (
    PluginChainEditor,
)
from multiprocess_prototype.frontend.widgets.tabs_setting.processes_tab.plugin_catalog_widget import (
    PluginCatalogWidget,
)
from multiprocess_prototype.frontend.widgets.tabs_setting.processes_tab.plugin_config_panel import (
    PluginConfigPanel,
)

logger = logging.getLogger(__name__)


class ProcessPluginPanel(QWidget):
    """Правая панель конструктора: chain editor + catalog + config для выбранного процесса.

    Signals:
        process_changed(str, dict): (proc_key, updated_proc_data) — при любом изменении plugins.
    """

    process_changed = Signal(str, dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Текущий контекст процесса
        self._proc_key: str | None = None
        self._proc_data: dict | None = None

        self._setup_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Построить layout: заголовок + вертикальный сплиттер."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Заголовок с именем процесса
        self._title_label = QLabel("")
        self._title_label.setStyleSheet(
            "font-weight: bold; font-size: 14px;"
        )
        layout.addWidget(self._title_label)

        # Верхний сплиттер (вертикальный): chain editor | нижняя часть
        self._v_splitter = QSplitter(Qt.Orientation.Vertical)

        # Chain editor — цепочка плагинов процесса
        self._chain_editor = PluginChainEditor()
        self._v_splitter.addWidget(self._chain_editor)

        # Нижний сплиттер (горизонтальный): catalog | config
        self._h_splitter = QSplitter(Qt.Orientation.Horizontal)

        self._catalog = PluginCatalogWidget()
        self._config_panel = PluginConfigPanel()

        self._h_splitter.addWidget(self._catalog)
        self._h_splitter.addWidget(self._config_panel)

        # Равное начальное разделение catalog / config
        self._h_splitter.setSizes([300, 300])

        self._v_splitter.addWidget(self._h_splitter)

        # Начальное разделение: chain editor 40% / нижняя часть 60%
        self._v_splitter.setSizes([300, 450])

        layout.addWidget(self._v_splitter, stretch=1)

    def _connect_signals(self) -> None:
        """Подключить сигналы дочерних виджетов."""
        # 1. Выбор плагина в chain editor → показать конфиг
        self._chain_editor.plugin_selected.connect(self._on_plugin_selected)

        # 2. Удаление плагина из chain editor
        self._chain_editor.plugin_removed.connect(self._on_plugin_removed)

        # 3. Перемещение плагина в chain editor
        self._chain_editor.plugin_moved.connect(self._on_plugin_moved)

        # 4. Добавление плагина из каталога
        self._catalog.plugin_activated.connect(self._on_plugin_activated)

        # 5. Изменение конфига плагина
        self._config_panel.config_changed.connect(self._on_config_changed)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def show_process(self, proc_key: str, proc_data: dict) -> None:
        """Отобразить плагины выбранного процесса.

        Args:
            proc_key:  Ключ процесса (строка-идентификатор).
            proc_data: Данные процесса как dict (Dict at Boundary).
                       Ожидаемые ключи: "name", "plugins" (list[dict]).
        """
        # Сохранить контекст (shallow copy — не мутируем оригинал снаружи)
        self._proc_key = proc_key
        self._proc_data = dict(proc_data)

        # Обновить заголовок
        name = proc_data.get("name", proc_key)
        self._title_label.setText(name)

        # Отобразить цепочку плагинов
        plugins: list[dict] = self._proc_data.get("plugins", [])
        self._chain_editor.set_chain(proc_key, plugins)

        # Сбросить конфиг — новый процесс, ничего не выбрано
        self._config_panel.clear()

        logger.debug(
            "ProcessPluginPanel: show_process '%s' (%d плагинов)",
            proc_key,
            len(plugins),
        )

    def clear(self) -> None:
        """Сбросить все дочерние виджеты и очистить контекст процесса."""
        self._proc_key = None
        self._proc_data = None

        self._title_label.setText("")
        self._chain_editor.set_chain("", [])
        self._config_panel.clear()

        logger.debug("ProcessPluginPanel: сброшена")

    def current_proc_key(self) -> str | None:
        """Вернуть ключ текущего выбранного процесса или None."""
        return self._proc_key

    # ------------------------------------------------------------------
    # Слоты дочерних виджетов
    # ------------------------------------------------------------------

    def _on_plugin_selected(self, proc_key: str, idx: int) -> None:
        """Слот выбора плагина в chain editor — показать его конфиг.

        Args:
            proc_key: Ключ процесса (из сигнала chain editor).
            idx:      Индекс плагина в списке plugins.
        """
        if self._proc_data is None:
            return

        plugins: list[dict] = self._proc_data.get("plugins", [])
        if 0 <= idx < len(plugins):
            self._config_panel.show_plugin(proc_key, idx, plugins[idx])
        else:
            logger.warning(
                "ProcessPluginPanel: plugin_selected индекс %d вне диапазона (всего %d)",
                idx,
                len(plugins),
            )

    def _on_plugin_removed(self, proc_key: str, idx: int) -> None:  # noqa: ARG002
        """Слот удаления плагина из chain editor.

        Args:
            proc_key: Ключ процесса (не используется — берём self._proc_key).
            idx:      Индекс удаляемого плагина.
        """
        if self._proc_data is None:
            return

        plugins: list[dict] = self._proc_data.get("plugins", [])
        if 0 <= idx < len(plugins):
            removed = plugins.pop(idx)
            logger.debug(
                "ProcessPluginPanel: удалён плагин [%d] '%s'",
                idx,
                removed.get("plugin_name", "?"),
            )
            self._config_panel.clear()
            self._emit_process_changed()
        else:
            logger.warning(
                "ProcessPluginPanel: plugin_removed индекс %d вне диапазона",
                idx,
            )

    def _on_plugin_moved(self, proc_key: str, from_idx: int, to_idx: int) -> None:  # noqa: ARG002
        """Слот перемещения плагина в chain editor.

        Args:
            proc_key:  Ключ процесса (не используется — берём self._proc_key).
            from_idx:  Исходный индекс.
            to_idx:    Целевой индекс.
        """
        if self._proc_data is None:
            return

        plugins: list[dict] = self._proc_data.get("plugins", [])
        n = len(plugins)
        if 0 <= from_idx < n and 0 <= to_idx < n:
            # Переставить элемент списка
            plugin = plugins.pop(from_idx)
            plugins.insert(to_idx, plugin)
            logger.debug(
                "ProcessPluginPanel: плагин '%s' перемещён %d → %d",
                plugin.get("plugin_name", "?"),
                from_idx,
                to_idx,
            )
            self._emit_process_changed()
        else:
            logger.warning(
                "ProcessPluginPanel: plugin_moved неверные индексы %d → %d (всего %d)",
                from_idx,
                to_idx,
                n,
            )

    def _on_plugin_activated(self, plugin_dict: dict) -> None:
        """Слот добавления плагина из каталога.

        Args:
            plugin_dict: Минимальный dict от PluginCatalogWidget
                         (ключи: plugin_class, plugin_name, category).
        """
        if self._proc_data is None:
            return

        plugins: list[dict] = self._proc_data.setdefault("plugins", [])
        plugins.append(dict(plugin_dict))  # добавляем копию

        logger.debug(
            "ProcessPluginPanel: добавлен плагин '%s'",
            plugin_dict.get("plugin_name", "?"),
        )
        self._emit_process_changed()

    def _on_config_changed(
        self, proc_key: str, plugin_index: int, updated_fields: dict  # noqa: ARG002
    ) -> None:
        """Слот изменения конфига плагина.

        Args:
            proc_key:       Ключ процесса (из сигнала PluginConfigPanel).
            plugin_index:   Индекс плагина в списке.
            updated_fields: Обновлённые поля (не-системные).
        """
        if self._proc_data is None:
            return

        plugins: list[dict] = self._proc_data.get("plugins", [])
        if 0 <= plugin_index < len(plugins):
            # Мёрджим обновлённые поля поверх текущего dict плагина
            plugins[plugin_index].update(updated_fields)
            logger.debug(
                "ProcessPluginPanel: обновлён конфиг плагина [%d], поля: %s",
                plugin_index,
                list(updated_fields.keys()),
            )
            self._emit_process_changed()
        else:
            logger.warning(
                "ProcessPluginPanel: config_changed индекс %d вне диапазона (всего %d)",
                plugin_index,
                len(plugins),
            )

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _emit_process_changed(self) -> None:
        """Переотобразить chain editor и эмитировать process_changed."""
        if self._proc_key and self._proc_data is not None:
            # Переотобразить chain после мутации
            self._chain_editor.set_chain(
                self._proc_key, self._proc_data.get("plugins", [])
            )
            self.process_changed.emit(self._proc_key, dict(self._proc_data))


__all__ = ["ProcessPluginPanel"]
