# -*- coding: utf-8 -*-
"""Опасные места САМОГО механизма дросселя (Ф7.1) — стражи автора.

Независимый тестировщик писал по критериям приёмки и контракт наружу закрыл
(`test_sampling_contract.py`). Здесь — то, что видно только изнутри
механизма: место в цепочке, потолок карты ключей, часы как зависимость,
переживание `reload` и запрет на правку общего словаря записи.

Каждое свойство предъявлено слом-инъекцией: набор красных предсказан ДО
прогона и записан в план (таблица Ф7.1).
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.channel_routing_module.interfaces import IChannel
from multiprocess_framework.modules.logger_module.core.log_types import LogLevel
from multiprocess_framework.modules.logger_module.core.logger_core import LoggerCore
from multiprocess_framework.modules.logger_module.core.sampling import (
    KEY_CEILING,
    SKIPPED_FIELD,
    RateSampler,
)


class _SpyChannel(IChannel):
    """Канал-шпион. Наследование от ``IChannel`` обязательно: реестр отвергает
    утиный тип, и записи поехали бы мимо наблюдения — тест «проверял» бы пустоту."""

    def __init__(self, name: str) -> None:
        self._name = name
        self.written: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "spy"

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        self.written.append(data)
        return {"status": "success", "channel": self._name}

    def close(self) -> None:
        pass


def _config(**sampling: Any) -> Dict[str, Any]:
    config = {
        "app_name": "sampling_hazards",
        "enable_batching": False,
        "channels": {},
        "default_level": "DEBUG",
        "scopes": {"SYSTEM": {"channels": ["a"]}},
    }
    config.update(sampling)
    return config


def _logger(**sampling: Any):
    mgr = LoggerCore(manager_name="HazardLogger", config=_config(**sampling))
    mgr.initialize()
    spy = _SpyChannel("a")
    mgr.register_channel(spy)
    return mgr, spy


class _Clock:
    """Часы-заглушка. Двигаются тестом, а не планетой."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class TestPlaceInTheChain:
    """Сэмплер стоит ПОСЛЕ редактора — и это проверяется наблюдаемым эффектом.

    Спай на имя процессора сторожил бы имя, а не свойство. Здесь свойство
    предъявлено через результат: две записи с РАЗНЫМИ паролями после редакции
    становятся одним и тем же текстом, то есть одним событием для дросселя.
    Если бы сэмплер стоял первым, ключи были бы разные и прошли бы обе.
    """

    def test_records_differing_only_by_a_secret_are_one_event(self) -> None:
        mgr, spy = _logger(sampling_first_n=1, sampling_every_mth=1000)

        mgr.log("SYSTEM", LogLevel.DEBUG, "connect password=hunter2", "mod")
        mgr.log("SYSTEM", LogLevel.DEBUG, "connect password=swordfish", "mod")

        assert len(spy.written) == 1, (
            "после редакции обе строки одинаковы — вторая обязана быть подавлена; "
            f"дошло {len(spy.written)}: {[w['message'] for w in spy.written]}"
        )
        assert "***" in spy.written[0]["message"]


class TestKeyMapCeiling:
    """Потолок карты ключей (класс Н5) и НАСЫЩЕНИЕ вместо чистки.

    Чистка вернула бы ``first_n`` сразу всем ключам, то есть шторм прорвался бы
    заново ровно в момент переполнения. Насыщение: новые ключи не заводятся,
    записи проходят, факт виден счётчиком.
    """

    def test_map_does_not_grow_past_the_ceiling(self) -> None:
        sampler = RateSampler(first_n=1, every_mth=1000, time_fn=_Clock())

        for i in range(KEY_CEILING + 500):
            sampler("SYSTEM", LogLevel.DEBUG, {"message": f"уникальный текст {i}"})

        assert sampler.keys_tracked == KEY_CEILING, (
            f"карта ключей выросла до {sampler.keys_tracked} при потолке {KEY_CEILING}"
        )
        assert sampler.keys_saturated == 500, f"мимо дросселя прошло {sampler.keys_saturated} записей, ожидалось 500"

    def test_saturation_passes_the_record_instead_of_dropping_it(self) -> None:
        """Насыщение НЕ имеет права глушить: «редкое проходит всегда»."""
        sampler = RateSampler(first_n=1, every_mth=1, time_fn=_Clock())
        for i in range(KEY_CEILING):
            sampler("SYSTEM", LogLevel.DEBUG, {"message": f"ключ {i}"})

        record = {"message": "ключ за потолком"}
        assert sampler("SYSTEM", LogLevel.DEBUG, record) is record
        assert sampler.records_sampled_out == 0


