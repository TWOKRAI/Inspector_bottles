"""Окно-монитор обмена с симулятором робота: две колонки + счётчик дублей.

Левая колонка — что ПРИНЯЛ симулятор от инспектора (записи Modbus, подписанные
именами из карты регистров). Правая — что ОТДАЛ робот (события ядра: приём
задания, завершение, стоп). Шапка: заданий / ДУБЛЕЙ / выполнено / чтений.

Смысл инструмента: показать деталь на камере и посчитать, сколько заданий ушло
роботу на ОДНУ деталь. Строка «ДУБЛЬ» с невязкой трекинга — прямая улика
пропавшего дедупа в тракте (см. ``sim_journal``).

Запуск — из CLI симулятора::

    python -m Services.robot_comm.server --gui

Поток: журнал наполняется из потоков сервера и ticker'а, окно тянет накопленное
таймером (``drain``) — сигналов между потоками нет, гонок тоже.
"""

from __future__ import annotations

import time
from html import escape

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from Services.robot_comm.server.sim_journal import JournalEntry, SimJournal

#: Цвет строки по классу события (тёмная тема панелей — инструмент отладки).
_TAG_COLOR = {
    "dup": "#ff5c57",  # дубль — то, ради чего окно и сделано
    "job": "#5af78e",  # новое задание
    "flag": "#f3f99d",  # взвод mailbox-флага
    "done": "#57c7ff",  # робот освободился
    "": "#c8c8c8",
}

_PANE_STYLE = "background:#1b1b1b; color:#c8c8c8; border:1px solid #3a3a3a;"


class SimMonitorWindow(QWidget):
    """Живой журнал обмена: принято от ПК ↔ отдано роботом.

    Args:
        journal:  Источник строк (наполняется сервером симулятора).
        poll_ms:  Период опроса журнала, мс.
        max_lines: Ёмкость каждой колонки в строках (старые вытесняются).
    """

    def __init__(self, journal: SimJournal, *, poll_ms: int = 100, max_lines: int = 3000) -> None:
        super().__init__()
        self._journal = journal
        # Якорь для перевода монотонных отметок журнала в настенное время.
        self._t0_mono = time.monotonic()
        self._t0_wall = time.time()
        # Предыдущая отметка ПО КАЖДОЙ стороне — Δt должен считаться внутри
        # колонки: «три задания за 100 мс» видно именно так.
        self._prev_t: dict[str, float] = {}

        self.setWindowTitle("Симулятор робота — обмен с инспектором")
        self.resize(1180, 700)

        self._lbl_counters = QLabel()
        self._lbl_counters.setTextFormat(Qt.TextFormat.RichText)
        self._chk_follow = QCheckBox("Автопрокрутка")
        self._chk_follow.setChecked(True)
        btn_clear = QPushButton("Очистить")
        btn_clear.clicked.connect(self._on_clear)

        head = QHBoxLayout()
        head.addWidget(self._lbl_counters, stretch=1)
        head.addWidget(self._chk_follow)
        head.addWidget(btn_clear)

        self._pane_in = self._make_pane(max_lines)
        self._pane_out = self._make_pane(max_lines)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._wrap(self._pane_in, "◀  Принято от инспектора"))
        splitter.addWidget(self._wrap(self._pane_out, "▶  Отдал робот"))
        splitter.setSizes([620, 560])

        root = QVBoxLayout(self)
        root.addLayout(head)
        root.addWidget(splitter, stretch=1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._pump)
        self._timer.start(poll_ms)
        self._refresh_counters()

    # ------------------------------------------------------------------ #
    # Сборка
    # ------------------------------------------------------------------ #

    @staticmethod
    def _make_pane(max_lines: int) -> QPlainTextEdit:
        """Панель журнала: моноширинная, только чтение, с ограничением строк."""
        pane = QPlainTextEdit()
        pane.setReadOnly(True)
        pane.setMaximumBlockCount(max_lines)
        pane.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        pane.setFont(QFont("Consolas", 10))
        pane.setStyleSheet(_PANE_STYLE)
        return pane

    @staticmethod
    def _wrap(pane: QPlainTextEdit, title: str) -> QWidget:
        """Панель с заголовком — одна колонка сплиттера."""
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        label = QLabel(title)
        label.setStyleSheet("font-weight:bold; padding:2px;")
        lay.addWidget(label)
        lay.addWidget(pane)
        return box

    # ------------------------------------------------------------------ #
    # Обновление
    # ------------------------------------------------------------------ #

    def _pump(self) -> None:
        """Тик таймера: забрать накопленное из журнала и дописать в колонки."""
        entries = self._journal.drain()
        for entry in entries:
            pane = self._pane_in if entry.side == "in" else self._pane_out
            pane.appendHtml(self._render(entry))
        if entries:
            self._refresh_counters()
            if self._chk_follow.isChecked():
                for pane in (self._pane_in, self._pane_out):
                    pane.verticalScrollBar().setValue(pane.verticalScrollBar().maximum())

    def _render(self, entry: JournalEntry) -> str:
        """Строка журнала → HTML: время, Δt внутри колонки, текст, цвет по классу."""
        wall = self._t0_wall + (entry.t - self._t0_mono)
        stamp = time.strftime("%H:%M:%S", time.localtime(wall)) + f".{int(wall % 1 * 1000):03d}"
        prev = self._prev_t.get(entry.side)
        self._prev_t[entry.side] = entry.t
        delta = "      " if prev is None else f"+{entry.t - prev:5.3f}"
        color = _TAG_COLOR.get(entry.tag, _TAG_COLOR[""])
        weight = "bold" if entry.tag in ("dup", "job") else "normal"
        return (
            f'<span style="color:#6d6d6d">{stamp} {delta}</span> '
            f'<span style="color:{color}; font-weight:{weight}">{escape(entry.text)}</span>'
        )

    def _refresh_counters(self) -> None:
        """Перерисовать шапку. Ненулевые дубли — красным: это и есть находка."""
        c = self._journal.counters()
        dup_color = "#c0392b" if c["dups"] else "#7f8c8d"
        self._lbl_counters.setText(
            f"заданий: <b>{c['jobs']}</b> &nbsp;·&nbsp; "
            f'<span style="color:{dup_color}">ДУБЛЕЙ: <b>{c["dups"]}</b></span> &nbsp;·&nbsp; '
            f"выполнено: <b>{c['done']}</b> &nbsp;·&nbsp; "
            f'<span style="color:#7f8c8d">чтений: {c["reads"]}</span>'
        )

    def _on_clear(self) -> None:
        """Сбросить обе колонки и счётчики (в т.ч. память о заданиях)."""
        self._journal.reset()
        self._pane_in.clear()
        self._pane_out.clear()
        self._prev_t.clear()
        self._refresh_counters()
