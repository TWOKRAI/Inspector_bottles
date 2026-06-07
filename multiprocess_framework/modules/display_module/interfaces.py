"""Публичный контракт display_module — DisplayEntry dataclass + Protocol-интерфейсы.

Определяет типы данных и Protocol'ы для работы с реестром дисплеев
и SHM-каналами отображения кадров.

ADR-решение по семантике полей:
    Поля vision-специфичной семантики — ``element_shape`` и ``dtype`` —
    намеренно вынесены за пределы framework-контракта. Они относятся к
    прикладному слою (prototype-обёртка) и не должны загрязнять
    framework-интерфейс. DisplayEntry остаётся generic-описанием канала
    (размер, формат, fps, SHM-ресурс), а конкретный numpy-shape вычисляется
    prototype-слоем при создании SHM-сегмента.
    Подробнее — ADR-DM-001 в ``display_module/DECISIONS.md`` (Task 4.9).

Правило слоёв:
    НИКАКИХ импортов из Services/, Plugins/, multiprocess_prototype/ —
    только stdlib и __future__.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class DisplayEntry:
    """Конфигурационная запись одного именованного дисплея.

    Описывает SHM-канал отображения кадров: ключ маршрута, параметры
    изображения и ring-buffer. Используется как единица хранения в
    ``DisplayRegistry`` и ключ конфигурации в ``displays.yaml``.

    Примечание:
        Поля ``element_shape`` и ``dtype`` (numpy-специфика) в этот dataclass
        **не включены** — они вычисляются prototype-слоем из ``width``,
        ``height``, ``format`` при создании SHM-сегмента (ADR-DM-001).

    Attributes:
        id: Уникальный идентификатор дисплея — ключ в реестре и в YAML.
        name: Человекочитаемое имя дисплея (отображается в GUI).
        width: Ширина кадра в пикселях.
        height: Высота кадра в пикселях.
        format: Формат пикселей кадра. Допустимые значения: ``"BGR"``,
            ``"RGB"``, ``"GRAY"``, ``"RGBA"``.
        fps_limit: Ограничение частоты кадров (0.0 — без ограничения).
        ring_buffer_blocks: Количество SHM-блоков в ring-buffer канала.

    Example::

        entry = DisplayEntry(
            id="main",
            name="Основной дисплей",
            width=1280,
            height=720,
            format="BGR",
            fps_limit=30.0,
            ring_buffer_blocks=3,
        )
    """

    id: str
    name: str
    width: int
    height: int
    format: str
    fps_limit: float
    ring_buffer_blocks: int


@runtime_checkable
class IDisplayChannel(Protocol):
    """Protocol для SHM-канала отображения кадров.

    Любой класс, реализующий свойство ``channel_key`` и методы
    ``subscribe``, ``unsubscribe``, ``is_active``, автоматически проходит
    ``isinstance(obj, IDisplayChannel)`` без явного наследования
    (structural subtyping).

    Пример::

        class MyChannel:
            @property
            def channel_key(self) -> str:
                return "display.main"

            def subscribe(self, consumer_id: str) -> bool:
                ...

            def unsubscribe(self, consumer_id: str) -> bool:
                ...

            def is_active(self) -> bool:
                return True

        assert isinstance(MyChannel(), IDisplayChannel)  # True
    """

    @property
    def channel_key(self) -> str:
        """Ключ маршрута в RouterManager.

        Например: ``"display.main"``, ``"display.debug"``.
        Формат: ``"display.<display_id>"``.
        """
        ...

    def subscribe(self, consumer_id: str) -> bool:
        """Подписать потребителя на канал.

        Args:
            consumer_id: Идентификатор потребителя (например, id окна превью).

        Returns:
            True при успешной подписке, False если уже подписан или ошибка.
        """
        ...

    def unsubscribe(self, consumer_id: str) -> bool:
        """Отписать потребителя от канала.

        Args:
            consumer_id: Идентификатор потребителя.

        Returns:
            True если подписка была и удалена, False если не найдена.
        """
        ...

    def is_active(self) -> bool:
        """Проверить, активен ли канал (SHM-сегмент открыт, поставщик пишет).

        Returns:
            True если канал активен и готов к чтению кадров.
        """
        ...


@runtime_checkable
class IDisplayRegistry(Protocol):
    """Protocol для реестра именованных дисплеев.

    Любой класс, реализующий методы ``register``, ``unregister``, ``get``,
    ``list``, ``persist``, автоматически проходит
    ``isinstance(obj, IDisplayRegistry)`` без явного наследования
    (structural subtyping).

    Пример::

        class MyRegistry:
            def register(self, entry: DisplayEntry) -> None: ...
            def unregister(self, display_id: str) -> bool: ...
            def get(self, display_id: str) -> DisplayEntry | None: ...
            def list(self) -> list[DisplayEntry]: ...
            def persist(self, path: Path) -> None: ...

        assert isinstance(MyRegistry(), IDisplayRegistry)  # True
    """

    def register(self, entry: DisplayEntry) -> None:
        """Зарегистрировать дисплей в реестре.

        Args:
            entry: Конфигурационная запись дисплея.

        Raises:
            ValueError: Если дисплей с таким ``entry.id`` уже зарегистрирован.
        """
        ...

    def unregister(self, display_id: str) -> bool:
        """Удалить дисплей из реестра.

        Args:
            display_id: Идентификатор дисплея для удаления.

        Returns:
            True если дисплей был найден и удалён, False если не существовал.
        """
        ...

    def get(self, display_id: str) -> DisplayEntry | None:
        """Получить запись дисплея по идентификатору.

        Args:
            display_id: Идентификатор дисплея.

        Returns:
            ``DisplayEntry`` если найден, иначе ``None``.
        """
        ...

    def list(self) -> list[DisplayEntry]:
        """Вернуть список всех зарегистрированных дисплеев.

        Returns:
            Копия списка ``DisplayEntry`` — безопасно итерировать
            параллельно с изменениями реестра.
        """
        ...

    def persist(self, path: Path) -> None:
        """Сохранить текущее состояние реестра в файл.

        Путь передаётся вызывающим кодом — prototype-слой решает,
        где хранить конфиг (ADR-DM-002). Framework-реестр сам путь
        не запоминает: это разделение ответственности позволяет
        реестру оставаться чистым singleton-ом без application-state.

        Args:
            path: Абсолютный или относительный путь к файлу для записи.
        """
        ...

    def reload(
        self,
        entries: list[dict],
        *,
        on_orphan: Callable[[str], None] | None = None,
    ) -> None:
        """Атомарно заменить содержимое реестра новыми определениями.

        Из каждого dict извлекаются ТОЛЬКО 7 SHM-полей ``DisplayEntry``
        (id, name, width, height, format, fps_limit, ring_buffer_blocks).
        Render-параметры (fit, scale, rotate, flip, crop, position и др.)
        **игнорируются** — реестр остаётся generic (ADR-DM-001).
        SHM реестром НЕ выделяется и НЕ освобождается (ADR-DM-003).

        Порядок: orphan-detection → on_orphan callback → _cleanup_shm_channel
        → clear → register новых. Дубль id → warning + пропуск.

        Args:
            entries: Список dict-определений дисплеев с границы процесса.
            on_orphan: Колбэк для каждого orphan-id (prototype подставит
                       закрытие окон). Если None — уведомление пропускается.
        """
        ...
