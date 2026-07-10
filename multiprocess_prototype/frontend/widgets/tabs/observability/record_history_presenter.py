# -*- coding: utf-8 -*-
"""
RecordHistoryPresenter — Qt-free логика вкладки истории записей (Ф5.19).

Отделяет пагинацию/фильтрацию/чтение от Qt-виджета (RecordHistoryPanel):
presenter держит источник (RecordSource), kind вкладки, фильтры (уровень,
источник-модуль) и offset; тестируется без QApplication. Панель — тонкая
View поверх него.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .record_source import RecordSource


class RecordHistoryPresenter:
    """Пагинация + фильтры целой истории одного kind (log/error/stats)."""

    def __init__(self, source: Optional[RecordSource], kind: str, page_size: int = 100) -> None:
        self._source = source
        self._kind = kind
        self._page_size = page_size
        self._offset = 0
        self._level_filter: Optional[List[str]] = None  # None → все уровни
        self._module_filter: Optional[str] = None

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def page_size(self) -> int:
        return self._page_size

    # ------------------------------------------------------------------
    # Фильтры (сбрасывают на первую страницу)
    # ------------------------------------------------------------------

    def set_level_filter(self, levels: Optional[List[str]]) -> None:
        """Membership-фильтр по severity (например ['error','critical']); None → все."""
        self._level_filter = [str(x).lower() for x in levels] if levels else None
        self._offset = 0

    def set_module_filter(self, module: Optional[str]) -> None:
        """Фильтр по источнику-модулю (точное совпадение); пустое → без фильтра."""
        self._module_filter = (module or "").strip() or None
        self._offset = 0

    # ------------------------------------------------------------------
    # Чтение страницы
    # ------------------------------------------------------------------

    def load(self) -> List[Dict[str, Any]]:
        """Прочитать текущую страницу истории из источника (свежие первыми)."""
        if self._source is None:
            return []
        try:
            return self._source.list_records(
                kind=self._kind,
                module=self._module_filter,
                severity_in=self._level_filter,
                offset=self._offset,
                limit=self._page_size,
                newest_first=True,
            )
        except Exception:  # noqa: BLE001 — сбой чтения → пустая страница, не падаем
            return []

    def matches_live(self, record: Dict[str, Any]) -> bool:
        """Подходит ли live-запись под kind+фильтры текущей вкладки (для хвоста)."""
        if record.get("kind") != self._kind:
            return False
        if self._level_filter is not None and str(record.get("severity", "")).lower() not in self._level_filter:
            return False
        if self._module_filter is not None and record.get("module") != self._module_filter:
            return False
        return True

    # ------------------------------------------------------------------
    # Пагинация
    # ------------------------------------------------------------------

    def next_page(self) -> None:
        self._offset += self._page_size

    def prev_page(self) -> None:
        self._offset = max(0, self._offset - self._page_size)

    def reset_page(self) -> None:
        self._offset = 0

    @property
    def offset(self) -> int:
        return self._offset

    @property
    def page_number(self) -> int:
        return self._offset // self._page_size + 1

    @property
    def has_prev(self) -> bool:
        return self._offset > 0

    def has_next(self, page_rows: List[Dict[str, Any]]) -> bool:
        """Есть ли следующая страница (текущая заполнена целиком)."""
        return len(page_rows) >= self._page_size

    @property
    def on_first_page(self) -> bool:
        return self._offset == 0

    # ------------------------------------------------------------------
    # Очистка
    # ------------------------------------------------------------------

    def clear(self) -> int:
        """Очистить историю этого kind в источнике. Возвращает число удалённых."""
        if self._source is None:
            return 0
        try:
            removed = self._source.clear(kind=self._kind)
        except Exception:  # noqa: BLE001
            removed = 0
        self._offset = 0
        return removed
