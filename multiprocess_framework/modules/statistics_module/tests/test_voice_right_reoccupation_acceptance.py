# -*- coding: utf-8 -*-
"""Независимая приёмка «права на голос» предела кардинальности (telemetry-stage6).

Написаны **от трёх критериев приёмки**, продиктованных постановщиком напрямую в
промпте задачи (К1/К2/К3), без чтения реализации: НЕ открывались
``core/cardinality_guard.py``, ``core/aggregation_window.py``, ``core/stats_manager.py``,
``tests/test_cardinality_voice_hazards.py``, ``tests/test_cardinality_voice_acceptance.py``,
``DECISIONS.md`` модуля, ``plans/QUEUE.md``, ``docs/sessions/2026-08-17.md``, и не
запрашивался ``git show``/``git log -p`` коммита fix'а (``ecd52e9b``).

Контракт взят из текста задачи (К1/К2/К3, дословно ниже в докстрингах классов) и из
публичного API: ``README.md`` / ``STATUS.md`` модуля, ``interfaces.py``, ``__init__.py``,
``configs/stats_config.py``, ``adapters/stats_adapter.py`` — и из уже существующего
файла ``tests/test_tempo_knob.py`` / ``tests/test_limits_acceptance.py``, прочитанных как
РАЗРЕШЁННЫЕ образцы сборки объектов (паттерн ``managers={"logger": MagicMock()}`` и
фильтр WARNING-вызовов по имени ручки — установленный в уже принятом
``test_limits_acceptance.py::TestCardinalityCeiling::test_voice_fires_exactly_once_per_condition_not_per_rejection``,
не выдуман заново).

Предмет: право на голос (WARNING) тратится при переходе StatsManager в состояние
«упёрся в max_series» и обязано вернуться ТОЛЬКО когда упор действительно снят —
не при тихом такте (К1) и не при смене темпа (К2), но обязано вернуться при настоящем
освобождении места (К3).

Ревизия после инъекций координатора (2026-08-17): исходный К3 был единым тестом
(``reset_metrics()`` + отдельный чистый такт), и координатор нашёл, что он не
различает «работает reset_metrics()» от «работает такт без единого отказа» — оба
события стояли рядом, и инъекция, отключающая именно освобождение через
reset_metrics(), не давала красного (такт без отказов сам по себе тянул тест).
К3 разделён на ДВА теста разных свойств:
``TestATickWithNoRejectionsReturnsTheVoice`` (такт без отказов возвращает право —
``reset_metrics()`` здесь лишь предусловие, без него такту неоткуда взяться:
проверено прямой пробой, красно) и
``TestFreeingAloneWithoutACleanTickReturnsTheVoice`` (``reset_metrics()`` —
единственное событие между упорами, отдельного чистого такта нет вовсе:
пересыщение и перелив идут одним смешанным тактом).
"""

import threading

from unittest.mock import MagicMock

from multiprocess_framework.modules.statistics_module import StatsManager
from multiprocess_framework.modules.channel_routing_module.interfaces import IChannel

# Потолок для тестов — далеко от дефолта 1000, число выбрано отдельно от 13,
# используемого в test_limits_acceptance.py, чтобы не путать происхождение чисел.
CEILING = 6


