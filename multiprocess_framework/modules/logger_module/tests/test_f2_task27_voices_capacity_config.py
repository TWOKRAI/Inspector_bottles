# -*- coding: utf-8 -*-
"""Task 2.7 плана observability-closure (добор ревью Ф1) — независимый тестер.

Критерий приёмки 2 (текст задачи, передан координатором; план
``phase-2-one-policy.md`` и реализация мне не показаны):

    «MAX_TRACKED_KEYS/_STALE_WINDOWS -> observability.voices.* (L0-дефолты те же:
    512 и 10), readback ЭФФЕКТИВНОГО значения + счётчик насыщения (по образцу
    sampler_keys_tracked/sampler_keys_saturated). introspect.observability
    показывает эффективные значения бывших литералов; изменение ключа конфига
    меняет ЭФФЕКТИВНОЕ значение в readback (не только принятое).»

Сегодня (2026-09-01, до реализации) в ``windowed_voice.py`` ``MAX_TRACKED_KEYS = 512``
и ``_STALE_WINDOWS = 10`` — МОДУЛЬНЫЕ КОНСТАНТЫ, не читаемые ни из какого конфига
(сверено чтением всего файла): ``set_voices_policy`` принимает только
``window_sec``/``escalate_after``, у ``ObservabilityVoicesConfig`` — только поля
``default_window_sec``/``escalate_after_repeats`` (сверено чтением класса,
``modules/process_module/configs/observability_config.py:123-165``), а
``observability_effective()`` публикует в секцию ``voices`` только эти же два поля
(``modules/process_module/managers/observability_reload.py:395-399``). Ни потолка
карты, ни такта протухания, ни счётчика насыщения там нет.

Три уровня контракта — три класса тестов ниже:

1. **Схема.** ``ObservabilityVoicesConfig`` обязана принимать
   ``max_tracked_keys``/``stale_windows`` и round-trip'ить их (см. память проекта
   "Pydantic extra=ignore hides RED" — прямое чтение атрибута, не факт того, что
   конструктор не бросил).
2. **Действующее ограничение.** ``set_voices_policy(max_tracked_keys=...)`` обязана
   МЕНЯТЬ реальный потолок ``WindowedVoices.take()`` — ручка, которая принимается
   схемой и не доходит до механизма, неотличима от отсутствующей (память проекта
   "ручка применена ≠ подтверждена").
3. **Readback.** ``observability_effective()["voices"]`` обязана показывать
   ЭФФЕКТИВНЫЕ (не запрошенные) значения — та же функция, что уже отдаёт
   ``default_window_sec``/``escalate_after_repeats`` БЕЗУСЛОВНО (без менеджеров,
   Task 1.4), поэтому вызывается напрямую, без похода через ``BuiltinCommands``.

Ожидание по красноте: все тесты этого файла — RED. Символ отказа — либо
``TypeError: unexpected keyword argument`` (симптом «параметр ещё не существует» —
тот же класс, что ``AttributeError`` для отсутствующего символа в RED-протоколе),
либо ``AssertionError`` на конкретном значении/потолке.
"""

from __future__ import annotations

from multiprocess_framework.modules.logger_module.core.windowed_voice import (
    WindowedVoices,
    reset_voices_policy,
    set_voices_policy,
)
from multiprocess_framework.modules.process_module.configs.observability_config import (
    ObservabilityVoicesConfig,
)
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    observability_effective,
)

#: Литералы запроса — намеренно НЕ совпадающие со встроенными дефолтами (512/10),
#: чтобы совпадение результата с запросом было уликой чтения из конфига, а не
#: случайным согласием с захардкоженным числом (тот же приём, что WINDOW=17.25 в
#: соседнем test_voices_policy_road_guards.py).
_DISTINCT_MAX_TRACKED_KEYS = 777
_DISTINCT_STALE_WINDOWS = 42


