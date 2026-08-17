# -*- coding: utf-8 -*-
"""Голос стража кардинальности — АВТОРСКИЕ тесты опасностей механизма.

Приёмку по критериям пишет независимый тестер
(``test_cardinality_voice_acceptance.py``); здесь — то, что видно только
автору правки: швы, порядок вызовов, реентерабельность и границы такта.

**Что чинилось и почему опасности именно эти.** У позиции ОКНА потребителей
периодных чисел два — машинный снапшот и голос оператору, — и оба читали одно
мутабельное состояние стража с разной семантикой сброса:
``AggregationWindow._build_snapshot`` под локом забирал ``take_report()``
(он чистит множество отказанных ключей и имена эпизода), а ``speak`` следом
строил текст из ``len()`` уже обнулённого множества. Голос окна ВСЕГДА говорил
«опущено серий 0», имена брал из недренируемого ``_names_total`` (в окне №3 —
серии окна №1), и звучал каждое окно, потому что удавшийся ``allow`` после
чистки окна снимал признак упора. Правка сделала отчёт АРГУМЕНТОМ ``speak``, а
границей условия — такт без единого отказа.

Отсюда и список опасностей: всё, что раньше держалось на порядке двух вызовов,
теперь обязано держаться конструкцией — и это надо проверять, а не заявлять.

**Числа взяты вдали от дефолта 1000** и от ``VOICE_NAME_LIMIT`` (5), чтобы
совпадение не могло пройти за верный ответ.
"""

import re
import threading
import time
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.statistics_module.core.aggregation_window import AggregationWindow
from multiprocess_framework.modules.statistics_module.core.cardinality_guard import (
    MAX_SERIES_KNOB,
    CardinalityGuard,
)
from multiprocess_framework.modules.statistics_module.core.stats_manager import StatsManager

#: Число из «опущено серий N» вырезается из живого текста, а не сверяется с
#: литералом, написанным рядом со вторым написанием того же числа.
_SERIES_RE = re.compile(r"опущено серий (?:не меньше чем )?(\d+)")
_EMISSIONS_RE = re.compile(r"\((\d+) эмиссий")


def _series_in(text: str) -> int:
    match = _SERIES_RE.search(text)
    assert match is not None, f"в голосе нет 'опущено серий N': {text!r}"
    return int(match.group(1))


def _emissions_in(text: str) -> int:
    match = _EMISSIONS_RE.search(text)
    assert match is not None, f"в голосе нет '(M эмиссий': {text!r}"
    return int(match.group(1))


def _run_with_deadline(fn, timeout=10.0):
    """``fn()`` в потоке-демоне с дедлайном.

    Правило проекта: тест, который может ЗАВИСНУТЬ, обязан падать по таймауту.
    Зависший тест хуже отсутствующего — он прячет регрессию за ожиданием.
    """
    box = {}

    def _target():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробрасываем в основной поток
            box["error"] = exc

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout)
    assert not t.is_alive(), f"тест завис дольше {timeout}s — это красный, а не таймаут окружения"
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _guard(limit, warn=None):
    """Страж на позиции ОКНА — собран ТАК ЖЕ, как его собирает ``StatsManager``.

    Через помощник, а не руками в каждом тесте: пока сборка была расписана по
    двенадцати местам, правка конструктора разъехалась с боевой проводкой, и
    тесты проверяли конфигурацию, которой в бою не существует.
    """
    return CardinalityGuard(limit, position="окно агрегации", warn=warn)


def _window(guard, sent):
    return AggregationWindow(flush_fn=lambda ch, batch: sent.append(batch[0]) or len(batch), guard=guard)


def _stats_manager(name: str, max_series: int, flush_interval: float = 1.0):
    """Боевой вход менеджера с mock-логгером в слоте 'logger' — туда уходит голос."""
    mock_logger = MagicMock()
    mgr = StatsManager(
        manager_name=name,
        config={
            "enable_logging": False,
            "channels": {},
            "max_series": max_series,
            "aggregation_interval": flush_interval,
            "flush_interval": flush_interval,
        },
        managers={"logger": mock_logger},
    )
    assert mgr.initialize() is True, "менеджер не поднялся — сценарий недостоверен"
    return mgr, mock_logger


def _voices(mock_logger: MagicMock, position: str) -> "list[str]":
    """Тексты голосов ОДНОЙ позиции стража."""
    return [str(c.args[0]) for c in mock_logger.warning.call_args_list if c.args and f"({position})" in str(c.args[0])]


