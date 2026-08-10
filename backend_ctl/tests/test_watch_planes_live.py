# -*- coding: utf-8 -*-
"""Task 6.1 ГАП 2 — ``watch_like_gui`` наполняет несколько плоскостей ``events_page``,
для «тихих» плоскостей — явная фиксация, что тишина есть свойство рецепта, а не дыра
в проводке.

Профиль GUI (``watch_like_gui`` = ``state.subscribe`` + ``observability.tail``) пушит
события в курсорный ``EventHub`` (``events.py``), который классифицирует их по
плоскостям (:data:`backend_ctl.events.PLANES`): ``state.changed`` разносится ЦЕЛИКОМ в
``state`` И поштучно (по дельте) в ``telemetry`` — та же живая система, тот же источник,
поэтому обе плоскости доказуемо ненулевые под активным watch на любом рецепте, где вообще
идёт какое-то состояние (``region_pipeline`` — синтетический, но живой конвейер).

``ui`` — плоскость, для которой black-box live-пруф ненуля на ЭТОМ рецепте
принципиально недостижим: она наполняется ТОЛЬКО явными ``ui.event`` push'ами,
которые шлёт живой GUI-клик (или ``ui_tap``/``ui_tap_ping``); headless-воплощение
презентации (``HeadlessGuiProcess``) не регистрирует ни одного debug-обработчика
``ui.tap.*`` — не флаки, а архитектурный факт. Второй тест ниже эту тишину не
ЗАЯВЛЯЕТ, а ДОКАЗЫВАЕТ: синтетический ``ui_tap_ping()`` обязан честно отказать
(отсутствие приёмника команды), и только при этом отказе тишина ``count == 0``
что-то значит — на мёртвой проводке ping тоже промолчал бы, но уже не тем же
самым явным отказом.

``errors`` (ErrorManager-записи, не Logger — см. проектное разделение
logger/error/stats) прежде считался «недоказуемым на этом рецепте» и просто
пинился как ``count == 0``. Это разоблачено: молчащий детектор ничего не
доказывает — тест оставался бы зелёным и при полностью мёртвой проводке
``report_error → ErrorManager → errors-плоскость``. Второй тест ниже доказывает
``errors`` ПОЛОЖИТЕЛЬНО: детерминированный раздражитель (``health.report`` с
``level=ERROR``) обязан породить запись ErrorManager с уникальным маркером,
видимую через ``events_page(plane="errors")`` в пределах дедлайна — маркер, а
не рост ``count`` (который мог бы приехать от чужой записи).
"""

from __future__ import annotations

import json
import time
import uuid

import pytest

from backend_ctl.driver import BackendDriver
from backend_ctl.harness import BackendHarness
from backend_ctl.protocol import unwrap
from backend_ctl.tests.conftest import bookmark_cursor as _bookmark
from backend_ctl.tests.conftest import page_events as _page

_PORT = 8797  # уникальный порт этого модуля (назначен координатором, Task 6.1 плана)


def _wait_plane_nonempty(drv: BackendDriver, plane: str, deadline: float) -> dict:
    """Дождаться первой непустой курсорной страницы заданной плоскости (с начала кольца)."""
    page = drv.events_page(plane=plane)
    while time.time() < deadline:
        page = drv.events_page(plane=plane)
        if page.get("count", 0) > 0:
            return page
        time.sleep(0.2)
    return page


def _wait_for_marker(drv: BackendDriver, plane: str, marker: str, cursor, deadline: float):
    """Дождаться (с дедлайном) записи, содержащей ``marker``, в плоскости от ``cursor``.

    Не «count вырос» — конкретный текст. Маркер ищется по сериализованному
    событию целиком (а не по одному фиксированному ключу вроде ``message``):
    устойчиво к тому, в каком именно поле записи ErrorManager реально осел текст.

    Returns:
        ``(found, records_seen, last_event_or_None)`` — ``records_seen`` идёт в
        сообщение ассерта: отличает «ничего не приехало» от «приехало N чужих записей».
    """
    seen = 0
    last_event = None
    while time.time() < deadline:
        events, cursor = _page(drv, cursor, plane=plane)
        for ev in events:
            seen += 1
            last_event = ev
            if marker in json.dumps(ev, ensure_ascii=False):
                return True, seen, ev
        if not events:
            time.sleep(0.2)
    return False, seen, last_event


