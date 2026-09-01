"""Ответ ``config.reload`` о ручках окна голоса обязан говорить ПРАВДУ (Ф2, дыра инъекции B2).

Найдено матрицей инъекций Ф2, заплата **B2**: в
``observability_wiring.apply_voices_policy`` возвращаемое значение
``max_tracked_keys`` было подменено литералом ``512`` — и из **928 собранных
тестов не покраснел ни один**.

Почему ноль, хотя readback вроде бы сторожится. Readback'ов у этих ручек ДВА, и
это разные поверхности:

1. **Живой** — ``observability_reload.observability_effective`` (строки 409–410),
   читает действующие геттеры ``max_tracked_keys()``/``stale_windows()``. Его
   сторожат тесты Task 2.7, и заплата B1 (геттер игнорирует политику) роняет
   четыре из них.
2. **Ответ применения** — ``apply_voices_policy`` возвращает то, что попадает в
   ``expanded[VOICES_SECTION_KEY]`` (``observability_reload.py:1094-1096``), то
   есть в ОТВЕТ ``config.reload`` оператору: «вот что я применил». Соврать здесь
   можно свободно.

Единственный тест, смотревший на эту поверхность
(``test_voices_policy_road_guards.TestRebuildReachesTheLiveMechanism::
test_the_answer_uses_schema_field_names``), подаёт секцию, которая
``max_tracked_keys`` НЕ называет, и ждёт схемный дефолт ``512``. Заплата
прибивала ответ тем же самым числом — правда и ложь совпали ровно в той точке,
где кто-то смотрел. Это класс «инъекция обязана смотреть другим объективом, чем
тест», только с обратной стороны: тест выбрал объектив, в котором поломка
неотличима от исправности.

Сторож ниже закрывает разницу: секция называет значения, ОТЛИЧНЫЕ от L0-дефолтов,
и ответ обязан повторить именно их. Литералы здесь намеренно не 512/10 — иначе
тест вернулся бы в ту же слепую точку.
"""

from __future__ import annotations

from typing import Iterator

import pytest

from multiprocess_framework.modules.logger_module.core.windowed_voice import (
    max_tracked_keys,
    reset_voices_policy,
    stale_windows,
)
from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    apply_voices_policy,
)

#: Значения СПЕЦИАЛЬНО не равны L0-дефолтам (512 и 10): совпадение ожидаемого
#: значения с встроенной константой и было причиной, по которой дыра дожила до
#: инъекции.
CAP = 2048
STALE = 7


@pytest.fixture(autouse=True)
def _isolated_policy() -> Iterator[None]:
    """Политика ПРОЦЕССНАЯ: без сброса тесты видели бы след соседа."""
    reset_voices_policy()
    yield
    reset_voices_policy()


class TestTheReloadAnswerReportsTheEffectiveCapacity:
    """Ответ применения = то, что реально в силе, а не встроенная константа."""

    def test_the_answer_repeats_the_named_capacity_not_the_builtin_default(self) -> None:
        applied = apply_voices_policy({"max_tracked_keys": CAP, "stale_windows": STALE})

        assert applied is not None, "секция подана — применение обязано состояться"
        assert applied["max_tracked_keys"] == CAP, (
            f"ответ config.reload назвал {applied['max_tracked_keys']} вместо {CAP} — "
            "оператор читает это как подтверждение применения"
        )
        assert applied["stale_windows"] == STALE, (
            f"ответ config.reload назвал {applied['stale_windows']} вместо {STALE}"
        )

    def test_the_answer_agrees_with_what_is_actually_in_force(self) -> None:
        """Пара к предыдущему: ответ сверяется с ДЕЙСТВУЮЩИМ значением.

        Первый тест ловит ответ, разошедшийся с запросом; этот — ответ,
        разошедшийся с механизмом. Две разные поломки: «соврал про вход» и
        «сказал правду про вход, но применил другое».
        """
        applied = apply_voices_policy({"max_tracked_keys": CAP, "stale_windows": STALE})

        assert applied is not None
        assert (applied["max_tracked_keys"], applied["stale_windows"]) == (
            max_tracked_keys(),
            stale_windows(),
        ), "ответ применения разошёлся с действующей политикой процесса"
