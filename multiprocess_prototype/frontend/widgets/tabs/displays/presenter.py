# -*- coding: utf-8 -*-
"""DisplaysPresenter — бизнес-логика таба дисплеев (MVP).

Pure Python, без Qt-импортов. Управляет CRUD над DisplayRegistry:
- load() / on_select() / on_create() / on_delete() / on_duplicate() / on_open_preview()

Персистентность — YAML через DisplayRegistry.persist(yaml_path).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from multiprocess_framework.modules.display_module import DisplayEntry, DisplayRegistry

if TYPE_CHECKING:
    from .view import IDisplaysView

logger = logging.getLogger(__name__)


class DisplaysPresenter:
    """Presenter для DisplaysTab.

    Содержит всю бизнес-логику работы с реестром дисплеев.
    View получает обновления только через методы IDisplaysView.

    Attributes:
        _registry: реестр дисплеев (singleton DisplayRegistry).
        _view: ссылка на view (IDisplaysView protocol).
        _yaml_path: путь к YAML для персистентности.
        _preview_callback: вызывается при on_open_preview (Task 4.7).
        _selected_id: текущий выбранный id дисплея.
    """

    def __init__(
        self,
        registry: DisplayRegistry,
        view: "IDisplaysView",
        yaml_path: Path,
        preview_callback: Callable[[DisplayEntry], None] | None = None,
    ) -> None:
        """Инициализировать presenter.

        Args:
            registry: реестр дисплеев.
            view: реализация IDisplaysView.
            yaml_path: путь к YAML-файлу для сохранения.
            preview_callback: опциональный callback для открытия превью (Task 4.7).
        """
        self._registry = registry
        self._view = view
        self._yaml_path = yaml_path
        self._preview_callback = preview_callback
        self._selected_id: str | None = None

    # ------------------------------------------------------------------ #
    #  Загрузка                                                            #
    # ------------------------------------------------------------------ #

    def load(self) -> None:
        """Загрузить дисплеи из реестра и обновить список в view.

        Сбрасывает выбор (set_buttons_state → False).
        """
        entries = self._registry.list()
        self._view.refresh_list(entries)
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
        entry = self._registry.get(display_id)
        self._view.show_entry(entry)
        self._view.set_buttons_state(True)

    # ------------------------------------------------------------------ #
    #  CRUD                                                                #
    # ------------------------------------------------------------------ #

    def on_create(self) -> None:
        """Создать новый дисплей из данных формы.

        Читает view.get_form_data(), строит DisplayEntry, регистрирует,
        сохраняет в YAML, обновляет список.
        При ValueError — показывает ошибку через view.show_error().
        """
        data = self._view.get_form_data()

        display_id = data.get("id", "").strip()
        if not display_id:
            self._view.show_error("Поле 'ID' не может быть пустым.")
            return

        try:
            entry = DisplayEntry(
                id=display_id,
                name=data.get("name", display_id),
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
            self._registry.register(entry)
        except ValueError as exc:
            self._view.show_error(str(exc))
            return

        self._persist()
        self._view.refresh_list(self._registry.list())
        logger.info("DisplaysPresenter: создан дисплей '%s'", display_id)

    def on_delete(self, display_id: str) -> None:
        """Удалить дисплей из реестра.

        Args:
            display_id: id дисплея для удаления.
        """
        removed = self._registry.unregister(display_id)
        if not removed:
            logger.warning("DisplaysPresenter: дисплей '%s' не найден для удаления", display_id)
            return

        self._persist()
        self._selected_id = None
        self._view.refresh_list(self._registry.list())
        self._view.show_entry(None)
        self._view.set_buttons_state(False)
        logger.info("DisplaysPresenter: удалён дисплей '%s'", display_id)

    def on_duplicate(self, display_id: str) -> None:
        """Дублировать дисплей с суффиксом _copy (или _copy2, _copy3 ...).

        Если id уже занят — перебирает _copy2, _copy3 и т.д.

        Args:
            display_id: id исходного дисплея.
        """
        source = self._registry.get(display_id)
        if source is None:
            logger.warning("DisplaysPresenter: дисплей '%s' не найден для дублирования", display_id)
            return

        # Генерируем уникальный id с суффиксом _copy / _copy2 / ...
        new_id = self._generate_copy_id(display_id)

        new_entry = DisplayEntry(
            id=new_id,
            name=f"{source.name} (копия)",
            width=source.width,
            height=source.height,
            format=source.format,
            fps_limit=source.fps_limit,
            ring_buffer_blocks=source.ring_buffer_blocks,
        )

        try:
            self._registry.register(new_entry)
        except ValueError as exc:
            # Теоретически невозможно — id уже проверен, но на всякий случай
            self._view.show_error(str(exc))
            return

        self._persist()
        self._view.refresh_list(self._registry.list())
        logger.info("DisplaysPresenter: дублирован '%s' → '%s'", display_id, new_id)

    def on_open_preview(self, display_id: str) -> None:
        """Открыть превью канала дисплея.

        В Phase 4 — заглушка: вызывает preview_callback если установлен,
        иначе логирует. Реальное окно будет в Task 4.7.

        Args:
            display_id: id дисплея для превью.
        """
        entry = self._registry.get(display_id)
        if entry is None:
            logger.warning("DisplaysPresenter: дисплей '%s' не найден для превью", display_id)
            return

        if self._preview_callback is not None:
            self._preview_callback(entry)
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
        if candidate not in self._registry:
            return candidate

        counter = 2
        while True:
            candidate = f"{source_id}_copy{counter}"
            if candidate not in self._registry:
                return candidate
            counter += 1

    def _persist(self) -> None:
        """Сохранить реестр в YAML. Логирует если yaml_path не задан."""
        try:
            self._registry.persist(self._yaml_path)
        except Exception as exc:
            logger.error("DisplaysPresenter: ошибка сохранения YAML: %s", exc)
