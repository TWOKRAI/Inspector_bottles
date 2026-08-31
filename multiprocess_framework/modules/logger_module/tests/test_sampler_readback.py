# -*- coding: utf-8 -*-
"""Readback действующих параметров дросселя (задача 4.4) — стражи автора.

Заведено живым прогоном: оператор включал дроссель командой ``config.reload``
на работающем процессе и получал вердикт ``unverifiable`` — ручка подана,
подтвердить нечем. Здесь сторожится ровно то, что делает ручку подтверждаемой:

  * readback отдаёт ЧЕТЫРЕ пути, по которым едет запрос (иначе вердикт снова
    станет «не проверено», и это будет тихо);
  * числа берутся у САМОГО процессора, а не у конфига менеджера — расхождение
    «конфиг принят, до сэмплера не доехало» обязано быть видно;
  * потолок показывается ДЕЙСТВУЮЩИМ: конфиг не вправе поднять его до ошибок,
    и readback, повторяющий запрос, врал бы ровно в этом месте.
"""

from __future__ import annotations

from typing import Any, Dict, List

from multiprocess_framework.modules.channel_routing_module.interfaces import IChannel
from multiprocess_framework.modules.logger_module.core.logger_core import LoggerCore
from multiprocess_framework.modules.logger_module.core.sampling import RateSampler

#: Ключи readback'а — те же имена, что у полей секции ``observability``. Список
#: литералом: производная от схемы согласилась бы с любым её изменением, включая
#: снятие ключа, ради которого страж и стоит.
READBACK_KEYS = (
    "sampling_first_n",
    "sampling_every_mth",
    "sampling_burst_reset_sec",
    "sampling_max_level",
)


class _SpyChannel(IChannel):
    """Канал-шпион (наследование обязательно: реестр отвергает утиный тип)."""

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
    config: Dict[str, Any] = {
        "app_name": "sampler_readback",
        "enable_batching": False,
        "channels": {},
        "default_level": "DEBUG",
        "scopes": {"SYSTEM": {"channels": ["a"]}},
    }
    config.update(sampling)
    return config


def _logger(**sampling: Any) -> LoggerCore:
    mgr = LoggerCore(manager_name="ReadbackLogger", config=_config(**sampling))
    mgr.initialize()
    mgr.register_channel(_SpyChannel("a"))
    return mgr


class TestSamplerReadback:
    """Сам процессор отвечает за то, что действует."""

    def test_reports_all_four_knobs(self) -> None:
        """Все четыре пути присутствуют — иначе вердикт снова «не проверено»."""
        sampler = RateSampler(first_n=7, every_mth=333, burst_reset_sec=11.5, max_level="INFO")

        readback = sampler.readback()

        assert set(readback) == set(READBACK_KEYS), f"readback отдал {sorted(readback)}"

    def test_values_are_the_acting_ones(self) -> None:
        """Числа — литералами, не производными от испытуемого."""
        sampler = RateSampler(first_n=7, every_mth=333, burst_reset_sec=11.5, max_level="INFO")

        assert sampler.readback() == {
            "sampling_first_n": 7,
            "sampling_every_mth": 333,
            "sampling_burst_reset_sec": 11.5,
            "sampling_max_level": "INFO",
        }

    def test_ceiling_above_errors_is_reported_clamped(self) -> None:
        """Просили CRITICAL — действует WARNING, и readback говорит именно это.

        Обрезка живёт в ``configure``; readback, повторяющий ЗАПРОС, показал бы
        оператору потолок, которого нет ни на одной записи.
        """
        sampler = RateSampler(first_n=1, max_level="CRITICAL")

        assert sampler.readback()["sampling_max_level"] == "WARNING"
        assert RateSampler(first_n=1, max_level="ERROR").readback()["sampling_max_level"] == "WARNING"

    def test_every_mth_is_reported_after_normalisation(self) -> None:
        """Ноль как «каждая M-я» невозможен: ``configure`` поднимает его до 1."""
        sampler = RateSampler(first_n=1, every_mth=0)

        assert sampler.readback()["sampling_every_mth"] == 1

    def test_disabled_sampler_says_so_by_the_parameter(self) -> None:
        """Выключенность выражена параметром — readback её и показывает."""
        assert RateSampler().readback()["sampling_first_n"] == 0


class TestManagerFacade:
    """Менеджер спрашивает процессор, а не свой конфиг."""

    def test_manager_reports_configured_sampling(self) -> None:
        mgr = _logger(sampling_first_n=4, sampling_every_mth=250, sampling_burst_reset_sec=9.0)

        assert mgr.sampling_readback() == {
            "sampling_first_n": 4,
            "sampling_every_mth": 250,
            "sampling_burst_reset_sec": 9.0,
            "sampling_max_level": "DEBUG",
        }

    def test_reads_the_object_in_the_chain_not_the_config(self) -> None:
        """Правка, до сэмплера не доехавшая, обязана быть ВИДНА расхождением.

        Конфигу менеджера присваивается новое значение мимо ``configure`` — то
        есть воспроизводится ровно тот отказ, ради которого readback и заведён.
        Ответ обязан остаться прежним: показывать надо действующее.
        """
        mgr = _logger(sampling_first_n=4, sampling_every_mth=250)

        mgr.config.sampling_first_n = 999

        assert mgr.sampling_readback()["sampling_first_n"] == 4

    def test_reconfigure_moves_the_readback(self) -> None:
        """Штатный путь смены конфига readback ДВИГАЕТ — иначе он мёртв."""
        mgr = _logger(sampling_first_n=4, sampling_every_mth=250)

        assert mgr.reconfigure(_config(sampling_first_n=6, sampling_every_mth=700)) is True

        assert mgr.sampling_readback()["sampling_first_n"] == 6
        assert mgr.sampling_readback()["sampling_every_mth"] == 700
