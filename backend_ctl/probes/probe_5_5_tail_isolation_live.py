# -*- coding: utf-8 -*-
"""Живая приёмка 5.5 — хвост доезжает ТОЛЬКО своему подписчику (находка Н-A приёмки F2).

Дефект живьём (приёмка F2, 2026-08-12, `session_isolation=OFF` — прежний дефолт):
два подключённых клиента получали события друг друга — в плоскости `logs` по 17
записей с чужим `_address`, в `state` 419/417/417 по трём адресам, третий мёртв.
Следствие хуже самой протечки: **арифметика любого потребителя умножалась на число
клиентов**, а `dropped` считался по чужому трафику. Первая сверка приёмки дала
мнимые 68 записей против 46 — и именно это держало оценку оси 3 на 7 из 10.

Проверки:

    I1  каждый клиент получает ТОЛЬКО свои пуши: событий с чужим `_address` — ноль;
    I2  признак жизни: у обоих клиентов своих событий > 0 (иначе «чужих ноль»
        доказывалось бы тишиной — ровно тот вердикт по одному маркеру, который
        на этом проекте уже врал);
    I3  поле `_address` есть у пушей хвоста — механизм фильтрации опирается на
        него; события БЕЗ адреса считаются и называются числом (они по-прежнему
        уезжают широковещательно, это названная граница, а не догадка);
    I4  снятие хвоста одним клиентом не глушит хвост другого (форвардер
        per-subscriber; дефект соседнего класса — общий подписчик `backend_ctl`);
    I5  readback канала подтверждает заявленное: `session_isolation=true` и
        `sessions >= 2` в `introspect.router_stats`.

Пара к прогону — тот же зонд против стенда, поднятого с
``BACKEND_CTL_SESSION_ISOLATION=0``: I1 обязан покраснеть. Ручка и есть инъекция,
своей не нужно.

Стенд не поднимается зондом (решение владельца 2026-08-11)::

    BACKEND_CTL=1 INSPECTOR_GUI_UNATTENDED=1 INSPECTOR_LOG_DIR=logs_live/f2_5_5 \\
        .venv/Scripts/python.exe multiprocess_prototype/frontend/run.py

Запуск: ``python -m backend_ctl.probes.probe_5_5_tail_isolation_live``
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

from backend_ctl.driver import BackendDriver  # noqa: E402
from backend_ctl.endpoint_config import resolve_endpoint  # noqa: E402

#: Источник хвоста. Оба клиента тейлят ОДИН процесс намеренно: тогда потоки
#: событий отличаются только адресом, и протечка не спрячется за разницей темпа.
SOURCE = "camera_0"
#: Окно сбора. Хвост INFO на живом стенде идёт постоянно, 20 с хватает на десятки
#: записей у каждого; больше — только дольше.
WINDOW_SEC = 20.0

FAILURES: List[str] = []


def log(message: str) -> None:
    print(message, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


class Collector:
    """Сбор сырых сообщений клиента (колбэк зовётся из reader-потока драйвера)."""

    def __init__(self, driver: BackendDriver, name: str) -> None:
        self.driver = driver
        self.name = name
        self.messages: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        driver.subscribe(self._on_message)

    def _on_message(self, msg: Dict[str, Any]) -> None:
        with self._lock:
            self.messages.append(msg)

    def snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.messages)

    @property
    def session(self) -> str:
        return str(self.driver._session)  # noqa: SLF001 — идентичность клиента только здесь


def address_of(msg: Dict[str, Any]) -> Optional[str]:
    addr = msg.get("_address")
    if isinstance(addr, list) and len(addr) > 1:
        return str(addr[1])
    return None


def tally(collector: Collector, foreign_sessions: List[str], *, command: Optional[str] = None) -> Dict[str, int]:
    """Разложить принятое по адресам. ``command`` сужает счёт до одной подписки.

    Сужение обязательно для I4: у клиента их ДВЕ (хвост наблюдаемости и GUI-профиль
    состояния), и счёт по всем сообщениям объявил бы «подписка не снята» ровно
    потому, что жива соседняя. Первая редакция зонда так и сделала — и покраснела
    на живом стенде, назвав дефектом свою собственную арифметику.
    """
    own = foreign = anonymous = 0
    messages = [m for m in collector.snapshot() if command is None or m.get("command") == command]
    for msg in messages:
        sid = address_of(msg)
        if sid is None:
            anonymous += 1
        elif sid == collector.session:
            own += 1
        elif sid in foreign_sessions:
            foreign += 1
        else:
            # Адрес есть, но он не наш и не соседа по прогону: чужая сессия
            # (GUI, другой инструмент). Для вердикта это тоже протечка.
            foreign += 1
    return {"own": own, "foreign": foreign, "anonymous": anonymous, "всего": len(messages)}


def provoke(drv: BackendDriver, times: int = 5) -> None:
    """Заставить источник написать в хвост детерминированные записи.

    Каждая пересборка слоёв пишет INFO «пересобран из слоёв» у источника. Ключ
    законный и снимается тут же — стенд остаётся как был. Естественного темпа
    хвоста INFO на `camera_0` не хватает (~1 запись за 20 с), а на единицах
    «чужих ноль» доказывалось бы тишиной.
    """
    for _ in range(times):
        drv.config_reload(SOURCE, observability={"stats": {"flush_interval": 4.0}}, timeout=30.0)
        time.sleep(0.4)
    drv.send_command(SOURCE, "config.reload", {"observability_reset": ["stats.flush_interval"]}, timeout=30.0)


def isolation_readback(drv: BackendDriver) -> Dict[str, Any]:
    """`session_isolation` и число сессий канала — из живого router_stats."""
    stats = drv.introspect_router_stats("ProcessManager", timeout=25.0)

    found: Dict[str, Any] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("name") == "backend_ctl" and "session_isolation" in node:
                found.update(node)
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)

    walk(stats)
    return found


def main() -> int:
    host, port = resolve_endpoint()
    log("=" * 78)
    log("Живая приёмка 5.5 — хвост фильтруется по адресу подписчика")
    log(f"эндпоинт: {host}:{port} · источник хвоста: {SOURCE} · окно {WINDOW_SEC:.0f} с")
    log("=" * 78)

    a, b = BackendDriver(host=host, port=port), BackendDriver(host=host, port=port)
    try:
        a.connect()
        b.connect()
    except Exception as exc:  # noqa: BLE001 — отсутствие стенда объясняем командой запуска
        log(f"стенд недоступен ({exc}). Подними его так:")
        log("  BACKEND_CTL=1 INSPECTOR_GUI_UNATTENDED=1 INSPECTOR_LOG_DIR=logs_live/f2_5_5 \\")
        log("      .venv/Scripts/python.exe multiprocess_prototype/frontend/run.py")
        return 2

    try:
        # Первичная команда каждого клиента биндит его session→сокет на канале.
        a.get_status(SOURCE, timeout=25.0)
        b.get_status(SOURCE, timeout=25.0)

        info = isolation_readback(a)
        check(
            info.get("session_isolation") is True,
            "I5 канал заявляет изоляцию в readback",
            f"session_isolation={info.get('session_isolation')}, sessions={info.get('sessions')}",
        )
        check(
            int(info.get("sessions") or 0) >= 2,
            "I5b канал видит оба клиента (иначе судили бы одиночку)",
            f"sessions={info.get('sessions')}, clients={info.get('clients')}",
        )

        ca, cb = Collector(a, "A"), Collector(b, "B")
        log(f"\n  сессии: A={ca.session[:8]}… B={cb.session[:8]}…")

        res_a = a.observability_tail(SOURCE, level="INFO", timeout=30.0)
        res_b = b.observability_tail(SOURCE, level="INFO", timeout=30.0)
        log(f"  подписки на хвост: A success={res_a.get('success')}, B success={res_b.get('success')}")

        # Плоскость `state` — та самая, где приёмка видела 419/417/417 по трём
        # адресам. Она же даёт НЕОДИНОЧНЫЕ числа: на одном хвосте INFO camera_0
        # за 20 с приходит ~1 запись, и «чужих ноль» доказывалось бы тишиной.
        watch_a = a.watch_like_gui(timeout=30.0)
        watch_b = b.watch_like_gui(timeout=30.0)
        log(f"  GUI-профиль: A success={watch_a.get('success')}, B success={watch_b.get('success')}")

        provoke(a)
        time.sleep(WINDOW_SEC)

        stat_a, stat_b = tally(ca, [cb.session]), tally(cb, [ca.session])
        log(f"\n  A: {stat_a}\n  B: {stat_b}")
        # Разбивка обязательна в самом зонде: сводные own/foreign не различают
        # «протекли пуши состояния» от «протекли ответы соседа», а лечатся они
        # разным. Адрес, не совпавший ни с A, ни с B, — призрак прошлого прогона
        # (см. residual о живучести подписок после отключения клиента).
        for tag, collector in (("A", ca), ("B", cb)):
            breakdown: Dict[str, int] = {}
            for msg in collector.snapshot():
                sid = address_of(msg)
                who = "свой" if sid == collector.session else ("нет адреса" if sid is None else f"чужой:{sid[:8]}")
                key = f"{msg.get('type')}/{msg.get('command')} → {who}"
                breakdown[key] = breakdown.get(key, 0) + 1
            log(f"  разбивка {tag}:")
            for key, count in sorted(breakdown.items(), key=lambda item: -item[1]):
                log(f"    {count:5}  {key}")

        check(
            stat_a["foreign"] == 0 and stat_b["foreign"] == 0,
            "I1 ни один клиент не получил чужого пуша",
            f"чужих у A={stat_a['foreign']}, у B={stat_b['foreign']}",
        )
        # Порог, а не «> 0»: приёмка F2 видела по 17 событий на клиента, и вердикт
        # «чужих ноль» на одном-двух событиях доказывался бы тишиной. Число взято
        # с запасом ниже наблюдаемого темпа плоскости `state`, но выше единиц.
        check(
            stat_a["own"] >= 10 and stat_b["own"] >= 10,
            "I2 признак жизни: у обоих поток своих событий, а не единицы",
            f"своих у A={stat_a['own']}, у B={stat_b['own']} (порог 10)",
        )
        # I3 назван по тому, что он МЕРИТ. Первая редакция называлась «у пушей
        # хвоста есть адрес» — и краснела под broadcast'ом не из-за пушей: без
        # адреса приходят `type=response`, то есть ОТВЕТЫ на команды соседа
        # (плоскость reply, эхо `session` живёт только при изоляции). Разбор:
        # 2 и 7 таких у двух клиентов на стенде с OFF, 0 при ON.
        check(
            stat_a["anonymous"] == 0 and stat_b["anonymous"] == 0,
            "I3 безадресного трафика нет вовсе (под broadcast'ом это чужие ОТВЕТЫ)",
            f"безадресных у A={stat_a['anonymous']}, у B={stat_b['anonymous']}",
        )

        # I4 — снятие одним не глушит другого. Мерить обязано ОДНУ подписку:
        # GUI-профиль сам держит хвост (на WARNING), и провокация даёт в том числе
        # WARNING-записи («канал не резолвится» в окне пересборки). Первые две
        # редакции зонда покраснели именно на этом — счёт по всем сообщениям, а
        # затем счёт по команде объявляли «подписка не снята» ровно потому, что
        # жива соседняя. Поэтому у A профиль снимается, и остаётся один INFO-хвост.
        if info.get("session_isolation") is not True:
            # Под broadcast'ом I4 НЕ СУДИТСЯ: «своё» считается по адресу, а адреса
            # приезжают все подряд — вердикт зависел бы от того, чей форвардер
            # успел первым. Красный тут был бы красным не по причине (шрам
            # «слишком грубая инъекция ничего не доказывает»).
            log("\n  I4 пропущен: стенд в broadcast-режиме, адресный счёт неоднозначен")
        else:
            a.unwatch(timeout=30.0)
            time.sleep(2.0)
            tail_cmd = "observability.record"
            before_a = tally(ca, [cb.session], command=tail_cmd)["own"]
            before_b = tally(cb, [ca.session], command=tail_cmd)["own"]
            log(f"  записей хвоста до снятия: A={before_a}, B={before_b}")
            a.observability_untail(SOURCE, timeout=30.0)
            # Провокация ПОСЛЕ снятия: без неё «B тоже молчит» означало бы лишь, что
            # в окне не было записей, — то есть проверка зеленела бы на любом поведении.
            #
            # ОЖИДАНИЕ с дедлайном, а не фиксированный сон: на фиксированном окне
            # 8 с эта проверка дала +4 в одном прогоне и 0 в другом при том же коде.
            #
            # **Поправка (приёмка раунд 2, находка Н2-6).** Я объяснил это таймингом —
            # объяснение было неверным, а неверное объяснение живёт дольше дефекта.
            # Настоящая причина: `a.unwatch()` строкой выше ГЛУШИЛ прицельный хвост,
            # которого не создавал (находка Н2-2), и проверка мерила уже понижённую
            # подписку. Корень снят задачей 5.6; ожидание с дедлайном оставлено —
            # оно и правда отличает «медленно доехало» от «хвост соседа умер».
            deadline = time.monotonic() + 45.0
            after_a = before_a
            after_b = before_b
            rounds = 0
            while time.monotonic() < deadline:
                rounds += 1
                provoke(b, times=2)
                time.sleep(4.0)
                after_a = tally(ca, [cb.session], command=tail_cmd)["own"]
                after_b = tally(cb, [ca.session], command=tail_cmd)["own"]
                if after_b > before_b:
                    break
            log(f"  раундов провокации после снятия: {rounds}")
            check(
                after_b > before_b,
                "I4 хвост соседа жив после снятия чужой подписки",
                f"записей хвоста у B: {before_b} → {after_b}",
            )
            check(
                after_a == before_a,
                "I4b снятая подписка действительно перестала слать",
                f"записей хвоста у A: {before_a} → {after_a}",
            )
    finally:
        # Уборка снимает ОБЕ подписки каждого клиента. Первая редакция снимала
        # только хвост, и GUI-профиль оставался пушить в мёртвый адрес: числа
        # СЛЕДУЮЩЕГО прогона приходили с чужими адресами прошлого — ровно тот
        # третий мёртвый адрес, что видела приёмка F2 (419/417/417).
        for drv, name in ((a, "A"), (b, "B")):
            for what, call in (
                ("хвост", lambda d=drv: d.observability_untail(SOURCE, timeout=20.0)),
                ("GUI-профиль", lambda d=drv: d.unwatch(timeout=20.0)),
            ):
                try:
                    call()
                except Exception as exc:  # noqa: BLE001 — уборка не топит вердикт, но названа
                    log(f"  уборка {name}/{what}: {type(exc).__name__}: {str(exc)[:80]}")
            try:
                drv.close()
            except Exception:  # noqa: BLE001
                pass

    log("\n" + "=" * 78)
    if FAILURES:
        log(f"ПРОВАЛЕНО проверок: {len(FAILURES)}")
        for item in FAILURES:
            log(f"  - {item}")
        return 1
    log("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
