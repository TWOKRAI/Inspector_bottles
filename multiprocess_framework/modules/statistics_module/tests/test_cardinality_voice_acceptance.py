# -*- coding: utf-8 -*-
"""
НЕЗАВИСИМЫЕ приёмочные тесты: голос стража кардинальности на позиции
«окно агрегации» — по критериям приёмки, БЕЗ чтения реализации
(``core/aggregation_window.py``, ``core/cardinality_guard.py`` не открывались).

Контракт взят из публичной поверхности ``StatsManager`` (README.md,
``core/stats_manager.py`` — комментарии владельца о двух независимых стражах,
``interfaces.py``): предел числа различных серий стоит на ДВУХ позициях —
«окно агрегации» (числа живут от сброса до сброса) и «живой слой» (числа за
весь срок процесса). При превышении предела страж обязан подать голос через
логгер-менеджер (WARNING) с числом опущенных серий и их именами.

Голос ловится тем же путём, что и любой ``self._log_warning(...)`` менеджера
(``ObservableMixin._call_manager("logger", "warning", message, **kwargs)``):
менеджеру подаётся mock-логгер через ``managers={"logger": mock_logger}``
конструктора, и голос — это вызов ``mock_logger.warning(text, module=...)``.
Формат текста (реально прозвучавший, разведано отдельным прогоном ДО записи
этих тестов, без чтения guard'а):

    потолок серий метрик (<позиция>) достигнут: <потолок> — новые серии не
    заводятся, опущено серий <N> (<M> эмиссий; первые имена: ...).
    Потолок задаётся ключом observability.stats.max_series (0 — без предела).

где ``<позиция>`` — ``окно агрегации`` либо ``живой слой``.

Числа, взятые для сравнения с сообщением, ВСЕГДА выводятся из сценария
(M − N), а не подсматриваются в другом месте того же кода.
"""

import re
from unittest.mock import MagicMock

from .. import StatsManager
from ...channel_routing_module.interfaces import IChannel

#: "опущено серий <N>" — число ЖИВОЕ, вырезается из текста, а не задаётся литералом.
_SERIES_RE = re.compile(r"опущено серий (\d+)")

_WINDOW_POSITION = "окно агрегации"
_LIVE_POSITION = "живой слой"


class _CapturingChannel(IChannel):
    """Канал-шпион: копит снапшоты окна такими, какими их видит канал (машинная сторона)."""

    def __init__(self, name: str = "capture"):
        self._name = name
        self.received = []

    @property
    def name(self):
        return self._name

    def write(self, data):
        self.received.append(data)
        return {"status": "ok"}

    def close(self):
        pass


def _make_manager(max_series: int, name: str = "CardVoiceTest") -> "tuple[StatsManager, MagicMock]":
    """Менеджер с mock-логгером в слоте 'logger' — туда же уходит и голос WARNING.

    ``aggregation_interval == flush_interval``, чтобы посторонний WARNING про
    «пол темпа» (``_warn_if_floor_raises_tempo``, не по теме кардинальности) не
    засорял список вызовов mock-логгера.
    """
    mock_logger = MagicMock()
    mgr = StatsManager(
        manager_name=name,
        config={
            "enable_logging": False,
            "channels": {},
            "max_series": max_series,
            "aggregation_interval": 1.0,
            "flush_interval": 1.0,
        },
        managers={"logger": mock_logger},
    )
    assert mgr.initialize() is True, "менеджер не инициализировался — сценарий недостоверен"
    return mgr, mock_logger


def _voice_texts(mock_logger: MagicMock, position: str) -> "list[str]":
    """Тексты голосов ОДНОЙ позиции стража ("окно агрегации" / "живой слой")."""
    out = []
    for call in mock_logger.warning.call_args_list:
        if not call.args:
            continue
        text = str(call.args[0])
        if f"({position})" in text:
            out.append(text)
    return out


def _series_number(text: str) -> int:
    """Число из «опущено серий N» — то самое число, что слышит оператор."""
    match = _SERIES_RE.search(text)
    assert match is not None, f"в тексте голоса нет 'опущено серий N': {text!r}"
    return int(match.group(1))


# =============================================================================
# Критерий 1 — число в голосе окна равно машинному числу СНАПШОТА того же окна.
# =============================================================================


