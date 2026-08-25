# -*- coding: utf-8 -*-
"""Шаблонная секция управления телеметрией процесса (telemetry-publish-control Ф4.1).

Конструкторный принцип: контролы НЕ хардкодятся per-метрика, а **строятся по шаблону
из каталога метрик** (`metrics` — обычно `gated_metrics()` фреймворка). Одна строка на метрику:

    [✓ вкл]  <метка>   [частота, с ▾]   <эфф. значение / ⚠ потолок>

Объявили метрику (`declare_metric`) — строка появилась автоматически, без правки UI.

**Резидуал Ф8.1 закрыт задачей 4.2.** Каталог строк больше не только импортный:
конструктор принимает ``readback`` — секцию ответа `introspect_telemetry(process)`
(``{"gated_metrics": [...]}``), а runtime-приход того же readback (поздний, через
:class:`TelemetryPoller`/``TelemetryViewModel`` — см. `_panels.py`) добавляет строки
методом :meth:`apply_readback`. Метрика, объявленная ТОЛЬКО в бэкенд-процессе, теперь
получает строку, как только readback с ней долетел; импортный каталог (``metrics``) —
ТОЛЬКО фолбэк на время до первого такого ответа (холодный GUI не остаётся пустым).
``apply_readback`` лишь ДОБАВЛЯЕТ отсутствующие строки — уже построенные (в т.ч. из
импортного фолбэка) не трогает, чтобы повторный readback не сбрасывал состояние
чекбокса/частоты, выставленное оператором.

**Проверено на живом стенде (Ф4/4.2, план `observation-port`).** Боевой вход с Qt-зондом,
восемь процессов: панель `camera_0` получила из readback процесса строки `capture_fps`
(`capture: 21.3`), `drops` (`capture: 0`) и `frame_count` (`capture: 6533`) — при целых шести
строках импортного каталога фреймворка. Контроль в ТОМ ЖЕ прогоне: панель процесса `devices`
(плагинов нет) получила те же шесть фреймворковых строк и НИ ОДНОЙ плагинной — значит строки
приходят из ответа конкретного процесса, а не из общего списка, раздаваемого всем.

**Что остаётся непроверенным вживую — половина якоря «до правки строки нет».** Прогон на
СТАРОМ коде не снимался: второй бэкенд на этой машине конфликтует с первым (PID-реестр и
SHM-cleanup). Резидуал воспроизведён на уровне кода — три теста независимого тестера были
красными до реализации (`collected 3, 3 failed`), и грепом подтверждено, что `gated_metrics`
не встречался во `frontend_module` ни разу: дороги доставки readback в GUI не существовало.

Секция ничего не знает о транспорте: на изменение зовёт колбэк ``on_change(metric,
enabled, interval_sec)`` (одно из значений — актуальное, другое ``None`` = «не менялось»).
Запись команды и разбор результата (``capped_by_throttle``) — на стороне владельца
(панель через command-result-bridge, presenter строит конверт).

Чтение статуса — из read-model: :meth:`update_readouts` тянет process-level значения
из :class:`TelemetryViewModel` и показывает их в строке. Адресов ДВА: агрегат
фреймворка — плоско (``processes.<P>.state.<metric>``), метрика плагина — в поддереве
писателя (``processes.<P>.state.plugins.<писатель>.<metric>``, Ф1 «порта наблюдений»);
во втором случае строка печатает и имя писателя.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QWidget,
)

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.state import TelemetryViewModel

# Колбэк изменения: (metric, enabled|None, interval_sec|None). ``None`` = «не менялось»
# на этой оси (тумблер дёрнули — enabled задан, интервал None; и наоборот).
ChangeCallback = Callable[[str, Optional[bool], Optional[float]], None]

# Границы поля частоты: минимум ~20 Гц (0.05с — мягкий дефолт IPC-страховки, ADR-PM-017),
# максимум 60с. Шаг 0.05с. Значение — минимальный интервал публикации метрики.
_INTERVAL_MIN = 0.05
_INTERVAL_MAX = 60.0
_INTERVAL_STEP = 0.05


class _MetricRow:
    """Виджеты одной строки метрики (чекбокс + метка + частота + читаемый статус)."""

    __slots__ = ("metric", "enable", "interval", "readout")

    def __init__(self, metric: str, enable: QCheckBox, interval: QDoubleSpinBox, readout: QLabel) -> None:
        self.metric = metric
        self.enable = enable
        self.interval = interval
        self.readout = readout


class TelemetryControlsSection(QGroupBox):
    """Секция «Телеметрия» — авто-строки контролов по списку метрик.

    Args:
        process_name: имя процесса-адресата (для read-model путей и подписи).
        metrics: список метрик — шаблон строк (обычно ``gated_metrics()`` фреймворка).
        labels: {метрика: русская метка} (отсутствует → сам ключ метрики).
        defaults: {метрика: дефолтный interval_sec} (отсутствует → ``_DEFAULT_INTERVAL``).
        on_change: колбэк изменения (запись делает владелец, не секция).
        readback: секция ответа `introspect_telemetry(process)` — ``{"gated_metrics":
            [...]}`` (Task 4.2). Метрики, которых нет в ``metrics``, получают
            дополнительные строки СВЕРХ импортного каталога; ``None`` (дефолт) —
            каталог остаётся ровно ``metrics`` (фолбэк, поведение до 4.2). Тот же
            приход ПОЗЖЕ, во время жизни секции, — через :meth:`apply_readback`.
        parent: Qt-родитель.
    """

    _DEFAULT_INTERVAL = 1.0

    def __init__(
        self,
        process_name: str,
        metrics: list[str],
        *,
        labels: Optional[dict[str, str]] = None,
        defaults: Optional[dict[str, float]] = None,
        on_change: Optional[ChangeCallback] = None,
        readback: Optional[dict[str, Any]] = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Телеметрия", parent)
        self._process_name = process_name
        self._labels = labels or {}
        self._defaults = defaults or {}
        self._on_change = on_change
        # Гвард: программное выставление значений (update_readouts) не должно
        # порождать команды записи (как blockSignals, но явно и локально).
        self._suppress = False
        self._rows: dict[str, _MetricRow] = {}

        grid = QGridLayout(self)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(3, 1)  # столбец статуса тянется
        self._grid = grid  # нужен apply_readback — дописывает строки ПОСЛЕ __init__

        # Шапка (компактная) — читаемость сетки.
        for col, title in enumerate(("Вкл", "Метрика", "Частота, с", "Статус")):
            header = QLabel(title)
            header.setStyleSheet("color: gray; font-size: 11px;")
            grid.addWidget(header, 0, col)

        # ГЛАВНОЕ: строки строятся В ЦИКЛЕ по списку метрик — не хардкод.
        row = 1
        for metric in metrics:
            self._build_row(grid, row, metric)
            row += 1
        self._next_row = row

        # Task 4.2: readback, если уже известен на момент конструирования, —
        # добавляет строки СВЕРХ метрик выше (не заменяет их, см. apply_readback).
        self.apply_readback(readback)

    # ------------------------------------------------------------------ #
    #  Build (шаблон одной строки)                                        #
    # ------------------------------------------------------------------ #

    def _build_row(self, grid: QGridLayout, row: int, metric: str) -> None:
        enable = QCheckBox()
        enable.setChecked(True)  # по умолчанию метрика включена (боевой дефолт gate)
        enable.setToolTip(f"Публиковать метрику «{metric}»")
        enable.toggled.connect(lambda checked, m=metric: self._emit_enabled(m, checked))

        label = QLabel(self._labels.get(metric, metric))

        interval = QDoubleSpinBox()
        interval.setRange(_INTERVAL_MIN, _INTERVAL_MAX)
        interval.setSingleStep(_INTERVAL_STEP)
        interval.setDecimals(2)
        interval.setValue(self._defaults.get(metric, self._DEFAULT_INTERVAL))
        interval.setToolTip("Минимальный интервал публикации (с). Меньше — чаще.")
        # editingFinished — коммитим по завершению ввода, не на каждый шаг спина.
        interval.editingFinished.connect(lambda m=metric: self._emit_interval(m))

        readout = QLabel("—")
        readout.setStyleSheet("color: gray;")
        readout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        grid.addWidget(enable, row, 0, Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(label, row, 1)
        grid.addWidget(interval, row, 2)
        grid.addWidget(readout, row, 3)

        self._rows[metric] = _MetricRow(metric, enable, interval, readout)

    # ------------------------------------------------------------------ #
    #  Readback (Task 4.2) — строки метрик, объявленных ТОЛЬКО в бэкенде   #
    # ------------------------------------------------------------------ #

    def apply_readback(self, readback: Optional[dict[str, Any]]) -> None:
        """Достроить строки для метрик из readback backend-процесса.

        ``readback`` — секция ответа `introspect_telemetry(process)`, форма
        ``{"gated_metrics": ["fps", "letter_confidence", ...]}``. Метод ТОЛЬКО
        добавляет строки для имён, которых ещё нет в :attr:`_rows` — уже
        построенную строку (в т.ч. из импортного каталога) не трогает: иначе
        повторный (или более поздний) readback сбрасывал бы чекбокс/частоту,
        которые оператор уже выставил руками.

        Вызывается дважды с разным поводом: из ``__init__`` (readback уже
        известен на момент постройки секции — late-binding снимок VM) и
        владельцем секции ПОЗЖЕ, когда readback приходит уже после открытия
        карточки (`_panels.py`, тот же батч-путь, что и у ``update_readouts``).

        Malformed/пустой/``None`` readback — тихий no-op. Секция не имеет
        права упасть из-за формы ответа readback-дороги (правило 5 CLAUDE.md):
        ``readback`` может быть не dict, без ключа ``gated_metrics``, с
        не-list значением или списком, где не все элементы — непустые строки.
        """
        for metric in self._extract_gated_metrics(readback):
            if metric in self._rows:
                continue
            self._build_row(self._grid, self._next_row, metric)
            self._next_row += 1

    @staticmethod
    def _extract_gated_metrics(readback: Optional[dict[str, Any]]) -> list[str]:
        """Достать список имён метрик из ``readback["gated_metrics"]`` робастно.

        Та же осторожность, что у :func:`_extract_caps` ниже: readback приходит
        по IPC (через ``TelemetryPoller`` → ``TelemetryViewModel``), и его форма
        не гарантирована статической типизацией на этой стороне границы.
        """
        if not isinstance(readback, dict):
            return []
        raw = readback.get("gated_metrics")
        if not isinstance(raw, list):
            return []
        return [metric for metric in raw if isinstance(metric, str) and metric]

    # ------------------------------------------------------------------ #
    #  Emit (изменения пользователя → колбэк владельца)                   #
    # ------------------------------------------------------------------ #

    def _emit_enabled(self, metric: str, checked: bool) -> None:
        if self._suppress or self._on_change is None:
            return
        # Выключенную метрику визуально гасим: поле частоты неактивно.
        self._rows[metric].interval.setEnabled(checked)
        self._on_change(metric, checked, None)

    def _emit_interval(self, metric: str) -> None:
        if self._suppress or self._on_change is None:
            return
        self._on_change(metric, None, float(self._rows[metric].interval.value()))

    # ------------------------------------------------------------------ #
    #  Read-model + результат записи                                      #
    # ------------------------------------------------------------------ #

    def update_readouts(self, telemetry: "TelemetryViewModel | None") -> None:
        """Обновить читаемый статус строк из read-model (process-level значения).

        Тянет ``processes.<P>.state.<metric>`` — доступно для агрегатных fps/latency_ms;
        остальные метрики (per-worker) остаются с эхом настройки. Каппинг-предупреждение,
        выставленное :meth:`show_result`, НЕ затирается (приоритет у явного потолка).

        Адресов у метрики ДВА (Ф1 «порта наблюдений»): агрегат фреймворка лежит
        плоско в ``state``, метрика плагина — в поддереве СВОЕГО писателя
        (``state.plugins.<писатель>.<metric>``). Плоский адрес пробуется первым,
        поддерево писателя — вторым; см. :meth:`_plugin_readout`.

        **Порядок этих двух попыток проверить нечем, и это по построению.**
        Наблюдаем он был бы только если ОДНО имя метрики лежит по ОБОИМ адресам
        сразу — то есть при двойной публикации, которую Ф1 как раз и запрещает
        (два писателя одного листа — тот самый класс, который фаза хоронит).
        Измерено ревью Task 1.4 (находка 7): перестановка приоритета оставляет
        61 тест зелёным. Формулировка «плоский первым» — описание кода, а не
        охраняемая гарантия; менять её местами бессмысленно, но и опираться на
        неё как на контракт нельзя.
        """
        if telemetry is None:
            return
        for metric, row in self._rows.items():
            # Не перетираем активное caps-предупреждение (оно важнее живого значения).
            if row.readout.property("capped"):
                continue
            value = telemetry.get(f"processes.{self._process_name}.state.{metric}")
            if value is not None:
                row.readout.setText(str(value))
                continue
            row.readout.setText(self._plugin_readout(telemetry, metric))

    def _plugin_readout(self, telemetry: "TelemetryViewModel", metric: str) -> str:
        """Показание метрики из поддеревьев писателей: ``«писатель: значение»`` или ``«—»``.

        **Писатель в тексте строки — не украшение.** Одноимённый лист у двух
        писателей после Ф1 законен (арбитраж имён удалён), и строка «17» тогда
        не отвечала бы на вопрос, чьи это 17. Поэтому имя писателя печатается
        ВСЕГДА, когда значение пришло из поддерева, — и при одном писателе тоже:
        иначе появление второго молча меняло бы смысл уже привычной строки.

        Писателем считается РОВНО ОДИН сегмент после ``plugins`` — глубже
        вложенные узлы (напр. ``plugins.<w>.workers.<x>.<metric>``) сюда не
        попадают: это не process-level показание, и печатать его в строке
        каталога было бы подменой величины.

        Модель без ``snapshot`` (урезанный дубль в тестах вызывающего) даёт
        прочерк, а не исключение: панель не имеет права падать из-за читалки.

        **Границу поддерева держит ``snapshot``, не эта читалка** (ревью Task 1.4,
        находка 7). Здесь стояла своя проверка ``path.startswith(prefix + ".")`` —
        снятие давало 61 зелёный, потому что ``TelemetryReadModel.snapshot``
        отдаёт только ключи ``== prefix`` или с префиксом ``prefix + "."``, а
        ключ, равный самому префиксу, отсеивается проверкой ``endswith(tail)``
        (префикс никогда не кончается на ``.<метрика>``). Дублирующую проверку
        убрал: код, который нечем сломать, — это код, про который врёт его
        собственное присутствие («границу держу я»).
        """
        snapshot = getattr(telemetry, "snapshot", None)
        if snapshot is None:
            return "—"
        prefix = f"processes.{self._process_name}.state.plugins"
        tail = f".{metric}"
        found: list[str] = []
        for path, value in snapshot(prefix).items():
            if not path.endswith(tail):
                continue
            writer = path[len(prefix) + 1 : -len(tail)]
            if not writer or "." in writer or value is None:
                continue
            found.append(f"{writer}: {value}")
        return ", ".join(sorted(found)) if found else "—"

    def show_result(self, metric: str, result: dict[str, Any]) -> None:
        """Показать результат записи метрики (command-result-bridge).

        ``capped_by_throttle`` (ADR-PM-017 / Task 1.4) → строка получает видимое
        предупреждение о потолке частоты: «no silent caps» доведено до пользователя.
        Успех без потолка — тихо очищаем прежнее предупреждение.
        """
        row = self._rows.get(metric)
        if row is None:
            return
        caps = _extract_caps(result).get(metric)
        if caps:
            throttle_sec = caps.get("throttle_interval_sec")
            row.readout.setText(f"⚠ троттл {throttle_sec} с")
            row.readout.setStyleSheet("color: #c8860a;")  # янтарный — не ошибка, потолок
            row.readout.setToolTip(
                "Центральный троттл строже запрошенной частоты — частота срезается. "
                "Ослабь central-правило (plane=throttle) или подними интервал."
            )
            row.readout.setProperty("capped", True)
        else:
            row.readout.setStyleSheet("color: gray;")
            row.readout.setToolTip("")
            row.readout.setProperty("capped", False)


def _extract_caps(result: Any) -> dict[str, dict[str, Any]]:
    """Достать ``capped_by_throttle`` из ответа команды (робастно к вложенности).

    Ответ ``telemetry.broadcast`` — ``{..., "publish": {..., "capped_by_throttle":
    {metric: {...}}}}`` — может приехать завёрнутым в ``result`` (одна-две вложенности,
    как в backend_ctl ``_leaf_result``). Спускаемся до узла с ``publish``.
    """
    node = result
    for _ in range(4):
        if not isinstance(node, dict):
            break
        publish = node.get("publish")
        if isinstance(publish, dict) and "capped_by_throttle" in publish:
            caps = publish["capped_by_throttle"]
            return caps if isinstance(caps, dict) else {}
        node = node.get("result")
    return {}


__all__ = ["TelemetryControlsSection", "ChangeCallback"]
