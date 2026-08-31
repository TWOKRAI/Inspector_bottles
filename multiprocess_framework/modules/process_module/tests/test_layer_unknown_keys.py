# -*- coding: utf-8 -*-
"""Задача 5.4 — ИМЯ ключа судится на границе слоя, а не вердиктом после записи.

Основание — приёмка F2 2026-08-12, находки Н-C/Н-D, воспроизведено на живом
стенде до правки::

    config.reload {"observability": {"logger": {"default_level": "DEBUG"}}}
    → success=true
      session_keys=['logger.default_level']      # лёг в L3 со сроком
      effective.logger.default_level='INFO'      # и НЕ действует
      verified={'verdict': 'failed', 'unknown_keys': ['logger.default_level']}

То есть честный вердикт лежал в ТОМ ЖЕ ответе и противоречил `success`. Оператор
читает `success` — правда была этажом ниже. Мерило 2 плана требует буквально:
«мусор любого рода (значение, тип, ключ) — адресный отказ».

Сосед по предмету — `test_layer_value_validation.py` (ЗНАЧЕНИЯ объявленных
ключей, B2). Разведены не по важности, а по двери: ручка оператора отказывает,
файл — принимает и называет вслух, иначе опечатка в спутнике валила бы switch
рецепта (та же политика, что у ссылок без приёмника, `observability_refs`).
"""

from __future__ import annotations

import pytest

from ..configs.observability_layers import (
    LAYER_APP,
    LAYER_RECIPE,
    LAYER_SESSION,
    ObservabilityLayers,
    format_unknown_keys,
    unknown_section_keys,
    validate_layer_section,
)
from ..managers.observability_reload import observability_verified

#: Незнакомые имена. Первый — ровно тот вход, на котором приёмка получила
#: «успех»: машинная форма ключа, которой на этой границе нет.
UNKNOWN_NAME_SECTIONS = [
    ({"logger": {"default_level": "DEBUG"}}, "logger.default_level"),
    ({"log_levl": "DEBUG"}, "log_levl"),
    ({"errors": {"lvl": "ERROR"}}, "errors.lvl"),
    ({"нет_такой_ручки": 1}, "нет_такой_ручки"),
]

#: Законные имена, которые механизм round-trip'а МОГ БЫ объявить незнакомыми.
#: Каждый пункт — воспроизведённая ловушка, а не догадка: схема переименовывает
#: имя скоупа в верхний регистр, а про ключ `telemetry` не знает вовсе. Обе
#: давали ложный `unknown_keys` уже в вердикте 5.7 (проверено до правки); с
#: отказом на границе они стали бы отказом ЗАКОННОЙ правке.
LEGAL_NAME_SECTIONS = [
    ({"scopes": {"system": {"channels": ["console"]}}}, "имя скоупа строчными"),
    ({"scopes": {"SYSTEM": {"channels": ["console"]}}}, "имя скоупа заглавными"),
    ({"log_level": "INFO", "telemetry": {"publish": {"tick_sec": 1.0}}}, "телеметрия рядом"),
    ({"telemetry": {"throttle": {"processes.**.state.fps": 2.0}}}, "непрозрачный лист троттла"),
    ({"channels": {"messages_file": {"enabled": False}}}, "адресный канал логгера"),
    ({"errors": {"channels": {"errors_file": {"enabled": False}}}}, "канал плоскости ошибок"),
    ({"stats": {"channels": {"file_stats": {"enabled": False}}}}, "канал плоскости статистики"),
    ({"loggers": {"multiprocess_framework.modules.router_module": {"level": "DEBUG"}}}, "правило по имени"),
    ({"logger_groups": {"болтовня": ["a.b", "c.d"]}}, "ярлык набора источников"),
    ({"documents": {"factory": "m:f", "config": {"db_path": "x.db"}}}, "словарь фабрики документов"),
    ({"log_level": "INFO"}, "ключ со значением по умолчанию"),
    ({"scopes": {}}, "владение пустотой (правило Г3)"),
]