# =============================================================================
# Шов «отчёт → голос»: то, что раньше держалось на порядке двух вызовов
# =============================================================================


class TestReportIsTheOnlySourceOfTheVoice:
    """Голос обязан назвать числа ПЕРЕДАННОГО отчёта, а не текущего состояния."""

    def test_refusals_arriving_after_the_close_do_not_leak_into_this_voice(self) -> None:
        """Отказы, пришедшие ПОСЛЕ забора отчёта, в этот голос не попадают.

        Это ровно тот шов, который был сломан, только вывернутый наизнанку.
        ``take_report`` идёт под локом окна, ``speak`` — вне его; между ними
        чужой поток успевает эмитить, и раньше голос читал состояние стража
        В МОМЕНТ ПРОИЗНЕСЕНИЯ. Сейчас единственный источник — аргумент, и
        никакая эмиссия в щели на него не влияет. Проверяется без потоков:
        щель воспроизводится порядком вызовов, а не таймингом (тест на
        тайминге был бы флейком, доказывающим планировщик).
        """
        said = []
        guard = _guard(3, warn=said.append)
        known = {"a": 1, "b": 2, "c": 3}
        for i in range(2):
            guard.allow(f"early{i}", known, f"early{i}")

        report = guard.take_report()  # закрытие окна забрало периодные числа

        for i in range(7):  # чужой поток эмитит в щели между закрытием и голосом
            guard.allow(f"late{i}", known, f"late{i}")

        guard.speak(report)

        assert len(said) == 1
        assert _series_in(said[0]) == report["series"] == 2, (
            f"голос обязан нести числа СВОЕГО закрытия (2), а не набежавшие 7+: {said[0]!r}"
        )
        assert _emissions_in(said[0]) == report["observations"] == 2
        assert "late" not in said[0], "имена, пришедшие после закрытия, — не этого эпизода"

    def test_voice_number_equals_the_snapshot_number_of_the_same_window(self) -> None:
        """Число голоса == ``series_dropped`` снапшота ТОГО ЖЕ закрытия, окно за окном.

        Свойство проверяется на ТРЁХ закрытиях подряд с разным превышением:
        одно совпадение можно получить и случайно (например, если оба числа —
        ноль), три с разными значениями — уже нет. Голос при этом звучит один
        (условие не снималось), поэтому сверяется он с тем окном, в котором
        прозвучал.

        Превышения держатся НИЖЕ ``max(потолок, K=5)``: выше него множество
        различных ключей насыщается по построению, и число законно становится
        оценкой снизу — это отдельное свойство и проверяется отдельно.
        """
        sent = []
        said = []
        guard = _guard(6, warn=said.append)
        window = _window(guard, sent)

        for round_no, extra in enumerate((3, 5, 2)):
            for i in range(6 + extra):
                window.enqueue("c", {"type": "counter", "name": f"r{round_no}.m{i}", "value": 1})
            window.flush_all()

        assert [s["series_dropped"] for s in sent] == [3, 5, 2], sent
        assert all("series_dropped_is_lower_bound" not in s for s in sent), "числа обязаны быть точными"
        assert len(said) == 1, "условие не снималось — голос обязан быть один"
        assert _series_in(said[0]) == sent[0]["series_dropped"] == 3

    def test_saturated_set_speaks_a_lower_bound_and_still_matches_the_snapshot(self) -> None:
        """Насыщение множества ключей: «не меньше чем N» — и N тот же, что в снапшоте.

        Признак ``series_is_lower_bound`` — штатный механизм (заниженное число,
        выданное как точное, хуже честной оценки). Он едет в отчёте, а значит
        обязан доехать и до голоса: раньше голос читал его из своего состояния
        и рассогласоваться со снапшотом мог молча.
        """
        sent = []
        said = []
        guard = _guard(2, warn=said.append)
        window = _window(guard, sent)
        for i in range(17):
            window.enqueue("c", {"type": "counter", "name": f"sat{i}", "value": 1})
        window.flush_all()

        snapshot = sent[0]
        assert snapshot["series_dropped_is_lower_bound"] is True
        assert "не меньше чем" in said[0], "оценка снизу обязана называться оценкой и вслух"
        assert _series_in(said[0]) == snapshot["series_dropped"]
        assert snapshot["series_dropped"] >= len(snapshot["dropped_series"])


# =============================================================================
# Граница такта: когда условие считается снятым
# =============================================================================


