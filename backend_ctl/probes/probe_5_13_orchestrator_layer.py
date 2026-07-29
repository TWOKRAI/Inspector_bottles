# -*- coding: utf-8 -*-
"""Живой зонд Task 5.13 — оркестратор получает свою секцию наблюдаемости.

Закрывает живую половину приёмки: пары A1, A2, A3, A5, A6 и A11. Остальные
доказаны pytest'ом (`test_pm_observability_routing.py`), но три из них — про
РЕАЛЬНЫЙ boot оркестратора, а его в unit-тесте нет: PM спавнится отдельным
кодом, и именно там жил дефект.

Что проверяется и почему именно живьём:

    A1/A11  рецепт задаёт `defaults: DEBUG` и `processes.ProcessManager: ERROR`.
            PM обязан взять ERROR (поимённо) и НЕ взять DEBUG (оптовый ключ);
            ребёнок — наоборот. Это решение владельца Р1, и до 5.13 PM не брал
            ни того ни другого.
    A6      `effective.logger.log_directory` у PM непуст И указывает на каталог,
            в который PM ДЕЙСТВИТЕЛЬНО пишет. Доказывается файлом на диске:
            поле, совпадающее с реальностью только на словах, — это ровно тот
            класс сигнала, который этот план и вычищает.
    A3      switch на рецепт, МОЛЧАЩИЙ про наблюдаемость, снимает слой L2 у PM
            (уровень возвращается к L1), а не оставляет покинутый рецепт жить.
    A2      после switch у PM меняются И уровень, И источник слоя.
    A5      boot ≡ switch: один и тот же рецепт, поданный на старте и через
            switch, даёт ПОЭЛЕМЕНТНО равный `effective`.

Запуск: ``python -m backend_ctl.probes.probe_5_13_orchestrator_layer``
(BACKEND_CTL выставляется самим зондом). Прогон ~3 минуты: реальный headless
бэкенд, реальный switch.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["BACKEND_CTL"] = "1"

# Консоль Windows отдаёт cp1251/cp866: юникод в заголовке роняет весь прогон
# UnicodeEncodeError'ом ПОСЕРЕДИНЕ стенда — то есть зонд убивает не проверка, а
# печать про неё.
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

from backend_ctl.driver import _leaf_result  # noqa: E402
from backend_ctl.harness import BackendHarness  # noqa: E402

RECIPES = PROJECT_ROOT / "multiprocess_prototype" / "recipes"
#: Рецепт стенда: та же топология, что dualcam_synth, ПЛЮС секция наблюдаемости.
#: Пишется зондом и удаляется им же — в репозитории он не живёт.
RECIPE_LOUD = RECIPES / "_probe_5_13_loud.yaml"
#: Рецепт, МОЛЧАЩИЙ про наблюдаемость — им проверяется снятие слоя (A3).
RECIPE_SILENT = RECIPES / "dualcam_synth.yaml"

CHILD = "camera_0"
FAILURES: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    mark = "PASS" if ok else "FAIL"
    log(f"  [{mark}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


def make_loud_recipe() -> None:
    """Стендовый рецепт: топология dualcam_synth + секция наблюдаемости.

    Секция кладётся ВНУТРЬ ``blueprint:`` — рецепт v3 разворачивается
    ``unwrap_recipe``, и плоская секция до неё просто не доехала бы.
    """
    import yaml

    data = yaml.safe_load(RECIPE_SILENT.read_text(encoding="utf-8"))
    data["blueprint"]["observability"] = {
        # Оптовый ключ: детям — да, оркестратору — НЕТ (решение владельца Р1).
        "defaults": {"log_level": "DEBUG"},
        # Поимённо — единственный способ адресовать оркестратора.
        "processes": {"ProcessManager": {"log_level": "ERROR"}},
    }
    RECIPE_LOUD.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def obs(drv, process: str) -> dict:
    """Readback наблюдаемости процесса (не мутирующая команда)."""
    return _leaf_result(drv.send_command(process, "introspect.observability", {"audit_limit": 5}, timeout=25.0)) or {}


def level_of(snapshot: dict) -> str:
    return (((snapshot.get("effective") or {}).get("logger") or {}).get("default_level")) or "?"


def switch(drv, recipe: Path) -> dict:
    """Настоящий switch: та же команда и тот же путь, что у GUI."""
    from multiprocess_prototype.backend.launch import load_topology_dict

    td = load_topology_dict(recipe)
    return (
        _leaf_result(
            drv.send_command(
                "ProcessManager",
                "topology.apply",
                {"topology_dict": td, "recipe_path": str(recipe)},
                timeout=180.0,
            )
        )
        or {}
    )


def main() -> int:
    make_loud_recipe()
    harness = BackendHarness(recipe=RECIPE_LOUD, warmup=6.0)
    drv = harness.start()
    try:
        # ---------------- A1 + A11 + A6: boot -------------------------------
        log("\n--- boot на рецепте с секцией: A1, A11, A6 ---")
        pm_boot = obs(drv, "ProcessManager")
        child_boot = obs(drv, CHILD)
        pm_level_boot = level_of(pm_boot)
        child_level = level_of(child_boot)

        check(
            pm_level_boot == "ERROR",
            "A1: PM берёт дольку, названную его именем",
            f"PM default_level={pm_level_boot!r} (ожидали ERROR из processes.ProcessManager)",
        )
        check(
            pm_level_boot != "DEBUG",
            "A11: оптовый ключ рецепта до PM НЕ доходит",
            f"defaults.log_level=DEBUG, а у PM {pm_level_boot!r}",
        )
        check(
            child_level == "DEBUG",
            "A11 (вторая половина): у ребёнка оптовый ключ действует",
            f"{CHILD} default_level={child_level!r} (ожидали DEBUG из defaults)",
        )
        pm_flag = ((pm_boot.get("layers") or {}).get("recipe_defaults_applied"),)
        child_flag = (child_boot.get("layers") or {}).get("recipe_defaults_applied")
        check(
            pm_flag[0] is False and child_flag is True,
            "шаг 9: readback объясняет асимметрию, а не оставляет догадкой",
            f"PM recipe_defaults_applied={pm_flag[0]}, {CHILD}={child_flag}",
        )

        # A6 — поле обязано совпасть с реальностью на диске, а не только звучать.
        log_dir = ((pm_boot.get("effective") or {}).get("logger") or {}).get("log_directory") or ""
        root = Path(log_dir) if log_dir else None
        files = sorted(p.name for p in root.rglob("*.log")) if root and root.exists() else []
        check(
            bool(log_dir) and root is not None and root.exists() and bool(files),
            "A6: каталог логов PM непуст И существует, с файлами внутри",
            f"log_directory={log_dir!r}, файлов *.log={len(files)}",
        )

        # ---------------- A3 + A2: switch на молчащий рецепт -----------------
        log("\n--- switch на рецепт, молчащий про наблюдаемость: A3, A2 ---")
        res = switch(drv, RECIPE_SILENT)
        check(bool(res.get("success")), "switch применён", f"ответ: {str(res)[:180]}")
        pm_silent = obs(drv, "ProcessManager")
        pm_level_silent = level_of(pm_silent)
        src_boot = (pm_boot.get("layers") or {}).get("recipe_source") or ""
        src_silent = (pm_silent.get("layers") or {}).get("recipe_source") or ""

        check(
            pm_level_silent != "ERROR",
            "A3: молчащий рецепт СНЯЛ слой L2 у оркестратора",
            f"было ERROR, стало {pm_level_silent!r} (падение на L1/L0)",
        )
        check(
            src_boot != src_silent and RECIPE_SILENT.name in src_silent,
            "A2: у PM сменился И уровень, И источник слоя",
            f"источник {Path(src_boot).name!r} -> {Path(src_silent).name!r}",
        )
        # Свой слой назван отдельно от рассылки детям — тот самый разрыв,
        # которым дефект и жил.
        reset = res.get("observability_session_reset") or {}
        check(
            "orchestrator_recipe_keys" in reset,
            "ответ switch'а различает «раздал детям» и «применил себе»",
            f"observability_session_reset={reset}",
        )

        # ---------------- A5: boot ≡ switch ---------------------------------
        log("\n--- switch ОБРАТНО на тот же рецепт: A5 (boot ≡ switch) ---")
        # Дебаунс hot-swap (`replace_debounce_s`, дефолт 1.0с от ЗАВЕРШЕНИЯ прошлой
        # замены) отклоняет второй switch подряд: `{'debounced': True}`. Первая
        # редакция зонда паузы не делала и получала три «провала» A5 — при том что
        # switch просто не состоялся. Проверка, принимающая неслучившееся действие
        # за отрицательный результат, хуже отсутствующей: она обвиняет продукт.
        import time as _time

        _time.sleep(3.0)
        res_back = switch(drv, RECIPE_LOUD)
        if res_back.get("debounced"):
            _time.sleep(3.0)
            res_back = switch(drv, RECIPE_LOUD)
        check(bool(res_back.get("success")), "обратный switch применён", f"ответ: {str(res_back)[:180]}")
        pm_back = obs(drv, "ProcessManager")
        pm_level_back = level_of(pm_back)
        check(
            pm_level_back == "ERROR",
            "A5 (уровень): switch на тот же рецепт даёт то же, что boot",
            f"boot={pm_level_boot!r}, после switch={pm_level_back!r}",
        )
        eff_boot = (pm_boot.get("effective") or {}).get("logger") or {}
        eff_back = (pm_back.get("effective") or {}).get("logger") or {}
        # Поэлементно, а не побайтово: порядок ключей сериализации не гарантирован,
        # и «побайтово» мигало бы на несущественном.
        diff = [k for k in set(eff_boot) | set(eff_back) if eff_boot.get(k) != eff_back.get(k)]
        check(
            not diff,
            "A5 (весь effective.logger): boot и switch поэлементно равны",
            f"расхождений: {diff or 'нет'}",
        )
    finally:
        harness.stop()
        RECIPE_LOUD.unlink(missing_ok=True)

    log("\n" + "=" * 60)
    if FAILURES:
        log(f"ПРОВАЛЕНО проверок: {len(FAILURES)}")
        for f in FAILURES:
            log(f"  - {f}")
        return 1
    log("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