class TestVoicesCapacityIsAConfigField:
    """Схема принимает бывшие литералы как поля, с прежними L0-дефолтами."""

    def test_max_tracked_keys_and_stale_windows_round_trip(self) -> None:
        cfg = ObservabilityVoicesConfig.model_validate(
            {
                "max_tracked_keys": _DISTINCT_MAX_TRACKED_KEYS,
                "stale_windows": _DISTINCT_STALE_WINDOWS,
            }
        )
        assert cfg.max_tracked_keys == _DISTINCT_MAX_TRACKED_KEYS, (
            "observability.voices.max_tracked_keys не существует как поле схемы (или "
            "не round-trip'ится) — MAX_TRACKED_KEYS всё ещё зашит литералом в windowed_voice.py"
        )
        assert cfg.stale_windows == _DISTINCT_STALE_WINDOWS, (
            "observability.voices.stale_windows не существует как поле схемы (или не "
            "round-trip'ится) — _STALE_WINDOWS всё ещё зашит литералом в windowed_voice.py"
        )

    def test_builtin_defaults_match_the_literals_being_replaced(self) -> None:
        """L0-дефолты схемы обязаны совпасть с сегодняшними литералами (512 и 10) —
        задача переносит литералы в конфиг БЕЗ смены поведения по умолчанию."""
        cfg = ObservabilityVoicesConfig()
        assert cfg.max_tracked_keys == 512, (
            f"дефолт max_tracked_keys обязан остаться 512 (текущий MAX_TRACKED_KEYS), "
            f"получено {getattr(cfg, 'max_tracked_keys', None)!r}"
        )
        assert cfg.stale_windows == 10, (
            f"дефолт stale_windows обязан остаться 10 (текущий _STALE_WINDOWS), "
            f"получено {getattr(cfg, 'stale_windows', None)!r}"
        )


class TestVoicesCapacityKnobsChangeEnforcement:
    """Ручка не украшение: применённое значение обязано реально ограничивать держатель окон."""

    def setup_method(self) -> None:
        reset_voices_policy()

    def teardown_method(self) -> None:
        reset_voices_policy()

    def test_configured_max_tracked_keys_caps_the_live_window_map(self) -> None:
        """set_voices_policy(max_tracked_keys=5) обязана менять РЕАЛЬНЫЙ потолок
        WindowedVoices.take() — иначе ручка принимается и лежит мёртвым грузом
        (память проекта "ручка применена ≠ подтверждена")."""
        set_voices_policy(max_tracked_keys=5, stale_windows=1000)

        voices = WindowedVoices()
        # 20 РАЗНЫХ ключей подряд с длинным окном (1000с — заведомо не протухнут за
        # время теста) — заведомо больше сконфигурированного потолка (5). Если
        # потолок всё ещё захардкожен на 512, все 20 останутся живы.
        for i in range(20):
            voices.take(f"probe-key-{i}", interval=1000.0)

        assert voices.tracked_keys() <= 5, (
            f"эффективный потолок карты окон не совпал со сконфигурированным (5): "
            f"живых ключей осталось {voices.tracked_keys()} из 20 — похоже, всё ещё "
            f"действует захардкоженный MAX_TRACKED_KEYS=512, а не значение из политики"
        )

    def test_configured_stale_windows_changes_when_silent_keys_are_swept(self) -> None:
        """set_voices_policy(stale_windows=2) обязана менять такт протухания.

        Различить «подмело по протуханию» от «подмело по приоритету при нехватке
        места» одним выжившим ключом нельзя (оба механизма при потолке 1 упор
        выбрасывают САМЫЙ старый недолжник — совпадают по итогу). Разводит их
        число: подметание протухших — БЕЗУСЛОВНОЕ и разом (``_sweep_locked``,
        первый цикл, снимает ВСЕ квалифицирующиеся ключи за один проход и не
        считается «выброшенными»), а откат по приоритету при нехватке места —
        РОВНО по одному на превышение. Три протухших недолжника (A, B, C) плюс
        один свежий должник (D, не тронет ни один механизм) плюс ОДИН вызов,
        поднимающий карту выше потолка (4 > 3):

        * ``stale_windows`` ЧИТАЕТСЯ (2 своих окна) → A, B, C протухли (возраст
          3 окна > 2) → сняты ВСЕ ТРИ разом (население 5 → 2: D и триггер), откат
          по приоритету не нужен вовсе (население уже не выше потолка).
        * ``stale_windows`` ВСЁ ЕЩЁ захардкожен (10) → возраст 3 окна < 10, ни
          один не протух → откат по приоритету снимает РОВНО столько, сколько не
          хватает до потолка (5 → 3, население ОСТАНАВЛИВАЕТСЯ на потолке, а не
          падает ниже).

        Итоговое население — 2 при честном ``stale_windows`` против 3 при
        захардкоженном — и есть наблюдаемое различие, не зависящее от того, что
        именно (протухание или приоритет) выбрало БЫ ту же самую жертву.
        """
        window = 1.0
        clock = [0.0]
        voices = WindowedVoices(clock=lambda: clock[0])
        set_voices_policy(max_tracked_keys=3, stale_windows=2)

        # Три немолчаливых недолжника (suppressed=0) — потенциальные жертвы ОБОИХ
        # механизмов.
        voices.take("stale-a", interval=window)
        voices.take("stale-b", interval=window)
        voices.take("stale-c", interval=window)
        # Один должник (suppressed>0) — priority-откат его не тронет НИКОГДА
        # (недолжники идут первыми по сортировке), а протухание — тоже (условие
        # первого цикла ``e[1] == 0`` требует нулевой недоимки).
        voices.take("debtor-d", interval=window)
        voices.take("debtor-d", interval=window)

        # Возраст A/B/C к моменту триггера — 3 своих окна: больше сконфигурированных
        # 2 (протухли БЫ), меньше захардкоженных 10 (не протухли БЫ).
        clock[0] += window * 3

        # Вставка НОВОГО ключа поднимает население с 4 до 5 > потолка(3) — ЕДИНСТВЕННЫЙ
        # вызов, запускающий подметание в этом тесте.
        voices.take("trigger-e", interval=window)

        assert voices.tracked_keys() == 2, (
            f"после подметания живо {voices.tracked_keys()} ключей (ожидалось 2 — "
            f"'debtor-d' и 'trigger-e', A/B/C протухли РАЗОМ по stale_windows=2). "
            f"Если протухания не случилось, откат по приоритету снял бы ровно "
            f"столько, сколько не хватает до потолка, и население ЗАСТРЯЛО бы на "
            f"потолке (3) — это и есть симптом захардкоженного _STALE_WINDOWS=10, "
            f"не читающего политику"
        )


