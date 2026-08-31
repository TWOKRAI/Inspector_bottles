# -*- coding: utf-8 -*-
"""RED acceptance — Критерий A и Критерий B на РЕАЛЬНЫХ сайтах device_hub.

Независимый тестер, стадия 1 (ДО реализации). Узкий скоуп — два критерия:

* **Критерий A** — деталь сайта (имя воркера) сегодня едет ТОЛЬКО текстом
  ``ctx.log_error(...)``; после миграции строка снимается, и деталь обязана
  остаться СТРУКТУРНО — в ``context``/полях инцидента, а не только в тексте.
* **Критерий B** — ключ окна голоса не имеет права схлопывать ДВА РАЗНЫХ
  отказа (два разных устройства) в один ключ; второй обязан прозвучать.

Сайты — РЕАЛЬНЫЙ ``Plugins/hub/device_hub/plugin.py::_ensure_device_workers``
(``НР-4``, две ветки):

* ``create_worker`` вернул ``False`` (строки ~397-404) — ОТКАЗ ВОЗВРАТОМ
  ЗНАЧЕНИЯ, сегодня НЕ доходит до плоскости ошибок вовсе (только
  ``ctx.log_error``). Это один из двух сайтов, названных ТЗ как «invisible to
  the error plane today».
* ``create_worker`` бросил исключение (строки ~405-408) — здесь
  ``ctx.health.report_error(exc, context="device_hub.create_worker")`` УЖЕ
  стоит, но БЕЗ полей: имя воркера (``wname``) остаётся только во втором,
  соседнем ``ctx.log_error(...)``. Это живой, СЕГОДНЯШНИЙ дефект — не нужно
  гадать форму миграции, чтобы его показать.

Проводка до плоскости ошибок — РЕАЛЬНАЯ: ``HealthReporter`` поверх РЕАЛЬНОГО
``HealthState`` (не мок), с настоящим ``report_error`` → ``_safe_track`` →
``track`` callback и настоящим ``WindowedVoices`` внутри. Мок остаётся только
там, где это оправданно НЕ по критерию: ``worker_manager`` (или его замена,
бросающая исключение), ``router_manager``, реестр устройств.

НЕ повторяет то, что уже покрыл предыдущий независимый тестер на этом же
механизме: не проверяет сам факт «камера/устройство → errors.log/health.status»
как двоичное свойство, не трогает ``system_overview().anomalies``, AST-страж
двух коннекторов, дедуп store-tap путей.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from multiprocess_framework.modules.process_module.health import HealthReporter, HealthState
from Plugins.hub.device_hub.plugin import DeviceHubPlugin

from .conftest import make_ctx


class _RaisingWorkerManager:
    """Замена ``FakeWorkerManager``: ``create_worker`` всегда бросает.

    Один и тот же класс исключения на ВСЕХ вызовах — намеренно: это
    воспроизводит реальный риск Критерия B («generic exception type used for
    every failure class»), а не искусственную синтетику.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def create_worker(self, name, fn, cfg=None, auto_start=False):  # noqa: ANN001 — тестовый дублёр
        self.calls.append(name)
        raise RuntimeError("создание воркера отклонено пулом воркеров")

    def remove_worker(self, name):  # noqa: ANN001
        return True


class _MixedWorkerManager:
    """Два РОДА отказа в одном контексте: один воркер бросает, другой возвращает False.

    Нужен для целевой стороны критерия B: вырождение ключа окна видно только
    тогда, когда в одном контексте встречаются отказ-исключение и
    отказ-возврат-значения. ``FakeWorkerManager`` даёт лишь второй, а
    ``_RaisingWorkerManager`` — лишь первый.
    """

    def __init__(self, *, raising_for: str) -> None:
        self._raising_for = raising_for
        self.workers: dict[str, object] = {}
        self.calls: list[str] = []

    def create_worker(self, name, fn, cfg=None, auto_start=False):  # noqa: ANN001 — тестовый дублёр
        self.calls.append(name)
        if name == self._raising_for:
            raise RuntimeError("создание воркера отклонено пулом воркеров")
        return False

    def remove_worker(self, name):  # noqa: ANN001
        return True