class TestSessionDoorRefusesUnknownNames:
    """Ручка оператора: незнакомое имя — отказ ДО записи, с адресом."""

    @pytest.mark.parametrize("section,address", UNKNOWN_NAME_SECTIONS)
    def test_whole_section_is_refused_with_the_path(self, section, address) -> None:
        with pytest.raises(ValueError) as exc:
            validate_layer_section(section, layer=LAYER_SESSION)
        assert address in str(exc.value), f"в отказе нет пути ключа: {exc.value}"

    def test_the_refusal_names_the_human_form_of_the_machine_key(self) -> None:
        """Подсказка обязана назвать ВЫХОД, а не только проблему.

        Приёмщик подал `logger.default_level` — машинную форму. Отказ без
        «имелось в виду log_level» оставил бы его там же, где он стоял: похожее
        по корню (`loggers`, `logger_groups`) есть, а нужное имя — не оно.
        """
        with pytest.raises(ValueError) as exc:
            validate_layer_section({"logger": {"default_level": "DEBUG"}}, layer=LAYER_SESSION)
        assert "log_level" in str(exc.value), exc.value

    @pytest.mark.parametrize("section,address", UNKNOWN_NAME_SECTIONS)
    def test_session_set_refuses_one_key_and_leaves_the_layer_empty(self, section, address) -> None:
        layers = ObservabilityLayers()
        value = section
        for part in address.split("."):
            value = value[part]
        with pytest.raises(ValueError):
            layers.session_set(address, value, origin="test")
        assert layers.session == {}, "незнакомый ключ всё равно лёг в сессию"
        assert layers.session_expiry == {}, "и съел срок"

    @pytest.mark.parametrize("section,title", LEGAL_NAME_SECTIONS)
    def test_legal_names_pass_the_same_door(self, section, title) -> None:
        """Пара к отказу: страж, срабатывающий всегда, не отличает мусор от настройки."""
        validate_layer_section(section, layer=LAYER_SESSION)

    def test_a_neighbour_is_not_poisoned_by_the_refusal(self) -> None:
        """Отказ не имеет права отравить следующую законную правку.

        Ровно этот класс уже стрелял на телеметрии (Н-4): отвергнутая правка
        оставалась в слое и валила соседа, который её не подавал.
        """
        layers = ObservabilityLayers()
        with pytest.raises(ValueError):
            layers.session_set("logger.default_level", "DEBUG", origin="test")
        layers.session_set("log_level", "DEBUG", origin="test")
        assert layers.session == {"log_level": "DEBUG"}
        assert layers.resolve()["log_level"] == "DEBUG", "законная правка не доехала до резолва"

    def test_a_good_key_alongside_an_unknown_one_does_not_smuggle_it_in(self) -> None:
        """Секция принимается ЦЕЛИКОМ или не принимается: половина хуже отказа."""
        with pytest.raises(ValueError) as exc:
            validate_layer_section({"log_level": "DEBUG", "log_levl": "X"}, layer=LAYER_SESSION)
        assert "log_levl" in str(exc.value), exc.value


class TestFileDoorNamesInsteadOfRefusing:
    """Файл: принято, но названо — в аудите и в строке журнала."""

    @pytest.mark.parametrize("layer", [LAYER_APP, LAYER_RECIPE])
    def test_the_section_still_lands_in_the_layer(self, layer) -> None:
        layers = ObservabilityLayers()
        keys = layers.replace_layer(
            layer, {"log_level": "DEBUG", "log_levl": "DEBUG"}, source="system.yaml", origin="test"
        )
        assert "log_levl" in keys, "файлу отказали — switch рецепта упал бы на опечатке"
        assert layers.audit.entries()[-1]["unknown_keys"] == ["log_levl"], layers.audit.entries()[-1]

    def test_the_journal_line_carries_them(self) -> None:
        """Кольцо аудита спрашивают редко; строку журнала читают в инциденте.

        Проверяем ФАКТ вывода через перехват `audit.log`, а не только формат:
        поле в записи, которого нет в строке, — тот же класс, что уже дал
        находку («страж существования ≠ страж содержимого»).
        """
        lines: list = []
        layers = ObservabilityLayers()
        layers.audit.log = lambda text, is_error: lines.append(text)
        layers.replace_layer(LAYER_APP, {"log_levl": "DEBUG"}, source="system.yaml", origin="test")
        assert lines, "запись слоя не оставила строки в журнале"
        assert "log_levl" in lines[-1], lines[-1]
        assert "эффекта нет" in lines[-1], lines[-1]

    def test_a_clean_file_says_nothing(self) -> None:
        """Пара: голос обязан молчать на здоровом конфиге, иначе он шум."""
        layers = ObservabilityLayers()
        layers.replace_layer(LAYER_APP, {"log_level": "DEBUG"}, source="system.yaml", origin="test")
        assert "unknown_keys" not in layers.audit.entries()[-1]

    def test_a_telemetry_key_in_a_file_is_not_a_stray_key(self) -> None:
        """Ключ `telemetry` — законный слой, а не опечатка. **Найдено инъекцией I3.**

        Предсказание разошлось с прогоном и вскрыло пробел: страж двери сессии
        снимает `telemetry` САМ (до вызова сверщика), поэтому снятие внутри
        сверщика доказывалось только вердиктом. А на файловой двери сверщик
        получает тело СЫРЫМ — и без снятия объявил бы «вне контракта» каждый
        путь телеметрии, то есть новый голос стал бы ложной тревогой на любом
        конфиге с секцией телеметрии.
        """
        layers = ObservabilityLayers()
        layers.replace_layer(
            LAYER_APP,
            {"log_level": "DEBUG", "telemetry": {"publish": {"tick_sec": 1.0}}},
            source="system.yaml",
            origin="test",
        )
        entry = layers.audit.entries()[-1]
        assert "unknown_keys" not in entry, entry