@pytest.mark.harness_smoke
def test_watch_like_gui_state_and_telemetry_planes_nonzero_live() -> None:
    """Плечо ненуля BCTL-ADR-007: под watch_like_gui state/telemetry реально наполняются."""
    harness = BackendHarness(with_base=True, port=_PORT)
    try:
        drv = harness.start()
        res = drv.watch_like_gui()
        assert res.get("success") is True

        state_page = _wait_plane_nonempty(drv, "state", time.time() + 15.0)
        assert state_page["success"] is True
        assert state_page["count"] > 0, "живая система обязана публиковать state.changed под watch_like_gui"

        # Тот же push state.changed фан-аутится по дельте в telemetry-плоскость
        # (events.py: классификация «state.changed → state целиком + telemetry поштучно») —
        # доказано ТЕМ ЖЕ источником, отдельного ожидания не требуется.
        telemetry_page = drv.events_page(plane="telemetry")
        assert telemetry_page["success"] is True
        assert telemetry_page["count"] > 0, "telemetry-плоскость — производная от тех же дельт, что state"
    finally:
        harness.stop()


@pytest.mark.harness_smoke
def test_watch_like_gui_errors_plane_proven_ui_silence_explained_live() -> None:
    """errors доказан МАРКЕРОМ (не count==0); ui-тишина объяснена честным отказом ping'а.

    Замена дефектного теста, чья посылка «тишина ui/errors — свойство рецепта»
    опровергнута: молчащий детектор (``count == 0`` без раздражителя) остаётся
    зелёным и на полностью мёртвой проводке — не доказательство, а отсутствие
    проверки, замаскированное под неё.
    """
    harness = BackendHarness(with_base=True, port=_PORT)
    try:
        drv = harness.start()
        assert drv.watch_like_gui().get("success") is True

        # П-3: признак жизни ДО раздражителя. Без этого «маркер не приехал» и
        # «стенд не поднялся» неразличимы — красный по обеим причинам выглядел бы
        # одинаково. state — та же плоскость, доказанная первым тестом файла под
        # тем же watch_like_gui-профилем.
        state_page = _wait_plane_nonempty(drv, "state", time.time() + 15.0)
        assert state_page["success"] is True
        assert state_page["count"] > 0, (
            "state-плоскость молчит под watch_like_gui — стенд не поднялся живым; "
            "проверка errors/ui ниже была бы неотличима от мёртвой проводки"
        )

        # ---- П-1: errors жива и наполняется ПО ТРЕБОВАНИЮ ----

        # Процесс-мишень — из ЖИВОЙ топологии (не хардкод имени): любой управляемый
        # ДОЧЕРНИЙ процесс, кроме "gui" (разбирается отдельно ниже, через
        # ui_tap_ping) и кроме "ProcessManager" (сам оркестратор технически тоже
        # отвечает на health.report, но раздражитель бьёт по РЯДОВОМУ процессу —
        # так же, как это делает соседний живой тест ``test_health_live.py``).
        overview = drv.system_overview()
        assert overview.get("success") is True, f"system_overview не success: {overview}"
        candidates = sorted(n for n in overview.get("processes", {}) if n not in ("gui", "ProcessManager"))
        assert candidates, f"нет ни одного рядового процесса в живой топологии: {sorted(overview.get('processes', {}))}"
        target_process = candidates[0]

        # (а) базовая позиция errors в спокойном окне — дальше судим ДЕЛЬТУ от неё,
        # а не всё кольцо с начала времён (там могли остаться посторонние записи).
        baseline_cursor = _bookmark(drv, plane="errors")

        # (б) детерминированный раздражитель: health.report с level=ERROR идёт по
        # маршруту report_error → ErrorManager (см. ADR C2 этой ветки) в живом
        # процессе. Ответ команды ПРОВЕРЯЕТСЯ явно — недоставленная команда не
        # должна маскироваться под «плоскость просто пуста».
        marker = f"TESTER-ERRORS-MARK-{uuid.uuid4().hex[:12]}"
        report = unwrap(
            drv.send_command(
                target_process,
                "health.report",
                {"context": "tester_errors_plane_proof", "message": marker, "level": "ERROR"},
                timeout=5.0,
            ),
            leaf=True,
        )
        assert report.get("success") is True, f"health.report на {target_process!r} не success: {report}"

        # (в) дождаться (с дедлайном, не бесконечно) записи ИМЕННО с нашим маркером —
        # не «count вырос» (могла прилететь чужая запись), а конкретный текст.
        #
        # Ищем ДВЕ дороги по отдельности, и это не педантизм: раздражитель бьёт по
        # плоскости ошибок дважды — инцидентом (`state.report_error`, текст = сам
        # маркер) и лог-записью уровня ERROR (текст = «[health.report] маркер»).
        # Первая редакция теста искала просто маркер и осталась ЗЕЛЁНОЙ под
        # инъекцией, убравшей лог-дорогу целиком: два предохранителя прятали, кто
        # из них держит. Ассерт стоит на ЛОГ-дороге (A1-уровень + C2-разъём), а
        # инцидентная дорога печатается в сообщении — чтобы «не приехало ничего» и
        # «приехала только половина» различались с первого взгляда.
        deadline = time.time() + 15.0
        logged_marker = f"[health.report] {marker}"
        found_log, seen_log, last_event = _wait_for_marker(drv, "errors", logged_marker, baseline_cursor, deadline)
        found_any, seen_any, _ = _wait_for_marker(drv, "errors", marker, baseline_cursor, time.time() + 5.0)
        assert found_log, (
            f"запись {logged_marker!r} не найдена в плоскости errors за 15с после успешного "
            f"health.report(level=ERROR) на {target_process!r} "
            f"(records_seen={seen_log}, инцидентная дорога {'дошла' if found_any else 'тоже молчит'}"
            f", seen={seen_any}, последняя запись={last_event!r}) — "
            "разъём ERROR-лог -> ErrorManager -> errors-плоскость не доставляет, "
            "хотя команда отрапортовала success"
        )

        # ---- П-2: тишина ui объяснена ПРИЧИНОЙ, а не заявлена ----

        # Синтетическое ui.event тем же путём доставки, что и живой клик (без клика).
        # HeadlessGuiProcess не регистрирует ни одного debug-обработчика ui.tap.* —
        # ping ОБЯЗАН честно отказать. Если он вдруг успешен — в headless появился
        # производитель ui.event, и заявление «ui молчит по архитектурной причине»
        # больше не верно: тест обязан покраснеть, а не молча остаться зелёным.
        # Сперва — что процесс презентации ЖИВ и отвечает на обычную команду.
        # Без этой пары отказ ping'а ниже читался бы одинаково в двух разных мирах:
        # «приёмника команды нет» (то, что мы утверждаем) и «процесс мёртв/не
        # отвечает» (тогда тишина ui не доказывает ровным счётом ничего).
        gui_health = unwrap(drv.send_command("gui", "health.status", {}, timeout=5.0), leaf=True)
        assert gui_health.get("success") is True, (
            f"процесс gui не отвечает на health.status: {gui_health!r} — отказ ui_tap_ping "
            "ниже был бы отказом мёртвого процесса, а не отсутствием приёмника команды"
        )

        ping = drv.ui_tap_ping("gui", note=f"tester-ui-silence-proof-{uuid.uuid4().hex[:8]}")
        assert isinstance(ping, dict), f"ui_tap_ping() вернул не dict: {ping!r}"
        assert ping.get("success") is not True, (
            f"ui_tap_ping() внезапно УСПЕШЕН в headless: {ping!r} — значит в "
            "HeadlessGuiProcess появился приёмник ui.tap.ping, и утверждение «ui молчит "
            "по архитектурной причине» больше не верно — пересмотреть тест, а не подгонять"
        )

        # Честно отказавший ping не мог сам породить ui.event — тишина плоскости при
        # этом отказе значит именно «нет производителя», а не «раздражитель не сработал».
        ui_page = drv.events_page(plane="ui")
        assert ui_page["success"] is True
        assert ui_page["count"] == 0, (
            f"ui-плоскость непуста ({ui_page['count']}) при честно отказавшем ping — "
            "кто-то ещё пушит ui.event помимо ping'а; событие(я): "
            f"{ui_page.get('items')}"
        )
    finally:
        harness.stop()