class TestClockIsADependency:
    """Окно всплеска двигается ВНЕДРЁННЫМИ часами.

    Глобальный патч ``time.monotonic`` уже приносил в этот проект флейк, а
    ``time.sleep`` в тесте делает его тайминговым. Здесь часы — параметр.
    """

    def test_silence_longer_than_the_window_starts_the_burst_over(self) -> None:
        clock = _Clock()
        sampler = RateSampler(first_n=2, every_mth=1000, burst_reset_sec=5.0, time_fn=clock)

        passed = [sampler("SYSTEM", LogLevel.DEBUG, {"message": "всплеск"}) for _ in range(4)]
        assert [p is not None for p in passed] == [True, True, False, False]

        clock.now += 5.001
        second_burst = [sampler("SYSTEM", LogLevel.DEBUG, {"message": "всплеск"}) for _ in range(3)]
        assert [p is not None for p in second_burst] == [True, True, False], (
            "после тишины дольше окна всплеск обязан начаться заново"
        )

    def test_steady_stream_inside_the_window_is_not_reset(self) -> None:
        """Обратная половина: сброс по ТИШИНЕ, а не по возрасту ключа.

        Сброс по возрасту означал бы, что непрерывный шторм каждые N секунд
        получает новую порцию ``first_n`` — то есть дроссель, который сам себя
        периодически отключает.
        """
        clock = _Clock()
        sampler = RateSampler(first_n=1, every_mth=1000, burst_reset_sec=5.0, time_fn=clock)

        results = []
        for _ in range(10):
            clock.now += 4.0  # тишина короче окна, но суммарно 40 секунд
            results.append(sampler("SYSTEM", LogLevel.DEBUG, {"message": "ровный поток"}))

        assert sum(1 for r in results if r is not None) == 1, (
            "внутри окна проходит только первая; сброс по возрасту ключа — дефект"
        )