def _run_with_deadline(fn, timeout=10.0):
    """Гоняет ``fn()`` в потоке-демоне с дедлайном на join.

    Правило проекта: тест, который может заблокироваться (здесь — гоняем именно тот
    механизм, где уже находили гонки: смена окна при reconfigure), обязан падать по
    таймауту, а не виснуть.
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


class _SpyChannel(IChannel):
    """Канал-шпион: копит ровно те снапшоты, что реально прилетели через flush().

    Тот же класс, что в ``test_limits_acceptance.py`` (образец сборки, разрешённый
    к чтению) — воспроизведён локально, чтобы файл был самодостаточным.
    """

    def __init__(self, name="spy"):
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


def _mgr(logger, max_series=CEILING, extra_config=None):
    cfg = {"max_series": max_series, "enable_logging": True, "channels": {}}
    if extra_config:
        cfg.update(extra_config)
    mgr = StatsManager(manager_name="VoiceReoccupationMgr", config=cfg, managers={"logger": logger})
    assert mgr.initialize() is True
    return mgr, cfg


def _voice_calls(logger):
    """WARNING-вызовы, адресованные ручке предела кардинальности.

    Фильтр по подстроке ``max_series`` — не выдуман: это буквальное имя поля
    конфигурации (``StatsManagerConfig.max_series``) и часть адреса ручки
    ``observability.stats.max_series``, названного в README и в уже принятом
    ``test_limits_acceptance.py`` тем же способом (там фильтр чуть шире — по слову
    «потолок» — здесь используется более узкий и явный маркер адреса ручки).
    """
    return [c for c in logger.method_calls if c[0] == "warning" and "max_series" in str(c)]


class TestQuietTickDoesNotReleaseTheVoice:
    """К1. Тихий такт не отпускает условие.

    Такт, в котором НИКТО не пробовал завести серию, не доказывает, что место
    появилось. После такого такта менеджер обязан остаться «упёршимся»: следующий
    отказ новому имени НЕ обязан породить новый голос.
    """

    def test_quiet_tick_between_two_rejections_does_not_add_a_second_voice(self):
        logger = MagicMock()
        mgr, _ = _mgr(logger)

        def _drive():
            for i in range(CEILING):
                mgr.increment(f"known{i}")
            mgr.increment("extra0")  # первая НОВАЯ серия сверх потолка -> первый упор
            mgr.flush()
            first_count = len(_voice_calls(logger))

            # Тихий такт: только СУЩЕСТВУЮЩАЯ серия, ни одной попытки завести новую.
            mgr.increment("known0")
            mgr.increment("known0")
            mgr.flush()
            quiet_count = len(_voice_calls(logger))

            # Такт, где СНОВА пробуем новую серию — отказ повторяется.
            mgr.increment("extra1")
            mgr.flush()
            after_repeat_count = len(_voice_calls(logger))
            return first_count, quiet_count, after_repeat_count

        first_count, quiet_count, after_repeat_count = _run_with_deadline(_drive)

        assert first_count >= 1, "первый упор обязан заговорить хотя бы одним голосом"
        assert quiet_count == first_count, (
            "тихий такт (без попыток завести новую серию) не доказывает освобождение места — "
            f"счёт голосов не должен был вырасти: было {first_count}, стало {quiet_count}"
        )
        assert after_repeat_count == first_count, (
            "право на голос не вернулось тихим тактом — повторный отказ новой серии не обязан "
            f"звучать снова: было {first_count}, стало {after_repeat_count}"
        )
        mgr.shutdown()


class TestTempoChangeDoesNotReleaseTheVoice:
    """К2. Смена темпа не возвращает право на голос.

    Изменение периода окна/темпа агрегации — событие расписания, а не изменение
    занятости мест. После смены темпа, при неснятом упоре, второго голоса быть
    не должно.
    """

    def test_reconfigure_of_tempo_alone_does_not_add_a_second_voice(self):
        logger = MagicMock()
        mgr, cfg = _mgr(logger, extra_config={"aggregation_interval": 12.0, "flush_interval": 12.0})

        def _drive():
            for i in range(CEILING):
                mgr.increment(f"known{i}")
            mgr.increment("extra0")  # первый упор -> первый голос
            mgr.flush()
            first_count = len(_voice_calls(logger))

            # Смена ТОЛЬКО темпа (max_series тот же) — событие расписания.
            new_cfg = dict(cfg)
            new_cfg.update({"aggregation_interval": 36.0, "flush_interval": 36.0})
            reconfigured = mgr.reconfigure(new_cfg)

            # Упор всё ещё не снят -> новая новая серия снова отказана.
            mgr.increment("extra1")
            mgr.flush()
            after_tempo_change_count = len(_voice_calls(logger))
            return reconfigured, first_count, after_tempo_change_count

        reconfigured, first_count, after_tempo_change_count = _run_with_deadline(_drive)

        assert reconfigured is True, "reconfigure обязан был принять новый темп"
        assert first_count >= 1, "первый упор обязан заговорить хотя бы одним голосом"
        assert after_tempo_change_count == first_count, (
            "смена темпа — событие расписания, а не освобождение места: счёт голосов "
            f"не должен был вырасти: было {first_count}, стало {after_tempo_change_count}"
        )
        mgr.shutdown()


class TestATickWithNoRejectionsReturnsTheVoice:
    """К3 (часть 1). Такт, в котором ВСЕ попытки успешны, возвращает право на голос.

    Честное имя после проверки координатором (инъекция + прямая проверка гипотезы,
    см. финальный отчёт): этот тест доказывает СВОЙСТВО «такт без единого отказа
    возвращает право на голос» — не изолированно доказывает именно
    ``reset_metrics()`` как единственную дорогу назад. ``reset_metrics()`` здесь
    нужен как ПРЕДВАРИТЕЛЬНОЕ УСЛОВИЕ (без него живой слой физически не пропустит
    ни одной новой ``fresh*`` серии — они будут отвергнуты С ПОРОГА, и такт не
    станет «без отказов»; проверено прямой проверкой без reset_metrics — красный,
    приведено в отчёте), но собственно ПРОВЕРЯЕМОЕ здесь свойство — то, что
    случается ПОСЛЕ: такт, где заведённые серии не отказаны ни разу.

    Изолированный тест на ``reset_metrics()`` как САМОДОСТАТОЧНУЮ дорогу назад,
    БЕЗ отдельного чистого такта между освобождением и повторным упором —
    отдельным классом ниже (``TestFreeingAloneWithoutACleanTickReturnsTheVoice``).
    """

    def test_a_tick_where_every_attempt_succeeds_lets_the_next_saturation_speak_again(self):
        logger = MagicMock()
        spy = _SpyChannel()
        mgr, _ = _mgr(logger)
        mgr.register_channel(spy)

        def _drive():
            # Эпизод 1: насыщаем и получаем первый голос.
            for i in range(CEILING):
                mgr.increment(f"known{i}")
            mgr.increment("extra0")  # первый отказ -> первый упор
            mgr.flush()
            first_count = len(_voice_calls(logger))
            first_snapshot = spy.received[-1]

            # Явное освобождение места — публичный reset_metrics(), не пересоздание менеджера.
            mgr.reset_metrics()

            # Такт, где серии ЗАВОДЯТСЯ и НИ ОДНА не отказана (другие имена — не зависим
            # от того, помнит ли страж имена прошлого эпизода): легитимное доказательство
            # того, что состав серий перестал упираться, а не просто прошло время.
            for i in range(CEILING):
                mgr.increment(f"fresh{i}")
            mgr.flush()
            freed_snapshot = spy.received[-1]

            # Предел снова достигнут -> обязан прозвучать НОВЫЙ голос.
            mgr.increment("overflow_again")
            mgr.flush()
            after_release_count = len(_voice_calls(logger))

            return first_count, first_snapshot, freed_snapshot, after_release_count

        first_count, first_snapshot, freed_snapshot, after_release_count = _run_with_deadline(_drive)

        # Контроль: эпизод 1 ДЕЙСТВИТЕЛЬНО упирался (не проходим на нуле).
        assert first_count >= 1, "первый упор обязан был заговорить — иначе критерий проверяет пустоту"
        assert first_snapshot["total_count"] > len(first_snapshot["metrics"]), (
            f"контроль: эпизод 1 обязан был реально упереться в потолок, снапшот: {first_snapshot}"
        )

        # Контроль: такт освобождения ДЕЙСТВИТЕЛЬНО был чист (без отказов) — иначе
        # «освобождение» было бы фикцией.
        assert freed_snapshot["total_count"] == len(freed_snapshot["metrics"]), (
            f"контроль: такт освобождения обязан быть БЕЗ отказов, снапшот: {freed_snapshot}"
        )

        # Само доказательство критерия К3: НОВЫЙ голос после настоящего освобождения.
        assert after_release_count > first_count, (
            "после настоящего освобождения места новый упор обязан заговорить СНОВА — "
            f"право на голос не вернулось: было {first_count}, осталось {after_release_count}"
        )
        mgr.shutdown()


class TestFreeingAloneWithoutACleanTickReturnsTheVoice:
    """К3 (часть 2). ``reset_metrics()`` — ЕДИНСТВЕННАЯ дорога назад, без чистого такта.

    Класс выше не мог различить «работает reset_metrics()» от «работает такт без
    отказов» — между освобождением и повторным упором там всегда стоял отдельный
    ПОЛНОСТЬЮ чистый такт (``fresh0..freshN``, ни одного отказа), и этот чистый такт
    сам по себе мог быть вторым, независимым основанием для голоса.

    Здесь эта лазейка закрыта КОНСТРУКТИВНО: между ``reset_metrics()`` и повторным
    упором стоит такт, в котором НЕ предпринимается вообще НИ ОДНОЙ попытки завести
    серию (пустой ``flush()``), а затем пересыщение и перелив идут ОДНИМ смешанным
    тактом — новые имена и упор в потолок в одном и том же цикле записи ДО
    единственного ``flush()``. Такой такт содержит отказ и поэтому НЕ является
    «тактом без единого отказа» ни для одной из позиций — значит, если голос всё
    равно прозвучит, единственное объяснение, оставшееся в сценарии, —
    ``reset_metrics()``.

    Проверено эмпирически (см. финальный отчёт): с ``reset_metrics()`` — рост
    счёта голосов (2 -> 3), без него — счёт не растёт (2 -> 2) на той же самой
    конструкции.
    """

    def test_reset_metrics_alone_reopens_the_voice_with_no_intervening_clean_tick(self):
        logger = MagicMock()
        mgr, _ = _mgr(logger)

        def _drive():
            # Эпизод 1: насыщаем и получаем первый голос (смешанный такт — это
            # неизбежно для самого первого упора, иначе упора бы не случилось).
            for i in range(CEILING):
                mgr.increment(f"known{i}")
            mgr.increment("extra0")
            mgr.flush()
            first_count = len(_voice_calls(logger))

            # ЕДИНСТВЕННОЕ событие между упорами — явное освобождение места.
            mgr.reset_metrics()

            # Полностью пустой такт: НИ ОДНОЙ попытки завести серию — не тот такт,
            # что мог бы сам по себе освободить право на голос по критерию К1/К3.
            mgr.flush()
            quiet_after_reset_count = len(_voice_calls(logger))

            # Пересыщение и перелив ОДНИМ смешанным тактом — без отдельного чистого
            # такта между ними: этот такт сам по себе НЕ «без отказов» (последняя
            # попытка в нём отказана), значит списать голос на «такт без отказов»
            # здесь нельзя.
            for i in range(CEILING):
                mgr.increment(f"again{i}")
            mgr.increment("again_overflow")
            mgr.flush()
            final_count = len(_voice_calls(logger))

            return first_count, quiet_after_reset_count, final_count

        first_count, quiet_after_reset_count, final_count = _run_with_deadline(_drive)

        assert first_count >= 1, "первый упор обязан был заговорить — иначе критерий проверяет пустоту"
        assert quiet_after_reset_count == first_count, (
            "пустой такт сразу после reset_metrics() не обязан САМ по себе добавить голос"
        )
        assert final_count > first_count, (
            "reset_metrics() без единого промежуточного чистого такта обязан быть достаточным, "
            f"чтобы повторный упор снова заговорил: было {first_count}, стало {final_count}"
        )
        mgr.shutdown()
