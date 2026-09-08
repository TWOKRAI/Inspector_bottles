# -*- coding: utf-8 -*-
"""Ф2/Ф4, задачи 2.12 и 4.11 — тесты АВТОРА на опасности механизма дросселя
``stats.enabled``.

Приёмка (``test_f2_task212_repurposed_voice_window.py``) проверяет контракт
СНАРУЖИ: сколько голосов и с каким текстом. Здесь — то, что видно только тому,
кто знает, КАК механизм построен: держатель окон резолвится на каждый вызов
(а не захватывается при импорте), лок держателя не удерживается на время
эмиссии, вход не проверен по типу (произвольный оператор конфига), и потолок
карты ключей — общий процессный ресурс, за который отвечает не эта функция.

**Дверь — Task 4.11, не прежний ``ObservabilityConfig.model_validate``.** До
задачи 4.11 голос жил внутри валидатора схемы
(``ObservabilityStatsConfig._complain_about_repurposed_enabled``), и этот файл
звал его напрямую — вызов валидатора БЫЛ единицей события. Задача 4.11 сняла
голос с валидатора целиком (он стал чистым парсером, см. его докстринг) и
перенесла на стадию «применяю» —
:func:`~..managers.observability_reload._voice_repurposed_stats_enabled`,
вызываемую из :func:`~..managers.observability_reload.compose_managers_payload`.
Каждый тест ниже переехал на эту дверь; что из старой формы теста перестало
быть применимо — названо в докстринге соответствующего класса.

Ключ голоса — ``"stats.enabled.repurposed"`` (Р-12) — не изменился при переезде;
тесты не привязаны к внутреннему имени функции (правило проекта «шпион на имя
стережёт имя, а не свойство»): они читают ``caplog`` по тексту записи, как и
приёмка.
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
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    _voice_repurposed_stats_enabled,
    compose_managers_payload,
)

_KEY = "stats.enabled.repurposed"


def _apply(section: dict, log_dir: str) -> None:
    """Позвать новую дверь голоса — тонкая обёртка ради краткости тестов ниже.

    ``compose_managers_payload`` строит полный конфиг менеджеров (побочный
    эффект — голос), но тестам он не нужен: их предмет — САМ голос, а не
    раскладка. Возврат отбрасывается сознательно.
    """
    compose_managers_payload(section, log_dir=log_dir)


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

    def test_reset_process_voices_is_visible_to_the_validator(self, tmp_path, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING)
        section = {"stats": {"enabled": False}}
        log_dir = str(tmp_path)

        _apply(section, log_dir)
        assert len(_voices(caplog)) == 1, "первый голос обязан прозвучать — иначе тест ничего не проверяет"
        caplog.clear()

        # Внутри окна — молчит (используем это как контроль: без сброса
        # следующий вызов остался бы тихим).
        _apply(section, log_dir)
        assert _voices(caplog) == [], "второй вызов внутри окна не обязан быть тихим — тест не воспроизвёл базу"
        caplog.clear()

        # Сброс держателя. Если проверка резолвит ``process_voices()`` на
        # каждый вызов (а не хранит старую ссылку), следующий вызов увидит
        # НОВЫЙ пустой держатель и заговорит немедленно — для него это первый
        # раз по новому ключу.
        reset_process_voices()
        _apply(section, log_dir)
        assert len(_voices(caplog)) == 1, (
            "голос не прозвучал сразу после reset_process_voices() — проверка, похоже, держит "
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
        self, tmp_path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clock = _fake_clock(monkeypatch)
        caplog.set_level(logging.WARNING)
        section = {"stats": {"enabled": False}}
        log_dir = str(tmp_path)

        n = 20
        barrier = threading.Barrier(n)
        errors: list = []

        def _worker() -> None:
            try:
                barrier.wait(timeout=5.0)
                _apply(section, log_dir)
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
        _apply(section, log_dir)

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

    def test_first_voice_still_sounds_when_the_keymap_is_at_capacity(
        self, tmp_path, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING)
        holder = process_voices()
        ceiling = max_tracked_keys()
        for i in range(ceiling):
            holder.take(f"unrelated_saturation_probe_key_{i}", 5.0)
        assert holder.tracked_keys() == ceiling, "проба не насытила карту ключей — тест не воспроизвёл предпосылку"

        _apply({"stats": {"enabled": False}}, str(tmp_path))

        assert len(_voices(caplog)) == 1, (
            "первый голос про stats.enabled не прозвучал при насыщенной карте ключей держателя — "
            "правило замолчало ровно там, где шума больше всего"
        )


# =========================================================================== #
# 4 — вход без типовой дисциплины: не падать, не голосить                     #
# =========================================================================== #
class TestMalformedInputNeitherRaisesNorVoices:
    """Опасность 4 — переехала на новую дверь целиком, а не только вызовом.

    До задачи 4.11 эта опасность звала валидатор схемы НАПРЯМУЮ, в обход
    Pydantic, с payload'ом в форме под-словаря ``stats`` (интерес был в
    поведении именно ЭТОЙ функции на мусорном входе). Тот вызов теперь
    БЕССМЫСЛЕН как тест: валидатор — чистый парсер (``return data`` всегда,
    см. его докстринг), и «не падает, не голосит» держится на нём вакуумно,
    при любом входе, включая корректный.

    Опасность переехала на функцию, где условие ``is False`` реально
    осталось, — :func:`_voice_repurposed_stats_enabled`. Она принимает
    словарь ВЕРХНЕГО уровня (``resolved``, тот же вид, что уходит в
    ``expand_observability``), поэтому форма мусора здесь ДВУХ родов: сам
    ``resolved`` не словарь, либо ``resolved["stats"]`` не словарь/не булев
    ``False`` буквально.
    """

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param(None, id="resolved_none"),
            pytest.param("not-a-dict", id="resolved_string"),
            pytest.param(42, id="resolved_int"),
            pytest.param([], id="resolved_empty_list"),
            pytest.param({}, id="stats_absent"),
            pytest.param({"stats": "not-a-dict"}, id="stats_not_a_dict"),
            pytest.param({"stats": {}}, id="enabled_absent"),
            pytest.param({"stats": {"enabled": "false"}}, id="enabled_string_false"),
            pytest.param({"stats": {"enabled": None}}, id="enabled_none"),
            pytest.param({"stats": {"enabled": 0}}, id="enabled_int_zero_not_bool_false"),
        ],
    )
    def test_no_crash_and_no_voice(self, caplog: pytest.LogCaptureFixture, payload: object) -> None:
        caplog.set_level(logging.WARNING)

        _voice_repurposed_stats_enabled(payload)  # не должно упасть

        assert _voices(caplog) == [], (
            f"на входе {payload!r} функция проголосовала, хотя 'enabled' не равно ИМЕННО False "
            f"(is False, не ==): {_voices(caplog)!r}"
        )


# =========================================================================== #
# 5 — эмиссия ВНЕ лока: реентерентный вызов не имеет права зависнуть           #
# =========================================================================== #
class TestEmissionOutsideLockAllowsReentry:
    """Опасность 5: докстринг ``windowed_voice`` требует эмиссию ВНЕ лока
    держателя — обработчик записи вправе позвать механизм СНОВА (тот же поток,
    тот же ключ), и удержание лока на время эмиссии превратило бы это в дедлок.
    Здесь это воспроизводится: обработчик ``logging`` на записи голоса сам
    зовёт новую дверь (:func:`compose_managers_payload`) ещё раз, СИНХРОННО,
    из того же потока. Правильная реализация не виснет (окно ещё не истекло —
    второй вызов просто молчит); проверяется join'ом с дедлайном, а не
    оптимистичным ожиданием.

    Обработчик вешается на КОРНЕВОЙ логгер, а не на конкретное имя модуля:
    задача 4.11 сменила адрес голоса (``FallbackLogger(__name__)`` в
    ``observability_reload.py``, а не ``FallbackLogger("observability_config")``
    в схеме), и тест не обязан знать точное имя — запись доходит до root
    пропагацией в любом случае (тот же приём, что уже применяет соседний
    ``_voices(caplog)``).
    """

    def test_a_handler_reentering_the_same_key_does_not_deadlock(
        self, tmp_path, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING)
        reentered = threading.Event()
        section = {"stats": {"enabled": False}}
        log_dir = str(tmp_path)

        class _ReentrantHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                if reentered.is_set():
                    return
                reentered.set()
                # Реентерим механизм СРАЗУ из обработчика записи — тот же
                # поток, тот же ключ, окно ещё не истекло: правильная
                # реализация не виснет (эмиссия сделана вне лока держателя),
                # просто молчит на этом повторном вызове.
                _apply(section, log_dir)

        logger = logging.getLogger()  # root — тот же адрес, что слушает caplog
        handler = _ReentrantHandler()
        logger.addHandler(handler)
        try:
            done: list = []

            def _run() -> None:
                _apply(section, log_dir)
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
        self, tmp_path, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING)
        section = {"stats": {"enabled": False}}
        log_dir = str(tmp_path)

        # Контроль-половина: при ДЕЙСТВУЮЩЕЙ политике три чтения дают один голос.
        for _ in range(3):
            _apply(section, log_dir)
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
                _apply(section, log_dir)
            voices = _voices(caplog)
        finally:
            reset_voices_policy()

        assert len(voices) == 3, (
            f"политика процесса сдвинута в window_sec=0.0, а голос всё равно прозвучал "
            f"{len(voices)} раз вместо 3 — окно взято ЛИТЕРАЛОМ в валидаторе, а не из "
            "политики; ручка observability.voices.default_window_sec на этот голос не "
            "действует (инъекция J3 матрицы 2.12 давала 0 красных именно поэтому)"
        )


# =========================================================================== #
# 7 — ЗОЛОТОЙ ПУТЬ: голос доезжает до ФАЙЛА журнала, а не только до caplog     #
# =========================================================================== #
class TestTheVoiceReachesTheLogFileNotOnlyCaplog:
    """Опасность 7 — **найдена вердиктом CTO, и она про сам этот файл тоже.**

    Все остальные тесты задачи 2.12 (11 приёмочных + 12 опасностей) смотрят
    через ``caplog``, то есть через stdlib-root. Это ФЕЙКОВЫЙ харнесс для
    данного вопроса: они честны о ЧИСЛЕ голосов и слепы к их АДРЕСУ, и остались
    бы зелёными при голосе, которого нет ни в одном файле ``logs/``. Ровно так и
    было до правки адреса: замер CTO на настоящем ``LoggerManager`` дал
    ``emergency_log`` → **0 строк в файле**, обе записи в stderr через
    ``logging.lastResort`` (у stdlib-root в процессах фреймворка нет ни одного
    хендлера), а вид (``FallbackLogger``) → **2 строки в файле**, включая
    сделанную ДО подъёма менеджера (слита из раннего буфера ``std_facade._EARLY``).

    Правило проекта, которое здесь исполняется дословно: «где командная
    поверхность тестируется на фейках, добавь ОДИН тест на настоящих объектах —
    иначе переименование боевого атрибута оставит все тесты зелёными».
    """

    def test_the_voice_lands_in_the_log_file_of_a_real_logger_manager(self, tmp_path) -> None:
        from multiprocess_framework.modules.logger_module.configs.logger_manager_config import (
            LoggerManagerConfig,
        )
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
        from multiprocess_framework.modules.process_module.core.process_module import ProcessModule

        log_dir = tmp_path / "golden"
        log_dir.mkdir()
        process = ProcessModule("t212_golden")
        logger = LoggerManager(
            manager_name="logger_t212_golden",
            config=LoggerManagerConfig(app_name="t212_golden", log_directory=str(log_dir)),
            process=process,
        )
        logger.initialize()
        process.logger_manager = logger
        process.register_manager("logger", logger, enabled=True)
        try:
            reset_process_voices()
            _apply({"stats": {"enabled": False}}, str(log_dir))
            logger.flush() if hasattr(logger, "flush") else None
            deadline = time.monotonic() + 5.0
            found: list = []
            while time.monotonic() < deadline and not found:
                for path in sorted(log_dir.rglob("*.log")):
                    text = path.read_text(encoding="utf-8", errors="replace")
                    if "ADR-PM-046" in text:
                        found.append(path.name)
                if not found:
                    threading.Event().wait(0.05)
        finally:
            logger.shutdown()

        assert found, (
            "голос ADR-PM-046 не попал НИ В ОДИН файл журнала настоящего LoggerManager — "
            f"файлы: {[p.name for p in sorted(log_dir.rglob('*.log'))]}. Это тот самый дефект, "
            "который caplog не видит: правило звучит ровно один раз на действие и уходит в "
            "stderr через logging.lastResort, а оператор со стендом читает logs/"
        )
