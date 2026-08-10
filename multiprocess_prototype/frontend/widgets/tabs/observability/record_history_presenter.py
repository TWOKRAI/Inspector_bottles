# -*- coding: utf-8 -*-
"""
RecordHistoryPresenter — Qt-free логика вкладки истории записей (Ф5.19).

Отделяет пагинацию/фильтрацию/чтение от Qt-виджета (RecordHistoryPanel):
presenter держит источник (RecordSource), kind вкладки, фильтры (уровень,
источник-модуль), строку поиска (1.6) и offset; тестируется без QApplication.
Панель — тонкая View поверх него.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .record_source import RecordSource, search_unavailability


class RecordHistoryPresenter:
    """Пагинация + фильтры целой истории одного kind (log/error/stats)."""

    def __init__(self, source: Optional[RecordSource], kind: str, page_size: int = 100) -> None:
        self._source = source
        self._kind = kind
        self._page_size = page_size
        self._offset = 0
        self._level_filter: Optional[List[str]] = None  # None → все уровни
        self._module_filter: Optional[str] = None
        self._query: Optional[str] = None  # None → лента, не поиск
        self._search_error: Optional[str] = None
        # Спрашиваем ОДИН раз при постройке: у стора это свойство соединения,
        # оно не меняется за жизнь источника, а панель обязана решить судьбу
        # поля ввода до того, как оператор в него напечатает.
        self._search_unavailable: Optional[str] = search_unavailability(source)

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
    # Поиск по слову (задача 1.6)
    # ------------------------------------------------------------------

    def set_search_query(self, query: Optional[str]) -> None:
        """Слово/выражение поиска; пустое — вернуться к ленте.

        Фильтры уровня и источника при этом НЕ сбрасываются: поиск сужает ту же
        выборку, что и лента (у стора это буквально один набор WHERE-условий),
        поэтому «искать в ошибках модуля X» — обычная комбинация, а не спор двух
        режимов.
        """
        self._query = (query or "").strip() or None
        self._offset = 0

    @property
    def searching(self) -> bool:
        """Идёт ли сейчас поиск (а не листание ленты)."""
        return self._query is not None

    @property
    def query(self) -> Optional[str]:
        return self._query

    @property
    def search_unavailable_reason(self) -> Optional[str]:
        """Почему поиск недоступен у источника; ``None`` — доступен."""
        return self._search_unavailable

    @property
    def search_error(self) -> Optional[str]:
        """Причина, по которой ПОСЛЕДНИЙ поиск не выполнен; ``None`` — выполнен.

        Существует ровно затем, чтобы «поиск не выполнен» не выглядело как «не
        нашлось»: оба состояния дают пустую таблицу, и без этого поля оператор
        уходит с ответом «записей нет» на вопрос, который никто не задал.
        """
        return self._search_error

    # ------------------------------------------------------------------
    # Чтение страницы
    # ------------------------------------------------------------------

    def load(self) -> List[Dict[str, Any]]:
        """Прочитать текущую страницу (поиск или лента) из источника, свежие первыми."""
        self._search_error = None
        if self._source is None:
            return []
        if self._query is not None:
            return self._load_search()
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

    def _load_search(self) -> List[Dict[str, Any]]:
        """Страница результатов поиска. Любой отказ — НАЗВАННЫЙ, не пустая страница."""
        if self._search_unavailable is not None:
            self._search_error = self._search_unavailable
            return []
        try:
            return self._source.search(  # type: ignore[union-attr]  # наличие search проверено выше
                self._query,
                kind=self._kind,
                module=self._module_filter,
                severity_in=self._level_filter,
                offset=self._offset,
                limit=self._page_size,
                newest_first=True,
            )
        except Exception as exc:  # noqa: BLE001 — сюда приходит и ObservabilitySearchError
            # Ловим широко намеренно: ObservabilitySearchError живёт во фреймворке,
            # а вкладка обязана пережить ЛЮБОЙ источник, включая чужой. Но не
            # глотаем: текст причины уходит оператору целиком.
            self._search_error = f"поиск не выполнен: {exc}"
            return []

    def matches_live(self, record: Dict[str, Any]) -> bool:
        """Подходит ли live-запись под kind+фильтры текущей вкладки (для хвоста).

        Во время поиска — всегда ``False``: совпадение со СЛОВОМ считает FTS5
        (префиксы, фразы, ``OR``), и повторить его здесь питоновским ``in``
        значило бы тихо разойтись с движком — хвост показывал бы строки, которых
        поиск не находит, и наоборот. Хвост на время поиска приостановлен, и
        панель обязана сказать об этом вслух: молча замерший поток через минуту
        неотличим от сломанного.
        """
        if self._query is not None:
            return False
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
