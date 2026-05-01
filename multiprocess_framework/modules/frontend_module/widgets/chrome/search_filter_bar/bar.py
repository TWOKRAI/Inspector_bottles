# multiprocess_framework/modules/frontend_module/widgets/chrome/search_filter_bar/bar.py
"""SearchFilterBar — строка поиска + фильтр категорий + сортировка."""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTimer,
    QWidget,
    Signal,
)

# Debounce задержка ввода поиска (мс) -- чтобы не перерисовывать карточки на каждый символ
_SEARCH_DEBOUNCE_MS = 200

# Варианты сортировки: (отображение, sort_field, ascending)
_SORT_OPTIONS: list[tuple[str, str, bool]] = [
    ("По умолчанию", "", True),
    ("По названию ▲", "param", True),
    ("По названию ▼", "param", False),
    ("По описанию ▲", "info", True),
    ("По описанию ▼", "info", False),
]


class SearchFilterBar(QWidget):
    """Панель поиска, фильтрации по категории и сортировки строк."""

    filter_changed = Signal(str, str)  # (search_text, category), '' = сброс
    sort_changed = Signal(str, bool)  # (sort_field, ascending)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Debounce таймер для поиска (категория/сортировка эмитятся сразу)
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.timeout.connect(self._emit_filter)

        # Поле поиска
        self._search = QLineEdit()
        self._search.setPlaceholderText("Поиск по названию или описанию...")
        self._search.textChanged.connect(self._on_search_text_changed)
        layout.addWidget(self._search, 1)

        # Фильтр по категории (без debounce -- меняется редко)
        self._category = QComboBox()
        self._category.addItem("Все категории")
        self._category.currentIndexChanged.connect(self._emit_filter)
        layout.addWidget(self._category)

        # Сортировка
        self._sort = QComboBox()
        for label, _, _ in _SORT_OPTIONS:
            self._sort.addItem(label)
        self._sort.currentIndexChanged.connect(self._emit_sort)
        layout.addWidget(self._sort)

        # Кнопка сброса
        self._btn_reset = QPushButton("✕")
        self._btn_reset.setFixedWidth(28)
        self._btn_reset.setToolTip("Сбросить фильтр")
        self._btn_reset.clicked.connect(self._reset)
        layout.addWidget(self._btn_reset)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def set_categories(self, categories: list[str]) -> None:
        """Заменить список категорий, сохраняя пункт 'Все категории'."""
        self._category.blockSignals(True)
        self._category.clear()
        self._category.addItem("Все категории")
        for cat in categories:
            self._category.addItem(cat)
        self._category.blockSignals(False)

    # ------------------------------------------------------------------
    # Внутренние обработчики
    # ------------------------------------------------------------------

    def _on_search_text_changed(self, _text: str) -> None:
        """Debounced re-trigger -- не дёргаем фильтр на каждый символ."""
        self._search_debounce.start(_SEARCH_DEBOUNCE_MS)

    def _emit_filter(self) -> None:
        text = self._search.text().strip()
        idx = self._category.currentIndex()
        category = "" if idx <= 0 else self._category.currentText()
        self.filter_changed.emit(text, category)

    def _emit_sort(self) -> None:
        idx = self._sort.currentIndex()
        if 0 <= idx < len(_SORT_OPTIONS):
            _, field, asc = _SORT_OPTIONS[idx]
            self.sort_changed.emit(field, asc)

    def _reset(self) -> None:
        self._search_debounce.stop()
        self._search.clear()
        self._category.setCurrentIndex(0)
        self._sort.setCurrentIndex(0)
        # category/sort уже эмитнули currentIndexChanged; фильтр явно сбрасываем сразу
        self._emit_filter()


def apply_filter(
    rows: list[dict],
    text: str = "",
    category: str = "",
    sort_field: str = "",
    ascending: bool = True,
) -> list[dict]:
    """
    Фильтрация и сортировка списка row-dict.

    - category="" -- все группы; иначе фильтр по schema_name или register_name
    - text ищет case-insensitive в param и info
    - sort_field: "param" | "info" | "" (без сортировки)
    """
    result = list(rows)

    # Фильтр по категории
    if category:
        result = [
            r
            for r in result
            if r.get("schema_name", r.get("register_name", "")) == category
        ]

    # Текстовый поиск
    if text:
        text_lower = text.lower()
        result = [
            r
            for r in result
            if text_lower in str(r.get("param", "")).lower()
            or text_lower in str(r.get("info", "")).lower()
        ]

    # Сортировка
    if sort_field and sort_field in ("param", "info"):
        result.sort(key=lambda r: str(r.get(sort_field, "")).lower(), reverse=not ascending)

    return result