class TestTickBoundaryOwnsTheCondition:
    def test_names_of_a_new_episode_do_not_carry_the_old_ones(self) -> None:
        """Имена нового эпизода — только свои (исправленная форма критерия 2).

        Проверить «имена не протекают» можно ТОЛЬКО там, где звучит второй
        голос, то есть после снятия условия. Два переполненных окна подряд
        второго голоса не дают вовсе — это требование «раз на условие», и
        сверять в таком сценарии «последний голос» не с чем.
        """
        sent = []
        said = []
        guard = _guard(3, warn=said.append)
        window = _window(guard, sent)

        for i in range(5):  # эпизод 1 — имена old.*
            window.enqueue("c", {"type": "counter", "name": f"old.m{i}", "value": 1})
        window.flush_all()

        for i in range(3):  # тихое окно ровно по потолку — условие снято
            window.enqueue("c", {"type": "counter", "name": f"calm.m{i}", "value": 1})
        window.flush_all()

        for i in range(5):  # эпизод 2 — имена new.*
            window.enqueue("c", {"type": "counter", "name": f"new.m{i}", "value": 1})
        window.flush_all()

        assert len(said) == 2, "снятие условия и новое переполнение обязаны дать второй голос"
        assert "old." in said[0] and "new." not in said[0]
        assert "new." in said[1], f"второй голос обязан называть свой эпизод: {said[1]!r}"
        assert "old." not in said[1], f"имена эпизода 1 протекли в голос эпизода 2: {said[1]!r}"

    def test_an_empty_window_proves_nothing_and_does_not_lift(self) -> None:
        """ПУСТОЕ окно условия НЕ снимает — никто не пробовал завести серию.

        **Прежняя редакция этого теста утверждала обратное**, и через неё
        прошёл M-2: если пустой сброс засчитывать за наблюдение, то право на
        голос возвращает любой сброс, тихий по построению, — базовый
        ``reconfigure`` осушает буфер, следом ``stop()`` сливает остаток, и
        два WARNING уходят на одно неизменное условие. Отсутствие отказов — не
        доказательство; доказательство — трафик БЕЗ отказов.
        """
        sent = []
        said = []
        guard = _guard(2, warn=said.append)
        window = _window(guard, sent)

        for i in range(4):
            window.enqueue("c", {"type": "counter", "name": f"x{i}", "value": 1})
        window.flush_all()
        assert len(said) == 1

        for _ in range(3):
            window.flush_all()  # пустые сбросы подряд — ровно форма M-2
        assert len(sent) == 1, "пустой снапшот не имеет права поехать"

        for i in range(4):
            window.enqueue("c", {"type": "counter", "name": f"y{i}", "value": 1})
        window.flush_all()
        assert len(said) == 1, f"пустые сбросы вернули право на голос — то же условие прозвучало дважды: {said}"

    def test_the_voice_does_not_depend_on_delivery(self) -> None:
        """Мёртвый сток не отменяет предупреждение.

        Замена прежней проверки «голос звучит ДО подавления пустого снапшота»:
        после починки M-2 пустое окно долга нести не может (отказ бывает только
        при полном словаре), и та формулировка стала непроверяемой по
        построению. Проверяемая часть свойства осталась и важнее: голос живёт
        ДО ``_call_flush_fn``, поэтому сток, который швыряется исключением и не
        принимает ничего, предупреждение оператору не съедает.
        """
        said = []

        def dead_sink(channel, batch):
            raise RuntimeError("сток мёртв")

        guard = _guard(2, warn=said.append)
        window = AggregationWindow(flush_fn=dead_sink, guard=guard)
        for i in range(5):
            window.enqueue("c", {"type": "counter", "name": f"z{i}", "value": 1})
        window.flush_all()

        assert len(said) == 1, "мёртвый сток съел голос про потолок"
        assert window.stats["flush_failed"] == 1, "потеря обязана быть видна числом — сценарий достоверен"

    def test_ten_overflowing_windows_in_a_row_speak_once(self) -> None:
        """Десять переполненных окон подряд — один голос, а не десять.

        Число взято с запасом над тремя окнами приёмки: механизм «раз на
        условие» обязан держать не только сценарий теста. Живая цена ошибки —
        8 процессов × окно 10 с ≈ 48 WARNING/мин на одном условии.
        """
        sent = []
        said = []
        guard = _guard(6, warn=said.append)
        window = _window(guard, sent)
        for w in range(10):
            for i in range(9):
                window.enqueue("c", {"type": "counter", "name": f"w{w}.m{i}", "value": 1})
            window.flush_all()

        assert len(sent) == 10, "все десять окон закрылись — сценарий достоверен"
        assert all(s["series_dropped"] == 3 for s in sent), sent
        assert len(said) == 1, f"условие одно — голос обязан быть один, прозвучало {len(said)}"

    def test_a_successful_allow_alone_does_not_lift_the_condition(self) -> None:
        """Удавшийся ``allow`` сам по себе условия НЕ снимает — снимает такт.

        Это корень третьего лица дефекта, в чистом виде и без окна: сброс окна
        освобождает место, первая серия проходит, и если признак упора снять
        прямо здесь, то следующее переполнение прочитается как новый переход.
        Между двумя переполнениями тут нет ни одного ``speak`` — значит и
        второго голоса быть не должно.
        """
        said = []
        guard = _guard(2, warn=said.append)
        known = {"a": 1, "b": 2}
        guard.allow("over1", known, "over1")  # упёрлись
        guard.speak(guard.take_report())
        assert len(said) == 1

        known.clear()  # «окно почистилось»
        assert guard.allow("fresh", known, "fresh") is True
        known["fresh"] = 1
        known["second"] = 1
        guard.allow("over2", known, "over2")  # то же условие, нового такта не было
        guard.speak(guard.take_report())
        assert len(said) == 1, f"тот же упор прозвучал дважды без границы такта: {said}"