def _make_plugin_with_real_health(tmp_path: Path) -> tuple[DeviceHubPlugin, MagicMock, list, list]:
    """Сконфигурированный DeviceHubPlugin с РЕАЛЬНЫМ HealthState/HealthReporter.

    ``ctx`` — MagicMock (роутер/воркер-менеджер/registers — не по критерию),
    но ``ctx.health`` — настоящий фасад над настоящим ``HealthState``: дорога
    ``report_error -> _safe_track -> track`` и ``WindowedVoices.take`` внутри
    исполняется целиком, без подмены.
    """
    captured_incidents: list[tuple[BaseException, dict | None]] = []
    captured_voices: list[str] = []

    def _track(exc: BaseException, payload: dict | None = None) -> None:
        captured_incidents.append((exc, payload))

    def _log(msg: str, **_kwargs: object) -> None:
        captured_voices.append(msg)

    state = HealthState(log=_log, track=_track, log_only=False)

    registry_file = tmp_path / "devices.yaml"
    ctx = make_ctx({}, tmp_registry=registry_file)
    ctx.health = HealthReporter(state, source="device_hub")

    plugin = DeviceHubPlugin()
    plugin.configure(ctx)

    return plugin, ctx, captured_incidents, captured_voices


def _prime_driver(plugin: DeviceHubPlugin, dev_id: str) -> None:
    driver = MagicMock()
    driver.is_connected = True
    driver.desired_connected = True
    driver.entry = MagicMock()
    driver.entry.params = {}
    plugin._manager._drivers[dev_id] = driver
    plugin._desired_connected[dev_id] = True


