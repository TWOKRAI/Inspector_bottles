# -*- coding: utf-8 -*-
"""DisplaysPresenter — бизнес-логика таба дисплеев (MVP).

Pure Python, без Qt-импортов. Управляет CRUD над DisplayCatalog (domain Protocol):
- load() / on_select() / on_create() / on_delete() / on_duplicate() / on_open_preview()

Персистентность — YAML через store.persist() (путь знает adapter).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from multiprocess_prototype.domain.protocols.display_catalog import (
    DisplayCatalog,
    DisplaySpec,
)

if TYPE_CHECKING:
    from .view import IDisplaysView

logger = logging.getLogger(__name__)


class DisplaysPresenter:
    """Presenter для DisplaysTab.

    Содержит всю бизнес-логику работы с реестром дисплеев.
    View получает обновления только через методы IDisplaysView.

    Attributes:
        _store: DisplayCatalog Protocol (read+write store).
        _view: ссылка на view (IDisplaysView protocol).
        _preview_callback: вызывается при on_open_preview (Task 4.7).
        _selected_id: текущий выбранный id дисплея.
    """

    def __init__(
        self,
        store: DisplayCatalog,
        view: "IDisplaysView",
        preview_callback: Callable[[DisplaySpec], None] | None = None,
    ) -> None:
        """Инициализировать presenter.

        Args:
            store: DisplayCatalog Protocol (read+write).
            view: реализация IDisplaysView.
            preview_callback: опциональный callback для открытия превью (Task 4.7).
        """
        self._store = store
        self._view = view
        self._preview_callback = preview_callback
        self._selected_id: str | None = None

    # ------------------------------------------------------------------ #
    #  Загрузка                                                            #
    # ------------------------------------------------------------------ #

    def load(self) -> None:
        """Загрузить дисплеи из store и обновить список в view.

        Сбрасывает выбор (set_buttons_state -> False).
        """
        specs = list(self._store.list_displays())
        self._view.refresh_list(specs)
        self._view.set_buttons_state(False)
        self._selected_id = None

    # ------------------------------------------------------------------ #
    #  Selection                                                           #
    # ------------------------------------------------------------------ #

    def on_select(self, display_id: str | None) -> None:
        """Обработать выбор записи в nav-списке.

        Args:
            display_id: id выбранного дисплея или None при снятии выбора.
        """
        self._selected_id = display_id
        if display_id is None:
            self._view.show_entry(None)
            self._view.set_buttons_state(False)
            return
        spec = self._store.resolve(display_id)
        self._view.show_entry(spec)
        self._view.set_buttons_state(True)

    # ------------------------------------------------------------------ #
    #  CRUD                                                                #
    # ------------------------------------------------------------------ #

    def on_create(self) -> None:
        """Создать новый дисплей из данных формы.

        Читает view.get_form_data(), строит DisplaySpec, регистрирует через store,
        сохраняет в YAML, обновляет список.
        При ValueError — показывает ошибку через view.show_error().
        """
        data = self._view.get_form_data()

        display_id = data.get("id", "").strip()
        if not display_id:
            self._view.show_error("Поле 'ID' не может быть пустым.")
            return

        try:
            spec = DisplaySpec(
                display_id=display_id,
                display_name=data.get("name", display_id),
                width=int(data.get("width", 1280)),
                height=int(data.get("height", 720)),
                format=str(data.get("format", "BGR")),
                fps_limit=float(data.get("fps_limit", 30.0)),
                ring_buffer_blocks=int(data.get("ring_buffer_blocks", 3)),
            )
        except (TypeError, ValueError) as exc:
            self._view.show_error(f"Некорректные данные формы: {exc}")
            return

        try:
            self._store.register(spec)
        except ValueError as exc:
            self._view.show_error(str(exc))
            return

        self._persist()
        self._view.refresh_list(list(self._store.list_displays()))
        logger.info("DisplaysPresenter: создан дисплей '%s'", display_id)

    def on_delete(self, display_id: str) -> None:
        """Удалить дисплей из store.

        Args:
            display_id: id дисплея для удаления.
        """
        removed = self._store.unregister(display_id)
        if not removed:
            logger.warning("DisplaysPresenter: дисплей '%s' не найден для удаления", display_id)
            return

        self._persist()
        self._selected_id = None
        self._view.refresh_list(list(self._store.list_displays()))
        self._view.show_entry(None)
        self._view.set_buttons_state(False)
        logger.info("DisplaysPresenter: удалён дисплей '%s'", display_id)

    def on_duplicate(self, display_id: str) -> None:
        """Дублировать дисплей с суффиксом _copy (или _copy2, _copy3 ...).

        Если id уже занят — перебирает _copy2, _copy3 и т.д.

        Args:
            display_id: id исходного дисплея.
        """
        source = self._store.resolve(display_id)
        if source is None:
            logger.warning("DisplaysPresenter: дисплей '%s' не найден для дублирования", display_id)
            return

        # Генерируем уникальный id с суффиксом _copy / _copy2 / ...
        new_id = self._generate_copy_id(display_id)

        new_spec = DisplaySpec(
            display_id=new_id,
            display_name=f"{source.display_name} (копия)",
            width=source.width,
            height=source.height,
            format=source.format,
            fps_limit=source.fps_limit,
            ring_buffer_blocks=source.ring_buffer_blocks,
        )

        try:
            self._store.register(new_spec)
        except ValueError as exc:
            # Теоретически невозможно — id уже проверен, но на всякий случай
            self._view.show_error(str(exc))
            return

        self._persist()
        self._view.refresh_list(list(self._store.list_displays()))
        logger.info("DisplaysPresenter: дублирован '%s' -> '%s'", display_id, new_id)

    def on_open_preview(self, display_id: str) -> None:
        """Открыть превью канала дисплея.

        Args:
            display_id: id дисплея для превью.
        """
        spec = self._store.resolve(display_id)
        if spec is None:
            logger.warning("DisplaysPresenter: дисплей '%s' не найден для превью", display_id)
            return

        if self._preview_callback is not None:
            self._preview_callback(spec)
        else:
            logger.info("DisplaysPresenter: открыть превью '%s' (заглушка Phase 4)", display_id)

    # ------------------------------------------------------------------ #
    #  Вспомогательные методы                                              #
    # ------------------------------------------------------------------ #

    def _generate_copy_id(self, source_id: str) -> str:
        """Сгенерировать уникальный id-копии для дублирования.

        Перебирает _copy, _copy2, _copy3 ... до нахождения незанятого id.

        Args:
            source_id: id оригинального дисплея.

        Returns:
            Первый свободный id с суффиксом _copy / _copy2 / ...
        """
        candidate = f"{source_id}_copy"
        if not self._store.has(candidate):
            return candidate

        counter = 2
        while True:
            candidate = f"{source_id}_copy{counter}"
            if not self._store.has(candidate):
                return candidate
            counter += 1

    def _persist(self) -> None:
        """Сохранить store в YAML. Логирует ошибку при исключении."""
        try:
            self._store.persist()
        except Exception as exc:
            logger.error("DisplaysPresenter: ошибка сохранения YAML: %s", exc)