# =============================================================================
# Ручка на лету, «без предела» и реентерабельность
# =============================================================================


class TestKnobAndReentrancy:
    def test_raising_the_limit_mid_episode_returns_the_voice_with_the_new_number(self) -> None:
        """``set_limit`` в середине эпизода — новый голос, и потолок в нём НОВЫЙ.

        Смена потолка — смена условия, право на голос возвращается сразу (не
        дожидаясь тихого такта): оператор, поднявший потолок и снова упёршийся,
        обязан услышать об этом. И услышать он обязан ДЕЙСТВУЮЩИЙ потолок —
        текст с прежним числом отправил бы его крутить уже покрученную ручку.
        """
        sent = []
        said = []
        guard = _guard(3, warn=said.append)
        window = _window(guard, sent)
        for i in range(5):
            window.enqueue("c", {"type": "counter", "name": f"p{i}", "value": 1})
        window.flush_all()
        assert len(said) == 1 and "достигнут: 3" in said[0]

        guard.set_limit(7)  # ручка поднята прямо в эпизоде
        for i in range(11):
            window.enqueue("c", {"type": "counter", "name": f"q{i}", "value": 1})
        window.flush_all()

        assert len(said) == 2, "поднятый и снова достигнутый потолок обязан прозвучать заново"
        assert "достигнут: 7" in said[1], f"голос называет прежний потолок: {said[1]!r}"
        assert _series_in(said[1]) == sent[1]["series_dropped"] == 4

    def test_no_limit_never_speaks_however_many_ticks_pass(self) -> None:
        """``max_series=0`` — без предела: ни отказов, ни голоса, сколько ни закрывай такт.

        Тик без отказов теперь ещё и СНИМАЕТ признак упора; на «без предела»
        это не должно превратиться в мигание. Проверяется многими тактами, а не
        одним: одиночный такт молчал бы и у сломанной версии.
        """
        sent = []
        said = []
        guard = _guard(0, warn=said.append)
        window = _window(guard, sent)
        for w in range(5):
            for i in range(40):
                window.enqueue("c", {"type": "counter", "name": f"free{w}.{i}", "value": 1})
            window.flush_all()

        assert said == [], f"страж без предела заговорил: {said}"
        assert all("series_dropped" not in s for s in sent)
        assert guard.report()["series"] == 0

    def test_a_warn_callback_that_re_enters_the_guard_does_not_deadlock(self) -> None:
        """Логгер, эмитящий метрику из-под голоса, не вешает страж.

        ``self._lock`` — обычный ``threading.Lock``, не реентерабельный, а
        ``warn`` уходит в ``LoggerManager`` с его каналами и tap'ами. Сегодня
        ни один tap метрик не эмитит — но tap, который начнёт, замкнёт цепочку
        ``speak → warning → record_metric → allow → тот же лок``. Шов держится
        тем, что текст собран под локом, а ``warn`` вызван вне его; проверяем
        именно это, с дедлайном — зависание обязано быть красным, а не
        таймаутом окружения.
        """
        said = []
        guard = _guard(2, warn=None)
        known = {"a": 1, "b": 2}

        def reentrant_warn(text: str) -> None:
            said.append(text)
            guard.allow("from_the_tap", known, "from_the_tap")  # tap эмитит метрику
            guard.report()  # и диагностика читает страж из-под голоса

        guard._warn = reentrant_warn
        guard.allow("over", known, "over")
        _run_with_deadline(lambda: guard.speak(guard.take_report()), timeout=5.0)

        assert len(said) == 1
        assert MAX_SERIES_KNOB in said[0]

    def test_a_second_closing_without_new_refusals_is_silent(self) -> None:
        """Второе закрытие без новых отказов — тишина, а не эхо.

        **Формулировка изменена вместе с контрактом, и это надо знать.** Раньше
        тест гонял ОДИН отчёт через ``speak`` трижды и требовал один голос:
        долг снимался в ``speak``. После починки M-3 долг забирается вместе с
        числами в ``take_report``, то есть отчёт стал ОДНОРАЗОВЫМ ТАЛОНОМ —
        произнести один и тот же талон дважды теперь и значит «произнести
        дважды». В бою так не бывает: каждая дорога сброса (``flush_all`` и
        ``_flush_channel``) берёт СВОЙ отчёт своим закрытием. Проверяем то,
        что действительно несущее и что бывает в бою: два закрытия подряд, долг
        только у первого.
        """
        said = []
        guard = _guard(2, warn=said.append)
        known = {"a": 1, "b": 2}
        guard.allow("over", known, "over")

        guard.speak(guard.take_report())
        guard.speak(guard.take_report())
        guard.speak(guard.take_report())
        assert len(said) == 1, f"эхо: тот же упор прозвучал {len(said)} раз(а): {said}"