class TestVoiceNumberMatchesWindowSnapshot:
    def test_window_voice_number_matches_snapshot_series_dropped(self):
        max_series = 5
        mgr, mock_logger = _make_manager(max_series=max_series)
        capture = _CapturingChannel()
        mgr.register_channel(capture)

        # M − N взято из сценария: эмитируем M различных серий в ОДНО окно,
        # потолок N — превышение ровно 4.
        total_series = max_series + 4
        for i in range(total_series):
            mgr.increment(f"probe.metric_{i}")
        mgr.flush()  # закрываем окно

        expected_dropped = total_series - max_series  # = 4, посчитано из сценария

        assert capture.received, "снапшот окна не дошёл до канала — сценарий недостоверен"
        snapshot = capture.received[0]
        assert snapshot.get("series_dropped") == expected_dropped, (
            f"машинное число снапшота окна разошлось со сценарием: ожидалось "
            f"{expected_dropped} (M={total_series} − N={max_series}), получено "
            f"{snapshot.get('series_dropped')}"
        )

        window_voices = _voice_texts(mock_logger, _WINDOW_POSITION)
        assert window_voices, "страж окна не подал голос при переполнении"
        voice_number = _series_number(window_voices[-1])
        assert voice_number == expected_dropped, (
            f"текст голоса окна называет {voice_number} опущенных серий, а по "
            f"сценарию (и по снапшоту того же окна) их {expected_dropped}: "
            f"{window_voices[-1]!r}"
        )

        mgr.shutdown()


# =============================================================================
# Критерий 2 — имена в голосе окна принадлежат ТЕКУЩЕМУ окну, не прошлому.
# =============================================================================


class TestVoiceNamesBelongToCurrentEpisode:
    """Критерий 2, ИСПРАВЛЕННАЯ формулировка координатора (было противоречие с
    критерием 3 — доказано инъекцией, не рассуждением: "голос каждое окно, имена
    эпизода починены" красит критерий 2 зелёным при красном критерии 3, а
    настоящая починка — наоборот).

    Раз критерий 3 требует ОДИН голос на непрерывный эпизод переполнения, то
    второе подряд переполненное окно обязано молчать (это его голос проверяет
    критерий 3, здесь — не дублируем). Проверять «текущий эпизод, не прошлый»
    нужно поэтому не на соседнем окне, а на ВТОРОМ голосе — том, что звучит
    ПОСЛЕ снятия условия и нового перехода в переполнение.
    """

    def test_last_voice_names_belong_to_the_new_episode_not_the_old_one(self):
        max_series = 3
        mgr, mock_logger = _make_manager(max_series=max_series)

        # эпизод 1: переполняем именами old.* -> первый голос (переход)
        for i in range(max_series + 2):
            mgr.increment(f"old.metric_{i}")
        mgr.flush()

        # условие СНЯТО: ровно по потолку, имена — СВОЙ отдельный неймспейс
        # (не old.*, не new.*), чтобы не путать проверку подстрокой ниже
        for i in range(max_series):
            mgr.increment(f"calm.metric_{i}")
        mgr.flush()

        # эпизод 2: переполняем СОВСЕМ ДРУГИМИ именами new.* -> НОВЫЙ переход,
        # второй голос
        for i in range(max_series + 2):
            mgr.increment(f"new.metric_{i}")
        mgr.flush()

        window_voices = _voice_texts(mock_logger, _WINDOW_POSITION)
        assert len(window_voices) == 2, (
            "по сценарию (переход -> снятие условия -> переход) ожидалось РОВНО "
            f"два голоса окна, получено {len(window_voices)}: {window_voices!r}"
        )
        last_voice = window_voices[-1]  # голос НОВОГО эпизода (new.*)
        assert "new." in last_voice, f"последний голос обязан называть имена ТЕКУЩЕГО эпизода (new.*): {last_voice!r}"
        assert "old." not in last_voice, (
            f"последний голос называет имена СТАРОГО эпизода (old.*) — устаревший эпизод, а не текущий: {last_voice!r}"
        )

        mgr.shutdown()


# =============================================================================
# Критерий 3 — голос на ПЕРЕХОД условия, а не на каждое окно.
# =============================================================================


class TestVoiceFiresOnTransitionNotEveryWindow:
    def test_window_voice_fires_once_per_episode(self):
        max_series = 5
        mgr, mock_logger = _make_manager(max_series=max_series)

        def overflow(prefix: str) -> None:
            for i in range(max_series + 2):
                mgr.increment(f"{prefix}.metric_{i}")
            mgr.flush()

        def calm(prefix: str) -> None:
            # ровно по потолку — переполнения в ЭТОМ окне нет
            for i in range(max_series):
                mgr.increment(f"{prefix}.metric_{i}")
            mgr.flush()

        overflow("a")
        overflow("b")
        overflow("c")

        after_three_windows = len(_voice_texts(mock_logger, _WINDOW_POSITION))
        assert after_three_windows == 1, (
            f"три подряд переполненных окна обязаны дать РОВНО один голос "
            f"(переход в состояние переполнения), получено {after_three_windows}"
        )

        calm("d")  # условие снято: серий ровно по потолку, переполнения нет

        overflow("e")  # переполняем снова -> НОВЫЙ переход -> второй голос

        after_full_scenario = len(_voice_texts(mock_logger, _WINDOW_POSITION))
        assert after_full_scenario == 2, (
            f"весь сценарий (переход в переполнение -> снятие условия -> "
            f"переход снова) обязан дать РОВНО два голоса, получено "
            f"{after_full_scenario}"
        )

        mgr.shutdown()


