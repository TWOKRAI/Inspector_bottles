# -*- coding: utf-8 -*-
"""Ф2, задача 2.12 — тесты АВТОРА на опасности механизма дросселя ``stats.enabled``.

Приёмка (``test_f2_task212_repurposed_voice_window.py``) проверяет контракт
СНАРУЖИ: сколько голосов и с каким текстом. Здесь — то, что видно только тому,
кто знает, КАК механизм построен: держатель окон резолвится на каждый вызов
(а не захватывается при импорте), лок держателя не удерживается на время
эмиссии, вход не проверен по типу (произвольный оператор конфига), и потолок
карты ключей — общий процессный ресурс, за который отвечает не эта функция.

Ключ голоса — ``"stats.enabled.repurposed"`` (Р-12) — тот же, что использует
``_complain_about_repurposed_enabled``; тесты не привязаны к внутреннему имени
функции (правило проекта «шпион на имя стережёт имя, а не свойство»): они
читают ``caplog`` по тексту записи, как и приёмка.
"""

from __future__ import annotations

import logging
import re
import threading
import time

import pytest

from multiprocess_framework.modules.logger_module.core.windowed_voice import (
    max_tracked_keys,
    process_voices,
    reset_process_voices,
    reset_voice_counters,
    reset_voices_policy,
    set_voices_policy,
)
from multiprocess_framework.modules.process_module.configs.observability_config import (
    ObservabilityConfig,
    ObservabilityStatsConfig,
)

_KEY = "stats.enabled.repurposed"


@pytest.fixture(autouse=True)
def _clean_process_wide_voice_state():
    """Тот же процессный держатель, что читает приёмка — сбрасывать вокруг КАЖДОГО теста.

    Без этого порядок тестов внутри файла (а тем более между файлами — см. отчёт
    задачи, раздел про соседей) решал бы, увидит ли следующий тест первый голос
    или подавленный. Это не страховка «на всякий случай»: без сброса тест
    насыщения карты ключей (см. ниже) оставил бы держатель раздутым для всех
    остальных тестов процесса.
    """
    reset_process_voices()
    reset_voice_counters()
    yield
    reset_process_voices()
    reset_voice_counters()


class _FakeClock:
    """Управляемые часы для ``monkeypatch.setattr(time, "monotonic", ...)``.

    Тот же приём, что у приёмки: держатель окон читает ``time.monotonic``
    (см. ``WindowedVoices.__init__`` — ``clock=None`` при создании держателя по
    умолчанию), поэтому глобальная подмена нужна и здесь.
    """

    def __init__(self, start: float) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, dt: float) -> None:
        self._now += dt


def _fake_clock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    clock = _FakeClock(time.monotonic())
    monkeypatch.setattr(time, "monotonic", clock)
    return clock


def _voices(caplog: pytest.LogCaptureFixture) -> list:
    return [
        r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING and "stats.enabled" in r.getMessage()
    ]


