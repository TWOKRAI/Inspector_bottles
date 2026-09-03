# -*- coding: utf-8 -*-
"""
Pytest: логи по умолчанию не пишутся в дерево исходников modules/.

Каталог задаётся через MULTIPROCESS_LOG_DIR (см. logger_module.core.log_paths).
"""

from __future__ import annotations

import os
import threading

import pytest


@pytest.fixture(autouse=True)
def _reset_early_log_buffer() -> None:
    """Ф6.4а: буфер ранних записей — ПРОЦЕССНОЕ состояние, и оно течёт между тестами.

    В проде это ровно то, что нужно: одна жизнь процесса — один старт, один
    слив. В прогоне процесс общий на тысячи тестов, поэтому запись, сделанная
    без менеджера в одном тесте, сливалась в первый же менеджер СЛЕДУЮЩЕГО и
    становилась там первой строкой файла (поймано тремя красными в
    ``test_fallback_handle`` и ``test_source_stamp_artifact``).

    Сброс до и после: «до» защищает тест от предшественника, «после» — от
    самого себя, если он упал на середине.
    """
    from .logger_module.adapters.std_facade import reset_early_buffer

    reset_early_buffer()
    yield
    reset_early_buffer()


@pytest.fixture(autouse=True)
def _reset_windowed_voice_holder() -> None:
    """Task 2.12: окна голосов — ПРОЦЕССНОЕ состояние того же класса, что буфер выше.

    С задачи 2.12 предупреждение о смене смысла ``stats.enabled`` (ADR-PM-046)
    дросселируется окном по ключу на процессном держателе
    (``windowed_voice._PROCESS_VOICES``). В проде это ровно то, что нужно: одна
    жизнь процесса — одно окно на ключ. В прогоне процесс общий, и окно, занятое
    одним тестом, глушит голос у следующего.

    **Ставится не «на всякий случай»: пойманы две поломки, и вторая опаснее.**
    ``statistics_module::test_c7_*`` краснел ДАЖЕ в изоляции своего файла (соседи
    по файлу съедали окно раньше). А пара
    ``test_f2_task29_fingerprint_probe::TestTheProbeDoesNotSpeakForTheOperator``
    перестала РАЗЛИЧАТЬ: её положительная половина покраснела, а отрицательная
    («зонд молчит») осталась ЗЕЛЁНОЙ — голос был подавлен чужим окном, и тест
    проходил, не проверив ничего. Красное видно, вакуумное зелёное — нет.

    Четыре теста, ассертящих голос, владеют окном ЯВНО и продолжают владеть:
    тест про окно обязан владеть окном так же, как тест про время — часами. Эта
    фикстура — второй рубеж для тех, кто про дроссель не знает: сегодня семь
    файлов зовут ``stats.enabled: false`` мимоходом, не проверяя голос, и любой
    из них может стать чужим окном для следующего.

    Радиус тот же, что у ``_reset_early_log_buffer``: одно процессное состояние
    плоскости наблюдаемости, сброс до и после. Боевых пользователей процессного
    держателя ровно один ключ (сверено грепом), так что фикстура ничего, кроме
    него, не двигает.
    """
    from .logger_module.core.windowed_voice import reset_process_voices

    reset_process_voices()
    yield
    reset_process_voices()