# =============================================================================
# Гонка: эмиссия из чужих потоков поперёк закрытий окна
# =============================================================================


class TestConcurrentEmissionDuringClose:
    def test_voices_never_outnumber_the_closings_and_carry_a_number_of_some_closing(self) -> None:
        """Под чужими потоками голос не отрывается от закрытия окна.

        Лок окна закрывает гонку данных; здесь опасна ПРИВЯЗКА: отчёт
        забирается под локом, голос звучит вне его, и эмиссии в щели не имеют
        права ни оторвать голос от такта окна, ни дать ему число, которого не
        было ни в одном закрытии.

        **Что этот тест НЕ доказывает — и почему так и оставлено.** Он не
        сторожит «раз на условие»: под потоками число голосов зависит от того,
        попал ли на какое-то закрытие ноль отказов (тихий такт законно снимает
        условие), а это решает планировщик. Прошлая редакция стояла на пороге
        `len(said) <= 2` и падала 1 прогон из 5 на почти свободной машине —
        классический тест, меряющий ОС. Порог убран, а не подкручен:
        «раз на условие» доказывают детерминированные соседи
        (``test_ten_overflowing_windows_in_a_row_speak_once`` и
        ``test_a_successful_allow_alone_does_not_lift_the_condition``).

        Честная цена: под инъекцией полного отката механизма этот тест
        ЗЕЛЁНЫЙ — там голос звучит на каждое закрытие, то есть ровно
        ``len(sent)`` раз, и границы «не больше закрытий» не переходит.
        Пустым он от этого не стал, и это проверено, а не заявлено — у каждого
        из двух оставшихся свойств есть свой красный:

        * «голос не отрывается от такта» — инъекция «голос на каждую эмиссию
          плюс долг не снимается»: **10 421 голос на 13 закрытий**;
        * «число голоса — число какого-то закрытия» — инъекция «голос на
          каждую эмиссию»: голос произносится в МОМЕНТ первого отказа и
          называет ``1``, которого нет ни в одном закрытии (там ``{0, 5}``).
          Это дословно та самая «числа первой секунды», ради которой долг и
          копится до такта окна.
        """
        sent = []
        said = []
        emitted = [0]
        counted = threading.Lock()
        guard = _guard(5, warn=said.append)
        window = AggregationWindow(flush_fn=lambda ch, batch: sent.append(batch[0]) or len(batch), guard=guard)
        stop = threading.Event()

        def writer(tag: str) -> None:
            i = 0
            while not stop.is_set():
                window.enqueue("c", {"type": "counter", "name": f"{tag}.{i}", "value": 1})
                i += 1
                with counted:
                    emitted[0] += 1

        def wait_for_emissions(target: int) -> None:
            """Ждать РЕАЛЬНЫХ эмиссий, а не «немножко времени».

            Без этого сценарий недостоверен по-тихому: двенадцать ``flush_all``
            в тесном цикле успевают пройти раньше, чем планировщик вообще даст
            писателям ход, — и тест мерил бы пустые закрытия, ничего не проверяя.
            """
            end = time.monotonic() + 10.0
            while time.monotonic() < end:
                with counted:
                    if emitted[0] >= target:
                        return
            raise AssertionError(f"писатели не дали {target} эмиссий за 10 с — сценарий недостоверен")

        threads = [threading.Thread(target=writer, args=(f"t{n}",), daemon=True) for n in range(4)]

        def _drive():
            for t in threads:
                t.start()
            for _ in range(12):
                with counted:
                    base = emitted[0]
                # 60 НОВЫХ серий при потолке 5 — переполнение каждого закрытия
                # гарантировано счётом, а не расчётом на скорость машины.
                wait_for_emissions(base + 60)
                window.flush_all()
            stop.set()
            for t in threads:
                t.join(timeout=5.0)
            window.flush_all(include_empty=True)

        _run_with_deadline(_drive, timeout=60.0)

        assert len(sent) == 13, f"ожидалось 12 закрытий под нагрузкой + финальное, получено {len(sent)}"
        assert all(s.get("series_dropped", 0) > 0 for s in sent[:12]), (
            "потолок 5 отказал не в каждом закрытии — сценарий недостоверен"
        )
        assert said, "под непрерывным переполнением страж не сказал ничего"

        # Числовых порогов на КОЛИЧЕСТВО голосов здесь нет сознательно.
        # Прошлая редакция стояла на `len(said) <= 2` и падала 1 прогон из 5:
        # тихий такт (закрытие, на которое не попало ни одного отказа) даёт
        # ЗАКОННЫЙ второй голос, и сколько их будет — решает планировщик, а не
        # механизм. Тест мерил ОС. Гарантию «раз на условие» несут
        # детерминированные соседи (десять переполненных окон = один голос);
        # здесь остаются ровно два свойства, от планировщика не зависящие.
        assert len(said) <= len(sent), (
            f"голосов {len(said)} больше, чем закрытий ({len(sent)}) — голос сорвался с такта окна"
        )
        numbers = {s.get("series_dropped", 0) for s in sent}
        for text in said:
            assert _series_in(text) in numbers, (
                f"голос назвал число {_series_in(text)}, которого нет ни в одном снапшоте: {sorted(numbers)}"
            )