class TestReloadDoesNotResetTheWindows:
    """``reload`` меняет параметры, но не стирает то, что уже произошло.

    Идемпотентность ≠ монотонность: оператор правит конфиг ИЗ-ЗА шторма, и
    пересоздание сэмплера вернуло бы ему шторм в ответ на правку.
    """

    def test_windows_survive_reconfigure(self) -> None:
        mgr, spy = _logger(sampling_first_n=1, sampling_every_mth=1000)
        mgr.log("SYSTEM", LogLevel.DEBUG, "повтор", "mod")
        mgr.log("SYSTEM", LogLevel.DEBUG, "повтор", "mod")
        assert len(spy.written) == 1

        assert mgr.reconfigure(_config(sampling_first_n=1, sampling_every_mth=1000)) is True
        spy_after = _SpyChannel("a")
        mgr.register_channel(spy_after)

        mgr.log("SYSTEM", LogLevel.DEBUG, "повтор", "mod")

        assert spy_after.written == [], "после reload серия начата заново — окна сэмплинга не пережили пересборку"

    def test_published_counters_belong_to_the_sampler_in_the_chain(self) -> None:
        """Счётчики наружу берутся у ТОГО экземпляра, который стоит в цепочке.

        Найдено слом-инъекцией, которая оказалась негодной: попытка «пересоздать
        сэмплер на reload» переприсваивала ``self._sampler``, а цепочка
        продолжала звать ПРЕЖНИЙ объект — то есть ломала не то, что задумано.
        Ровно этим и опасен алиас: правка выглядит подействовавшей, дроссель
        работает по-старому, а ``get_stats()`` показывает нули нового
        экземпляра. Расхождение молчаливое, поэтому у него страж.
        """
        mgr, _ = _logger(sampling_first_n=1, sampling_every_mth=1000)
        assert any(p is mgr._sampler for p in mgr._processors), (
            "объект, у которого спрашивают счётчики, не тот, что стоит в цепочке"
        )
        mgr.reconfigure(_config(sampling_first_n=1, sampling_every_mth=1000))
        assert any(p is mgr._sampler for p in mgr._processors), (
            "после reload счётчики публикуются с экземпляра, которого нет в цепочке"
        )

    def test_reconfigure_applies_the_new_parameters(self) -> None:
        """Вторая половина того же: параметры МЕНЯЮТСЯ, иначе живёт мёртвая ручка."""
        mgr, spy = _logger(sampling_first_n=1, sampling_every_mth=1000)
        mgr.log("SYSTEM", LogLevel.DEBUG, "повтор", "mod")
        mgr.log("SYSTEM", LogLevel.DEBUG, "повтор", "mod")
        assert len(spy.written) == 1

        assert mgr.reconfigure(_config(sampling_first_n=0)) is True
        spy_after = _SpyChannel("a")
        mgr.register_channel(spy_after)

        mgr.log("SYSTEM", LogLevel.DEBUG, "повтор", "mod")
        mgr.log("SYSTEM", LogLevel.DEBUG, "повтор", "mod")

        assert len(spy_after.written) == 2, "выключение дросселя конфигом не подействовало"

    def test_reconfigure_can_also_enable_the_sampler(self) -> None:
        """Обратная половина ручки (Ф7.х.2, Н-7 верификации): включение на живой системе.

        Прежний тест проверял только выключение — мёртвая половина «включить
        дроссель под штормом, не перезапуская процесс» осталась бы незамеченной.
        """
        mgr, spy = _logger(sampling_first_n=0)
        mgr.log("SYSTEM", LogLevel.DEBUG, "повтор", "mod")
        mgr.log("SYSTEM", LogLevel.DEBUG, "повтор", "mod")
        assert len(spy.written) == 2, "стенд не воспроизведён: выключенный дроссель что-то задушил"

        assert mgr.reconfigure(_config(sampling_first_n=1, sampling_every_mth=1000)) is True
        spy_after = _SpyChannel("a")
        mgr.register_channel(spy_after)

        mgr.log("SYSTEM", LogLevel.DEBUG, "повтор", "mod")
        mgr.log("SYSTEM", LogLevel.DEBUG, "повтор", "mod")
        mgr.log("SYSTEM", LogLevel.DEBUG, "повтор", "mod")

        # Ключ уже видел 2 записи при выключенном дросселе? Нет: при first_n=0
        # учёт не вёлся вовсе, поэтому включённый дроссель начинает серию с нуля —
        # первая проходит, дальше душится.
        assert len(spy_after.written) == 1, "включение дросселя конфигом не подействовало"
        assert mgr._sampler.records_sampled_out >= 2


