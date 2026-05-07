"""ImagePanelWidget — мульти-дисплейная панель кадров."""
import logging

from PySide6.QtWidgets import QWidget, QHBoxLayout

from .display_slot import DisplaySlot
from .presenter import ImagePanelPresenter

logger = logging.getLogger(__name__)

# Конфигурация слота по умолчанию
_DEFAULT_SLOTS = [{"id": "main", "label": "Main"}]


class ImagePanelWidget(QWidget):
    """Горизонтальная панель из N слотов отображения кадров.

    Каждый слот — независимый DisplaySlot, идентифицируемый строковым id.
    Presenter маршрутизирует BGR numpy-кадры в нужный слот.

    Пример создания:
        panel = ImagePanelWidget()  # один слот "main"
        panel = ImagePanelWidget(slots=[
            {"id": "original", "label": "Original"},
            {"id": "processed", "label": "Processed"},
        ])
    """

    def __init__(self, slots: list | None = None, parent=None):
        super().__init__(parent)

        self._presenter = ImagePanelPresenter()
        # slot_id → DisplaySlot
        self._slots: dict[str, DisplaySlot] = {}

        # Горизонтальный layout для слотов
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)

        # Создать слоты из конфига (или дефолт)
        config = slots if slots is not None else _DEFAULT_SLOTS
        for slot_cfg in config:
            self.add_slot(
                slot_id=slot_cfg["id"],
                label=slot_cfg.get("label", ""),
            )

    # ------------------------------------------------------------------
    # Управление слотами
    # ------------------------------------------------------------------

    def add_slot(self, slot_id: str, label: str = "") -> DisplaySlot:
        """Добавить новый слот отображения.

        Возвращает созданный DisplaySlot.
        Если слот с таким id уже существует — возвращает существующий.
        """
        if slot_id in self._slots:
            logger.warning("add_slot: слот '%s' уже существует", slot_id)
            return self._slots[slot_id]

        slot = DisplaySlot(slot_id=slot_id, label=label, parent=self)
        self._slots[slot_id] = slot
        self._presenter.register_slot(slot_id, slot)
        self._layout.addWidget(slot)

        logger.debug("Добавлен слот: %s (label=%r)", slot_id, label)
        return slot

    def remove_slot(self, slot_id: str) -> None:
        """Удалить слот из панели. Предупреждение если не найден."""
        if slot_id not in self._slots:
            logger.warning("remove_slot: слот '%s' не найден", slot_id)
            return

        slot = self._slots.pop(slot_id)
        self._presenter.unregister_slot(slot_id)

        # Убрать виджет из layout и удалить
        self._layout.removeWidget(slot)
        slot.setParent(None)
        slot.deleteLater()

        logger.debug("Удалён слот: %s", slot_id)

    # ------------------------------------------------------------------
    # Отображение кадров
    # ------------------------------------------------------------------

    def display_frame(self, slot_id: str, frame) -> None:
        """Отобразить один BGR-кадр в указанном слоте."""
        self._presenter.on_frame(slot_id, frame)

    def display_frames(self, frames: dict) -> None:
        """Отобразить несколько кадров: dict[slot_id, np.ndarray]."""
        self._presenter.on_frames(frames)

    # ------------------------------------------------------------------
    # Свойства
    # ------------------------------------------------------------------

    @property
    def presenter(self) -> ImagePanelPresenter:
        """Доступ к presenter'у (для внешней регистрации/управления)."""
        return self._presenter

    @property
    def slot_ids(self) -> list[str]:
        """Список идентификаторов активных слотов."""
        return list(self._slots.keys())