class TestCreateWorkerFalseFailureClass:
    """Ветка НР-4: ``create_worker`` вернул ``False`` — отказ ВОЗВРАТОМ значения.

    Сегодня зовёт ТОЛЬКО ``ctx.log_error(...)``. Ни разу не зовёт
    ``ctx.health.report_error`` — сайт назван ТЗ как «invisible to the error
    plane today». Форма того, ЧТО должно появиться после миграции, здесь —
    ДОГАДКА (в репозитории нет ни одного сайта, который бы уже заводил
    инцидент из отказа-возврата без исключения): я проверяю наблюдаемый
    эффект («инцидент со структурным полем, содержащим имя воркера»), а не
    конкретное имя метода, которым он будет заведён.
    """

    def _prime_two_colliding_devices(self, tmp_path: Path):
        plugin, ctx, incidents, voices = _make_plugin_with_real_health(tmp_path)
        for dev_id in ("dev_alpha", "dev_beta"):
            _prime_driver(plugin, dev_id)
            # Занять оба имени -> create_worker вернёт False для ОБОИХ (НР-4).
            ctx.worker_manager.workers[f"dev_{dev_id}"] = {"fn": None}
        return plugin, ctx, incidents, voices

    def test_worker_name_of_a_false_create_reaches_the_incident_structurally(self, tmp_path: Path) -> None:
        """Критерий A: имя воркера обязано быть в инциденте СТРУКТУРНО.

        Сегодня текст ``ctx.log_error`` называет имя (``dev_dev_alpha``), а
        инцидент вообще не заводится — это ожидаемый RED сегодняшнего дня,
        и он ГРУБЕЕ, чем чистое «текст vs структура» (см. отчёт: этот сайт
        совсем не долетает до плоскости ошибок). Тест тем не менее пинует
        целевое свойство станции 1, а не промежуточное состояние.
        """
        plugin, ctx, incidents, _voices = self._prime_two_colliding_devices(tmp_path)

        plugin._ensure_device_workers()

        # Контроль: сегодняшний текст ДЕЙСТВИТЕЛЬНО называет имя воркера —
        # иначе тест ничего не грунтует.
        logged_texts = [str(c) for c in ctx.log_error.call_args_list]
        assert any("dev_dev_alpha" in text for text in logged_texts), (
            f"контрольная проверка провалилась: сегодняшний ctx.log_error не назвал имя воркера: {logged_texts}"
        )

        assert incidents, (
            "create_worker() вернул False, но НИ ОДИН инцидент не долетел до плоскости ошибок — "
            "сайт report_error для этой ветки ещё не заведён (НР-4 остаётся log-only)"
        )
        payloads_without_context = [
            {k: v for k, v in (payload or {}).items() if k != "context"} for _exc, payload in incidents
        ]
        found = any("alpha" in str(value) for payload in payloads_without_context for value in payload.values())
        assert found, f"имя воркера видно только в снятом ctx.log_error, структура инцидента его не несёт: {incidents}"

    def test_two_devices_of_one_failure_class_give_two_facts_and_one_voice(self, tmp_path: Path) -> None:
        """Критерий B, сторона «окно работает»: один класс — один голос, факты все.

        **Здесь заявленный контракт РАЗОШЁЛСЯ с моделью независимого тестера,
        и расхождение решено в пользу окна (вердикт 2026-08-31).** Тестер
        требовал голос НА УСТРОЙСТВО: dev_alpha и dev_beta, падающие одинаково,
        должны были дать две строки. Отвергнуто: ключ с identity инстанса
        отключает механизм ровно в том состоянии, ради которого он заведён —
        хаб на 20 устройств, отваливающихся одной причиной, дал бы 20 строк,
        то есть шторм, против которого Task 1.4 и делалась. Различимость
        устройств при этом НЕ теряется: факт пер-девайсный и несёт имя воркера
        структурным полем (тест выше), теряются только строки журнала.

        «Два разных отказа» в критерии задачи — это два разных КЛАССА отказа,
        и они проверяются соседом ``test_two_failure_classes_...`` ниже.
        Гранулярность остаётся управляемой: сайт, которому нужен голос на
        устройство, кладёт идентификатор в ``context`` сам — фреймворк
        фиксирует форму ключа (класс, контекст), а не его дробность.
        """
        plugin, _ctx, incidents, voices = self._prime_two_colliding_devices(tmp_path)

        plugin._ensure_device_workers()

        assert len(incidents) == 2, (
            f"факт обязан учитываться на КАЖДЫЙ отказ (Task 1.3a), окно его не касается: {incidents}"
        )
        assert len(voices) == 1, (
            f"один класс отказа в одном контексте обязан дать РОВНО ОДИН голос — "
            f"иначе окно не работает и хаб на N устройствах даст N строк: {voices}"
        )
        assert "подавлено" in voices[0], (
            f"голос обязан назвать число подавленных вхождений, иначе «одна строка» неотличима "
            f"от «потеряли остальные»: {voices[0]!r}"
        )