# =============================================================================
# Граница условия РАЗНАЯ у двух позиций — регрессия, внесённая первой редакцией
# =============================================================================


class TestTheLiftBoundaryDiffersByPosition:
    """Условие снимает ДОКАЗАТЕЛЬСТВО, а не отсутствие новостей.

    **Это регрессия первой редакции правки, найденная ревью.** Я снимал
    признак упора на любом такте без отказов, не заметив, что «отказов не
    было» и «место освободилось» — разные утверждения. У живого слоя
    справочник не чистится вовсе (шапка самого стража, п. 2), поэтому тихий
    такт там значит лишь «не пришло нового ключа»: 1 голос за срок процесса
    превратился в 6 при потолке, который не отпускал ни разу. Прежний страж
    держал это свойство СЛУЧАЙНО — владелец зовёт ``allow`` только при
    отсутствии ключа, а при полном словаре тот не мог удаться.

    Снимает условие теперь только доказательство: такт, в котором серии
    ЗАВОДИЛИСЬ и ни одна не отказана, либо явное освобождение места.
    """

    def test_a_tick_without_new_keys_does_not_lift_the_condition_on_the_live_layer(self) -> None:
        """Чередование «такт без новых серий / такт с отказом» — один голос, не шесть.

        Живой слой заполнен 4 из 4 всё время: условие не отпускает ни разу, и
        оператор обязан услышать об этом РОВНО один раз. Три пары тактов —
        чтобы отличить «раз на условие» от «раз на пару».
        """
        mgr, mock_logger = _stats_manager("LiveQuietTick", max_series=4)
        try:
            for i in range(4):  # живой слой заполнен под потолок
                mgr.increment(f"known{i}")
            mgr.flush()

            for round_no in range(3):
                mgr.increment("known0")  # такт БЕЗ новых ключей — отказа нет
                mgr.flush()
                mgr.increment(f"newcomer{round_no}")  # такт с отказом
                mgr.flush()

            assert mgr.get_metric("newcomer0") is None, "живой слой обязан быть полон — сценарий недостоверен"
            assert mgr.get_stats()["series_dropped"] == 3, mgr.get_stats()["series_dropped"]

            voices = _voices(mock_logger, "живой слой")
            assert len(voices) == 1, (
                f"живой слой не освобождался ни разу — голос обязан быть один, прозвучало {len(voices)}"
            )
        finally:
            mgr.shutdown()

    def test_a_tick_that_worked_without_refusing_still_lifts(self) -> None:
        """Контроль к предыдущему: такт С ТРАФИКОМ и без отказов условие снимает.

        Без этой пары починка M-1 свелась бы к «не снимать никогда», а тогда
        вернулся бы первый дефект наизнанку — голос, который после
        единственного переполнения молчит до конца смены.
        """
        said = []
        sent = []
        guard = _guard(3, warn=said.append)
        window = _window(guard, sent)
        for i in range(5):
            window.enqueue("c", {"type": "counter", "name": f"a{i}", "value": 1})
        window.flush_all()
        for i in range(3):  # тихое окно ровно по потолку
            window.enqueue("c", {"type": "counter", "name": f"calm{i}", "value": 1})
        window.flush_all()
        for i in range(5):
            window.enqueue("c", {"type": "counter", "name": f"b{i}", "value": 1})
        window.flush_all()
        assert len(said) == 2, f"окно обязано заговорить снова после тихого такта, голосов {len(said)}"

    def test_freeing_the_live_layer_returns_the_voice(self) -> None:
        """``reset_metrics`` — событие, реально освобождающее место: голос возвращается.

        Обратная сторона M-1, и без неё починка была бы хуже болезни: страж,
        у которого условие не снимает НИЧЕГО, замолчал бы навсегда после
        первого переполнения. Право на голос возвращает не такт, а событие.
        """
        mgr, mock_logger = _stats_manager("LiveReset", max_series=3)
        try:
            for i in range(3):
                mgr.increment(f"k{i}")
            mgr.increment("over1")
            mgr.flush()
            assert len(_voices(mock_logger, "живой слой")) == 1

            mgr.reset_metrics()  # место реально освободилось
            for i in range(3):
                mgr.increment(f"n{i}")
            mgr.increment("over2")
            mgr.flush()
            assert len(_voices(mock_logger, "живой слой")) == 2, (
                "после освобождения справочника новое переполнение обязано прозвучать"
            )
        finally:
            mgr.shutdown()

    def test_a_tempo_reload_does_not_hand_back_the_right_to_speak(self) -> None:
        """Смена ТЕМПА не возвращает голос: финальный сброс старого окна — не такт.

        ``_swap_aggregation_window`` → ``old.stop()`` → ``flush_all(include_empty=True)``.
        Этот сброс идёт сразу за уже осушённым буфером, поэтому такт тихий ПО
        ПОСТРОЕНИЮ, а не потому что условие отпустило. Потолок при этом не
        менялся — значит и условие то же, и второго голоса быть не должно.
        """
        mgr, mock_logger = _stats_manager("TempoReload", max_series=3, flush_interval=1.0)
        try:
            for i in range(5):
                mgr.increment(f"p{i}")
            mgr.flush()
            assert len(_voices(mock_logger, "окно агрегации")) == 1

            assert (
                mgr.reconfigure(
                    {
                        "enable_logging": False,
                        "channels": {},
                        "max_series": 3,
                        "aggregation_interval": 2.0,
                        "flush_interval": 2.0,
                    }
                )
                is True
            )
            assert mgr.observability_readback()["max_series"] == 3, "потолок обязан остаться прежним"

            for i in range(5):
                mgr.increment(f"q{i}")
            mgr.flush()
            assert len(_voices(mock_logger, "окно агрегации")) == 1, (
                "смена темпа при том же потолке вернула право на голос — условие то же"
            )
        finally:
            mgr.shutdown()