# =========================================================================== #
# 1 — держатель резолвится НА КАЖДЫЙ вызов, а не захвачен при импорте          #
# =========================================================================== #
class TestHolderIsResolvedPerCallNotCapturedAtImport:
    """Опасность 1 (названа в задаче явно): если бы валидатор держал ссылку на
    держатель окон, схваченную ОДИН раз (модульная переменная при импорте или
    замыкание), ``reset_process_voices()`` подменяет глобальный держатель
    ЦЕЛИКОМ (новый объект ``WindowedVoices()``) — и захваченная ссылка
    продолжала бы смотреть на СТАРЫЙ объект. Тогда сброс между тестами не
    работал бы: старое состояние (окно ``stats.enabled.repurposed`` ещё не
    истекло) утекало бы в следующий тест, который ожидает свежий голос.
    """

    def test_reset_process_voices_is_visible_to_the_validator(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING)

        ObservabilityConfig.model_validate({"stats": {"enabled": False}})
        assert len(_voices(caplog)) == 1, "первый голос обязан прозвучать — иначе тест ничего не проверяет"
        caplog.clear()

        # Внутри окна — молчит (используем это как контроль: без сброса
        # следующий вызов остался бы тихим).
        ObservabilityConfig.model_validate({"stats": {"enabled": False}})
        assert _voices(caplog) == [], "второй вызов внутри окна не обязан быть тихим — тест не воспроизвёл базу"
        caplog.clear()

        # Сброс держателя. Если валидатор резолвит ``process_voices()`` на
        # каждый вызов (а не хранит старую ссылку), следующий вызов увидит
        # НОВЫЙ пустой держатель и заговорит немедленно — для него это первый
        # раз по новому ключу.
        reset_process_voices()
        ObservabilityConfig.model_validate({"stats": {"enabled": False}})
        assert len(_voices(caplog)) == 1, (
            "голос не прозвучал сразу после reset_process_voices() — валидатор, похоже, держит "
            "ссылку на держатель, схваченную один раз, а не резолвит process_voices() на каждый вызов"
        )