class TestCreateWorkerRaisesFailureClass:
    """Ветка ``except Exception``: ``create_worker`` бросил.

    ``ctx.health.report_error(exc, context="device_hub.create_worker")`` УЖЕ
    стоит на этом сайте СЕГОДНЯ (строка ~407 plugin.py) — здесь НЕ нужно
    гадать форму миграции, дефект уже живёт в коде: вызов без полей, имя
    воркера остаётся только в соседнем ``ctx.log_error`` (строка ~408).
    """

    def _prime_two_raising_devices(self, tmp_path: Path):
        plugin, ctx, incidents, voices = _make_plugin_with_real_health(tmp_path)

        raising_wm = _RaisingWorkerManager()
        ctx.worker_manager = raising_wm
        plugin._ctx = ctx  # configure() уже сохранил ctx — переустановим ссылку на worker_manager

        for dev_id in ("dev_gamma", "dev_delta"):
            _prime_driver(plugin, dev_id)

        return plugin, ctx, incidents, voices

    def test_worker_name_of_a_raise_reaches_the_incident_structurally(self, tmp_path: Path) -> None:
        """Критерий A на сайте, где report_error УЖЕ вызывается — без полей."""
        plugin, ctx, incidents, _voices = self._prime_two_raising_devices(tmp_path)

        plugin._ensure_device_workers()

        logged_texts = [str(c) for c in ctx.log_error.call_args_list]
        assert any("dev_dev_gamma" in text for text in logged_texts), (
            f"контрольная проверка провалилась: сегодняшний ctx.log_error не назвал имя воркера: {logged_texts}"
        )

        assert incidents, "create_worker() бросил — report_error() уже стоит на сайте, инцидент обязан долететь"
        payloads_without_context = [
            {k: v for k, v in (payload or {}).items() if k != "context"} for _exc, payload in incidents
        ]
        found = any("gamma" in str(value) for payload in payloads_without_context for value in payload.values())
        assert found, (
            f"имя воркера (`wname`) видно только в снятом ctx.log_error — "
            f"report_error(exc, context=...) вызывается БЕЗ полей: {incidents}"
        )

    def test_two_devices_raising_one_class_give_two_facts_and_one_voice(self, tmp_path: Path) -> None:
        """Критерий B на ветке исключения: факты все, голос один.

        **Этот тест ЗЕЛЁН уже сегодня — и это его назначение.** Он не приёмка
        новой работы, а сторож регрессии: свойство «2 факта / 1 голос» на этой
        ветке даёт Task 1.3a, и миграция 1.3b обязана его не сломать. Красным
        он станет ровно тогда, когда переписывание сайта потеряет факт или
        расщепит окно, — то есть в том единственном случае, ради которого он
        здесь и стоит. Зелёный прогон этого файла целиком доказательством
        задачи не является; доказывают четыре его красных соседа.

        Контроль здесь ценен сам по себе: ``len(incidents) == 2`` подтверждает,
        что «факт всегда» (Task 1.3a) на этом сайте уже работает — то есть
        красное ниже, если оно появится, будет про голос, а не про факт.

        Про то, почему голосов ОДИН, а не два (модель тестера отвергнута), —
        см. докстринг ``test_two_devices_of_one_failure_class_...`` выше.
        """
        plugin, _ctx, incidents, voices = self._prime_two_raising_devices(tmp_path)

        plugin._ensure_device_workers()

        assert len(incidents) == 2, (
            f"факт обязан учитываться на КАЖДЫЙ отказ (Task 1.3a) независимо от окна голоса: {incidents}"
        )
        assert len(voices) == 1, (
            f"оба устройства делят класс отказа и контекст -> один ключ окна -> ровно один голос: {voices}"
        )

    def test_two_failure_classes_in_one_context_do_not_silence_each_other(self, tmp_path: Path) -> None:
        """Критерий B, ЦЕЛЕВАЯ сторона: разные КЛАССЫ отказа — разные ключи.

        Это и есть опасность, ради которой задача заводит типы отказов. В одном
        контексте ``device_hub.create_worker`` живут ДВА разных отказа:

        * ``create_worker`` вернул ``False`` (отказ возвратом значения);
        * ``create_worker`` бросил исключение.

        Если второй фабрикуется общим ``RuntimeError`` — а именно так и выйдет
        у реализатора, которому не дали типов, — ключ ``RuntimeError|context``
        совпадёт у обоих, и отказ одного рода **молча заглушит** отказ другого
        рода на всё окно. Сегодня тест красный по более грубой причине: ветка
        ``False`` не заводит инцидента вовсе, поэтому голос ровно один.
        """
        plugin, ctx, incidents, voices = _make_plugin_with_real_health(tmp_path)
        ctx.worker_manager = _MixedWorkerManager(raising_for="dev_dev_delta")
        plugin._ctx = ctx

        for dev_id in ("dev_gamma", "dev_delta"):
            _prime_driver(plugin, dev_id)

        plugin._ensure_device_workers()

        assert len(incidents) == 2, (
            f"оба отказа обязаны быть фактами плоскости ошибок, независимо от того, "
            f"пришёл отказ исключением или возвратом значения: {incidents}"
        )
        classes = {type(exc).__name__ for exc, _payload in incidents}
        assert len(classes) == 2, (
            f"два разных рода отказа приехали ОДНИМ классом {classes} — ключ окна "
            f"(класс, контекст) вырожден, и один род заглушит другой"
        )
        assert len(voices) == 2, (
            f"разные классы отказа в одном контексте обязаны прозвучать оба: голосов {len(voices)}: {voices}"
        )