class TestVoicesCapacityReadbackShowsEffectiveValues:
    """introspect.observability (через observability_effective()) — эффективные значения."""

    def setup_method(self) -> None:
        reset_voices_policy()

    def teardown_method(self) -> None:
        reset_voices_policy()

    def test_effective_voices_reports_configured_capacity(self) -> None:
        set_voices_policy(max_tracked_keys=128, stale_windows=4)

        effective = observability_effective()
        voices = effective.get("voices", {})

        assert voices.get("max_tracked_keys") == 128, (
            f"observability_effective()['voices'] не показывает ЭФФЕКТИВНЫЙ потолок "
            f"карты (бывший литерал MAX_TRACKED_KEYS): {voices!r}"
        )
        assert voices.get("stale_windows") == 4, (
            f"observability_effective()['voices'] не показывает ЭФФЕКТИВНЫЙ такт "
            f"протухания (бывший литерал _STALE_WINDOWS): {voices!r}"
        )

    def test_effective_voices_reflects_a_change_not_just_the_accepted_request(self) -> None:
        """Дважды применённая РАЗНАЯ политика — readback обязан отражать ВТОРОЕ
        значение, а не первое (эффективное, не эхо первого принятого запроса)."""
        set_voices_policy(max_tracked_keys=100, stale_windows=2)
        set_voices_policy(max_tracked_keys=999, stale_windows=7)

        voices = observability_effective().get("voices", {})

        assert voices.get("max_tracked_keys") == 999, (
            f"readback не поспел за ВТОРЫМ применением — застрял на первом значении: {voices!r}"
        )
        assert voices.get("stale_windows") == 7, (
            f"readback не поспел за ВТОРЫМ применением — застрял на первом значении: {voices!r}"
        )
