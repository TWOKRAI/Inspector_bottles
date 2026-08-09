# -*- coding: utf-8 -*-
"""B2 — мусор не доживает до слоя: `success=true` ⇔ «валидно, сохранено и действует».

Основание — major-8 приёмочного ревью 2026-08-09, воспроизведено до правки
(`config.reload` с `observability={"log_level": "БОЛТОВНЯ"}`)::

    success   : True
    session   : {'log_level': 'БОЛТОВНЯ'}
    effective : None            # действует прежний уровень

То же на двух соседних ручках: `errors.level="ЧУШЬ"` и `stats.log_level="ЕРУНДА"`
ложились в L3 с тем же успехом. Проверка имени уровня стояла НА РЕЗОЛВЕ (в
`LoggerManagerConfig`), то есть срабатывала уже после того, как значение
записано в слой: применение откатывалось, ответ рапортовал успех, а мусор
оставался лежать в сессии со сроком.

Дефект, починенный на одном пути из четырёх, воскресает на соседних развилках,
поэтому тесты параметризованы по СЛОЯМ: L1 (файл/`replace_layer`), L2 (рецепт),
L3 (сессия — и целой секцией, и одним ключом через `session_set`), плюс
persist-путь, который переносит L3 в L2.

**Граница правила названа вслух.** Проверяются ЗНАЧЕНИЯ объявленных ключей.
Незнакомый ключ (`log_levl`) схемой молча отбрасывается и ловится не здесь, а
вердиктом `config.reload` (`unknown_keys` → `verdict=failed`) — второй
предохранитель на то же место сделал бы неизвестным, который из них держит.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ..configs.observability_layers import (
    LAYER_APP,
    LAYER_RECIPE,
    ObservabilityLayers,
    validate_layer_section,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))

#: Три ручки уровня в трёх разных секциях — у каждой свой адрес, и адрес обязан
#: приехать в отказе: WARNING без адреса ключа уже был находкой Ф8.5.
BAD_SECTIONS = [
    ({"log_level": "БОЛТОВНЯ"}, "log_level"),
    ({"errors": {"level": "ЧУШЬ"}}, "errors.level"),
    ({"stats": {"log_level": "ЕРУНДА"}}, "stats.log_level"),
]

GOOD_SECTIONS = [
    ({"log_level": "DEBUG"}, "log_level"),
    ({"errors": {"level": "ERROR"}}, "errors.level"),
    ({"stats": {"log_level": "warning"}}, "stats.log_level"),
]


class TestValidatorItself:
    @pytest.mark.parametrize("section,address", BAD_SECTIONS)
    def test_rejection_names_the_key_and_the_allowed_values(self, section, address) -> None:
        with pytest.raises(ValueError) as exc:
            validate_layer_section(section, layer=LAYER_APP)
        message = str(exc.value)
        assert address in message, f"в отказе нет адреса ключа: {message}"
        assert "DEBUG" in message and "CRITICAL" in message, f"в отказе нет списка допустимых: {message}"

    @pytest.mark.parametrize("section,address", GOOD_SECTIONS)
    def test_valid_value_passes(self, section, address) -> None:
        """Пара к отказу: детектор, срабатывающий всегда, не отличает мусор от настройки."""
        validate_layer_section(section, layer=LAYER_APP)

    def test_alias_and_lower_case_are_accepted(self) -> None:
        validate_layer_section({"log_level": "warn"}, layer=LAYER_APP)

    def test_unknown_key_is_not_this_guard_business(self) -> None:
        """Опечатка в ИМЕНИ ключа судится вердиктом (`unknown_keys`), не здесь."""
        validate_layer_section({"log_levl": "DEBUG"}, layer=LAYER_APP)


class TestEveryLayerRejectsTheSameWay:
    @pytest.mark.parametrize("section,address", BAD_SECTIONS)
    @pytest.mark.parametrize("layer", [LAYER_APP, LAYER_RECIPE])
    def test_replace_layer_refuses(self, layer, section, address) -> None:
        layers = ObservabilityLayers()
        with pytest.raises(ValueError) as exc:
            layers.replace_layer(layer, section, source="проба", origin="test")
        assert address in str(exc.value)
        assert getattr(layers, layer) == {}, "отвергнутая секция всё равно легла в слой"

    @pytest.mark.parametrize("section,address", BAD_SECTIONS)
    def test_session_set_refuses_a_single_key(self, section, address) -> None:
        layers = ObservabilityLayers()
        value = section
        for part in address.split("."):
            value = value[part]
        with pytest.raises(ValueError) as exc:
            layers.session_set(address, value, origin="test")
        assert address in str(exc.value)
        assert layers.session == {}, "отвергнутое значение всё равно легло в сессию"
        assert layers.session_keys() == ()

    def test_session_set_still_accepts_a_valid_key(self) -> None:
        layers = ObservabilityLayers()
        layers.session_set("log_level", "DEBUG", origin="test")
        assert layers.session == {"log_level": "DEBUG"}

    def test_sink_toggle_path_is_not_broken_by_the_guard(self) -> None:
        """Путь `logger.sink.disable` пишет вложенный ключ — он обязан пройти."""
        layers = ObservabilityLayers()
        layers.session_set("channels.messages_file.enabled", False, origin="test")
        assert layers.session == {"channels": {"messages_file": {"enabled": False}}}

    def test_opaque_telemetry_path_is_not_judged_by_this_schema(self) -> None:
        """Непрозрачный лист телеметрии схемой наблюдаемости не описан — не судим."""
        layers = ObservabilityLayers()
        layers.session_set("telemetry.throttle", {"processes.**.state.fps": 2.0}, origin="test")
        assert "telemetry" in layers.session


class TestCommandSurface:
    """Тот же отказ, но глазами оператора: ответ команды, а не исключение."""

    @staticmethod
    def _make():
        import test_observability_commands as H  # харнесс соседнего теста

        return H._make(logger=H._FakeLogger())

    @pytest.mark.parametrize("section,address", BAD_SECTIONS)
    def test_reload_refuses_and_the_session_stays_clean(self, section, address) -> None:
        from ..configs.observability_layers import process_observability_layers

        svc, cm = self._make()
        res = cm.dispatch("config.reload", {"observability": section})
        assert res["success"] is False, res
        assert address in str(res.get("reason", "")), res
        assert "DEBUG" in str(res.get("reason", "")), res
        assert process_observability_layers(svc).session == {}, "мусор дожил до L3"

    def test_valid_reload_still_applies(self) -> None:
        """Вторая половина пары: приём, а не только отказ."""
        from ..configs.observability_layers import process_observability_layers

        svc, cm = self._make()
        res = cm.dispatch("config.reload", {"observability": {"log_level": "DEBUG"}})
        assert res["success"] is True, res
        assert process_observability_layers(svc).session == {"log_level": "DEBUG"}


class TestPersistInheritsTheGuarantee:
    def test_persist_moves_only_validated_keys(self, tmp_path: Path) -> None:
        """L3 → L2 переносит то, что уже прошло проверку на записи в L3.

        Отдельный тест, а не «очевидно из построения»: persist ходит своим
        путём (`replace_layer(LAYER_RECIPE, ...)`), и если бы проверка стояла
        только в командном хендлере, этот путь остался бы дырой.
        """
        layers = ObservabilityLayers()
        layers.session_set("log_level", "DEBUG", origin="test")
        with pytest.raises(ValueError):
            layers.session_set("log_level", "БОЛТОВНЯ", origin="test")
        assert layers.session == {"log_level": "DEBUG"}
        layers.replace_layer(LAYER_RECIPE, dict(layers.session), source=str(tmp_path), origin="test")
        assert layers.recipe == {"log_level": "DEBUG"}