# =============================================================================
# Долг — свойство МОМЕНТА ЗАБОРА отчёта, а не момента произнесения
# =============================================================================


class TestTheDebtIsCapturedWithTheReport:
    def test_a_debt_born_after_the_capture_is_not_spoken_with_the_old_report(self) -> None:
        """Отказ ПОСЛЕ забора отчёта не произносится нулём этого отчёта.

        **Дыра в моём же заявлении «порядок нарушить больше нечем».** Отчёт
        стал аргументом, но право голоса ``speak`` до сих пор читал живым — и
        долг, родившийся между забором и произнесением, выдавал ровно тот
        ноль, ради которого правка делалась: «опущено серий 0 (0 эмиссий)»
        при ``{'series': 1, 'observations': 1}`` у стража. Через окно сегодня
        недостижимо (владелец чистит словарь под тем же локом), но защищала
        это чужая дисциплина, а не конструкция. Долг забирается вместе с
        числами — тогда голос и право на него приходят из одного снимка.
        """
        said = []
        guard = _guard(2, warn=said.append)
        known = {"a": 1, "b": 2}

        report = guard.take_report()  # закрытие тихого окна: долга нет
        assert report["series"] == 0

        guard.allow("late", known, "late")  # отказ родился ПОСЛЕ забора
        guard.speak(report)

        assert said == [], f"произнесён нулевой голос по отчёту, в котором долга не было: {said}"
        assert guard.report()["series"] == 1, "сам отказ при этом обязан быть учтён"

    def test_the_debt_captured_with_the_report_is_spoken_even_if_a_later_tick_is_quiet(self) -> None:
        """Обратная сторона: забранный вместе с отчётом долг не теряется.

        Снимок долга не имеет права стать способом ПРОГЛОТИТЬ предупреждение —
        иначе починка M-3 обменяла бы ложный ноль на тишину, что хуже.
        """
        said = []
        guard = _guard(2, warn=said.append)
        known = {"a": 1, "b": 2}
        guard.allow("over", known, "over")
        report = guard.take_report()
        assert report["series"] == 1
        guard.speak(report)
        assert len(said) == 1, "долг, существовавший на момент забора, обязан прозвучать"
        assert _series_in(said[0]) == 1

    def test_lifting_the_limit_to_unlimited_swallows_a_pending_voice(self) -> None:
        """``max_series=0`` — «без предела»: недосказанный долг снимается, а не врёт.

        Текст читает ДЕЙСТВУЮЩИЙ потолок, поэтому долг, взятый при потолке 3 и
        произнесённый после ``set_limit(0)``, давал строку, противоречащую
        самой себе: «достигнут: 0 — новые серии не заводятся … (0 — без
        предела)». Предела больше нет — говорить не о чем.
        """
        said = []
        guard = CardinalityGuard(3, position="живой слой", warn=said.append)
        known = {"a": 1, "b": 2, "c": 3}
        guard.allow("over", known, "over")
        guard.set_limit(0)
        guard.speak()
        assert said == [], f"страж без предела произнёс самопротиворечивый голос: {said}"
        assert guard.limit == 0


