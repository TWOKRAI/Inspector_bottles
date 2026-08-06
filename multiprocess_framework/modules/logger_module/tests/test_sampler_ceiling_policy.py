# -*- coding: utf-8 -*-
"""Потолок кардинальности дросселя не убивает его навсегда (Ф7.х, M-2 ревью Ф7).

Ф7.1 выбрала на переполнении карты ключей **насыщение навсегда**: новые ключи не
заводятся и проходят без дросселя. Довод был про полную чистку, и он верен — но
цена оказалась больше названной, и ревью её воспроизвело: после насыщения шторм
из 50 000 повторов ОДНОГО текста прошёл целиком, подавлено 0. То есть дроссель
умирает именно для того случая, ради которого заведён. И насыщение достигается не
в теории: 90 секунд живого прогона дали 204 ключа, экстраполяция до потолка ~30
минут — короче наблюдения Б-6.

Политика теперь двухступенчатая, и здесь сторожатся обе ступени плюс граница
между ними:

  * протухшие ключи подметаются (их состояние всё равно ничего не значит —
    правило всплеска обнулило бы его при следующей встрече);
  * карта, забитая ГОРЯЧИМИ ключами, по-прежнему насыщается — против шторма
    высокой кардинальности дроссель по повторяемости бессилен по построению, и
    делать вид, что это не так, значило бы врать счётчиком.

Часы — зависимость объекта (``time_fn``), а не глобальный патч: глобально
подменённые часы уже приносили в этот проект флейк.
"""

from __future__ import annotations

from typing import Any, Dict

from multiprocess_framework.modules.logger_module.core.sampling import KEY_CEILING, RateSampler


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _record(message: str, level: str = "DEBUG") -> Dict[str, Any]:
    return {"level": level, "message": message, "extra": {}}


def _sampler(clock: _Clock, **kwargs: Any) -> RateSampler:
    params: Dict[str, Any] = {"first_n": 3, "every_mth": 1_000_000, "burst_reset_sec": 5.0}
    params.update(kwargs)
    return RateSampler(time_fn=clock, **params)


def _fill_to_ceiling(sampler: RateSampler, clock: _Clock, prefix: str = "cold") -> None:
    for i in range(KEY_CEILING):
        sampler("system", "DEBUG", _record(f"{prefix}-{i}"))
    assert sampler.keys_tracked == KEY_CEILING


