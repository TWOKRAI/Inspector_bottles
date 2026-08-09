# -*- coding: utf-8 -*-
"""Живая приёмка корзины 2 сквозного ревью Ф5 — восемь проверок на реальном бэкенде.

Зачем живьём, если 6449 тестов зелены. Тесты доказывают МЕХАНИКУ; живой прогон
ловит другой класс — проводку: сигнал, который никто не подключил, поле, не
доехавшее до поверхности, правило, работающее на моке и мёртвое на реальном
процессе. Этот класс на проекте задокументирован отдельно, и корзина 1 уже
показала его дважды.

Что проверяется (по пунктам фикс-плана):

    L1  п.2 B-1-1  — готовность PM честна: `introspect.capabilities` отвечает
                     сразу после старта, в журнале boot нет «No handler».
    L2  п.1 B-5-1  — снятие подписки действительно останавливает поток записей
                     (форвардер-сирота гнал бы их вечно мёртвому адресу).
    L3  п.8/9 C-3-1/C-2-1 — новые поля окна доставки доехали до ответа драйвера,
                     и `cost_exceeds_window` поднимается при втором клиенте.
    L4  п.3 A-A1-1 — `publish=null` слоистым путём реально снимает гейт.
    L5  п.4 A-A1-2 — сброс родителя `telemetry` не режет непрозрачный лист.
    L6  п.6 A-A4-1 — `{}` в слое = владение (решение владельца Г3).
    L7  п.7 A-A4-2 — слой, молчащий про уровень, его не двигает (границы
                     сценария названы в докстринге самой проверки).
    L8  п.10       — `persist` в config.reload отказывает громко и ничего не пишет.

Чего здесь НЕТ и почему — названо вслух:

    п.5 A-A6-1 (схлопывание повторов отказа) живьём не провоцируется без
    инъекции сбоя в пересборку: залипший отказ — это состояние, которого на
    здоровом стенде не бывает. Доказан продакшн-путём в pytest через настоящий
    `sweep_session_ttl` (2 теста) + 4 слом-инъекции.
    п.10 (удаление мёртвого фасада) и п.11 (док-фиксы) живой поверхности не имеют.

Запуск: ``python -m backend_ctl.probes.probe_basket2_live`` (BACKEND_CTL зонд
выставляет сам). Прогон ~2 минуты. Стенд одиночный — порт 8765 не терпит двух.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["BACKEND_CTL"] = "1"
# L7: машинный контекст задаётся ДО старта — именно его частичный слой и затирал.
os.environ["INSPECTOR_LOG_LEVEL"] = "DEBUG"

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

from backend_ctl.driver import _leaf_result  # noqa: E402
from backend_ctl.harness import BackendHarness  # noqa: E402

RECIPES = PROJECT_ROOT / "multiprocess_prototype" / "recipes"
BASE_RECIPE = RECIPES / "dualcam_synth.yaml"
#: Рецепт стенда: топология dualcam_synth + слой, который говорит ТОЛЬКО про
#: каналы. Ровно такой слой и возвращал уровень окружения к дефолту L0 (A-A4-2).
RECIPE_PARTIAL = RECIPES / "_probe_basket2_partial.yaml"

CHILD = "camera_0"
FAILURES: list[str] = []
SKIPPED: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


def make_partial_recipe() -> None:
    """Слой рецепта, молчащий про уровень и говорящий только про каналы."""
    import yaml

    data = yaml.safe_load(BASE_RECIPE.read_text(encoding="utf-8"))
    data["blueprint"]["observability"] = {
        "defaults": {"channels": {"messages_file": {"enabled": True}}},
    }
    RECIPE_PARTIAL.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def obs(drv, process: str, **args) -> dict:
    return _leaf_result(drv.send_command(process, "introspect.observability", args, timeout=25.0)) or {}


def level_of(snapshot: dict) -> str:
    return (((snapshot.get("effective") or {}).get("logger") or {}).get("default_level")) or "?"


# --------------------------------------------------------------------------


def l1_ready_signal(drv) -> None:
    """B-1-1: готовность PM объявляется после регистрации команд."""
    log("\n--- L1 (п.2, B-1-1): честный ready-сигнал оркестратора ---")
    reply = drv.send_command("ProcessManager", "introspect.capabilities", {}, timeout=25.0)
    ok = bool(reply.get("success"))
    check(ok, "introspect.capabilities отвечает сразу после старта", f"success={ok}")

    caps = _leaf_result(reply) or {}
    processes = caps.get("processes") or caps.get("commands") or {}
    check(bool(processes), "ответ содержательный, а не пустая оболочка", f"ключей: {len(processes)}")


def _emit(drv, marker: str) -> None:
    """Заставить процесс написать опознаваемую запись.

    Ждать «фонового» потока нельзя: синтетический стенд на INFO молча не пишет
    почти ничего, и первая редакция этой проверки получила ноль записей ДО снятия
    подписки — то есть её вторая половина («поток прекратился») была вакуумной.
    Молчащий детектор ничего не доказывает, поэтому источник провоцируется явно.
    """
    drv.send_command(
        CHILD,
        "health.report",
        {"message": f"{marker}::{CHILD}", "level": "ERROR", "context": "probe_basket2"},
        timeout=10.0,
    )


def _collect(drv, marker: str, wait: float = 5.0) -> int:
    seen = 0
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        for rec in drv.observability_records(level="DEBUG"):
            if marker in str(rec.get("message") or ""):
                seen += 1
        time.sleep(0.3)
    return seen


def _drain(drv) -> None:
    for _ in range(3):
        drv.observability_records(level="DEBUG")
        time.sleep(0.2)


def l2_unsubscribe_stops_the_flow(drv) -> None:
    """B-5-1: снятие намерения реально останавливает поток записей."""
    log("\n--- L2 (п.1, B-5-1): снятие подписки останавливает поток ---")
    # Адрес подписчика НЕ подменяем: записи пушатся `targets=[subscriber]`, и
    # произвольная строка уводит их по несуществующему адресу — драйвер тогда не
    # видит потока ни до снятия, ни после, и ОБЕ половины пары вакуумны (поймано
    # первой редакцией этого зонда). По умолчанию подписчик — сам драйвер.
    drv.observability_tail_all()
    time.sleep(1.5)
    _drain(drv)

    _emit(drv, "BASKET2_WHILE_SUBSCRIBED")
    during = _collect(drv, "BASKET2_WHILE_SUBSCRIBED")
    check(during > 0, "подписка даёт поток (контроль: иначе проверять нечего)", f"записей с маркером: {during}")

    drv.observability_untail_all()
    time.sleep(2.0)
    _drain(drv)

    _emit(drv, "BASKET2_AFTER_UNTAIL")
    after = _collect(drv, "BASKET2_AFTER_UNTAIL")
    check(
        after == 0,
        "после снятия поток прекращается (форвардера-сироты нет)",
        f"записей с маркером после untail: {after}",
    )


def l3_delivery_window_fields(drv) -> None:
    """C-3-1 / C-2-1: новые поля окна доехали до ответа и работают."""
    log("\n--- L3 (п.8/9, C-3-1/C-2-1): поля окна доставки на живом ответе ---")
    out = drv.config_reload_verified(CHILD, observability={"log_level": "DEBUG"}, settle=2.0)
    has_fields = "reset_planes" in out and "cost_exceeds_window" in out
    check(has_fields, "reset_planes и cost_exceeds_window есть в ответе драйвера", f"ключи: {sorted(out)[:12]}")
    check(
        out.get("counters_reset") is False and out.get("reset_planes") == [],
        "на спокойном стенде база не уехала (контроль на ложную тревогу)",
        f"counters_reset={out.get('counters_reset')} reset_planes={out.get('reset_planes')}",
    )

    # Второй клиент льёт опросы в то же окно — вычет обязан признать себя
    # недостоверным, а не объявить пишущий процесс молчащим.
    stop = threading.Event()

    def _noise() -> None:
        while not stop.is_set():
            try:
                obs(drv, CHILD, flush=True)
            except Exception:  # noqa: BLE001 — шумовой поток не судит
                pass

    noisy = threading.Thread(target=_noise, daemon=True)
    noisy.start()
    try:
        contested = drv.config_reload_verified(CHILD, observability={"log_level": "DEBUG"}, settle=2.0)
    finally:
        stop.set()
        noisy.join(timeout=5.0)

    verdict_honest = contested.get("cost_exceeds_window") is True or contested.get("silent_source") is False
    check(
        verdict_honest,
        "при втором клиенте вердикт не выдаёт уверенную тишину",
        f"cost_exceeds_window={contested.get('cost_exceeds_window')} "
        f"silent_source={contested.get('silent_source')} "
        f"self_cost={contested.get('self_cost')} written_delta={contested.get('written_delta')}",
    )


def l4_publish_none_via_layers(drv) -> None:
    """A-A1-1: publish=null слоистым путём снимает гейт по-настоящему."""
    log("\n--- L4 (п.3, A-A1-1): publish=null на слоистом пути ---")
    drv.telemetry_reconfigure(CHILD, publish={"metrics": {"fps": {"interval_sec": 1.0}}}, mode="replace")
    time.sleep(1.0)
    drv.send_command(CHILD, "config.reload", {"telemetry": {"publish": None}}, timeout=25.0)
    time.sleep(1.5)
    snap = _leaf_result(drv.send_command(CHILD, "introspect.telemetry", {}, timeout=25.0)) or {}
    publish = snap.get("publish")
    check(
        publish in (None, {}, False) or not publish,
        "гейт публикации снят фактически, а не только success=true",
        f"introspect.telemetry.publish = {publish!r}",
    )


def l5_opaque_survives_parent_reset(drv) -> None:
    """A-A1-2: сброс родителя не режет непрозрачный лист троттла."""
    log("\n--- L5 (п.4, A-A1-2): сброс родителя не пробивает opaque-лист ---")
    drv.send_command(
        CHILD,
        "config.reload",
        {"observability": {"telemetry": {"throttle": {"processes.**.state.fps": 2.0}}}},
        timeout=25.0,
    )
    reply = drv.send_command(CHILD, "config.reload", {"observability_reset": ["telemetry"]}, timeout=25.0)
    result = _leaf_result(reply) or {}
    snap = obs(drv, CHILD, audit_limit=10)
    entries = (snap.get("audit") or {}).get("entries") or []
    resets = [e for e in entries if e.get("action") == "reset"]
    keys = [k for e in resets for k in (e.get("keys") or [])]
    phantom = [k for k in keys if "processes.**" in k]
    check(
        not phantom,
        "в аудите нет ключей, которых в namespace не существует",
        f"снятые ключи: {keys or '—'} (success={result.get('success')})",
    )


def l6_empty_dict_is_ownership(drv) -> None:
    """A-A4-1 / решение Г3: `{}` в слое = владение."""
    log("\n--- L6 (п.6, A-A4-1 + решение Г3): пустой словарь = владение ---")
    drv.config_reload(CHILD, observability={"scopes": {}}, timeout=25.0)
    snap = obs(drv, CHILD)
    prov = snap.get("provenance") or {}
    owner = (prov.get("scopes") or {}).get("layer") if isinstance(prov.get("scopes"), dict) else prov.get("scopes")
    check(
        owner == "session",
        "provenance отдаёт слой, который ДЕЙСТВИТЕЛЬНО владеет пустым словарём",
        f"provenance[scopes] = {prov.get('scopes')!r}",
    )


def l7_partial_layer_does_not_move_the_level(drv) -> None:
    """A-A4-2 — то, что на ЭТОМ стенде проверяемо, и честная граница.

    Исходный сценарий находки — «частичный слой возвращает уровень из
    `INSPECTOR_LOG_LEVEL` к дефолту L0» — на прототипном стенде НЕ воспроизводится,
    и первая редакция зонда упала именно на этом. Причина не в правке, а в стенде:
    `system.yaml:47` задаёт `log_level: INFO` ЯВНО, то есть слоем приложения. Явный
    ключ владеет и обязан побеждать машинный контекст — это правило, а не дефект.
    ADR-PM-020 отмечал ровно это: «в прототипе `system.yaml` всегда несёт секцию
    observability, а значит слои никогда не молчат». Стенд, где уровень не задан ни
    одним слоем, пришлось бы построить отдельно.

    Поэтому живьём проверяется то же ПРАВИЛО на доступном материале: слой, который
    про уровень молчит, не двигает действующий уровень; слой, который его задаёт, —
    двигает. Пара, а не одиночный маркер.
    """
    log("\n--- L7 (п.7, A-A4-2): частичный слой не двигает действующий уровень ---")
    before = level_of(obs(drv, CHILD))

    drv.config_reload(CHILD, observability={"channels": {"messages_file": {"enabled": True}}}, timeout=25.0)
    time.sleep(1.0)
    after_partial = level_of(obs(drv, CHILD))
    check(
        after_partial == before,
        "слой, молчащий про уровень, оставил его на месте",
        f"{before} → {after_partial}",
    )

    drv.config_reload(CHILD, observability={"log_level": "WARNING"}, timeout=25.0)
    time.sleep(1.0)
    after_explicit = level_of(obs(drv, CHILD))
    check(
        after_explicit == "WARNING",
        "пара к нему: слой, который уровень ЗАДАЁТ, его двигает",
        f"{after_partial} → {after_explicit}",
    )
    # Вернуть стенд в исходное — дальше идут проверки, которым нужен живой поток.
    drv.send_command(CHILD, "config.reload", {"observability_reset": ["log_level"]}, timeout=25.0)


def l8_persist_is_refused(drv) -> None:
    """п.10: persist отказывает громко и ничего не пишет."""
    log("\n--- L8 (п.10): persist в config.reload — громкий отказ ---")
    # Сравниваются КЛЮЧИ слоя, а не весь снимок: в нём живёт обратный отсчёт TTL,
    # и он тикает между двумя чтениями сам по себе. Первая редакция сравнивала
    # снимок целиком и падала на разнице 280.5 → 280.4 — то есть ловила часы, а не
    # запись.
    before = sorted((obs(drv, CHILD).get("layers") or {}).get("session_keys") or [])
    reply = drv.send_command(
        CHILD,
        "config.reload",
        {"observability": {"log_level": "ERROR"}, "persist": True},
        timeout=25.0,
    )
    result = _leaf_result(reply) or {}
    refused = result.get("success") is False
    names_the_way = "observability.persist" in str(result.get("reason", ""))
    check(refused, "команда отказала, а не приняла молча", f"success={result.get('success')}")
    check(names_the_way, "отказ называет реальный способ записать навсегда", f"reason={result.get('reason')!r}")
    after = sorted((obs(drv, CHILD).get("layers") or {}).get("session_keys") or [])
    check(
        after == before,
        "отказ ничего не записал в слой сессии",
        f"до={before!r} | после={after!r}",
    )


def main() -> int:
    make_partial_recipe()
    harness = BackendHarness(recipe=RECIPE_PARTIAL, warmup=6.0)
    drv = harness.start()
    try:
        l1_ready_signal(drv)
        l7_partial_layer_does_not_move_the_level(drv)
        l2_unsubscribe_stops_the_flow(drv)
        l3_delivery_window_fields(drv)
        l4_publish_none_via_layers(drv)
        l5_opaque_survives_parent_reset(drv)
        l6_empty_dict_is_ownership(drv)
        l8_persist_is_refused(drv)
    finally:
        harness.stop()
        RECIPE_PARTIAL.unlink(missing_ok=True)

    SKIPPED.append("п.5 A-A6-1 — залипший отказ не провоцируется на здоровом стенде (доказан продакшн-путём в pytest)")
    SKIPPED.append("п.10 удаление фасада и п.11 док-фиксы — живой поверхности не имеют")

    log("\n" + "=" * 70)
    for line in SKIPPED:
        log(f"  [SKIP] {line}")
    if FAILURES:
        log(f"\nЖИВАЯ ПРИЁМКА КОРЗИНЫ 2: ПРОВАЛ — {len(FAILURES)} проверок")
        for f in FAILURES:
            log(f"  - {f}")
        return 1
    log("\nЖИВАЯ ПРИЁМКА КОРЗИНЫ 2: ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
