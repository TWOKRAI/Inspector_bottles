# -*- coding: utf-8 -*-
"""Живая приёмка корзины 2.1 — правило Г3 на всех швах, на реальном бэкенде.

Зачем живьём, если 6466 тестов зелены и слом-инъекция 9/9. Тесты доказывают
МЕХАНИКУ; живой прогон ловит другой класс — проводку: правило, работающее на
фикстуре и мёртвое на настоящем процессе, поле, не доехавшее до поверхности,
файл, который команда обещала записать. На этом проекте класс задокументирован
отдельно, и корзина 2 показала его четырьмя дефектами самого зонда.

Что проверяется:

    G1  шов 5 — оператор может СНЯТЬ собственную правку (`{}` поверх своей же);
    G2  побочный путь Г3 — затенённый ключ уносит свой срок, и снятое НАЗВАНО;
    G3  шов 1 — `observability.persist` не меняет действующее состояние;
    G4  швы 2/3 — спутник на диске содержит владение, а не воскресшие ключи;
    G5  шов 4 — `defaults` рецепта заглушается per-process у ОДНОГО процесса,
        сосед при этом наследует (пара, а не одиночный маркер);
    G6  находка Ф-3 — непрозрачный лист троттла заменяется целиком: вторая
        дельта не сливается с первой по ключам.

Шов 6 (слои поверх загрузочной телеметрии) живой поверхности через `publish: {}`
на этом стенде не имеет — синтетические процессы гейт публикации не строят;
доказан продакшн-путём в pytest (`apply_telemetry_layers` + перехват получателя)
и двумя инъекциями. Названо вслух, а не пропущено молча.

Стенд — `dualcam_synth` (синтетика, без железа), тот же, что у корзины 2, плюс
слой рецепта со ВСЕМИ формами: `defaults` + per-process. Стенд обязан содержать
непустой L2, иначе «владение пустотой» проверять не над чем (урок R6 Ф5).

Запуск: ``python -m backend_ctl.probes.probe_basket2_1_live``. Прогон ~1.5 мин.
Стенд одиночный — порт 8765 не терпит двух.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["BACKEND_CTL"] = "1"

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

from backend_ctl.driver import _leaf_result  # noqa: E402
from backend_ctl.harness import BackendHarness  # noqa: E402

RECIPES = PROJECT_ROOT / "multiprocess_prototype" / "recipes"
RECIPE_G3 = RECIPES / "_probe_basket2_1_g3.yaml"

#: Стенды, на которых правило проверяется. Первый — синтетика (детерминирован, без
#: железа), второй — ПРИКЛАДНОЙ рецепт с настоящими плагинами: правило слоёв не
#: имеет права зависеть от того, кто именно крутится в процессах, и утверждать это
#: без второго стенда было бы обобщением с одного случая. Пара «владелец / сосед»
#: у каждого своя — оба процесса обязаны быть в топологии рецепта.
STANDS = {
    "dualcam_synth": ("dualcam_synth.yaml", "camera_0", "camera_1"),
    "webcam_sketch": ("webcam_sketch.yaml", "seg", "lines"),
}

BASE_RECIPE = RECIPES / STANDS["dualcam_synth"][0]
OWNER = "camera_0"  # у него per-process владение пустотой
NEIGHBOUR = "camera_1"  # он наследует defaults — контрольный сосед

#: Охваты, объявленные рецептом в `defaults`. Именно их оператор и снимает.
RECIPE_SCOPES = {"SYSTEM": {"min_level": "DEBUG"}}

FAILURES: list[str] = []
SKIPPED: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


def make_recipe() -> None:
    """Стенд со ВСЕМИ формами слоя L2: оптовый `defaults` + адресный per-process."""
    import yaml

    data = yaml.safe_load(BASE_RECIPE.read_text(encoding="utf-8"))
    data["blueprint"]["observability"] = {
        "defaults": {"scopes": dict(RECIPE_SCOPES)},
        "processes": {OWNER: {"scopes": {}}},
    }
    RECIPE_G3.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def obs(drv, process: str, **args) -> dict:
    return _leaf_result(drv.send_command(process, "introspect.observability", args, timeout=25.0)) or {}


def reload_obs(drv, process: str, section: dict, **extra) -> dict:
    payload = {"observability": section}
    payload.update(extra)
    return _leaf_result(drv.send_command(process, "config.reload", payload, timeout=25.0)) or {}


def owner_of(snapshot: dict, key: str) -> object:
    """Слой-владелец ключа по живому provenance.

    Читается ИМЕННО provenance, а не «resolved»: разрешённой секции в ответе
    команды нет вовсе — первая редакция зонда спрашивала `layers.resolved` и
    получала `<нет ключа>` на шести проверках подряд, то есть мерила свой
    читатель, а не систему. Владение пустотой видно здесь острее всего: ветка,
    объявленная `{}`, приходит ОДНИМ листом `scopes` со своим слоем, а
    унаследованная — набором `scopes.<имя>.<поле>`.
    """
    entry = (snapshot.get("provenance") or {}).get(key)
    return entry.get("layer") if isinstance(entry, dict) else "<нет ключа>"


def session_keys_of(snapshot: dict) -> list:
    return sorted((snapshot.get("layers") or {}).get("session_keys") or [])


def effective_scope(snapshot: dict, name: str, field: str) -> object:
    scopes = ((snapshot.get("effective") or {}).get("logger") or {}).get("scopes") or {}
    return (scopes.get(name) or {}).get(field, "<нет ключа>")


# --------------------------------------------------------------------------


def g5_defaults_are_silenced_per_process(drv) -> None:
    """Шов 4: `defaults` рецепта заглушён у ОДНОГО процесса, сосед наследует.

    Идёт первым: это состояние стенда на boot, до единой команды. Любая правка
    сессии ниже уже смешала бы два шва.
    """
    log("\n--- G5 (шов 4): defaults→per-process, владение пустотой у одного ---")
    owner_snap, neighbour_snap = obs(drv, OWNER), obs(drv, NEIGHBOUR)
    # Дискриминатор точный: при каноническом мерже долька camera_0 была бы такой
    # же, как у соседа (`defaults` побеждает `{}`), и лист `scopes` не появился
    # бы вовсе — provenance показал бы ровно ту же картину, что у camera_1.
    check(
        owner_of(owner_snap, "scopes") == "recipe",
        f"{OWNER}: ветка `scopes` пришла ОДНИМ листом за рецептом — оптовый defaults заглушён",
        f"provenance[scopes] = {owner_of(owner_snap, 'scopes')!r}",
    )
    check(
        owner_of(neighbour_snap, "scopes") == "<нет ключа>"
        and owner_of(neighbour_snap, "scopes.SYSTEM.min_level") == "recipe",
        f"пара к нему: {NEIGHBOUR} НАСЛЕДУЕТ defaults по ключам (правило узкое, не тотальное)",
        f"provenance[scopes]={owner_of(neighbour_snap, 'scopes')!r} "
        f"provenance[scopes.SYSTEM.min_level]={owner_of(neighbour_snap, 'scopes.SYSTEM.min_level')!r}",
    )
    # Действующее состояние, а не только бухгалтерия слоёв: у соседа охват
    # рецепта реально работает, у владельца пустоты — нет.
    check(
        effective_scope(neighbour_snap, "SYSTEM", "min_level") == "DEBUG"
        and effective_scope(owner_snap, "SYSTEM", "min_level") != "DEBUG",
        "и это видно в ДЕЙСТВУЮЩЕМ конфиге логгера, а не только в провенансе",
        f"{OWNER}: SYSTEM.min_level={effective_scope(owner_snap, 'SYSTEM', 'min_level')!r} | "
        f"{NEIGHBOUR}: {effective_scope(neighbour_snap, 'SYSTEM', 'min_level')!r}",
    )


def g1_operator_can_take_back_his_edit(drv) -> None:
    """Шов 5: снять собственную правку второй командой."""
    log("\n--- G1 (шов 5): оператор снимает свою же правку ---")
    reload_obs(drv, NEIGHBOUR, {"scopes": {"BUSINESS": {"min_level": "INFO"}}}, ttl=600)
    time.sleep(0.8)
    after_set = session_keys_of(obs(drv, NEIGHBOUR))
    check(
        after_set == ["scopes.BUSINESS.min_level"],
        "контроль: правка легла в слой сессии поимённо (иначе снимать нечего)",
        f"session_keys = {after_set}",
    )

    reload_obs(drv, NEIGHBOUR, {"scopes": {}}, ttl=600)
    time.sleep(0.8)
    after_clear = session_keys_of(obs(drv, NEIGHBOUR))
    check(
        after_clear == ["scopes"],
        "вторая команда СНЯЛА первую: в сессии остался один лист-владение",
        f"session_keys = {after_clear} (при каноне здесь был бы 'scopes.BUSINESS.min_level')",
    )


def g2_shadowed_key_loses_its_deadline(drv) -> None:
    """Побочный путь Г3: срок ушёл вместе с ключом, и снятое названо в аудите."""
    log("\n--- G2 (побочный путь): затенённый ключ уносит свой срок ---")
    snap = obs(drv, NEIGHBOUR, audit_limit=10)
    ttl_view = (snap.get("layers") or {}).get("ttl") or {}
    orphans = [k for k in ttl_view if k.startswith("scopes.")]
    check(
        not orphans,
        "срок затенённого ключа не пережил свой ключ",
        f"сроки под scopes.*: {orphans or '—'} (весь ttl: {sorted(ttl_view)})",
    )

    entries = (snap.get("audit") or {}).get("entries") or []
    touches = [e for e in entries if e.get("action") == "touch"]
    named = [k for e in touches for k in (e.get("removed") or [])]
    check(
        "scopes.BUSINESS.min_level" in named,
        "снятый той же командой ключ НАЗВАН в записи аудита",
        f"removed за последние записи: {named or '—'}",
    )


def g6_opaque_leaf_is_replaced_whole(drv) -> None:
    """Находка Ф-3: вторая дельта троттла заменяет первую целиком, а не мержится.

    Адресат — ОРКЕСТРАТОР: центральный store-троттл живёт только у него
    (у обычного процесса ``throttle_rules`` пуст, и обе половины пары были бы
    вакуумны). Читается применённое правило, а не слой: слой без применения
    доказывал бы бухгалтерию, а не поведение.
    """
    log("\n--- G6 (Ф-3): непрозрачный лист троттла заменяется целиком ---")
    pm = "ProcessManager"
    reload_obs(drv, pm, {"telemetry": {"throttle": {"processes.aaa.state.fps": 1.0}}})
    time.sleep(0.8)
    first = _leaf_result(drv.send_command(pm, "introspect.telemetry", {}, timeout=25.0)) or {}
    if not (first.get("throttle_rules") or {}):
        SKIPPED.append("G6 — у стенда нет центрального троттла (throttle_rules пуст): проверять нечего")
        log("  [SKIP] у стенда нет центрального store-троттла — обе половины были бы вакуумны")
        return
    check(
        "processes.aaa.state.fps" in (first.get("throttle_rules") or {}),
        "контроль: первая дельта реально применилась",
        f"throttle_rules = {sorted(first.get('throttle_rules') or {})}",
    )

    reload_obs(drv, pm, {"telemetry": {"throttle": {"processes.bbb.state.fps": 2.0}}})
    time.sleep(0.8)
    second = _leaf_result(drv.send_command(pm, "introspect.telemetry", {}, timeout=25.0)) or {}
    rules = second.get("throttle_rules") or {}
    check(
        "processes.bbb.state.fps" in rules and "processes.aaa.state.fps" not in rules,
        "лист заменён целиком: правило первой дельты не выжило",
        f"throttle_rules = {sorted(rules)}",
    )


def g3_persist_keeps_the_effective_state(drv) -> None:
    """Шов 1: `persist` переезжает владельцем, не трогая действующее состояние."""
    log("\n--- G3 (шов 1): persist не меняет действующее состояние ---")
    # Владение пустотой у процесса, чей слой L2 НЕПУСТ (defaults рецепта):
    # только на таком стенде воскрешение вообще наблюдаемо.
    reload_obs(drv, NEIGHBOUR, {"scopes": {}})
    time.sleep(0.8)
    before_snap = obs(drv, NEIGHBOUR)
    before_effective = effective_scope(before_snap, "SYSTEM", "min_level")
    check(
        owner_of(before_snap, "scopes") == "session",
        "контроль: до persist веткой владеет сессия",
        f"provenance[scopes] = {owner_of(before_snap, 'scopes')!r}",
    )

    reply = _leaf_result(drv.send_command(NEIGHBOUR, "observability.persist", {}, timeout=30.0)) or {}
    check(bool(reply.get("success")), "команда отчиталась успехом", f"success={reply.get('success')}")
    time.sleep(0.8)

    after_snap = obs(drv, NEIGHBOUR)
    after_effective = effective_scope(after_snap, "SYSTEM", "min_level")
    check(
        after_effective == before_effective,
        "ДЕЙСТВУЮЩЕЕ состояние после persist то же (ключи рецепта не воскресли)",
        f"SYSTEM.min_level: {before_effective!r} → {after_effective!r}",
    )
    check(
        owner_of(after_snap, "scopes") == "recipe" and not session_keys_of(after_snap),
        "владелец переехал в слой рецепта, сессия опустела — как и обещает команда",
        f"provenance[scopes]={owner_of(after_snap, 'scopes')!r} session_keys={session_keys_of(after_snap)}",
    )
    return reply


def g4_companion_on_disk_holds_the_ownership(reply: dict) -> None:
    """Швы 2/3: то, что записано на диск, — владение, а не воскресшие ключи."""
    log("\n--- G4 (швы 2/3): спутник на диске содержит владение ---")
    import yaml

    path = Path(str(reply.get("path") or ""))
    check(bool(path) and path.exists(), "файл спутника действительно создан", f"path={path}")
    if not path.exists():
        return
    section = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("observability") or {}
    saved = ((section.get("processes") or {}).get(NEIGHBOUR) or {}).get("scopes", "<нет ключа>")
    check(
        saved == {},
        "в спутнике лежит `scopes: {}` — снятие доехало до файла",
        f"observability.processes.{NEIGHBOUR}.scopes = {saved!r}",
    )

    from multiprocess_framework.modules.process_module.configs.observability_companion import (
        compose_over_base,
    )

    body, source = compose_over_base({"scopes": dict(RECIPE_SCOPES)}, RECIPE_G3, NEIGHBOUR)
    check(
        body.get("scopes") == {},
        "перезагрузка «рецепт + спутник» даёт то же владение (как после рестарта)",
        f"compose_over_base → scopes={body.get('scopes')!r}, источник={Path(source).name}",
    )


def select_stand(name: str) -> None:
    """Переключить зонд на другой стенд (глобальные имена — по одному месту)."""
    global BASE_RECIPE, OWNER, NEIGHBOUR
    if name not in STANDS:
        raise SystemExit(f"неизвестный стенд {name!r}; доступны: {', '.join(STANDS)}")
    recipe, OWNER, NEIGHBOUR = STANDS[name]
    BASE_RECIPE = RECIPES / recipe


def main(argv: list[str] | None = None) -> int:
    select_stand((argv or ["dualcam_synth"])[0])
    log(f"стенд: {BASE_RECIPE.name} (владелец пустоты: {OWNER}, сосед-наследник: {NEIGHBOUR})")
    make_recipe()
    harness = BackendHarness(recipe=RECIPE_G3, warmup=6.0)
    drv = harness.start()
    persist_reply: dict = {}
    try:
        g5_defaults_are_silenced_per_process(drv)
        g1_operator_can_take_back_his_edit(drv)
        g2_shadowed_key_loses_its_deadline(drv)
        g6_opaque_leaf_is_replaced_whole(drv)
        persist_reply = g3_persist_keeps_the_effective_state(drv) or {}
    finally:
        harness.stop()

    try:
        g4_companion_on_disk_holds_the_ownership(persist_reply)
    finally:
        RECIPE_G3.unlink(missing_ok=True)
        companion = RECIPE_G3.with_name(RECIPE_G3.stem + ".observability.yaml")
        companion.unlink(missing_ok=True)

    SKIPPED.append(
        "шов 6 (слои поверх boot телеметрии) — синтетический стенд гейта публикации не строит; "
        "доказан продакшн-путём в pytest + двумя инъекциями"
    )

    log("\n" + "=" * 70)
    for line in SKIPPED:
        log(f"  [SKIP] {line}")
    if FAILURES:
        log(f"\nЖИВАЯ ПРИЁМКА КОРЗИНЫ 2.1: ПРОВАЛ — {len(FAILURES)} проверок")
        for f in FAILURES:
            log(f"  - {f}")
        return 1
    log("\nЖИВАЯ ПРИЁМКА КОРЗИНЫ 2.1: ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
