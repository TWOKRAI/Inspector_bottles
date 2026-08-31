# -*- coding: utf-8 -*-
"""
RecordHistoryPanel — переиспользуемая вкладка истории записей наблюдаемости (Ф5.19).

ОДИН виджет на три вкладки (Логи / Ошибки / Статистика) — каждый инстанс на свой
kind. Целую историю читает пагинацией из RecordSource (стор Ф5.20a), живой хвост
принимает методом ``append_live_records`` из hub→GUI-канала (Ф5.20b).

Переиспользует BaseAdminPanel (таблица/группа/read-only) — тот же паттерн, что
AuditLogPanel; отличия: фильтр по уровню, колонка источник/канал, кнопка
Копировать, live-append (аудит-лог статичен, наблюдаемость течёт).

Задача 1.6 добавила поиск по слову: поле рядом с фильтрами, движок — FTS5
стора. Разбор инцидента начинается со слова, а лента отвечает только «покажи
страницу»; поэтому же поиск обязан различать «не нашлось» и «не выполнен» —
обе пустые таблицы выглядят одинаково, а значат противоположное.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...primitives import BaseAdminPanel
from .record_history_presenter import RecordHistoryPresenter
from .record_source import RecordSource

# Опции фильтра уровня по kind. stats → None: фильтр скрыт, потому что severity
# у метрики не уровень логирования. Веток две, и живьём едет ТОЛЬКО первая
# (замер стенда 2026-08-14, 112 строк вкладки — все агрегаты):
#   агрегат окна  → severity="snapshot"      (2.1, `hub_record_to_display`)
#   одна метрика  → severity=<тип метрики>   (counter/gauge/timing/histogram)
# Список уровней бессмыслен в обоих случаях, поэтому ветку не различаем.
LEVEL_OPTIONS = {
    "log": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    "error": ["ERROR", "CRITICAL"],
}

#: Ф5.2 (Б-8): чем объяснить ПУСТУЮ вкладку. Пустота бывает трёх разных причин —
#: записей правда нет, порог выше пишущих записей, история уже срезана ретеншеном, —
#: и «просто пустая таблица» одинаково выглядит при каждой. Три года наблюдений за
#: этим проектом сводятся к одному правилу: молчащий сигнал через час неотличим от
#: сломанного.
#:
#: У ``stats`` причина СЕГОДНЯ структурная и названа прямо. Формулировка
#: самоограничивающаяся: подсказка показывается только пока строк ноль, поэтому
#: после Ф8.3 (охват hub'а) она исчезнет сама, а не превратится в устаревшую ложь.
EMPTY_HINTS = {
    "log": (
        "Записей нет. Порог записи в историю задаёт observability.history.level "
        "(дефолт INFO) — проверьте его в introspect.observability → history."
    ),
    "error": "Ошибок в истории нет. Это нормальное состояние здорового прогона.",
    # 2.1: причина «у плоскости нет эмитента» УШЛА — снапшот окна доезжает до
    # стора. Подсказка обязана называть только то, что верно сейчас: пустая
    # вкладка теперь означает либо тихий процесс (в окне не было эмиссий —
    # пустые снапшоты подавляются намеренно), либо снятый приёмник.
    "stats": (
        "Метрик в истории нет. Пустое окно агрегации в историю не пишется — если "
        "процесс молчит, это нормально. Иначе проверьте приёмник hub_stats "
        "(introspect.observability → effective.stats) и фильтр страницы."
    ),
}


def _format_ts(ts: Any) -> str:
    """float epoch → 'YYYY-MM-DD HH:MM:SS.mmm'; мусор/0 → '—'."""
    try:
        val = float(ts)
    except (TypeError, ValueError):
        return "—"
    if val <= 0:
        return "—"
    try:
        return datetime.fromtimestamp(val).strftime("%Y-%m-%d %H:%M:%S.") + f"{int((val % 1) * 1000):03d}"
    except (ValueError, OverflowError, OSError):
        return "—"


def _delivery_lag(record: Any) -> Optional[float]:
    """Задержка доставки записи: ``observed_ts - ts``, либо ``None`` (Ф5.2).

    ``None`` возвращается в трёх случаях, и все три означают «мерить нечем»:
    записи из истории (у эмитента отметки приёма нет), мусор в любом из полей,
    отрицательная разность (часы источника ушли вперёд — «задержка −0.3 с» не
    ответ, а новая загадка).

    Функция чистая и вынесена из виджета намеренно: правило «что считать
    задержкой» проверяется без Qt и одинаково для метки и для карточки записи —
    два прочтения одного числа разошлись бы.
    """
    if not isinstance(record, dict):
        return None
    observed = record.get("observed_ts")
    ts = record.get("ts")
    if not isinstance(observed, (int, float)) or not isinstance(ts, (int, float)):
        return None
    if isinstance(observed, bool) or isinstance(ts, bool):
        return None
    lag = float(observed) - float(ts)
    return lag if lag >= 0 else None


class RecordHistoryPanel(BaseAdminPanel):
    """Read-only вкладка истории одного kind: история из стора + живой хвост."""

    _TABLE_COLUMNS = [
        ("ts", "Время", 190),
        ("severity", "Уровень", 90),
        # 5.21 (c): «Процесс» — процесс-источник (camera_0), «Источник» — scope
        # логгера/модуль (для hub-записей совпадают, для error-write-through — нет).
        ("process", "Процесс", 130),
        ("module", "Источник", 150),
        ("message", "Сообщение", 300),
    ]
    _MAX_LIVE_ROWS = 500  # верхний предел отображаемых строк при live-append

    def __init__(
        self,
        source: Optional[RecordSource],
        kind: str,
        *,
        title: str = "",
        page_size: int = 100,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._HEADER_TITLE = title or kind.capitalize()
        self._presenter = RecordHistoryPresenter(source, kind, page_size=page_size)
        self._rows: List[Dict[str, Any]] = []
        # 5.21 (e): счётчик live-записей, отброшенных при переполнении _MAX_LIVE_ROWS.
        # Полная история — в сторе (кнопка «Обновить»); тут показываем, что хвост
        # усечён, чтобы усечение не читалось как «больше ничего не было».
        self._dropped_live = 0
        self._setup_ui()
        self.reload()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = self._create_group()

        # Фильтры: уровень (если применим) + источник.
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(8)

        self._combo_level: QComboBox | None = None
        level_options = LEVEL_OPTIONS.get(self._presenter.kind)
        if level_options:
            filter_layout.addWidget(QLabel("Уровень:"))
            self._combo_level = QComboBox()
            self._combo_level.addItem("Все", userData=None)
            for lvl in level_options:
                self._combo_level.addItem(lvl, userData=lvl)
            self._combo_level.currentIndexChanged.connect(self._on_filters_changed)
            filter_layout.addWidget(self._combo_level)

        filter_layout.addWidget(QLabel("Источник:"))
        self._edit_module = QLineEdit()
        self._edit_module.setPlaceholderText("модуль (точное совпадение)")
        self._edit_module.setMinimumWidth(140)
        self._edit_module.returnPressed.connect(self._on_filters_changed)
        filter_layout.addWidget(self._edit_module)

        # 1.6: поиск по слову. Отдельным полем от «Источник» — тот сужает точным
        # совпадением имени, это ищет по тексту сообщения; слить их в одно поле
        # значило бы гадать за оператора, что он ввёл.
        filter_layout.addWidget(QLabel("Поиск:"))
        self._edit_search = QLineEdit()
        self._edit_search.setMinimumWidth(180)
        self._edit_search.setClearButtonEnabled(True)
        self._edit_search.returnPressed.connect(self._on_search_changed)
        self._edit_search.textChanged.connect(self._on_search_text_changed)
        self._apply_search_availability()
        filter_layout.addWidget(self._edit_search)

        filter_layout.addStretch()
        root.addLayout(filter_layout)

        # Таблица.
        self._table = self._create_table()
        self._table.itemDoubleClicked.connect(self._on_row_double_clicked)
        root.addWidget(self._table, stretch=1)

        # Ф5.2 (Б-8): объяснение пустоты. Живёт под таблицей и появляется ТОЛЬКО
        # когда строк ноль: подсказка, висящая над непустой историей, была бы
        # шумом, а исчезающая сама — не может устареть незамеченной.
        self._lbl_empty = QLabel("")
        self._lbl_empty.setWordWrap(True)
        self._lbl_empty.setObjectName("EmptyHint")
        self._lbl_empty.setVisible(False)
        root.addWidget(self._lbl_empty)

        # Кнопки Обновить / Копировать / Очистить создаём здесь, но НЕ кладём в
        # контент — они уходят в action-колонку вкладки (колонка 1) через
        # action_buttons(), чтобы «Наблюдаемость» выглядела как остальные вкладки
        # (BaseTreeNavTab: кнопки | список разделов | контент).
        self._btn_reload = QPushButton("Обновить")
        self._btn_reload.setToolTip("Перечитать историю из стора")
        self._btn_reload.clicked.connect(self.reload)

        self._btn_copy = QPushButton("Копировать")
        self._btn_copy.setToolTip("Скопировать видимые записи в буфер обмена")
        self._btn_copy.clicked.connect(self._on_copy)

        self._btn_clear = QPushButton("Очистить")
        self._btn_clear.setToolTip("Очистить историю этой вкладки (необратимо)")
        self._btn_clear.clicked.connect(self._on_clear)

        # Пагинация ← / → + метка страницы (остаётся в контенте под таблицей).
        pagination_layout = QHBoxLayout()
        pagination_layout.addStretch()

        self._btn_prev = QPushButton("←")
        self._btn_prev.setObjectName("PaginationArrow")
        self._btn_prev.clicked.connect(self._on_prev_page)
        pagination_layout.addWidget(self._btn_prev)

        self._lbl_page = QLabel("Стр. 1")
        pagination_layout.addWidget(self._lbl_page)

        # Ф5.2 (Б-3/Н-4): задержка плоскости. Показывается ЗДЕСЬ, а не колонкой в
        # истории: отметку приёма ставит этот процесс на живом хвосте, а в стор
        # пишут процессы-эмитенты — историческую задержку взять неоткуда, и
        # колонка под неё простояла пустой всю жизнь (0 из 303 016 строк).
        self._lbl_lag = QLabel("")
        self._lbl_lag.setToolTip(
            "Задержка живого хвоста: сколько прошло между эмиссией записи и её приёмом GUI. "
            "Пусто — по этой вкладке ещё не приезжало живых записей."
        )
        pagination_layout.addWidget(self._lbl_lag)

        self._btn_next = QPushButton("→")
        self._btn_next.setObjectName("PaginationArrow")
        self._btn_next.clicked.connect(self._on_next_page)
        pagination_layout.addWidget(self._btn_next)

        pagination_layout.addStretch()
        root.addLayout(pagination_layout)

    def action_buttons(self) -> List[QWidget]:
        """Кнопки для action-колонки вкладки (колонка 1): Обновить / Копировать / Очистить.

        Контракт SectionProtocol.action_buttons — BaseTreeNavTab кладёт их в
        action-стек и переключает по активной секции (как в Settings).
        """
        return [self._btn_reload, self._btn_copy, self._btn_clear]

    # ------------------------------------------------------------------
    # Фильтры / загрузка
    # ------------------------------------------------------------------

    def _apply_search_availability(self) -> None:
        """Живое поле поиска — или мёртвое, но с названной причиной (1.6).

        Причина уходит и в подсказку поля, и в tooltip: «поиск недоступен» без
        «почему» — приглашение решить, что сломана вкладка.
        """
        reason = self._presenter.search_unavailable_reason
        if reason is None:
            self._edit_search.setPlaceholderText("слово или кусок сообщения")
            self._edit_search.setToolTip(
                "Полнотекстовый поиск по сообщению, источнику и процессу. "
                "Обычный текст ищется как есть — кусок сообщения можно вставить из буфера. "
                'Дополнительно: "точная фраза", префикс hik*, a OR b. '
                "Enter — искать, пустая строка — вернуться к ленте."
            )
            return
        self._edit_search.setEnabled(False)
        self._edit_search.setPlaceholderText("поиск недоступен")
        self._edit_search.setToolTip(reason)

    def _on_search_changed(self) -> None:
        """Enter в поле поиска: искать (или вернуться к ленте, если поле пустое)."""
        self._presenter.set_search_query(self._edit_search.text())
        self.reload()

    def _on_search_text_changed(self, text: str) -> None:
        """Очистка поля (крестик/Backspace) возвращает ленту без Enter.

        Только на переход «был поиск → поле пусто»: на каждый набранный символ
        поиск НЕ перезапускается — у частого слова запрос стоит десятки
        миллисекунд, и посимвольный поиск превратил бы набор слова в очередь
        заведомо ненужных полных проходов.
        """
        if not text.strip() and self._presenter.searching:
            self._presenter.set_search_query(None)
            self.reload()

    def _on_filters_changed(self) -> None:
        if self._combo_level is not None:
            level = self._combo_level.currentData()
            self._presenter.set_level_filter([level] if level else None)
        self._presenter.set_module_filter(self._edit_module.text())
        self.reload()

    def reload(self) -> None:
        """Перечитать текущую страницу истории и заполнить таблицу.

        Счётчик усечения live-хвоста сбрасывается: после перечитки таблица
        показывает полную историю из стора, и метка «хвост усечён: N»
        относилась бы к уже не отображаемому хвосту (ревью 2026-07-10, R4d).
        """
        self._dropped_live = 0
        self._rows = self._presenter.load()
        self._fill_table(self._rows)
        self._update_pagination()

    def _fill_table(self, rows: List[Dict[str, Any]]) -> None:
        self._table.setRowCount(len(rows))
        for r, rec in enumerate(rows):
            self._set_row(r, rec)
        self._update_empty_hint(bool(rows))

    def _update_empty_hint(self, has_rows: bool) -> None:
        """Пустая вкладка обязана сказать, ПОЧЕМУ она пуста (Ф5.2, Б-8; 1.6).

        Подсказка не показывается, если строки есть, и не показывается на первой
        странице пагинации при непустой истории — то есть не может застрять
        поверх работающей вкладки.

        Пустых теперь ЧЕТЫРЕ разных, и три из них дают одинаковую пустую таблицу:
        история пуста, поиск не нашёл, поиск не выполнен (непонятый запрос или
        нечем искать). Ответ «записей нет» на невыполненный поиск — ровно тот
        класс тихой потери, ради которого движок и отвечает исключением.
        """
        error = self._presenter.search_error
        if error is not None:
            # Причина отказа — самое конкретное, что можно сказать про эту
            # пустоту, поэтому проверяется первой. Таблица при отказе пуста по
            # построению (``load`` возвращает пустую страницу), но порядок
            # ветвей от этого не зависит: причина важнее любой общей подсказки.
            self._lbl_empty.setText(error)
            self._lbl_empty.setVisible(True)
            return
        if has_rows:
            self._lbl_empty.setVisible(False)
            return
        if self._presenter.searching:
            self._lbl_empty.setText(
                f"По запросу «{self._presenter.query}» ничего не найдено. "
                "Это ответ поиска, а не пустая история — очистите поле, чтобы вернуться к ленте."
            )
            self._lbl_empty.setVisible(True)
            return
        hint = EMPTY_HINTS.get(self._presenter.kind, "")
        self._lbl_empty.setText(hint)
        self._lbl_empty.setVisible(bool(hint))

    def _set_row(self, row: int, rec: Dict[str, Any]) -> None:
        cells = [
            _format_ts(rec.get("ts")),
            str(rec.get("severity", "") or "—"),
            str(rec.get("process", "") or "—"),
            str(rec.get("module", "") or "—"),
            str(rec.get("message", "") or ""),
        ]
        for col, text in enumerate(cells):
            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, col, item)

    # ------------------------------------------------------------------
    # Живой хвост (Ф5.20b)
    # ------------------------------------------------------------------

    def append_live_records(self, records: List[Dict[str, Any]]) -> int:
        """Добавить live-записи хвоста (свежие — сверху). Возвращает число добавленных.

        Только на первой странице (иначе перемешали бы пагинацию) и только
        подходящие под kind+фильтры вкладки. Ограничение _MAX_LIVE_ROWS: старые
        строки снизу отбрасываются (drop_oldest — как в bounded-каналах hub'а).
        """
        if not self._presenter.on_first_page:
            return 0
        fresh = [rec for rec in records if self._presenter.matches_live(rec)]
        if not fresh:
            return 0
        # Свежие сверху. Инкрементально (O(fresh), не O(всей таблицы)): вставляем
        # строки в начало таблицы, не пересоздавая её целиком — под busy-хвостом
        # полный rebuild на каждый батч давал бы GUI-jank.
        self._rows = fresh + self._rows
        self._table.setUpdatesEnabled(False)
        try:
            for i, rec in enumerate(fresh):
                self._table.insertRow(i)
                self._set_row(i, rec)
            # drop_oldest: обрезаем хвост модели И таблицы до _MAX_LIVE_ROWS.
            while len(self._rows) > self._MAX_LIVE_ROWS:
                self._rows.pop()
                self._table.removeRow(self._table.rowCount() - 1)
                self._dropped_live += 1  # 5.21 (e): усечение хвоста не молчим
        finally:
            self._table.setUpdatesEnabled(True)
        self._update_live_lag(fresh)
        # Пагинация зависит от числа строк (has_next) — держим кнопки честными.
        self._update_pagination()
        return len(fresh)

    def _update_live_lag(self, fresh: List[Dict[str, Any]]) -> None:
        """Показать задержку плоскости по свежей пачке (Ф5.2, Б-3 + Н-4).

        Задержка = ``observed_ts - ts``: момент приёма ставит ЭТОТ процесс
        (``stamp_observed`` в обработчике пуша), момент эмиссии несёт запись.
        Информация появляется ровно на границе процессов, поэтому показать её
        может только принимающая сторона — и только для живого хвоста.

        Берётся МАКСИМУМ по пачке, а не последняя запись: вопрос, ради которого
        число показывается, звучит «не застряла ли плоскость», и на него отвечает
        худшая запись, а не случайно оказавшаяся последней.

        Отрицательная разность (часы источника ушли вперёд) не показывается:
        «задержка −0.3 с» — не ответ, а новая загадка. Молчание здесь честнее.
        """
        lags = [lag for lag in (_delivery_lag(rec) for rec in fresh) if lag is not None]
        if not lags:
            return
        self._lbl_lag.setText(f"задержка: {max(lags):.2f} с")

    # ------------------------------------------------------------------
    # Кнопки
    # ------------------------------------------------------------------

    def _on_copy(self) -> None:
        """Скопировать видимые записи (TSV) в буфер обмена."""
        from PySide6.QtWidgets import QApplication

        lines = ["\t".join(c[1] for c in self._TABLE_COLUMNS)]
        for rec in self._rows:
            lines.append(
                "\t".join(
                    [
                        _format_ts(rec.get("ts")),
                        str(rec.get("severity", "")),
                        str(rec.get("process", "")),
                        str(rec.get("module", "")),
                        str(rec.get("message", "")),
                    ]
                )
            )
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText("\n".join(lines))

    def _on_clear(self) -> None:
        self._presenter.clear()
        self.reload()

    # ------------------------------------------------------------------
    # Пагинация
    # ------------------------------------------------------------------

    def _on_prev_page(self) -> None:
        if self._presenter.has_prev:
            self._presenter.prev_page()
            self.reload()

    def _on_next_page(self) -> None:
        if self._presenter.has_next(self._rows):
            self._presenter.next_page()
            self.reload()

    def _update_pagination(self) -> None:
        label = f"Стр. {self._presenter.page_number}"
        if self._presenter.searching:
            # 1.6: во время поиска живой хвост не доливается (совпадение со словом
            # считает FTS5, а не панель). Замерший поток обязан быть НАЗВАН —
            # молчащий через минуту неотличим от сломанного.
            label += " · поиск: живой хвост приостановлен"
        if self._dropped_live:
            # Видимый счётчик усечённого live-хвоста (полная история — в сторе).
            label += f" · хвост усечён: {self._dropped_live}"
            self._lbl_page.setToolTip(
                f"{self._dropped_live} live-записей вытеснено из хвоста "
                f"(лимит {self._MAX_LIVE_ROWS}); полная история — по кнопке «Обновить»"
            )
        else:
            self._lbl_page.setToolTip("")
        self._lbl_page.setText(label)
        self._btn_prev.setEnabled(self._presenter.has_prev)
        self._btn_next.setEnabled(self._presenter.has_next(self._rows))

    # ------------------------------------------------------------------
    # Детальный просмотр
    # ------------------------------------------------------------------

    def _on_row_double_clicked(self, item: QTableWidgetItem) -> None:
        row = item.row()
        if 0 <= row < len(self._rows):
            _RecordDetailDialog(self._rows[row], parent=self).exec()


class _RecordDetailDialog(QDialog):
    """QDialog с полным содержимым записи (включая extra/context/traceback)."""

    def __init__(self, record: Dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Детали записи")
        self.setMinimumSize(520, 360)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        meta = [
            f"<b>Время:</b> {escape(_format_ts(record.get('ts')))}",
            f"<b>Kind:</b> {escape(str(record.get('kind', '')))}",
            f"<b>Уровень:</b> {escape(str(record.get('severity', '')))}",
            f"<b>Процесс:</b> {escape(str(record.get('process', '')))}",
            f"<b>Источник:</b> {escape(str(record.get('module', '')))}",
            f"<b>Сообщение:</b> {escape(str(record.get('message', '')))}",
        ]
        # Ф5.2: задержка — только у живых записей. У строки из истории отметки
        # приёма нет и быть не может (в стор пишет эмитент), поэтому строка
        # добавляется, а не показывается вечным «—»: прочерк читался бы как
        # «задержки не было», а не как «здесь её не измеряют».
        lag = _delivery_lag(record)
        if lag is not None:
            meta.append(f"<b>Задержка доставки:</b> {lag:.3f} с")
        for line in meta:
            lbl = QLabel(line)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setWordWrap(True)
            layout.addWidget(lbl)

        layout.addWidget(QLabel("<b>extra:</b>"))
        extra_edit = QTextEdit()
        extra_edit.setReadOnly(True)
        import json

        try:
            extra_text = json.dumps(record.get("extra", {}), ensure_ascii=False, indent=2, default=str)
        except (TypeError, ValueError):
            extra_text = str(record.get("extra", {}))
        extra_edit.setPlainText(extra_text)
        layout.addWidget(extra_edit)

        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(self.accept)
        h = QHBoxLayout()
        h.addStretch()
        h.addWidget(btn_close)
        layout.addLayout(h)
