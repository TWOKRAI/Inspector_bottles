"""PluginSandboxWidget -- GUI-виджет для тестирования плагина на одном кадре.

Vertical slice (Task 6.2 + Task 6.3):
  - ISandboxView Protocol
  - PluginSandboxWidget: выбор файла / webcam snapshot -> before-preview -> «Применить» -> after-preview
  - Зона параметров: динамические QSpinBox/QDoubleSpinBox по register_class.model_fields
  - run_once выполняется в QThreadPool (_SandboxWorker) -- UI не замораживается
  - Конвертация BGR numpy -> QPixmap через cv2.cvtColor + QImage
  - show_error (красный QLabel), set_running (disable + текст)

MVP-паттерн: ISandboxView (Protocol) + PluginSandboxWidget (реализует Protocol).
SandboxPresenter инжектируется снаружи.

By design: sandbox требует живой Python plugin_class (entry.register_classes[0]),
а webcam требует живой service entry (svc_registry.get("webcam_camera")) --
не покрывается PluginCatalog/ServiceManager Protocol (метаданные).
Bridge _registry остаётся навсегда. Q-F2=C (owner-decision 2026-05-28).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Protocol

import cv2
import numpy as np
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from multiprocess_prototype.domain.app_services import AppServices
    from multiprocess_prototype.frontend.widgets.tabs.plugins.sandbox_presenter import (
        SandboxPresenter,
    )


# ---------------------------------------------------------------------------
# Protocol (ISandboxView)
# ---------------------------------------------------------------------------


class ISandboxView(Protocol):
    """Интерфейс View для sandbox-виджета.

    Определяет контракт между PluginSandboxWidget и SandboxPresenter.
    Позволяет тестировать presenter с mock-view.
    """

    def show_result(self, before: np.ndarray, after: np.ndarray | None) -> None:
        """Показать результат применения плагина (before и after кадры).

        Args:
            before: исходный BGR кадр.
            after: результирующий BGR кадр или None (плагин не вернул данные).
        """
        ...

    def show_error(self, msg: str) -> None:
        """Показать сообщение об ошибке (красным цветом).

        Args:
            msg: текст ошибки для пользователя.
        """
        ...

    def set_running(self, is_running: bool) -> None:
        """Переключить состояние «выполняется».

        Args:
            is_running: True — disable кнопку + текст «Применяется…».
                        False — enable кнопку + текст «Применить».
        """
        ...


# ---------------------------------------------------------------------------
# Вспомогательная функция конвертации
# ---------------------------------------------------------------------------


def _numpy_bgr_to_pixmap(frame: np.ndarray) -> QPixmap | None:
    """Конвертировать BGR numpy array в QPixmap.

    cv2.imread возвращает BGR, QImage.Format_RGB888 ожидает RGB.
    Шаги: BGR → RGB через cvtColor → QImage (contiguous buffer) → QPixmap.

    Args:
        frame: numpy array формата BGR, dtype=uint8.

    Returns:
        QPixmap или None при ошибке конвертации.
    """
    if frame is None or frame.size == 0:
        return None

    try:
        # Обеспечиваем contiguous layout для QImage
        if not frame.flags["C_CONTIGUOUS"]:
            frame = np.ascontiguousarray(frame)

        if frame.ndim == 3 and frame.shape[2] == 3:
            # BGR → RGB
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            bytes_per_line = ch * w
            qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        elif frame.ndim == 2:
            # Grayscale (2D)
            h, w = frame.shape
            qimg = QImage(frame.data, w, h, w, QImage.Format.Format_Grayscale8)
        else:
            return None

        return QPixmap.fromImage(qimg)

    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# QRunnable worker для run_once (Thread-safety: frame копируется)
# ---------------------------------------------------------------------------


class _WorkerSignals(QObject):
    """Сигналы для _SandboxWorker.

    QRunnable не является QObject — сигналы вынесены в отдельный объект.
    """

    # Результат: (исходный кадр, результирующий кадр или None)
    finished = Signal(object, object)  # (np.ndarray, np.ndarray | None)
    # Ошибка: строка с сообщением
    error = Signal(str)


class _SandboxWorker(QRunnable):
    """QRunnable для запуска run_once в пуле потоков.

    Копирует frame перед запуском — thread-safe относительно GUI.
    По завершении эмитирует signals.finished или signals.error.

    Args:
        presenter: SandboxPresenter с методом run_once().
        plugin_name: имя плагина.
        frame: исходный BGR кадр (будет скопирован).
        config_overrides: параметры конфига из спинбоксов.
    """

    def __init__(
        self,
        presenter: "SandboxPresenter",
        plugin_name: str,
        frame: np.ndarray,
        config_overrides: dict[str, Any],
    ) -> None:
        super().__init__()
        self._presenter = presenter
        self._plugin_name = plugin_name
        # Копируем кадр — thread-safe
        self._frame = frame.copy()
        self._config_overrides = dict(config_overrides)
        self.signals = _WorkerSignals()

    def run(self) -> None:
        """Выполнить run_once в worker-потоке и эмитировать сигнал."""
        try:
            result = self._presenter.run_once(
                self._plugin_name,
                self._frame,
                self._config_overrides,
            )
            # result может быть None — это валидный исход (плагин не вернул кадр)
            self.signals.finished.emit(self._frame, result)
        except Exception as exc:  # noqa: BLE001
            self.signals.error.emit(f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# PluginSandboxWidget
# ---------------------------------------------------------------------------


class PluginSandboxWidget(QWidget):
    """Виджет для sandbox-тестирования плагина на одном кадре.

    Четыре зоны:
      1. Источник — QPushButton «Выбрать файл…» + «Снимок с камеры» + QLabel.
      2. Параметры — динамическая форма QSpinBox/QDoubleSpinBox по register_class.
      3. Действие — QPushButton «Применить» (disabled до загрузки кадра).
      4. Preview — два QLabel (before / after) в QHBoxLayout, высота 200px.

    Реализует ISandboxView Protocol.
    run_once выполняется в QThreadPool — UI не замораживается.

    Args:
        presenter: SandboxPresenter — бизнес-логика sandbox.
        plugin_name: имя плагина для передачи в presenter.run_once().
        services: AppServices для доступа к registry/service_registry (опционально).
        parent: родительский виджет (опционально).
    """

    def __init__(
        self,
        presenter: "SandboxPresenter",
        plugin_name: str,
        services: "AppServices | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._presenter = presenter
        self._plugin_name = plugin_name
        # By design: sandbox требует живой Python register_classes[0] (Pydantic model)
        # и живой service entry (status, get_current_frame) -- не покрывается
        # PluginCatalog/ServiceManager Protocol (метаданные). Q-F2=C (owner-decision 2026-05-28).
        self._registry = getattr(services.plugins, "_registry", None) if services is not None else None
        self._svc_registry = getattr(services.services, "_registry", None) if services is not None else None
        self._current_frame: np.ndarray | None = None  # текущий загруженный кадр

        # Словарь QSpinBox/QDoubleSpinBox: field_name → widget
        self._param_widgets: dict[str, QSpinBox | QDoubleSpinBox] = {}

        self._build_ui()
        self._build_params_zone()
        self._refresh_webcam_button_state()

    # ------------------------------------------------------------------ #
    #  Построение UI                                                       #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        """Собрать компоновку виджета."""
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        # Заголовок
        title = QLabel(f"Sandbox: {self._plugin_name}")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        root_layout.addWidget(title)

        # -- Зона источника (input_zone) --
        input_zone = QWidget()
        input_layout = QHBoxLayout(input_zone)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(6)

        self._btn_file = QPushButton("Выбрать файл…")
        self._btn_file.clicked.connect(self._on_file_selected)
        input_layout.addWidget(self._btn_file)

        self._btn_webcam = QPushButton("Снимок с камеры")
        self._btn_webcam.clicked.connect(self._on_webcam_snapshot)
        self._btn_webcam.setEnabled(False)  # включится когда сервис running
        input_layout.addWidget(self._btn_webcam)

        self._lbl_filename = QLabel("файл не выбран")
        self._lbl_filename.setStyleSheet("color: gray;")
        input_layout.addWidget(self._lbl_filename, stretch=1)

        root_layout.addWidget(input_zone)

        # -- Зона ошибок (скрыта по умолчанию) --
        self._lbl_error = QLabel("")
        self._lbl_error.setStyleSheet("color: red;")
        self._lbl_error.setWordWrap(True)
        self._lbl_error.hide()
        root_layout.addWidget(self._lbl_error)

        # -- Зона параметров (заполняется в _build_params_zone) --
        self._params_group = QGroupBox("Параметры плагина")
        self._params_form_layout = QFormLayout()
        self._params_form_layout.setContentsMargins(6, 6, 6, 6)
        self._params_form_layout.setSpacing(4)
        self._params_group.setLayout(self._params_form_layout)
        # По умолчанию скрыта — покажется если у плагина есть register_class
        self._params_group.hide()
        root_layout.addWidget(self._params_group)

        # Сохраняем root_layout чтобы добавить кнопку после _build_params_zone
        self._root_layout = root_layout

        # -- Зона действия --
        self._btn_apply = QPushButton("Применить")
        self._btn_apply.setEnabled(False)  # disabled пока нет кадра
        self._btn_apply.clicked.connect(self._on_apply_clicked)
        root_layout.addWidget(self._btn_apply)

        # -- Зона preview (before / after) --
        preview_zone = QWidget()
        preview_layout = QHBoxLayout(preview_zone)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(4)

        # Before-панель
        before_col = QVBoxLayout()
        before_col.setSpacing(2)
        lbl_before_title = QLabel("До:")
        lbl_before_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        before_col.addWidget(lbl_before_title)
        self.before_label = QLabel()
        self.before_label.setFixedHeight(200)
        self.before_label.setMinimumWidth(150)
        self.before_label.setScaledContents(True)
        self.before_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.before_label.setStyleSheet("background: #1a1a1a; border: 1px solid #444;")
        before_col.addWidget(self.before_label)
        preview_layout.addLayout(before_col)

        # After-панель
        after_col = QVBoxLayout()
        after_col.setSpacing(2)
        lbl_after_title = QLabel("После:")
        lbl_after_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        after_col.addWidget(lbl_after_title)
        self.after_label = QLabel()
        self.after_label.setFixedHeight(200)
        self.after_label.setMinimumWidth(150)
        self.after_label.setScaledContents(True)
        self.after_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.after_label.setStyleSheet("background: #1a1a1a; border: 1px solid #444;")
        after_col.addWidget(self.after_label)
        preview_layout.addLayout(after_col)

        root_layout.addWidget(preview_zone, stretch=1)

    def _build_params_zone(self) -> None:
        """Построить зону параметров по register_class плагина.

        Ищет register_class через PluginRegistry → entry.register_classes[0].
        Если register_class отсутствует — params_group скрыт, _param_widgets пуст.

        Для каждого поля register_class создаёт:
          - QSpinBox (int) или QDoubleSpinBox (float)
          - Label из FieldMeta.description (иначе — имя поля)
          - Min/max из FieldMeta.min/max (иначе: int→0..255, float→0.0..1.0)
          - Значение по умолчанию из экземпляра register_class()
        """
        self._param_widgets.clear()

        # Очищаем форму (на случай повторного вызова)
        while self._params_form_layout.rowCount() > 0:
            self._params_form_layout.removeRow(0)

        register_class = self._resolve_register_class()
        if register_class is None:
            self._params_group.hide()
            return

        # Создаём экземпляр с дефолтными значениями
        try:
            defaults_instance = register_class()
        except Exception:  # noqa: BLE001
            self._params_group.hide()
            return

        # Итерируем поля Pydantic модели
        for field_name, field_info in register_class.model_fields.items():
            field_meta = self._extract_field_meta(field_info)
            label_text = field_meta.description if field_meta is not None and field_meta.description else field_name

            # Определяем тип поля (int или float)
            python_type = self._resolve_field_python_type(field_info)

            # Получаем дефолтное значение
            default_value = getattr(defaults_instance, field_name, 0)

            if python_type is float:
                spinbox: QSpinBox | QDoubleSpinBox = QDoubleSpinBox()
                f_min = float(field_meta.min) if field_meta is not None and field_meta.min is not None else 0.0
                f_max = float(field_meta.max) if field_meta is not None and field_meta.max is not None else 1.0
                spinbox.setMinimum(f_min)
                spinbox.setMaximum(f_max)
                spinbox.setDecimals(4)
                spinbox.setSingleStep(0.01)
                spinbox.setValue(float(default_value))
            else:
                # По умолчанию — int
                spinbox = QSpinBox()
                i_min = int(field_meta.min) if field_meta is not None and field_meta.min is not None else 0
                i_max = int(field_meta.max) if field_meta is not None and field_meta.max is not None else 255
                spinbox.setMinimum(i_min)
                spinbox.setMaximum(i_max)
                spinbox.setValue(int(default_value))

            self._params_form_layout.addRow(label_text + ":", spinbox)
            self._param_widgets[field_name] = spinbox

        # Показываем группу только если есть параметры
        if self._param_widgets:
            self._params_group.show()
        else:
            self._params_group.hide()

    # ------------------------------------------------------------------ #
    #  Вспомогательные методы построения UI                               #
    # ------------------------------------------------------------------ #

    def _resolve_register_class(self):
        """Найти register_class плагина через PluginRegistry.

        Returns:
            Класс register_class (Pydantic model) или None.
        """
        if self._registry is None:
            return None

        try:
            registry = self._registry
            entry = registry.get(self._plugin_name)
            if entry is None:
                return None
            # entry.register_classes — список; берём первый если есть
            register_classes = getattr(entry, "register_classes", [])
            if register_classes:
                return register_classes[0]
            return None
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _extract_field_meta(field_info: Any):
        """Извлечь FieldMeta из pydantic FieldInfo.metadata.

        Args:
            field_info: pydantic FieldInfo объект.

        Returns:
            FieldMeta или None если не найдено.
        """
        metadata = getattr(field_info, "metadata", [])
        for item in metadata:
            # FieldMeta идентифицируется по наличию атрибутов description и min/max
            if hasattr(item, "description") and hasattr(item, "min") and hasattr(item, "max"):
                return item
        return None

    @staticmethod
    def _resolve_field_python_type(field_info: Any) -> type:
        """Определить Python-тип поля из Pydantic FieldInfo.

        Args:
            field_info: pydantic FieldInfo объект.

        Returns:
            float если тип float, иначе int (дефолт для числовых полей).
        """
        annotation = getattr(field_info, "annotation", None)
        if annotation is float:
            return float
        # Проверяем через __args__ для Annotated-типов
        origin_args = getattr(annotation, "__args__", None)
        if origin_args and float in origin_args:
            return float
        return int

    def _refresh_webcam_button_state(self) -> None:
        """Обновить состояние кнопки «Снимок с камеры».

        Кнопка enabled только если webcam_camera service в состоянии "running".
        Вызывается при создании виджета.
        """
        enabled = self._is_webcam_running()
        self._btn_webcam.setEnabled(enabled)

    def _is_webcam_running(self) -> bool:
        """Проверить что webcam_camera service в состоянии running.

        Returns:
            True если сервис доступен и статус "running".
        """
        if self._svc_registry is None:
            return False
        try:
            svc = self._svc_registry.get("webcam_camera")
            if svc is None:
                return False
            status = getattr(svc, "status", "stopped")
            return status == "running"
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------ #
    #  Слоты                                                               #
    # ------------------------------------------------------------------ #

    def _on_file_selected(self) -> None:
        """Открыть диалог выбора файла и загрузить изображение."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выбрать изображение",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp)",
        )
        if not path:
            # Пользователь отменил диалог
            return

        frame = cv2.imread(path)
        if frame is None:
            # Файл повреждён или формат не поддерживается
            self.show_error("Не удалось прочитать изображение")
            return

        # Скрыть предыдущую ошибку
        self._lbl_error.hide()

        # Сохранить кадр и показать before-preview
        self._current_frame = frame

        basename = os.path.basename(path)
        self._lbl_filename.setText(basename)
        self._lbl_filename.setStyleSheet("color: white;")

        # Показать before-preview
        pixmap = _numpy_bgr_to_pixmap(frame)
        if pixmap is not None:
            self.before_label.setPixmap(pixmap)

        # Активировать кнопку «Применить»
        self._btn_apply.setEnabled(True)

    def _on_webcam_snapshot(self) -> None:
        """Захватить кадр с веб-камеры через WebcamCameraService."""
        if self._svc_registry is None:
            self.show_error("Сервисы недоступны")
            return

        frame = None
        try:
            svc = self._svc_registry.get("webcam_camera")
            if svc is not None and hasattr(svc, "get_current_frame"):
                frame = svc.get_current_frame()
        except Exception:  # noqa: BLE001  # nosec B110 — frame=None уже обработан ниже
            pass

        if frame is None:
            self.show_error("Камера недоступна")
            return

        # Скрыть предыдущую ошибку
        self._lbl_error.hide()

        # Сохранить кадр и показать before-preview
        self._current_frame = frame
        self._lbl_filename.setText("webcam snapshot")
        self._lbl_filename.setStyleSheet("color: white;")

        pixmap = _numpy_bgr_to_pixmap(frame)
        if pixmap is not None:
            self.before_label.setPixmap(pixmap)

        # Активировать кнопку «Применить»
        self._btn_apply.setEnabled(True)

    def _on_apply_clicked(self) -> None:
        """Применить плагин к текущему кадру в QThreadPool (non-blocking)."""
        if self._current_frame is None:
            return

        config_overrides = self._collect_config_overrides()

        # Создаём worker — он скопирует frame внутри
        worker = _SandboxWorker(
            presenter=self._presenter,
            plugin_name=self._plugin_name,
            frame=self._current_frame,
            config_overrides=config_overrides,
        )
        worker.signals.finished.connect(self._on_worker_finished)
        worker.signals.error.connect(self._on_worker_error)

        self.set_running(True)
        QThreadPool.globalInstance().start(worker)

    def _on_worker_finished(self, original_frame: np.ndarray, result: np.ndarray | None) -> None:
        """Обработать завершение worker (вызывается в main thread через signal).

        Args:
            original_frame: исходный кадр (уже скопированный worker'ом).
            result: результирующий кадр или None.
        """
        self.set_running(False)

        if result is None:
            # Плагин не вернул результат — сообщение без ошибки
            self._lbl_error.setText("нет результата")
            self._lbl_error.setStyleSheet("color: orange;")
            self._lbl_error.show()
        else:
            # Успех — показать результат
            self._lbl_error.hide()
            self.show_result(original_frame, result)

    def _on_worker_error(self, error_msg: str) -> None:
        """Обработать ошибку worker (вызывается в main thread через signal).

        Args:
            error_msg: строка с описанием ошибки.
        """
        self.set_running(False)
        self.show_error(f"Ошибка выполнения: {error_msg}")

    def _collect_config_overrides(self) -> dict[str, Any]:
        """Собрать значения параметров из спинбоксов.

        Returns:
            Словарь field_name → value. Пустой если параметров нет.
        """
        overrides: dict[str, Any] = {}
        for field_name, spinbox in self._param_widgets.items():
            overrides[field_name] = spinbox.value()
        return overrides

    # ------------------------------------------------------------------ #
    #  ISandboxView — публичный API (Protocol)                             #
    # ------------------------------------------------------------------ #

    def show_result(self, before: np.ndarray, after: np.ndarray | None) -> None:
        """Показать before и after кадры в preview-зонах.

        Args:
            before: исходный BGR кадр.
            after: результирующий BGR кадр или None.
        """
        # Before всегда показываем
        pixmap_before = _numpy_bgr_to_pixmap(before)
        if pixmap_before is not None:
            self.before_label.setPixmap(pixmap_before)

        # After — только если есть результат
        if after is not None:
            pixmap_after = _numpy_bgr_to_pixmap(after)
            if pixmap_after is not None:
                self.after_label.setPixmap(pixmap_after)
        # after=None — after_label остаётся как есть (пустым или со старым кадром)

    def show_error(self, msg: str) -> None:
        """Показать сообщение об ошибке красным цветом.

        Args:
            msg: текст ошибки (может быть пустым — label просто скроется).
        """
        if msg:
            self._lbl_error.setText(msg)
            self._lbl_error.setStyleSheet("color: red;")
            self._lbl_error.show()
        else:
            self._lbl_error.hide()

    def set_running(self, is_running: bool) -> None:
        """Переключить состояние «выполняется» на кнопке «Применить».

        Args:
            is_running: True — disable + «Применяется…»; False — enable + «Применить».
        """
        if is_running:
            self._btn_apply.setEnabled(False)
            self._btn_apply.setText("Применяется…")
        else:
            self._btn_apply.setEnabled(self._current_frame is not None)
            self._btn_apply.setText("Применить")