class TestOneAnswerForBothDoors:
    """Граница и вердикт считают имена ОДНОЙ функцией, а не двумя копиями."""

    @pytest.mark.parametrize("section,address", UNKNOWN_NAME_SECTIONS)
    def test_verdict_and_boundary_agree_on_unknown(self, section, address) -> None:
        assert unknown_section_keys(section) == observability_verified(section, {})["unknown_keys"] == [address]

    @pytest.mark.parametrize("section,title", LEGAL_NAME_SECTIONS)
    def test_verdict_and_boundary_agree_on_legal(self, section, title) -> None:
        assert unknown_section_keys(section) == observability_verified(section, {})["unknown_keys"] == []

    def test_a_bad_value_is_not_reported_as_an_unknown_name(self) -> None:
        """Один вход — одно объяснение. Мусорное ЗНАЧЕНИЕ судит сосед (B2).

        Иначе `log_level: "БОЛТОВНЯ"` получал бы «ключа нет в контракте» — то
        есть отказ уводил бы правку не туда, где ошибка.
        """
        assert unknown_section_keys({"log_level": "БОЛТОВНЯ"}) == []
        with pytest.raises(ValueError) as exc:
            validate_layer_section({"log_level": "БОЛТОВНЯ"}, layer=LAYER_SESSION)
        assert "log_level" in str(exc.value) and "DEBUG" in str(exc.value), exc.value

    def test_format_names_the_consequence_and_the_source(self) -> None:
        text = format_unknown_keys(["logger.default_level"], layer=LAYER_SESSION, source="system.yaml")
        assert "эффекта нет" in text and "system.yaml" in text, text


class TestCommandSurface:
    """Тот же отказ глазами оператора: ответ команды, а не исключение."""

    @staticmethod
    def _make():
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import test_observability_commands as H  # харнесс соседнего теста

        return H._make(logger=H._FakeLogger())

    @pytest.mark.parametrize("section,address", UNKNOWN_NAME_SECTIONS)
    def test_reload_refuses_and_the_session_stays_clean(self, section, address) -> None:
        from ..configs.observability_layers import process_observability_layers

        svc, cm = self._make()
        res = cm.dispatch("config.reload", {"observability": section})
        assert res["success"] is False, res
        assert address in str(res.get("reason", "")), res
        assert process_observability_layers(svc).session == {}, "незнакомый ключ дожил до L3"
        assert "verified" not in res, "отказ не имеет права нести вердикт применения"

    def test_the_answer_does_not_contradict_itself(self) -> None:
        """Мерило 2: `success` и вложенный вердикт обязаны говорить одно.

        До правки ответ нёс `success=true` И `verified.verdict='failed'` —
        именно эта пара и есть находка Н-C.
        """
        svc, cm = self._make()
        res = cm.dispatch("config.reload", {"observability": {"logger": {"default_level": "DEBUG"}}})
        verdict = (res.get("verified") or {}).get("verdict")
        assert not (res.get("success") is True and verdict == "failed"), res

    def test_a_legal_edit_through_the_same_door_still_applies(self) -> None:
        """Вторая половина пары: приём, а не только отказ — на самом опасном входе.

        Строчное имя скоупа выбрано намеренно: именно оно ложно объявлялось
        незнакомым до правки. Проверяются ДВА факта, потому что они разные:

        * в слое лежит написание ОПЕРАТОРА (`scopes.system`) — канон появляется
          не здесь, а на резолве, и `session_keys` показывает то, что человек
          написал;
        * раскладка приводит его к канону (`SYSTEM`) — то есть правка ДЕЙСТВУЕТ,
          а не просто лежит.
        """
        from ..configs.observability_config import expand_observability
        from ..configs.observability_layers import process_observability_layers

        svc, cm = self._make()
        res = cm.dispatch("config.reload", {"observability": {"scopes": {"system": {"channels": ["console"]}}}})
        assert res["success"] is True, res
        layers = process_observability_layers(svc)
        assert layers.session == {"scopes": {"system": {"channels": ["console"]}}}
        applied = expand_observability(layers.resolve())["logger"]["scopes"]
        assert applied == {"SYSTEM": {"channels": ["console"]}}, applied