# =========================================================================== #
# 2 — N параллельных чтений одного и того же ключа                            #
# =========================================================================== #
class TestConcurrentValidationsGiveOneVoiceAndCountEverySuppression:
    """Опасность 2: N потоков валидируют конфиг ОДНОВРЕМЕННО.

    Голос обязан прозвучать РОВНО один раз (первый вызов создаёт ключ и держит
    лок держателя на время своей проверки — конкуренты ждут лока, а не гонятся
    за состоянием), а остальные N-1 обязаны быть УЧТЕНЫ, а не потеряны гонкой на
    инкременте счётчика подавленных: это проверяется ВТОРЫМ голосом после
    истечения окна, который обязан назвать РОВНО N-1.

    Поток, который зависает вместо ошибки, хуже отсутствующего — join с
    дедлайном, а не бесконечное ожидание.
    """

    def test_n_concurrent_validations_count_every_suppression_exactly(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clock = _fake_clock(monkeypatch)
        caplog.set_level(logging.WARNING)

        n = 20
        barrier = threading.Barrier(n)
        errors: list = []

        def _worker() -> None:
            try:
                barrier.wait(timeout=5.0)
                ObservabilityConfig.model_validate({"stats": {"enabled": False}})
            except Exception as exc:  # pragma: no cover — диагностика гонки, не ожидаемый путь
                errors.append(exc)

        threads = [threading.Thread(target=_worker, daemon=True) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)
            assert not t.is_alive(), "поток завис — подозрение на дедлок держателя окна под конкуренцией"
        assert not errors, f"поток(и) упали с исключением: {errors!r}"

        first_voices = _voices(caplog)
        assert len(first_voices) == 1, (
            f"{n} параллельных первых чтений одного ключа дали {len(first_voices)} голосов вместо 1: {first_voices!r}"
        )
        caplog.clear()

        clock.advance(1_000_000.0)  # заведомо больше любого разумного окна
        ObservabilityConfig.model_validate({"stats": {"enabled": False}})

        re_voices = _voices(caplog)
        assert len(re_voices) == 1, re_voices
        text = re_voices[0]
        expected_suppressed = n - 1
        assert re.search(rf"(?<!\d){expected_suppressed}(?!\d)", text), (
            f"после {n} параллельных чтений возобновившийся голос не назвал {expected_suppressed} "
            f"подавленных: {text!r} — инкремент счётчика подавленных не пережил гонку"
        )


# =========================================================================== #
# 3 — первый голос по ключу не может быть проглочен насыщенной картой         #
# =========================================================================== #
class TestFirstVoiceSurvivesASaturatedKeyMap:
    """Опасность 3: держатель окон делит потолок карты ключей
    (``observability.voices.max_tracked_keys``, L0-дефолт 512) со ВСЕМИ
    остальными дросселируемыми голосами процесса. ``WindowedVoices.take()``
    защищает только что вставленный ключ от вытеснения ЦЕЛИКОМ (см. докстринг
    ``windowed_voice`` — «protect»), но это утверждение проверяемое, а не
    формальное: для КОНКРЕТНОГО ключа этой задачи (``stats.enabled.repurposed``)
    отдельного теста не было. Без этой защиты первый голос про смену смысла
    ключа на насыщенном стенде тихо проглатывался бы вставкой и немедленным
    вытеснением — то есть правило переставало бы звучать ровно там, где старых
    конфигов и шума больше всего.
    """

    def test_first_voice_still_sounds_when_the_keymap_is_at_capacity(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING)
        holder = process_voices()
        ceiling = max_tracked_keys()
        for i in range(ceiling):
            holder.take(f"unrelated_saturation_probe_key_{i}", 5.0)
        assert holder.tracked_keys() == ceiling, "проба не насытила карту ключей — тест не воспроизвёл предпосылку"

        ObservabilityConfig.model_validate({"stats": {"enabled": False}})

        assert len(_voices(caplog)) == 1, (
            "первый голос про stats.enabled не прозвучал при насыщенной карте ключей держателя — "
            "правило замолчало ровно там, где шума больше всего"
        )


# =========================================================================== #
# 4 — вход без типовой дисциплины: не падать, не голосить                     #
# =========================================================================== #
class TestMalformedInputNeitherRaisesNorVoices:
    """Опасность 4: валидатор вызывается ПРЯМО (минуя конструирование Pydantic),
    потому что интерес здесь — поведение ЭТОЙ функции на входе, которого сама
    схема не обязана принимать. Для не-словаря/не-булева ``enabled``/пустого
    входа условие ``data.get("enabled") is False`` обязано остаться ложным —
    ни падения, ни голоса.
    """

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param(None, id="none"),
            pytest.param("not-a-dict", id="string"),
            pytest.param(42, id="int"),
            pytest.param([], id="empty_list"),
            pytest.param({}, id="empty_dict_enabled_absent"),
            pytest.param({"enabled": "false"}, id="enabled_string_false"),
            pytest.param({"enabled": None}, id="enabled_none"),
            pytest.param({"enabled": 0}, id="enabled_int_zero_not_bool_false"),
        ],
    )
    def test_no_crash_and_no_voice(self, caplog: pytest.LogCaptureFixture, payload: object) -> None:
        caplog.set_level(logging.WARNING)

        result = ObservabilityStatsConfig._complain_about_repurposed_enabled(payload)

        assert result is payload, "before-хук обязан вернуть данные БЕЗ изменений — это не преобразователь"
        assert _voices(caplog) == [], (
            f"на входе {payload!r} валидатор проголосовал, хотя 'enabled' не равно ИМЕННО False "
            f"(is False, не ==): {_voices(caplog)!r}"
        )