class TestTheThrottleSurvivesASaturatedMap:
    def test_a_storm_arriving_after_saturation_is_still_throttled(self) -> None:
        """Главное свойство: шторм ПОСЛЕ насыщения давится, а не проходит целиком.

        Ровно сценарий ревью, уменьшенный по числу повторов: карта набита
        уникальными ключами (точка с переменной в тексте), и только потом
        начинается шторм одного текста.
        """
        clock = _Clock()
        sampler = _sampler(clock)
        _fill_to_ceiling(sampler, clock)

        # Уникальные ключи протухли: их не видели дольше окна всплеска.
        clock.advance(60.0)

        passed = sum(1 for _ in range(50_000) if sampler("system", "DEBUG", _record("шторм")) is not None)

        assert passed <= 4, f"после насыщения дроссель пропустил {passed} записей шторма вместо первых N"
        assert sampler.records_sampled_out >= 49_000
        assert sampler.keys_expired >= KEY_CEILING, "протухшие ключи не подметаются — карта мертва навсегда"

    def test_sweeping_does_not_reset_the_windows_of_hot_keys(self) -> None:
        """Довод против полной чистки остаётся в силе — и проверяется.

        Подметание обязано трогать ТОЛЬКО протухшее. Обнули оно окно горячего
        ключа — шторм получал бы свои ``first_n`` заново на каждом переполнении,
        то есть прорывался бы ровно в момент, когда карту переполнил он же.
        """
        clock = _Clock()
        sampler = _sampler(clock)

        # Холодные ключи занимают карту и протухают.
        for i in range(KEY_CEILING - 1):
            sampler("system", "DEBUG", _record(f"cold-{i}"))
        clock.advance(60.0)

        # Горячий ключ занимает последнюю ячейку и израсходовал свои first_n
        # ПРЯМО СЕЙЧАС — то есть протухшим он не является.
        for _ in range(10):
            sampler("system", "DEBUG", _record("горячий"))
        assert sampler.keys_tracked == KEY_CEILING
        assert sampler("system", "DEBUG", _record("горячий")) is None, "стенд не воспроизведён: ключ не подавляется"

        # Переполнение → подметание протухших.
        sampler("system", "DEBUG", _record("новичок"))

        assert sampler.keys_expired > 0, "подметания не было — стенд не воспроизведён"
        assert sampler("system", "DEBUG", _record("горячий")) is None, (
            "подметание обнулило окно ГОРЯЧЕГО ключа — шторм прорывается на каждом переполнении"
        )

    def test_a_map_full_of_hot_keys_saturates_and_says_so(self) -> None:
        """Вторая ступень: мести нечего — работает прежнее поведение, и оно названо.

        Шторм высокой кардинальности (каждая запись — новый текст) дросселю по
        повторяемости не поддаётся по построению. Правильный ответ — пропустить
        и сказать об этом счётчиком, а не изображать работу.
        """
        clock = _Clock()
        sampler = _sampler(clock)
        _fill_to_ceiling(sampler, clock)  # все ключи свежие: часы не двигали

        before_expired = sampler.keys_expired
        for i in range(100):
            assert sampler("system", "DEBUG", _record(f"новый-{i}")) is not None

        assert sampler.keys_saturated == 100, "насыщение перестало считаться — «дроссель не работает» стало невидимым"
        assert sampler.keys_expired == before_expired, "подмели горячие ключи — это и есть запрещённая полная чистка"
        assert sampler.keys_tracked == KEY_CEILING

    def test_a_fruitless_sweep_is_not_repeated_on_every_record(self) -> None:
        """Цена потолка ограничена: бесплодный проход O(N) не повторяется покадрово.

        Раньше протухнуть некому, чем через окно всплеска, — значит и смотреть
        незачем. Считаем сами проходы, а не время: время на прогоне шумит.
        """
        clock = _Clock()

        class _CountingSampler(RateSampler):
            """``__slots__`` не даёт подменить метод на экземпляре — считаем наследником."""

            __slots__ = ("scans",)

            def __init__(self, **kwargs: Any) -> None:
                self.scans = 0
                super().__init__(**kwargs)

            def _make_room(self, now: float) -> bool:
                # Считаем ФАКТИЧЕСКИЕ проходы по карте, а не вызовы: отсечка по
                # времени стоит внутри, и вызов сам по себе ничего не стоит.
                before_allowed = now >= self._next_sweep_at
                if before_allowed:
                    self.scans += 1
                return super()._make_room(now)

        sampler = _CountingSampler(first_n=3, every_mth=1_000_000, burst_reset_sec=5.0, time_fn=clock)
        _fill_to_ceiling(sampler, clock)

        for i in range(500):
            sampler("system", "DEBUG", _record(f"новый-{i}"))

        assert sampler.scans == 1, (
            f"бесплодный проход по карте повторился {sampler.scans} раз — цена потолка не ограничена"
        )
        assert sampler.keys_saturated == 500

        # А после того, как окно истекло, проход снова разрешён и находит добычу.
        clock.advance(60.0)
        assert sampler("system", "DEBUG", _record("после окна")) is not None
        assert sampler.keys_expired > 0


class TestTheThrottleIsNotSilentlyDisabledByItsOwnConfig:
    def test_burst_reset_below_the_minimum_is_rejected_by_both_layers(self) -> None:
        """``burst_reset_sec=0.0`` был валиден и молча выключал дроссель целиком.

        Любая пауза оказывалась «дольше окна», всплеск начинался заново на каждой
        записи. Шторм Б-6 шёл с паузами ~20 мс — то есть ручка включённого с виду
        дросселя отдавала бы 100 % записей. Отвергают ОБА слоя: L3 (секция
        ``observability``, куда смотрит оператор) и L0 (схема менеджера).

        Держит границу РОВНО ОДИН механизм — ``FieldMeta(min=...)`` через
        ``SchemaBase._check_field_constraints``. Первая редакция ставила рядом
        собственный ``field_validator``, и слом-инъекция показала цену дубля:
        снятие любого одного предохранителя не давало ни одного красного, то есть
        тест не сторожил ничего конкретного. Дубль снят, страж остался.
        """
        import pytest

        from multiprocess_framework.modules.logger_module.configs.logger_manager_config import (
            MIN_BURST_RESET_SEC,
            LoggerManagerConfig,
        )
        from multiprocess_framework.modules.process_module.configs.observability_config import ObservabilityConfig

        for factory in (LoggerManagerConfig, ObservabilityConfig):
            with pytest.raises(Exception) as excinfo:
                factory(sampling_burst_reset_sec=0.0)
            message = str(excinfo.value)
            assert "sampling_burst_reset_sec" in message, f"{factory.__name__}: отказ не называет поле — {message}"
            assert str(MIN_BURST_RESET_SEC) in message, f"{factory.__name__}: отказ не называет границу — {message}"

            # Граница включительно: минимум — законное значение.
            factory(sampling_burst_reset_sec=MIN_BURST_RESET_SEC)

    def test_unknown_max_level_is_rejected_by_both_layers_too(self) -> None:
        """Симметрия слоёв: L0 отвергал опечатку в имени уровня, L3 принимал молча."""
        import pytest

        from multiprocess_framework.modules.logger_module.configs.logger_manager_config import LoggerManagerConfig
        from multiprocess_framework.modules.process_module.configs.observability_config import ObservabilityConfig

        for factory in (LoggerManagerConfig, ObservabilityConfig):
            with pytest.raises(Exception) as excinfo:
                factory(sampling_max_level="TRACE")
            assert "sampling_max_level" in str(excinfo.value)

            assert factory(sampling_max_level="warn").sampling_max_level == "WARNING"

    def test_a_window_at_the_minimum_still_throttles_a_twenty_millisecond_storm(self) -> None:
        """Минимум выбран не «красивым числом», а шире паузы измеренного шторма."""
        from multiprocess_framework.modules.logger_module.configs.logger_manager_config import MIN_BURST_RESET_SEC

        clock = _Clock()
        sampler = _sampler(clock, burst_reset_sec=MIN_BURST_RESET_SEC)

        passed = 0
        for _ in range(1000):
            clock.advance(0.02)  # темп шторма Б-6
            if sampler("system", "DEBUG", _record("повтор")) is not None:
                passed += 1

        assert passed <= 4, f"на минимальном окне дроссель пропустил {passed} записей — окно уже паузы шторма"


