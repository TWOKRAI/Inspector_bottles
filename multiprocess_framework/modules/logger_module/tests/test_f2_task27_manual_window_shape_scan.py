# -*- coding: utf-8 -*-
"""Замыкатель класса (координатор, добор ревью Ф2, 2026-09-01) — Н-3 ОБЩИМ ходом.

**Правило вычисленного охвата.** Сторож заявления «таких X больше нет / все X
учтены» обязан получать список X СКАНОМ ДЕРЕВА, а не ручным перечнем; ручной
список допустим только для ИСКЛЮЧЕНИЙ, и у каждого исключения — причина.

До этого файла у Н-3 было два сторожа, оба смотрящие на ТЕКСТ ЗАЯВЛЕНИЙ, а не на
код:

* ``test_f2_task27_manual_window_registry_matches_claims.py`` — сверяет ЧИСЛО в
  прозе с длиной ``REPLACED_MANUAL_WINDOWS``;
* ``test_windowed_voice_injection_guards.py::TestTheManualWindowCountLivesInExactlyOnePlace``
  — проверяет, что три захардкоженных файла (``_WATCHED``) не пишут число словом.

Оба слепы к экземпляру, который НИЧЕГО не заявляет о себе: `data_receiver.py`
(Н-3, ревью Ф2) содержит форму «ручное окно с подавлением»
(``_lag_log_window``/``_lag_last_log``/``_lag_dropped_since_log``) и не упомянут
НИ В ОДНОМ из двух текстовых сторожей, потому что сам факт наличия кода не
требует, чтобы кто-то о нём написал прозой. Пропущенный экземпляр лежал вне
охвата сторожа, но внутри охвата заявления «ручных копий больше нет».

## Форма, которую ищет скан

Два регекса ловят ДВЕ ПОЛОВИНЫ формы «ручное окно с подавлением» (см. докстринг
``windowed_voice.py``: «по одному состоянию ``_last_log``/``_suppressed`` на
файл»):

1. состояние «когда в последний раз логировали/предупреждали» —
   ``self.*last*(log|warn)*``;
2. состояние «сколько подавлено/выброшено с прошлого раза» —
   ``self.*(suppress|dropped|evict)*``.

ОБЕ половины в ОДНОМ файле — это и есть форма. По отдельности первая половина
ловит ещё 4 файла в этом дереве (``chain_module/metrics/latency.py``,
``Plugins/sources/frame_counter/plugin.py``,
``frontend_module/state/telemetry_poller.py``,
``Plugins/processing/roi_crop/plugin.py`` — числа сверены грепом при написании
теста, 2026-09-01), но ни один из них не несёт вторую половину: это
ПЕРИОДИЧЕСКИЕ ОТЧЁТЫ (безусловная публикация на тик — FPS, percentiles), а не
троттлинг диагностического события с подсчётом подавленного. У windowed_voice
нет отношения к «отчитайся не чаще раза в N секунд о том, что и так происходило
непрерывно» — это другой контракт, и мигрировать их на windowed_voice значило
бы решать чужую задачу. ``TestScanDoesNotFlagPeriodicReportersAsManualWindows``
ниже — контроль этого решения, не самоочевидная деталь.

## Находка ЭТОГО скана, которую разбор со стороны не назвал

Полный AND-скан (обе половины, весь репозиторий) даёт РОВНО ДВА хита:
``data_receiver.py`` (уже известен) и
**``multiprocess_framework/modules/logger_module/channels/log_channel.py``**
(новый — не упомянут ни в постановке Н-3, ни во внешнем разборе координатора).
Это ДВЕ разные ручных копии в одном файле: ``LogChannel._warn_sink_stuck``
(``_last_warning_ts``/``_WARNING_INTERVAL_SEC``, унаследовано ``ConsoleChannel``)
и ``_SafeRotatingFileHandler._warn_rollover_stuck``
(``_last_rollover_warning_ts``/``_ROLLOVER_WARNING_INTERVAL_SEC``).

Разбор: обе предупреждают о СБОЕ САМОГО МЕХАНИЗМА ЛОГИРОВАНИЯ (застрявший сток,
не сработавшая ротация) и НАМЕРЕННО не идут через ``LoggerManager``/каналы —
файл говорит об этом прямо в шапке (строки 30-34): «Сообщения О САМОМ
логировании... НЕ маршрутизируются через LoggerManager/каналы — тот механизм и
есть то, что сломано в этот момент». ``ConsoleChannel._warn_sink_stuck`` это же
объясняет ещё раз на своём месте: «сообщение о том, что консоль не принимает
записи, не имеет права идти в консоль тем же путём, который сейчас затык».
``windowed_voice`` живёт ВНУТРИ ``logger_module`` и его политика
(``observability.voices.*``) читается через процессную обвязку, завязанную на
тот же ``LoggerManager`` — подключить его здесь значило бы протянуть
диагностику отказа логирования через код, который зависит от логирования.
Это ТОТ ЖЕ довод, что уже документирован в самом ``windowed_voice.py`` про
``process_module/health/state.py``: «не занимай окно у чужого механизма, если
его отказ может быть как раз тем, что ты диагностируешь» — только здесь
зависимость прямая, а не заимствование окна.

**Вывод: `log_channel.py` — НЕ тот же класс, что `data_receiver.py`.**
`data_receiver.py` не диагностирует сам логгер — там ничто не мешало бы
migration на ``windowed_voice``, миграция там просто не сделана (долг). У
`log_channel.py` есть архитектурная причина остаться в стороне — она
задокументирована в самом коде, не придумана здесь. Оба идут в
``_NAMED_EXCEPTIONS`` — но с РАЗНЫМИ причинами, и разница написана в тексте
исключения, а не молчит за одинаковой галочкой.

**Честная оговорка.** Эта находка (``log_channel.py``) НЕ была в постановке
задачи и не проверена вторым независимым взглядом — только мной, чтением кода
и докстринга файла. Аргумент правдоподобен и подкреплён явным текстом в самом
файле, но я не проверял, есть ли способ подключить windowed_voice БЕЗ
циклической зависимости (например, передав в него голый калбэк вместо похода
через LoggerManager) — возможно, изоляция чуть менее абсолютна, чем текст файла
утверждает. Называю это в отчёте координатору, а не тихо.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Tuple

import multiprocess_framework as _mpf

#: Корневые директории источника, которые сканируются целиком — форма может
#: завестись в любом слое, не только там, где живёт windowed_voice.
_SCAN_DIRS = ("multiprocess_framework", "Services", "Plugins", "multiprocess_prototype", "backend_ctl")

#: Каталоги, исключённые из скана целиком. ``tests`` — тем же доводом, что у
#: узкого сторожа: файлы ПРО эту самую находку законно цитируют её код.
_SKIP_DIR_NAMES = {"tests", "__pycache__", ".git", ".venv", "node_modules", ".claude"}

#: Дом механизма — исключён явно, а не по случайности регекса (сегодня он и так
#: не матчится, но экслюзия защищает от будущего переименования внутри модуля).
_MECHANISM_FILE = "multiprocess_framework/modules/logger_module/core/windowed_voice.py"

#: Половина формы 1: «когда в последний раз логировали/предупреждали».
_LAST_LOG_RE = re.compile(r"self\.[a-zA-Z_]*last[a-zA-Z_]*(log|warn)[a-zA-Z_]*\s*=")

#: Половина формы 2: «сколько подавлено/выброшено» — шире, чем «...since_log»,
#: чтобы ловить и булев флаг стиля старого ``_send_error_suppressed``, а не
#: только счётчик-с-таймингом стиля ``_lag_dropped_since_log``.
_SUPPRESSED_RE = re.compile(r"self\.[a-zA-Z_]*(suppress|dropped|evict)[a-zA-Z_]*\s*=")

#: Поимённые исключения: файл → причина. Каждая запись обязана быть причиной,
#: не галочкой — скан не различит «долг» от «архитектурного решения» сам.
_NAMED_EXCEPTIONS: Dict[str, str] = {
    "multiprocess_framework/modules/process_module/generic/data_receiver.py": (
        "живая седьмая ручная копия окна голоса (_lag_log_window/_lag_last_log/"
        "_lag_dropped_since_log), не заведённая в REPLACED_MANUAL_WINDOWS. Найдена "
        "ревью Ф2 (Н-3), 2026-09-01. Миграция на windowed_voice — правка ПОВЕДЕНИЯ, "
        "вне охвата этой задачи; долг записан в docs/claude/OPEN_QUESTIONS.md."
    ),
    "multiprocess_framework/modules/logger_module/channels/log_channel.py": (
        "НЕ долг, архитектурное решение: LogChannel._warn_sink_stuck (унаследовано "
        "ConsoleChannel) и _SafeRotatingFileHandler._warn_rollover_stuck предупреждают "
        "о сбое САМОГО механизма логирования и намеренно идут через emergency_log() "
        "в обход LoggerManager/каналов — файл говорит об этом прямо (строки 30-34: "
        "'тот механизм и есть то, что сломано в этот момент'). windowed_voice живёт "
        "внутри logger_module и его политика читается через ту же процессную обвязку, "
        "что и LoggerManager — подключить его здесь значило бы протянуть диагностику "
        "отказа логирования через код, зависящий от логирования. Найдена этим сканом "
        "2026-09-01, не была в исходной постановке Н-3 — независимо не перепроверена, "
        "см. докстринг модуля."
    ),
}


def _repo_root() -> Path:
    return Path(_mpf.__file__).resolve().parent.parent


def _iter_source_files(root: Path):
    for base in _SCAN_DIRS:
        base_dir = root / base
        if not base_dir.is_dir():
            continue
        for path in base_dir.rglob("*.py"):
            if any(part in _SKIP_DIR_NAMES for part in path.relative_to(root).parts[:-1]):
                continue
            yield path


@lru_cache(maxsize=1)
def _scan_manual_window_shape() -> Tuple[Tuple[str, str], ...]:
    """Каждый файл дерева, где встречаются ОБЕ половины формы «ручное окно с
    подавлением» — независимо от того, заявляет ли файл о себе прозой (в
    отличие от текстовых сторожей выше, этот смотрит на КОД). Кэш на процесс
    теста: файл дерева не меняется между вызовами внутри одного прогона.
    """
    root = _repo_root()
    hits: List[Tuple[str, str]] = []
    for path in sorted(_iter_source_files(root)):
        rel = path.relative_to(root).as_posix()
        if rel == _MECHANISM_FILE:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _LAST_LOG_RE.search(text) and _SUPPRESSED_RE.search(text):
            hits.append((rel, text))
    return tuple(hits)


class TestManualWindowShapeScanIsComputedNotWatched:
    """Замена подхода ``_WATCHED`` (захардкоженный список файлов) на вычисляемый
    скан ФОРМЫ КОДА по всему дереву. Дополняет, а не заменяет два текстовых
    сторожа (см. докстринг модуля) — те смотрят на ЗАЯВЛЕНИЯ, этот на КОД, и не
    требует, чтобы кто-то вообще что-то заявил о найденном экземпляре.
    """

    def test_scanner_is_not_vacuous(self) -> None:
        """Самопроверка механики: скан обязан находить СВОЮ форму хоть где-то —
        иначе регексы могли молча перестать матчить (переименование, рефакторинг
        state-атрибутов), и класс закрывался бы пустым списком по ошибке скана,
        а не по факту отсутствия ручных копий."""
        hits = _scan_manual_window_shape()
        assert hits, (
            "скан формы «ручное окно с подавлением» не нашёл НИ ОДНОГО файла во "
            "всём дереве — подозрительно пусто (известные кандидаты: "
            f"{sorted(_NAMED_EXCEPTIONS)}); вероятно, регексы сломаны, а не находка чиста"
        )

    def test_every_hit_outside_the_mechanism_is_a_named_exception(self) -> None:
        hit_paths = {rel for rel, _ in _scan_manual_window_shape()}

        unnamed = sorted(hit_paths - set(_NAMED_EXCEPTIONS))
        assert unnamed == [], (
            "форма «ручное окно с подавлением» найдена вне механизма и вне "
            f"поимённых исключений: {unnamed} — мигрируйте на windowed_voice ЛИБО "
            "заведите именованное исключение с причиной в _NAMED_EXCEPTIONS"
        )

    def test_named_exceptions_are_still_findable(self) -> None:
        """Пара-контроль: исключение не имеет права протухнуть молча. Если файл
        смигрировали на windowed_voice, запись в ``_NAMED_EXCEPTIONS`` обязана
        быть УДАЛЕНА — этот тест валится, напоминая об этом, вместо того чтобы
        список исключений тихо разошёлся с реальностью.
        """
        hit_paths = {rel for rel, _ in _scan_manual_window_shape()}

        stale = sorted(set(_NAMED_EXCEPTIONS) - hit_paths)
        assert stale == [], (
            f"поимённое исключение больше не находится сканом: {stale} — похоже, "
            "форму убрали (мигрировали на windowed_voice?); удалите запись из "
            "_NAMED_EXCEPTIONS, чтобы список исключений не расходился с реальностью"
        )


class TestScanCatchesTheKnownDataReceiverCopy:
    """Не самопроверка инструмента, а находка ФАКТА: седьмая копия существует в
    дереве прямо сейчас, скан обязан её видеть."""

    def test_data_receiver_is_found_by_the_shape_scan(self) -> None:
        hit_paths = {rel for rel, _ in _scan_manual_window_shape()}

        assert "multiprocess_framework/modules/process_module/generic/data_receiver.py" in hit_paths, (
            "скан не нашёл известную седьмую копию (_lag_log_window/_lag_last_log/"
            "_lag_dropped_since_log в data_receiver.py) — либо копию смигрировали "
            "(тогда обновите _NAMED_EXCEPTIONS), либо регексы сломаны"
        )


class TestScanCatchesTheLogChannelEmergencyCopies:
    """Находка ЭТОГО скана (не была в исходной постановке Н-3, см. докстринг
    модуля) — тоже обязана оставаться видимой, а не потеряться при рефакторинге
    регексов."""

    def test_log_channel_is_found_by_the_shape_scan(self) -> None:
        hit_paths = {rel for rel, _ in _scan_manual_window_shape()}

        assert "multiprocess_framework/modules/logger_module/channels/log_channel.py" in hit_paths, (
            "скан не нашёл emergency-копии в log_channel.py "
            "(_last_warning_ts/_WARNING_INTERVAL_SEC, "
            "_last_rollover_warning_ts/_ROLLOVER_WARNING_INTERVAL_SEC) — либо их "
            "убрали, либо регексы сломаны"
        )


class TestScanDoesNotFlagPeriodicReportersAsManualWindows:
    """Контроль ложноположительных: периодические отчётчики (``latency.py``,
    ``frame_counter``) несут ПОЛОВИНУ формы (``_last_log_time`` + окно), но НЕ
    подавляют повторы и не считают подавленное — публикуют БЕЗУСЛОВНО на тик.
    Другой контракт, не тот, что чинит ``windowed_voice``. Без этого теста
    требование «ОБЕ половины формы» доказано одним удачным совпадением
    (data_receiver.py), а не тем, что скан НАМЕРЕННО их не ловит."""

    def test_latency_tracker_is_not_flagged(self) -> None:
        hit_paths = {rel for rel, _ in _scan_manual_window_shape()}
        assert "multiprocess_framework/modules/chain_module/metrics/latency.py" not in hit_paths

    def test_frame_counter_plugin_is_not_flagged(self) -> None:
        hit_paths = {rel for rel, _ in _scan_manual_window_shape()}
        assert "Plugins/sources/frame_counter/plugin.py" not in hit_paths