# =========================================================================== #
# 5 — эмиссия ВНЕ лока: реентерентный вызов не имеет права зависнуть           #
# =========================================================================== #
class TestEmissionOutsideLockAllowsReentry:
    """Опасность 5: докстринг ``windowed_voice`` требует эмиссию ВНЕ лока
    держателя — обработчик записи вправе позвать механизм СНОВА (тот же поток,
    тот же ключ), и удержание лока на время эмиссии превратило бы это в дедлок.
    Здесь это воспроизводится: обработчик ``logging`` на записи валидатора сам
    вызывает ``ObservabilityConfig.model_validate`` ещё раз, СИНХРОННО, из того
    же потока. Правильная реализация не виснет (окно ещё не истекло — второй
    вызов просто молчит); проверяется join'ом с дедлайном, а не оптимистичным
    ожиданием.
    """

    def test_a_handler_reentering_the_same_key_does_not_deadlock(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING)
        reentered = threading.Event()

        class _ReentrantHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                if reentered.is_set():
                    return
                reentered.set()
                # Реентерим механизм СРАЗУ из обработчика записи — тот же
                # поток, тот же ключ, окно ещё не истекло: правильная
                # реализация не виснет (эмиссия сделана вне лока держателя),
                # просто молчит на этом повторном вызове.
                ObservabilityConfig.model_validate({"stats": {"enabled": False}})

        logger = logging.getLogger("observability_config")
        handler = _ReentrantHandler()
        logger.addHandler(handler)
        try:
            done: list = []

            def _run() -> None:
                ObservabilityConfig.model_validate({"stats": {"enabled": False}})
                done.append(True)

            thread = threading.Thread(target=_run, daemon=True)
            thread.start()
            thread.join(timeout=5.0)
            assert not thread.is_alive(), (
                "поток завис — подозрение на дедлок держателя окна при реентерентном вызове "
                "(эмиссия обязана происходить ВНЕ лока держателя)"
            )
            assert done == [True], "поток не дошёл до конца — упал ДО отметки завершения"
        finally:
            logger.removeHandler(handler)

        assert reentered.is_set(), "обработчик ни разу не реентерировал — тест ничего не проверил"
        assert len(_voices(caplog)) == 1, (
            f"реентерентный вызов внутри окна дал больше одного голоса: {_voices(caplog)!r}"
        )


# =========================================================================== #
# 6 — окно приходит из ПОЛИТИКИ процесса, а не из литерала в этой функции      #
# =========================================================================== #
class TestTheWindowComesFromProcessPolicyNotALiteral:
    """Опасность 6 — **найдена не рассуждением, а инъекцией J3 матрицы задачи**.

    Заплата «заменить ``take(key, None)`` на ``take(key, 5.0)``» — то есть
    прибить окно литералом вместо политики процесса — дала **0 красных из 163**.
    Поведение при дефолтной политике совпадает дословно (L0-дефолт как раз 5.0),
    поэтому ни приёмка, ни остальные опасности разницы не видят: ручка
    ``observability.voices.default_window_sec`` была бы применена и
    неподтверждаема — ровно класс «ручка применена ≠ подтверждена».

    Здесь ручка проверяется ДВИЖЕНИЕМ: политика процесса ставится в ``0.0``
    («без окна»), и голос обязан прозвучать на КАЖДОМ чтении. Литерал в функции
    этого движения не заметит и продолжит глушить — тест краснеет.

    Литерал ``0.0``, а не «какое-нибудь другое число», выбран потому, что он даёт
    наблюдаемый эффект БЕЗ подмены часов: сравнение ``(now - last) < 0.0`` ложно
    всегда, каким бы ни было реальное время между вызовами.
    """

    def test_moving_the_process_policy_changes_how_often_the_voice_speaks(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING)

        # Контроль-половина: при ДЕЙСТВУЮЩЕЙ политике три чтения дают один голос.
        for _ in range(3):
            ObservabilityConfig.model_validate({"stats": {"enabled": False}})
        assert len(_voices(caplog)) == 1, (
            f"контроль не воспроизвёлся: при дефолтной политике три чтения дали "
            f"{len(_voices(caplog))} голосов вместо одного"
        )
        caplog.clear()
        reset_process_voices()

        # Движение ручки: окно 0.0 — «без окна».
        set_voices_policy(window_sec=0.0)
        try:
            for _ in range(3):
                ObservabilityConfig.model_validate({"stats": {"enabled": False}})
            voices = _voices(caplog)
        finally:
            reset_voices_policy()

        assert len(voices) == 3, (
            f"политика процесса сдвинута в window_sec=0.0, а голос всё равно прозвучал "
            f"{len(voices)} раз вместо 3 — окно взято ЛИТЕРАЛОМ в валидаторе, а не из "
            "политики; ручка observability.voices.default_window_sec на этот голос не "
            "действует (инъекция J3 матрицы 2.12 давала 0 красных именно поэтому)"
        )