# =============================================================================
# Критерий 4 (КОНТРОЛЬ) — та же механика на живом слое. Обязан быть зелёным
# И ДО, И ПОСЛЕ починки окна: отличает «сломали окно» от «сломали всё».
# =============================================================================


class TestLiveLayerVoiceControlGroup:
    def test_live_layer_voice_number_correct_and_single_firing(self):
        max_series = 5
        mgr, mock_logger = _make_manager(max_series=max_series)

        # 2 серии сверх потолка, ОДНИМ окном (единственный переход) — так же,
        # как в критерии 1, чтобы момент подачи голоса совпадал с моментом
        # снапшота: живой страж говорит РОВНО на переходе, дальнейшие отказы
        # внутри того же «уже превышено» состояния голос не повторяют (это и
        # есть верная транзитная семантика — критерий 3 требует её для окна).
        total_series = max_series + 2
        for i in range(total_series):
            mgr.increment(f"live.metric_{i}")
        mgr.flush()  # закрываем окно — здесь и должен прозвучать единственный голос

        live_voices = _voice_texts(mock_logger, _LIVE_POSITION)
        assert len(live_voices) == 1, (
            f"контроль: живой слой обязан подать РОВНО один голос за непрерывное "
            f"переполнение (несколько окон подряд, условие не снималось), "
            f"получено {len(live_voices)}"
        )

        expected_dropped = total_series - max_series  # = 2, из сценария
        voice_number = _series_number(live_voices[-1])
        assert voice_number == expected_dropped, (
            f"контроль: число в голосе живого слоя должно быть {expected_dropped} "
            f"по сценарию, получено {voice_number}: {live_voices[-1]!r}"
        )

        stats = mgr.get_stats()
        assert stats["series_dropped"] == expected_dropped, (
            f"контроль: машинное число живого слоя (get_stats) разошлось со "
            f"сценарием: ожидалось {expected_dropped}, получено "
            f"{stats['series_dropped']}"
        )

        mgr.shutdown()


# =============================================================================
# Критерий 5 — машинные числа не поехали: окно за окно, живой слой за срок.
# =============================================================================


class TestMachineNumbersKeepTheirScope:
    def test_window_dropped_count_resets_while_live_accumulates(self):
        max_series = 4
        mgr, mock_logger = _make_manager(max_series=max_series)
        capture = _CapturingChannel()
        mgr.register_channel(capture)

        # окно 1: N+2 НОВЫХ серий -> 2 отказа
        for i in range(max_series + 2):
            mgr.increment(f"r1.metric_{i}")
        mgr.flush()
        snapshot_1 = capture.received[-1]
        live_dropped_after_1 = mgr.get_stats()["series_dropped"]

        # окно 2: ещё N+2 НОВЫХ (других) серий -> в СВОЁМ окне тоже 2 отказа,
        # а НЕ 4 (сумма с окном 1) — окно обязано сбрасываться со сбросом.
        for i in range(max_series + 2):
            mgr.increment(f"r2.metric_{i}")
        mgr.flush()
        snapshot_2 = capture.received[-1]
        live_dropped_after_2 = mgr.get_stats()["series_dropped"]

        assert snapshot_1.get("series_dropped") == 2, (
            f"окно 1: ожидалось 2 отказа по сценарию, получено {snapshot_1.get('series_dropped')}"
        )
        assert snapshot_2.get("series_dropped") == 2, (
            f"число отказов ОКНА 2 не должно включать отказы ОКНА 1 (сбрасывается "
            f"со сбросом окна): ожидалось 2, получено {snapshot_2.get('series_dropped')}"
        )

        # живой слой копится за срок процесса — окно 2 добавляет к тому, что уже
        # накопило окно 1, а не начинает с нуля.
        assert live_dropped_after_2 > live_dropped_after_1, (
            f"живой слой обязан накапливать отказы за срок процесса, а не "
            f"сбрасываться вместе с окном: было {live_dropped_after_1}, стало "
            f"{live_dropped_after_2}"
        )

        mgr.shutdown()