@pytest.fixture(autouse=True)
def _reset_logger_manager_singleton() -> None:
    """Ф6.х.1: ``LoggerManager._instance`` — второе процессное состояние, текущее между тестами.

    Тест, забывший ``shutdown()``, оставлял живой менеджер (его потоки, каналы и
    tap'ы) всем последующим: измерено на ``test_send_error_visibility`` —
    перестановка одного файла меняла время прогона 16.8 с ↔ 88–95 с, из них
    72 с приходились на один чужой тест. Снимаем через ``shutdown()``: голое
    ``_instance = None`` не бампит эпоху наблюдаемости, и закэшированные фасады
    в ``std_facade._CACHE`` остались бы связаны с мёртвым менеджером.

    Определена ПОСЛЕ ``_reset_early_log_buffer`` намеренно: teardown идёт в
    обратном порядке, поэтому сперва снимается менеджер, потом чистится буфер —
    записи, набуференные самим shutdown-переходом, не переживают тест.
    """
    from .logger_module.core.logger_manager import LoggerManager

    def _shutdown_leftover() -> None:
        manager = LoggerManager._instance
        if manager is not None:
            manager.shutdown()

    _shutdown_leftover()
    yield
    _shutdown_leftover()


#: Долгоживущие стенды ПО РЕШЕНИЮ: префикс nodeid → причина. Пусто не случайно:
#: сегодня ни один тест не имеет права держать flusher дольше себя. Запись без
#: причины не считается (образец дисциплины — _RUNNERLESS_BY_DECISION в 4.0).
_FLUSHER_LONG_LIVED_ALLOWED: dict[str, str] = {}


@pytest.fixture(autouse=True)
def _no_leaked_state_flushers(request: pytest.FixtureRequest):
    """Третье текущее процессное состояние: daemon-flusher'ы StateStoreManager.

    ``initialize()`` запускает поток ``StateCoalesceFlusher`` (тик 0.12 с), и
    гасит его только ``shutdown()``. Тест, забывший пару, оставляет поток
    ЖИВЫМ до конца прогона: поток держит диспетчер сильной ссылкой (bound
    method в target), поэтому стенд не собирается GC и не финализируется —
    он бессмертен. Замерено пробой 2026-08-12 на корневом гейте: 18 утёкших
    потоков из 4 файлов state_store_module/tests — ~150 пробуждений в секунду
    фонового шума всему остатку прогона; все 18 фигурируют в каждом
    faulthandler-дампе access violation (там они соседи детонации, не причина —
    причина закрыта отдельно, MPLBACKEND в корневом conftest).

    Сравнение по МНОЖЕСТВУ потоков до/после, не по числу: чужая утечка,
    пережившая свой тест, не должна красить соседей — краснеет только тест,
    ДОБАВИВШИЙ живой поток. Утёкший поток гасится best-effort до fail, чтобы
    один забытый shutdown() не шумел остатку прогона.
    """
    marker = "StateCoalesceFlusher"
    before = {t.ident for t in threading.enumerate() if t.name == marker and t.is_alive()}
    yield
    leaked = [t for t in threading.enumerate() if t.name == marker and t.is_alive() and t.ident not in before]
    if not leaked:
        return
    for prefix, _reason in _FLUSHER_LONG_LIVED_ALLOWED.items():
        if request.node.nodeid.startswith(prefix):
            return
    for t in leaked:
        owner = getattr(getattr(t, "_target", None), "__self__", None)
        if owner is not None and hasattr(owner, "stop_flusher"):
            owner.stop_flusher(timeout=1.0)
    pytest.fail(
        f"Тест оставил {len(leaked)} живой(ых) поток(ов) {marker}: "
        "StateStoreManager.initialize() обязан закрываться shutdown() в teardown "
        "(try/finally или фикстура с yield). Долгоживущий стенд по решению — "
        "запись в _FLUSHER_LONG_LIVED_ALLOWED с причиной."
    )


@pytest.fixture(scope="session", autouse=True)
def _multiprocess_framework_log_dir(tmp_path_factory: pytest.TempPathFactory) -> None:
    d = tmp_path_factory.mktemp("multiprocess_logs")
    previous = os.environ.get("MULTIPROCESS_LOG_DIR")
    os.environ["MULTIPROCESS_LOG_DIR"] = str(d)
    yield
    if previous is None:
        os.environ.pop("MULTIPROCESS_LOG_DIR", None)
    else:
        os.environ["MULTIPROCESS_LOG_DIR"] = previous