class TestSharedRecordIsNotMutated:
    """Аннотация «сколько подавлено» делается на КОПИИ.

    Словарь записи после Ф4.1 один на всех приёмников, а его ``extra`` держит
    ссылки на объекты вызывающего. Правка на месте испортила бы и запись
    соседним приёмникам, и данные того, кто её всего лишь залогировал.
    """

    def test_annotation_does_not_touch_the_incoming_dict(self) -> None:
        clock = _Clock()
        sampler = RateSampler(first_n=1, every_mth=2, burst_reset_sec=1000.0, time_fn=clock)
        caller_extra: Dict[str, Any] = {"trace_id": "abc"}

        record = {"message": "повтор", "extra": caller_extra}
        sampler("SYSTEM", LogLevel.DEBUG, dict(record))  # 1 — проходит
        sampler("SYSTEM", LogLevel.DEBUG, dict(record))  # 2 — подавлена
        annotated = sampler("SYSTEM", LogLevel.DEBUG, record)  # 3 — проходит с числом

        assert annotated is not None
        assert annotated is not record, "аннотация сделана на месте, а не на копии"
        assert annotated["extra"][SKIPPED_FIELD] == 1
        assert caller_extra == {"trace_id": "abc"}, f"словарь вызывающего испорчен: {caller_extra}"

    def test_clean_pass_travels_by_reference(self) -> None:
        """Цена: запись без подавлений едет ТЕМ ЖЕ словарём, копии нет.

        Контракт цепочки это разрешает, а копия на каждой записи была бы
        аллокацией ради ничего — записей без подавления большинство.
        """
        sampler = RateSampler(first_n=5, every_mth=1000, time_fn=_Clock())
        record = {"message": "первая"}
        assert sampler("SYSTEM", LogLevel.DEBUG, record) is record

    def test_disabled_sampler_returns_the_very_same_dict(self) -> None:
        sampler = RateSampler(first_n=0, time_fn=_Clock())
        record = {"message": "любая"}
        for _ in range(100):
            assert sampler("SYSTEM", LogLevel.DEBUG, record) is record
        assert sampler.keys_tracked == 0, "выключенный дроссель ведёт учёт — цена без пользы"


class TestSkippedCounterIsPerPass:
    """``sampled_skipped`` — «с прошлого пропуска», а не «за всё время».

    Накопительное число выглядело бы как растущая потеря там, где о ней уже
    сообщили: оператор читал бы одну и ту же потерю дважды.
    """

    def test_counter_resets_after_each_pass(self) -> None:
        clock = _Clock()
        sampler = RateSampler(first_n=1, every_mth=3, burst_reset_sec=1000.0, time_fn=clock)
        skipped: List[Any] = []

        for _ in range(10):
            result = sampler("SYSTEM", LogLevel.DEBUG, {"message": "повтор"})
            if result is not None:
                skipped.append(result.get("extra", {}).get(SKIPPED_FIELD))

        assert skipped == [None, 2, 2, 2], f"числа подавленных накапливаются: {skipped}"


class TestErrorPlaneHasNoSampling:
    """У плоскости ошибок полей сэмплинга нет вовсе — и это ответ, а не пробел."""

    def test_missing_config_fields_mean_disabled(self) -> None:
        class _NoSamplingConfig:
            pass

        mgr, spy = _logger()
        mgr._apply_sampling_config(_NoSamplingConfig())  # type: ignore[arg-type]

        for _ in range(50):
            mgr.log("SYSTEM", LogLevel.DEBUG, "повтор", "mod")

        assert len(spy.written) == 50
        assert mgr.get_stats()["records_sampled_out"] == 0


class TestConfigBoundaryRejectsUnknownLevel:
    """Имя уровня проверяется на границе — иначе опечатка глушила бы не тот уровень."""

    def test_unknown_sampling_max_level_is_rejected(self) -> None:
        with pytest.raises(Exception) as exc_info:
            LoggerCore(manager_name="BadLevel", config=_config(sampling_max_level="ЧТОТО"))
        assert "sampling_max_level" in str(exc_info.value)

    def test_alias_is_accepted(self) -> None:
        mgr, spy = _logger(sampling_first_n=1, sampling_every_mth=1000, sampling_max_level="WARN")
        for _ in range(5):
            mgr.log("SYSTEM", LogLevel.WARNING, "повтор", "mod")
        assert len(spy.written) == 1, "синоним WARN не раскрылся — дроссель не увидел уровень"