# =============================================================================
# Живой слой — контроль: у него ПЕРИОДА нет, и он не должен его получить
# =============================================================================


class TestLiveLayerKeepsLifetimeSemantics:
    def test_live_voice_and_stats_accumulate_while_the_window_resets(self) -> None:
        """Позиция живого слоя считает за СРОК, позиция окна — за окно.

        Правка сделала отчёт аргументом голоса; соблазн передать его и живому
        слою есть, а цена ошибки — молчаливая подмена периода. Здесь обе
        позиции проверяются одним сценарием: расхождение чисел и есть предмет.
        """
        mock_logger = MagicMock()
        mgr = StatsManager(
            manager_name="LiveLayerControl",
            config={
                "enable_logging": False,
                "channels": {},
                "max_series": 4,
                "aggregation_interval": 1.0,
                "flush_interval": 1.0,
            },
            managers={"logger": mock_logger},
        )
        assert mgr.initialize() is True

        try:
            for i in range(6):  # окно 1: 4 прошли, 2 отказано
                mgr.increment(f"a.m{i}")
            mgr.flush()
            live_after_1 = mgr.get_stats()["series_dropped"]

            for i in range(7):  # окно 2: свои 3 отказа
                mgr.increment(f"b.m{i}")
            mgr.flush()
            live_after_2 = mgr.get_stats()["series_dropped"]

            assert live_after_1 == 2, live_after_1
            assert live_after_2 == 5, f"живой слой обязан копить (2+3), получено {live_after_2}"

            live_voices = [
                str(c.args[0])
                for c in mock_logger.warning.call_args_list
                if c.args and "(живой слой)" in str(c.args[0])
            ]
            assert len(live_voices) == 1, f"живой слой: одно условие — один голос, {live_voices}"
            assert _series_in(live_voices[0]) == live_after_1, (
                "голос живого слоя обязан назвать число НА МОМЕНТ произнесения (переход), "
                f"а назвал {_series_in(live_voices[0])} при {live_after_1}"
            )
        finally:
            mgr.shutdown()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
