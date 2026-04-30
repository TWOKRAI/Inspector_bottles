"""ProcessesTabWidget — вкладка «Процессы» (editor + monitor).

Полноценная вкладка для конфигурирования и мониторинга процессов:
- CRUD процессов и воркеров через ProcessesSectionView (SystemTopologyEditor)
- Runtime-мониторинг через ProcessMonitorModel + ProcessDataBridge
- Применение изменений через TopologyBridge.apply(SECTION_PROCESSES)
- Merged tree view: конфигурация + runtime в одном дереве
- Detail panel: QStackedWidget (placeholder / process / worker + timing)
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype.frontend.widgets.base.editor.base_editor_toolbar import (
    BaseEditorToolbar,
)

from .blueprint_io import (
    blueprint_to_topology,
    load_blueprint,
    save_blueprint,
    topology_to_blueprint,
)
from .constants import ROLE_PROC, ROLE_TYPE, ROLE_WORKER
from .create_process_dialog import CreateProcessDialog
from .plugin_catalog_widget import PluginCatalogWidget
from .process_data_bridge import ProcessDataBridge
from .process_detail_panel import ProcessDetailPanel
from .process_monitor_model import ProcessMonitorModel
from .process_tree_view import ProcessTreeView

logger = logging.getLogger(__name__)

# Имена кнопок toolbar — константы для set_button_enabled
_BTN_ADD_PROCESS = "+ Процесс"
_BTN_ADD_WORKER = "+ Воркер"
_BTN_REMOVE = "Удалить"
_BTN_START = "Запустить"
_BTN_STOP = "Остановить"
_BTN_RESTART = "Перезапустить"
_BTN_PAUSE = "Пауза"
_BTN_SAVE_BLUEPRINT = "Сохранить рецепт"
_BTN_LOAD_BLUEPRINT = "Загрузить рецепт"

# Дефолтная директория для сохранения blueprint-рецептов
_BLUEPRINTS_DIR = (
    Path(__file__).parent.parent.parent.parent.parent
    / "backend" / "plugins" / "blueprints"
)

# Время debounce после управляющих команд (мс)
_DEBOUNCE_MS = 2000


class ProcessesTabWidget(QWidget):
    """Вкладка конфигурирования и мониторинга процессов системы.

    Состав:
    - ProcessesSectionView — section view для SystemTopologyEditor
    - ProcessMonitorModel  — runtime-статусы процессов
    - ProcessDataBridge    — polling + broadcast → monitor model
    - TopologyBridge       — применение изменений через apply(SECTION_PROCESSES)
    - BaseEditorToolbar    — кнопки CRUD + управления + Apply
    - ProcessTreeView      — merged дерево (editor + monitor)
    - ProcessDetailPanel   — QStackedWidget (placeholder / process / worker)

    Layout: QSplitter(Vertical) — [toolbar + tree] сверху (5),
    detail panel снизу (1).
    """

    def __init__(
        self,
        *,
        command_handler: Any | None = None,
        topology_editor: Any | None = None,
        topology_bridge: Any | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Инициализировать вкладку «Процессы».

        Args:
            command_handler: RoutedCommandSender для отправки команд ProcessManager.
            topology_editor: SystemTopologyEditor — источник конфигурации процессов.
            topology_bridge: TopologyBridge для применения изменений через IPC.
            parent:          Родительский виджет.
        """
        super().__init__(parent)

        self._command_handler = command_handler

        # Имя текущего выбранного процесса (для управляющих кнопок)
        self._selected_process: str | None = None
        # Текущий статус выбранного процесса
        self._selected_status: str = ""
        # Ключ текущего выбранного элемента (process key или "proc/worker")
        self._selected_key: str | None = None
        # Тип текущего выбранного элемента ("process" или "worker")
        self._selected_type: str | None = None

        # -- SystemTopologyEditor --
        self._topology_editor = topology_editor
        self._topology_bridge = topology_bridge

        # Section view для процессов из SystemTopologyEditor
        self._section = topology_editor.processes if topology_editor is not None else None

        # -- Модели данных --
        self._monitor_model = ProcessMonitorModel()

        # -- Bridge для polling мониторинга (всегда активен) --
        self._data_bridge = ProcessDataBridge(self._monitor_model, command_handler)

        # -- Toolbar --
        buttons = [
            (_BTN_ADD_PROCESS, "Создать новый процесс", self._on_add_process),
            (_BTN_ADD_WORKER, "Создать новый воркер", self._on_add_worker),
            (_BTN_REMOVE, "Удалить выбранный элемент", self._on_remove),
            (_BTN_START, "Запустить процесс", self._on_start),
            (_BTN_STOP, "Остановить процесс", self._on_stop),
            (_BTN_RESTART, "Перезапустить процесс", self._on_restart),
            (_BTN_PAUSE, "Приостановить/возобновить", self._on_pause_resume),
            (_BTN_SAVE_BLUEPRINT, "Сохранить конфигурацию процессов как рецепт", self._on_save_blueprint),
            (_BTN_LOAD_BLUEPRINT, "Загрузить конфигурацию процессов из рецепта", self._on_load_blueprint),
        ]
        self._toolbar = BaseEditorToolbar(buttons=buttons, show_apply=True)

        # -- Дерево процессов (merged view) --
        self._tree = ProcessTreeView(
            self._monitor_model, editor_model=self._section
        )

        # -- Detail panel (QStackedWidget) --
        self._detail = ProcessDetailPanel()

        # -- Layout --
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)
        top_layout.addWidget(self._toolbar)
        top_layout.addWidget(self._tree)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(top_widget)
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 1)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(splitter)

        # -- Wiring --
        if self._topology_editor is not None:
            # Подписка через SystemTopologyEditor.subscribe()
            from multiprocess_prototype.registers.system_topology.schemas import SECTION_PROCESSES
            self._topology_editor.subscribe(SECTION_PROCESSES, self._on_editor_changed)
        self._monitor_model.add_change_callback(self._on_monitor_changed)
        self._tree.item_selected.connect(self._on_item_selected)
        self._tree.selection_cleared.connect(self._on_selection_cleared)
        self._toolbar.apply_clicked.connect(self._on_apply)
        self._detail.target_interval_changed.connect(
            self._on_target_interval_changed
        )

        # -- Wiring plugin UI --
        self._detail.chain_editor.plugin_selected.connect(
            self._on_plugin_selected
        )
        self._detail.chain_editor.plugin_removed.connect(
            self._on_plugin_removed
        )
        self._detail.chain_editor.plugin_moved.connect(
            self._on_plugin_moved
        )
        self._detail.chain_editor.add_plugin_requested.connect(
            self._on_add_plugin_requested
        )
        self._detail.config_panel.config_changed.connect(
            self._on_plugin_config_changed
        )

        # Начальное состояние кнопок управления — выключены
        self._update_control_buttons()

        # Первичное заполнение дерева
        self._tree.refresh()

        # Запустить polling (QTimer 5с) как fallback
        self._data_bridge.start_polling(self)

    # ------------------------------------------------------------------
    # set_command_handler (lazy init)
    # ------------------------------------------------------------------

    def set_command_handler(self, handler: Any) -> None:
        """Установить command_handler после создания виджета.

        Используется при lazy-инициализации, когда widget создаётся
        до того, как command_handler станет доступен.

        Args:
            handler: RoutedCommandSender для отправки команд.
        """
        self._command_handler = handler
        # Обновить data bridge (мониторинг)
        self._data_bridge = ProcessDataBridge(self._monitor_model, handler)
        # Перезапустить polling
        self._data_bridge.start_polling(self)

    # ------------------------------------------------------------------
    # Вспомогательное свойство для унифицированного доступа к модели
    # ------------------------------------------------------------------

    @property
    def _active_model(self) -> Any:
        """Section view для процессов из SystemTopologyEditor.

        Предоставляет duck-type API:
          .processes, .workers, .workers_for_process(), .add_process(),
          .add_worker(), .remove_process(), .remove_worker(), .modify_worker(),
          .validate(), .dirty
        """
        return self._section

    def _call_add_worker(
        self,
        process_ref: str,
        worker_name: str,
        worker_type: str,
        target_interval_ms: int,
    ) -> str:
        """Добавить воркер через ProcessesSectionView.

        Args:
            process_ref:        Ключ процесса-владельца.
            worker_name:        Имя нового воркера.
            worker_type:        Тип воркера.
            target_interval_ms: Целевой интервал цикла.

        Returns:
            Ключ созданного воркера.
        """
        return self._section.add_worker(
            process_ref=process_ref,
            name=worker_name,
            worker_type=worker_type,
            target_interval_ms=target_interval_ms,
        )

    # ------------------------------------------------------------------
    # Обработчики CRUD
    # ------------------------------------------------------------------

    def _on_add_process(self) -> None:
        """Открыть диалог создания нового процесса."""
        dialog = CreateProcessDialog(parent=self)
        dialog.set_mode("process")
        dialog.set_available_processes(list(self._active_model.processes.keys()))

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        data = dialog.get_data()
        if data.get("mode") != "process":
            return

        process_name = data.get("process_name", "").strip()
        class_path = data.get("class_path", "")

        if not process_name or not class_path:
            QMessageBox.warning(
                self, "Ошибка", "Имя и класс процесса обязательны"
            )
            return

        try:
            self._active_model.add_process(
                name=process_name,
                class_path=class_path,
                priority=data.get("priority", "normal"),
                auto_start=data.get("auto_start", True),
            )
            logger.info(
                "ProcessesTabWidget: добавлен процесс '%s'", process_name
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Ошибка", str(exc))

    def _on_add_worker(self) -> None:
        """Открыть диалог создания нового воркера."""
        proc_keys = list(self._active_model.processes.keys())
        if not proc_keys:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Сначала создайте хотя бы один процесс",
            )
            return

        dialog = CreateProcessDialog(parent=self)
        dialog.set_mode("worker")
        dialog.set_available_processes(proc_keys)

        # Если выбран процесс в дереве — предвыбрать его
        if self._selected_process and self._selected_process in proc_keys:
            idx = proc_keys.index(self._selected_process)
            dialog._process_ref_combo.setCurrentIndex(idx)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        data = dialog.get_data()
        if data.get("mode") != "worker":
            return

        worker_name = data.get("worker_name", "").strip()
        process_ref = data.get("process_ref", "")

        if not worker_name:
            QMessageBox.warning(self, "Ошибка", "Имя воркера обязательно")
            return

        if not process_ref:
            QMessageBox.warning(
                self, "Ошибка", "Необходимо выбрать процесс-владелец"
            )
            return

        try:
            self._call_add_worker(
                process_ref=process_ref,
                worker_name=worker_name,
                worker_type=data.get("worker_type", "custom"),
                target_interval_ms=data.get("target_interval_ms", 0),
            )
            logger.info(
                "ProcessesTabWidget: добавлен воркер '%s' → '%s'",
                worker_name,
                process_ref,
            )
        except (KeyError, ValueError) as exc:
            QMessageBox.warning(self, "Ошибка", str(exc))

    def _on_remove(self) -> None:
        """Удалить выбранный элемент (процесс или воркер) с подтверждением."""
        if self._selected_key is None or self._selected_type is None:
            return

        if self._selected_type == "process":
            self._remove_process(self._selected_key)
        elif self._selected_type == "worker":
            self._remove_worker(self._selected_key)

    def _remove_process(self, proc_key: str) -> None:
        """Удалить процесс после подтверждения.

        Args:
            proc_key: Ключ удаляемого процесса.
        """
        reply = QMessageBox.question(
            self,
            "Подтверждение удаления",
            f"Удалить процесс «{proc_key}» и все его воркеры?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self._active_model.remove_process(proc_key)
            logger.info(
                "ProcessesTabWidget: удалён процесс '%s'", proc_key
            )
        except KeyError as exc:
            QMessageBox.warning(self, "Ошибка", str(exc))

    def _remove_worker(self, selected_key: str) -> None:
        """Удалить воркер после подтверждения.

        selected_key в формате "proc_name/worker_name" (из дерева).
        Для editor_model нужен worker_key в формате "proc_name_worker_name".

        Args:
            selected_key: Ключ в формате "proc_name/worker_name".
        """
        parts = selected_key.split("/", 1)
        if len(parts) != 2:
            return

        proc_name, worker_name = parts
        worker_key = f"{proc_name}_{worker_name}"

        reply = QMessageBox.question(
            self,
            "Подтверждение удаления",
            f"Удалить воркер «{worker_name}» процесса «{proc_name}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self._active_model.remove_worker(worker_key)
            logger.info(
                "ProcessesTabWidget: удалён воркер '%s'", worker_key
            )
        except ValueError as exc:
            # Protected воркер — нельзя удалить
            QMessageBox.warning(self, "Ошибка", str(exc))
        except KeyError as exc:
            QMessageBox.warning(self, "Ошибка", str(exc))

    # ------------------------------------------------------------------
    # Обработчики управления (Start/Stop/Restart/Pause)
    # ------------------------------------------------------------------

    def _send_pm_command(self, cmd: str, **params: Any) -> None:
        """Отправить команду в ProcessManager через process.command wrapper.

        Args:
            cmd:     Идентификатор команды ("process.start" и т.д.).
            **params: Дополнительные параметры (process_name и т.д.).
        """
        if self._command_handler is None:
            logger.warning(
                "ProcessesTabWidget._send_pm_command: command_handler не задан"
            )
            return
        try:
            data = {"cmd": cmd, "correlation_id": str(uuid.uuid4()), **params}
            self._command_handler.send("process.command", data=data)
        except Exception:
            logger.exception(
                "ProcessesTabWidget._send_pm_command: ошибка отправки %s", cmd
            )

    def _on_start(self) -> None:
        """Запустить выбранный процесс."""
        if not self._selected_process:
            return

        self._send_pm_command(
            "process.start", process_name=self._selected_process
        )
        logger.info(
            "ProcessesTabWidget: process.start для '%s'",
            self._selected_process,
        )
        self._debounce_controls()

    def _on_stop(self) -> None:
        """Остановить выбранный процесс с подтверждением."""
        if not self._selected_process:
            return

        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Остановить процесс «{self._selected_process}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._send_pm_command(
            "process.stop", process_name=self._selected_process
        )
        logger.info(
            "ProcessesTabWidget: process.stop для '%s'",
            self._selected_process,
        )
        self._debounce_controls()

    def _on_restart(self) -> None:
        """Перезапустить выбранный процесс с подтверждением."""
        if not self._selected_process:
            return

        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Перезапустить процесс «{self._selected_process}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._send_pm_command(
            "process.restart", process_name=self._selected_process
        )
        logger.info(
            "ProcessesTabWidget: process.restart для '%s'",
            self._selected_process,
        )
        self._debounce_controls()

    def _on_pause_resume(self) -> None:
        """Приостановить или возобновить выбранный процесс.

        Определяет действие по текущему статусу:
        - paused → process.resume
        - иначе → process.pause
        """
        if not self._selected_process:
            return

        if self._selected_status == "paused":
            cmd = "process.resume"
        else:
            cmd = "process.pause"

        self._send_pm_command(cmd, process_name=self._selected_process)
        logger.info(
            "ProcessesTabWidget: %s для '%s'", cmd, self._selected_process
        )
        self._debounce_controls()

    def _debounce_controls(self) -> None:
        """Заблокировать кнопки управления на _DEBOUNCE_MS мс."""
        for label in (_BTN_START, _BTN_STOP, _BTN_RESTART, _BTN_PAUSE):
            self._toolbar.set_button_enabled(label, False)
        QTimer.singleShot(_DEBOUNCE_MS, self._update_control_buttons)

    # ------------------------------------------------------------------
    # Обработчики Blueprint save/load
    # ------------------------------------------------------------------

    def _on_save_blueprint(self) -> None:
        """Сохранить текущую конфигурацию процессов как blueprint-рецепт.

        Шаги:
        1. Запросить имя рецепта через QInputDialog.
        2. Конвертировать processes dict → SystemBlueprint.
        3. Выбрать путь сохранения через QFileDialog (дефолт: blueprints/).
        4. Записать JSON.
        """
        if self._active_model is None:
            QMessageBox.warning(self, "Ошибка", "Нет активной модели данных")
            return

        proc_data = self._active_model.processes
        if not proc_data:
            QMessageBox.information(
                self, "Нечего сохранять", "Список процессов пуст"
            )
            return

        # Запросить имя рецепта
        recipe_name, ok = QInputDialog.getText(
            self,
            "Имя рецепта",
            "Введите название конфигурации:",
            text="my_recipe",
        )
        if not ok or not recipe_name.strip():
            return

        recipe_name = recipe_name.strip()

        # Конвертировать
        try:
            bp = topology_to_blueprint(proc_data, name=recipe_name)
        except Exception as exc:
            logger.exception("ProcessesTabWidget: ошибка конвертации в blueprint")
            QMessageBox.critical(self, "Ошибка", f"Ошибка конвертации:\n{exc}")
            return

        # Дефолтный путь
        default_path = str(_BLUEPRINTS_DIR / f"{recipe_name}.json")

        # Диалог сохранения файла
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить рецепт",
            default_path,
            "JSON файлы (*.json);;Все файлы (*)",
        )
        if not file_path:
            return

        try:
            save_blueprint(bp, Path(file_path))
        except OSError as exc:
            logger.exception("ProcessesTabWidget: ошибка записи blueprint")
            QMessageBox.critical(self, "Ошибка сохранения", f"Не удалось записать файл:\n{exc}")
            return

        QMessageBox.information(
            self,
            "Рецепт сохранён",
            f"Рецепт «{recipe_name}» сохранён:\n{file_path}",
        )
        logger.info(
            "ProcessesTabWidget: blueprint '%s' сохранён в %s",
            recipe_name, file_path,
        )

    def _on_load_blueprint(self) -> None:
        """Загрузить конфигурацию процессов из blueprint-рецепта.

        Шаги:
        1. Выбрать JSON файл через QFileDialog.
        2. Загрузить SystemBlueprint.
        3. Конвертировать → topology snapshot.
        4. Применить через section.load_from_snapshot().
        5. Обновить дерево.
        """
        if self._active_model is None:
            QMessageBox.warning(self, "Ошибка", "Нет активной модели данных")
            return

        # Диалог выбора файла
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Загрузить рецепт",
            str(_BLUEPRINTS_DIR),
            "JSON файлы (*.json);;Все файлы (*)",
        )
        if not file_path:
            return

        # Загрузить blueprint
        try:
            bp = load_blueprint(Path(file_path))
        except FileNotFoundError:
            QMessageBox.critical(self, "Ошибка", f"Файл не найден:\n{file_path}")
            return
        except Exception as exc:
            logger.exception("ProcessesTabWidget: ошибка загрузки blueprint")
            QMessageBox.critical(self, "Ошибка загрузки", f"Не удалось загрузить рецепт:\n{exc}")
            return

        # Конвертировать blueprint → topology snapshot
        try:
            snapshot = blueprint_to_topology(bp)
        except Exception as exc:
            logger.exception("ProcessesTabWidget: ошибка конвертации blueprint в topology")
            QMessageBox.critical(self, "Ошибка", f"Ошибка конвертации:\n{exc}")
            return

        # Применить snapshot (заменит текущие данные)
        try:
            self._active_model.load_from_snapshot(snapshot)
        except Exception as exc:
            logger.exception("ProcessesTabWidget: ошибка применения snapshot")
            QMessageBox.critical(self, "Ошибка", f"Не удалось применить конфигурацию:\n{exc}")
            return

        # Обновить дерево
        self._tree.refresh()

        QMessageBox.information(
            self,
            "Рецепт загружен",
            f"Загружен рецепт «{bp.name}» ({len(bp.processes)} процессов)",
        )
        logger.info(
            "ProcessesTabWidget: blueprint '%s' загружен из %s (%d процессов)",
            bp.name, file_path, len(bp.processes),
        )

    # ------------------------------------------------------------------
    # Обработчик Apply
    # ------------------------------------------------------------------

    def _on_apply(self) -> None:
        """Валидировать конфигурацию и применить изменения через TopologyBridge."""
        errors = self._active_model.validate()
        if errors:
            error_text = "\n".join(f"  - {e}" for e in errors)
            QMessageBox.warning(
                self,
                "Ошибки валидации",
                f"Невозможно применить изменения:\n{error_text}",
            )
            return

        if self._topology_bridge is not None:
            from multiprocess_prototype.registers.system_topology.schemas import SECTION_PROCESSES
            self._topology_bridge.apply(SECTION_PROCESSES)

        self._toolbar.set_dirty(False)
        logger.info("ProcessesTabWidget: изменения применены")

    # ------------------------------------------------------------------
    # Обработчик target_interval_changed (от detail panel)
    # ------------------------------------------------------------------

    def _on_target_interval_changed(
        self, worker_key: str, value: int
    ) -> None:
        """Обработать изменение целевого интервала воркера в detail panel.

        worker_key из detail panel имеет формат "proc_name/worker_name".
        Для editor_model нужен формат "proc_name_worker_name".

        Args:
            worker_key: Ключ воркера в формате "proc_name/worker_name".
            value:      Новое значение target_interval_ms.
        """
        # Преобразовать "proc/worker" → "proc_worker" для editor_model
        parts = worker_key.split("/", 1)
        if len(parts) != 2:
            return

        editor_key = f"{parts[0]}_{parts[1]}"
        try:
            self._active_model.modify_worker(
                editor_key, {"target_interval_ms": value}
            )
        except KeyError:
            logger.warning(
                "ProcessesTabWidget: воркер '%s' не найден в active_model",
                editor_key,
            )

    # ------------------------------------------------------------------
    # Callbacks моделей
    # ------------------------------------------------------------------

    def _on_editor_changed(self) -> None:
        """Обновить дерево и dirty-состояние при изменении active model.

        Если сейчас отображается страница плагинов — обновить chain editor.
        """
        self._tree.refresh()
        self._toolbar.set_dirty(self._active_model.dirty)

        # Обновить plugin chain если сейчас показана страница плагинов
        if (
            self._detail.currentIndex() == 3
            and self._selected_key is not None
            and self._selected_type == "process"
        ):
            self._refresh_plugin_chain(self._selected_key)

    def _on_monitor_changed(self) -> None:
        """Обновить дерево и detail panel при изменении monitor_model.

        Конфигурация управляется через SystemTopologyEditor напрямую —
        синхронизация из monitor не нужна.
        """
        self._tree.refresh()

        # Обновить detail panel если показывает текущий выбранный элемент
        if self._selected_key is not None:
            self._update_detail_panel()

    # ------------------------------------------------------------------
    # Обработчики выбора в дереве
    # ------------------------------------------------------------------

    def _on_item_selected(self, key: str) -> None:
        """Обработать выбор элемента в дереве.

        Определяет тип элемента (процесс или воркер), обновляет
        detail panel и состояние кнопок управления.

        Args:
            key: Ключ элемента (data Qt.UserRole из дерева).
        """
        item_type, proc_name, worker_name = self._resolve_selected_item()

        self._selected_key = key
        self._selected_type = item_type

        if item_type == "worker" and proc_name:
            # Для воркера — привязать управление к родительскому процессу
            self._selected_process = proc_name
            self._selected_status = self._get_process_status(proc_name)
            self._update_detail_panel()
            self._update_control_buttons()
            return

        # Тип "process" или fallback
        process_name = proc_name or key
        self._selected_process = process_name
        self._selected_status = self._get_process_status(process_name)
        self._update_detail_panel()
        self._update_control_buttons()

    def _on_selection_cleared(self) -> None:
        """Сбросить detail panel и кнопки управления."""
        self._selected_key = None
        self._selected_type = None
        self._selected_process = None
        self._selected_status = ""
        self._detail.show_placeholder()
        self._update_control_buttons()

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _resolve_selected_item(
        self,
    ) -> tuple[str | None, str | None, str | None]:
        """Определить тип и роли текущего выбранного элемента дерева.

        Returns:
            Кортеж (item_type, proc_name, worker_name).
            Все значения могут быть None если ничего не выбрано.
        """
        index = self._tree._tree.selectionModel().currentIndex()
        if not index.isValid():
            return None, None, None
        # Берём item из первой колонки строки для ролей
        first_col = self._tree._model.index(index.row(), 0, index.parent())
        item = self._tree._model.itemFromIndex(first_col)
        if item is None:
            return None, None, None
        return (
            item.data(ROLE_TYPE),
            item.data(ROLE_PROC),
            item.data(ROLE_WORKER),
        )

    def _get_process_status(self, proc_name: str) -> str:
        """Получить runtime-статус процесса из monitor_model.

        Args:
            proc_name: Имя процесса.

        Returns:
            Строка статуса или пустая строка если данных нет.
        """
        processes = self._monitor_model.processes
        data = processes.get(proc_name, {})
        return data.get("status", "")

    def _update_detail_panel(self) -> None:
        """Обновить detail panel данными текущего выбранного элемента."""
        if self._selected_key is None or self._selected_type is None:
            self._detail.show_placeholder()
            return

        if self._selected_type == "process":
            self._show_process_detail(self._selected_key)
        elif self._selected_type == "worker":
            parts = self._selected_key.split("/", 1)
            if len(parts) == 2:
                self._show_worker_detail(parts[0], parts[1])

    def _show_process_detail(self, proc_key: str) -> None:
        """Собрать merged данные процесса и показать в detail panel.

        Если у процесса есть плагины — показывает plugin UI (страница 3).
        Иначе — legacy ProcessInfoForm (страница 1).

        Объединяет данные из active model и monitor_model.

        Args:
            proc_key: Ключ процесса.
        """
        # Данные из active model (section view или editor_model)
        ed_procs = self._active_model.processes
        ed_data = ed_procs.get(proc_key, {})

        # Проверяем наличие плагинов — если есть, показываем plugin UI
        plugins = ed_data.get("plugins", [])
        if plugins:
            self._refresh_plugin_chain(proc_key)
            self._detail.show_plugins()
            return

        # Данные из monitor
        mon_procs = self._monitor_model.processes
        mon_data = mon_procs.get(proc_key, {})

        # Merged dict: editor как база, monitor перезаписывает runtime-поля
        merged: dict[str, Any] = {
            "name": proc_key,
            "class_path": ed_data.get("class_path", "")
            or mon_data.get("class_path", ""),
            "priority": ed_data.get("priority", "")
            or mon_data.get("priority", ""),
            "status": mon_data.get("status", "configured"),
            "pid": mon_data.get("pid"),
            "alive": mon_data.get("alive", False),
            "workers": mon_data.get("workers", {}),
        }

        self._detail.show_process(merged)

    def _show_worker_detail(self, proc_name: str, worker_name: str) -> None:
        """Собрать merged данные воркера и показать в detail panel.

        Args:
            proc_name:   Имя родительского процесса.
            worker_name: Имя воркера.
        """
        # Данные из active model (section view или editor_model)
        ed_workers = self._active_model.workers_for_process(proc_name)
        ed_worker: dict[str, Any] = {}
        for _wk, wd in ed_workers.items():
            if wd.get("name") == worker_name:
                ed_worker = wd
                break

        # Данные из monitor
        mon_procs = self._monitor_model.processes
        mon_proc = mon_procs.get(proc_name, {})
        mon_workers = mon_proc.get("workers", {})
        mon_worker = mon_workers.get(worker_name, {})

        # Merged dict: editor как база, monitor перезаписывает runtime-поля
        merged: dict[str, Any] = {
            "name": worker_name,
            "worker_type": ed_worker.get("worker_type", "")
            or mon_worker.get("worker_type", ""),
            "protected": ed_worker.get("protected", False),
            "target_interval_ms": ed_worker.get("target_interval_ms", 0),
            # Runtime-поля из monitor
            "status": mon_worker.get("status", "configured"),
            "is_alive": mon_worker.get("is_alive", False),
            "restart_count": mon_worker.get("restart_count", 0),
            "last_error": mon_worker.get("last_error"),
            "cycle_duration_ms": mon_worker.get("cycle_duration_ms"),
            "effective_hz": mon_worker.get("effective_hz"),
            "sleep_ms": mon_worker.get("sleep_ms"),
        }

        self._detail.show_worker(proc_name, merged)

    # ------------------------------------------------------------------
    # Обработчики plugin UI
    # ------------------------------------------------------------------

    def _on_plugin_selected(self, proc_key: str, plugin_index: int) -> None:
        """Обработать выбор карточки плагина — показать конфиг в панели справа.

        Args:
            proc_key:     Ключ процесса.
            plugin_index: Индекс плагина в chain.
        """
        try:
            plugins = self._section.plugins_for_process(proc_key)
        except KeyError:
            return

        if 0 <= plugin_index < len(plugins):
            plugin_dict = plugins[plugin_index]
            self._detail.config_panel.show_plugin(
                proc_key, plugin_index, plugin_dict
            )

    def _on_plugin_removed(self, proc_key: str, plugin_index: int) -> None:
        """Обработать удаление плагина из chain editor.

        Args:
            proc_key:     Ключ процесса.
            plugin_index: Индекс удаляемого плагина.
        """
        try:
            self._section.remove_plugin(proc_key, plugin_index)
        except (KeyError, IndexError) as exc:
            QMessageBox.warning(self, "Ошибка", str(exc))
            return

        # Сбросить config panel — удалённый плагин мог быть выбран
        self._detail.config_panel.clear()
        logger.info(
            "ProcessesTabWidget: удалён плагин [idx=%d] из '%s'",
            plugin_index, proc_key,
        )

    def _on_plugin_moved(
        self, proc_key: str, from_idx: int, to_idx: int
    ) -> None:
        """Обработать перемещение плагина вверх/вниз.

        Args:
            proc_key: Ключ процесса.
            from_idx: Исходный индекс.
            to_idx:   Целевой индекс.
        """
        try:
            self._section.move_plugin(proc_key, from_idx, to_idx)
        except (KeyError, IndexError) as exc:
            QMessageBox.warning(self, "Ошибка", str(exc))
            return

        logger.info(
            "ProcessesTabWidget: перемещён плагин [%d → %d] в '%s'",
            from_idx, to_idx, proc_key,
        )

    def _on_add_plugin_requested(self, proc_key: str) -> None:
        """Открыть каталог плагинов как диалог для добавления.

        Args:
            proc_key: Ключ процесса, в который добавляется плагин.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("Каталог плагинов")
        dialog.setMinimumSize(400, 500)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)

        catalog = PluginCatalogWidget()
        layout.addWidget(catalog)

        def _on_activated(plugin_dict: dict) -> None:
            """Обработать выбор плагина в каталоге — добавить в section view."""
            try:
                self._section.add_plugin(proc_key, plugin_dict)
            except (KeyError, ValueError) as exc:
                QMessageBox.warning(self, "Ошибка", str(exc))
                return

            logger.info(
                "ProcessesTabWidget: добавлен плагин '%s' → '%s'",
                plugin_dict.get("plugin_name", "?"), proc_key,
            )
            dialog.accept()

        catalog.plugin_activated.connect(_on_activated)

        dialog.exec()

    def _on_plugin_config_changed(
        self, proc_key: str, plugin_index: int, fields: dict
    ) -> None:
        """Обработать изменение конфига плагина в config panel.

        Args:
            proc_key:     Ключ процесса.
            plugin_index: Индекс плагина.
            fields:       Обновлённые поля конфига.
        """
        try:
            self._section.update_plugin_config(proc_key, plugin_index, fields)
        except (KeyError, IndexError) as exc:
            logger.warning(
                "ProcessesTabWidget: ошибка обновления конфига плагина: %s", exc
            )

    def _refresh_plugin_chain(self, proc_key: str) -> None:
        """Обновить chain editor данными плагинов из section view.

        Args:
            proc_key: Ключ процесса.
        """
        try:
            plugins = self._section.plugins_for_process(proc_key)
        except KeyError:
            plugins = []

        self._detail.chain_editor.set_chain(proc_key, plugins)

    def _update_control_buttons(self) -> None:
        """Обновить доступность кнопок управления по текущему выбору."""
        has_process = self._selected_process is not None
        has_selection = self._selected_key is not None
        status = self._selected_status

        # CRUD-кнопки: Remove требует выбранного элемента
        self._toolbar.set_button_enabled(_BTN_REMOVE, has_selection)

        # Start: остановлен, упал или недоступен
        can_start = has_process and status in (
            "created", "stopped", "crashed", "failed", "",
        )
        self._toolbar.set_button_enabled(_BTN_START, can_start)

        # Stop: работает, инициализируется или на паузе
        can_stop = has_process and status in (
            "running", "ready", "initializing", "paused",
        )
        self._toolbar.set_button_enabled(_BTN_STOP, can_stop)

        # Restart: работает
        can_restart = has_process and status in ("running", "ready")
        self._toolbar.set_button_enabled(_BTN_RESTART, can_restart)

        # Pause/Resume
        can_pause = has_process and status == "running"
        can_resume = has_process and status == "paused"
        self._toolbar.set_button_enabled(_BTN_PAUSE, can_pause or can_resume)

        # Обновить текст кнопки Pause
        pause_btn = self._toolbar.get_button(_BTN_PAUSE)
        if pause_btn is not None:
            if status == "paused":
                pause_btn.setText("Возобновить")
            else:
                pause_btn.setText("Пауза")


__all__ = ["ProcessesTabWidget"]