class TestSweepScheduleCacheDoesNotOutliveItsWindow:
    """Ф7.х.2 (НД-2 верификации): ``configure`` сбрасывает кэш расписания подметания.

    ``_next_sweep_at`` — решение «раньше X мести бессмысленно», вычисленное из
    ПРЕЖНЕГО окна. Первая редакция его сохраняла: оператор, сузивший окно под
    штормом (ровно тот сценарий, ради которого ручка существует), получал
    подметание, заблокированное на срок старого окна — при окне в сутки на сутки.
    """

    def test_narrowing_the_window_by_reload_unblocks_the_sweep(self) -> None:
        clock = _Clock()
        sampler = _sampler(clock, burst_reset_sec=3600.0)
        _fill_to_ceiling(sampler, clock)

        # Переполнение при горячей карте: бесплодный проход взводит кэш
        # расписания на ЧАС вперёд.
        sampler("system", "DEBUG", _record("hot-overflow"))
        assert sampler.keys_saturated == 1

        clock.advance(10.0)
        sampler.configure(first_n=3, every_mth=1_000_000, burst_reset_sec=0.1, max_level="DEBUG")

        # По НОВОМУ окну вся карта протухла (возраст 10 с > 0.1 с). Если кэш
        # расписания пережил reload — подметание молчит до конца старого окна,
        # и новый ключ проходит мимо дросселя с ростом насыщения.
        sampler("system", "DEBUG", _record("fresh-after-reload"))
        assert sampler.keys_expired == KEY_CEILING, (
            "правка окна не подействовала: подметание заблокировано расписанием, вычисленным по старому окну"
        )
        assert sampler.keys_saturated == 1, "насыщение выросло после сужения окна — ручка мертва"


class TestSweepIsSafeUnderConcurrentEmitters:
    """Ф7.х.2 (НД-1 верификации): подметание не роняет параллельных эмитентов.

    Класс безлоковый по контракту, а первая редакция подметания добавила в него
    итерацию по словарю с удалением — два потока на переполнении ловили
    ``KeyError`` (пересекающиеся списки протухших) и ``RuntimeError: dictionary
    changed size during iteration``. Исключение отсюда выходит из процессора и
    ПИШЕТСЯ аварийным путём — механизм снижения объёма на отказе объём добавляет.

    Часы здесь настоящие (``time.monotonic``): гонка живёт в реальном времени, а
    внедрённые часы сделали бы стенд однопоточным по смыслу.
    """

    def test_no_exceptions_under_a_storm_of_unique_keys(self) -> None:
        import threading
        import time as _time

        sampler = RateSampler(first_n=1, every_mth=2, burst_reset_sec=0.05, time_fn=_time.monotonic)
        errors: list = []
        stop = _time.monotonic() + 1.5

        def _hammer(worker: int) -> None:
            i = 0
            try:
                while _time.monotonic() < stop:
                    sampler("system", "DEBUG", _record(f"w{worker}-{i}"))
                    i += 1
            except Exception as exc:  # noqa: BLE001 — сам факт исключения и есть дефект
                errors.append(exc)

        threads = [threading.Thread(target=_hammer, args=(w,), daemon=True) for w in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)
        assert not any(t.is_alive() for t in threads), "эмитент завис в сэмплере"
        assert errors == [], f"подметание уронило эмитентов: {[repr(e) for e in errors[:3]]}"
