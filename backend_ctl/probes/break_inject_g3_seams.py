# -*- coding: utf-8 -*-
"""Слом-инъекция по правилу Г3 на всех швах (корзина 2.1, находки Ф-1 и Ф-3).

Каждая инъекция возвращает РОВНО один шов к каноническому ``deep_merge`` (или
снимает знание о непрозрачных путях у примитива), гоняет наблюдаемость целиком и
печатает, кто умер. Файлы восстанавливаются из бэкапа всегда.

**Прогноз объявлен ЗДЕСЬ, до прогона** — в ``EXPECTED``, и составлен ПОСЛЕ того,
как написаны все тесты (урок Ф5: прогноз по неполному набору — арифметика на
песке). Расхождение в любую сторону — находка: либо тест не сторожит то, что
заявлено, либо неверен прогноз, и разбирать надо оба случая.

Набор тестов шире целевого файла намеренно: шов, «починенный» ценой поломки
соседней гарантии, обязан проявиться здесь, а не на общем гейте.

Запуск: ``python -m backend_ctl.probes.break_inject_g3_seams``
        ``python -m backend_ctl.probes.break_inject_g3_seams G3-2 G3-6``
"""

from __future__ import annotations

import re
import shutil
import subprocess  # nosec B404 — dev-утилита: гоняет pytest проекта, как scripts/
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

MOD = ROOT / "multiprocess_framework/modules/process_module"
LAYERS = MOD / "configs/observability_layers.py"
COMPANION = MOD / "configs/observability_companion.py"
COMMANDS = MOD / "commands/builtin_commands.py"
RELOAD = MOD / "managers/observability_reload.py"

TESTS = [
    "multiprocess_framework/modules/process_module/tests/test_g3_ownership_on_all_seams.py",
    "multiprocess_framework/modules/process_module/tests/test_observability_empty_dict_ownership.py",
    "multiprocess_framework/modules/process_module/tests/test_observability_companion.py",
    "multiprocess_framework/modules/process_module/tests/test_observability_layers.py",
    "multiprocess_framework/modules/process_module/tests/test_telemetry_publish_null.py",
    "multiprocess_framework/modules/process_module/tests/test_telemetry_layers.py",
    "multiprocess_framework/modules/process_module/tests/test_observability_recipe_switch.py",
    "multiprocess_framework/modules/process_module/tests/test_observability_ttl.py",
    "multiprocess_framework/modules/process_manager_module/tests/test_pm_observability_routing.py",
]


def g3_1(text: str) -> str:
    """Слои снова не знают про непрозрачные пути (находка Ф-3).

    Бьём по ЕДИНСТВЕННОЙ точке правила — предикату листа. До корзины 2.2 та же
    сверка стояла буква в букву в трёх обходах, и инъекция в один из них
    оставляла два других правыми: частичный слом = ложный зелёный (урок I-7 Ф5).
    Теперь точка одна, и снимать надо её.
    """
    return text.replace(
        "    return not (isinstance(value, dict) and value and path not in OPAQUE_LAYER_PATHS)",
        "    return not (isinstance(value, dict) and value)  # G3-1: непрозрачность забыта",
    )


def g3_2(text: str) -> str:
    """Шов 1: переезд L3 → L2 снова каноническим мержем — ключи рецепта воскресают."""
    return text.replace(
        "                layer_merge(layers.recipe, session),",
        "                __import__(\n"
        '                    "multiprocess_framework.modules.data_schema_module", fromlist=["deep_merge"]\n'
        "                ).deep_merge(layers.recipe, session),  # G3-2",
    )


def g3_3(text: str) -> str:
    """Шов 2: дельта в спутник поверх сохранённого — каноном (снятие не доезжает до файла)."""
    return text.replace(
        "    processes[process_name] = layer_merge(processes.get(process_name) or {}, delta)",
        "    from ...data_schema_module import deep_merge  # G3-3\n"
        "    processes[process_name] = deep_merge(processes.get(process_name) or {}, delta)",
    )


def g3_4(text: str) -> str:
    """Шов 3: спутник поверх базы слоя — каноном (после рестарта ветка рецепта оживает)."""
    return text.replace(
        "    return layer_merge(body, persisted), str(companion_path(recipe_path))",
        "    from ...data_schema_module import deep_merge  # G3-4\n"
        "    return deep_merge(body, persisted), str(companion_path(recipe_path))",
    )


def g3_5(text: str) -> str:
    """Шов 4: ``defaults`` → per-process каноном («заглушить у одного» не работает)."""
    return text.replace(
        "    return layer_merge(defaults, per_process)",
        "    return deep_merge(defaults, per_process)  # G3-5",
    )


def g3_6(text: str) -> str:
    """Шов 6: слои поверх загрузочной телеметрии — каноном И без проверки на пустоту.

    Обе половины снимаются одной заплатой намеренно: это ровно та редакция, что
    была до правки. Частичная инъекция (снять только ``and layered_sub``) оставила
    бы вложенный случай зелёным и дала бы ложное «тест сторожит» — урок I-7 Ф5.
    """
    return text.replace(
        "        elif isinstance(boot_sub, dict) and isinstance(layered_sub, dict) and layered_sub:\n"
        '            merged_sub = layer_merge(boot_sub, layered_sub, prefix=f"{TELEMETRY_KEY}.{sub}.")',
        "        elif isinstance(boot_sub, dict) and isinstance(layered_sub, dict):  # G3-6\n"
        "            from ...data_schema_module import deep_merge\n"
        "            merged_sub = deep_merge(boot_sub, layered_sub)",
    )


def g3_7(text: str) -> str:
    """Шов 5: inline-дельта в сессию каноном — оператор не может снять свою же правку."""
    return text.replace(
        "                        layers.session = layer_merge(layers.session, obs_section)",
        "                        from ...data_schema_module import deep_merge  # G3-7\n"
        "                        layers.session = deep_merge(layers.session, obs_section)",
    )


def g3_8(text: str) -> str:
    """Побочный путь Г3: сроки затенённых ключей не снимаются — дедлайн-сирота."""
    return text.replace(
        "                        if shadowed:\n                            layers.session_forget_expiry(shadowed)",
        "                        if False:  # G3-8: сроки сирот остаются висеть\n"
        "                            layers.session_forget_expiry(shadowed)",
    )


def g3_9(text: str) -> str:
    """То же снятие, но молча: аудит не называет ключи, исчезнувшие этой же командой."""
    return text.replace(
        "                            removed=shadowed or None,",
        "                            removed=None,  # G3-9: снятое не названо",
    )


INJECTIONS = [
    ("G3-1 примитив забыл непрозрачные пути", LAYERS, g3_1),
    ("G3-2 переезд L3→L2 каноном", COMMANDS, g3_2),
    ("G3-3 запись в спутник каноном", COMPANION, g3_3),
    ("G3-4 спутник поверх базы каноном", COMPANION, g3_4),
    ("G3-5 defaults→per-process каноном", LAYERS, g3_5),
    ("G3-6 слои поверх boot телеметрии каноном", RELOAD, g3_6),
    ("G3-7 inline-дельта в сессию каноном", COMMANDS, g3_7),
    ("G3-8 сроки затенённых ключей не снимаются", COMMANDS, g3_8),
    ("G3-9 снятое не названо в аудите", COMMANDS, g3_9),
]

# Прогноз ДО прогона. Пусто у соседних файлов — заявка, что ни один шов не держится
# чужой гарантией: если сосед умрёт, значит свойство сторожил не тот тест.
EXPECTED: dict[str, set[str]] = {
    # Прогноз корзины 2.1 называл ДВА теста и не сошёлся — умерли пять. Причина
    # установлена и сама по себе находка: тогда сверка с OPAQUE_LAYER_PATHS стояла
    # в трёх обходах отдельно, инъекция била по одному (мержу), и три сторожа
    # правила из пяти оставались зелёными на сломанном правиле. После унификации
    # предиката (`_is_layer_leaf`, корзина 2.2) точка одна — её слом валит всех,
    # кто это правило охраняет, включая соседние файлы телеметрии. Прогноз
    # обновлён по факту, с объяснением: молча переписать число значило бы
    # подогнать ожидание под результат.
    "G3-1 примитив забыл непрозрачные пути": {
        "test_upper_layer_replaces_the_opaque_leaf",
        "test_resolve_and_provenance_agree_on_the_opaque_leaf",
        "test_pattern_with_dots_stays_one_key",
        "test_ttl_on_a_throttle_only_command_is_honoured_not_swallowed",
        "test_delta_expires_back_to_boot_rules",
    },
    "G3-2 переезд L3→L2 каноном": {
        "test_persist_does_not_change_the_effective_state",
    },
    "G3-3 запись в спутник каноном": {
        "test_second_persist_does_not_resurrect_the_first",
    },
    "G3-4 спутник поверх базы каноном": {
        "test_ownership_survives_a_restart",
    },
    "G3-5 defaults→per-process каноном": {
        "test_per_process_empty_dict_beats_defaults",
    },
    "G3-6 слои поверх boot телеметрии каноном": {
        "test_empty_publish_owns_and_does_not_revive_boot",
        "test_empty_nested_branch_owns_too",
    },
    # Каноном ключ из сессии не исчезает вовсе — значит и «сирота» не рождается,
    # и называть нечего: обе пары побочного пути умирают вместе с самим швом.
    "G3-7 inline-дельта в сессию каноном": {
        "test_operator_can_take_back_his_own_edit",
        "test_shadowed_key_loses_its_deadline_with_its_value",
        "test_shadowed_key_is_named_in_the_audit",
    },
    "G3-8 сроки затенённых ключей не снимаются": {
        "test_shadowed_key_loses_its_deadline_with_its_value",
    },
    "G3-9 снятое не названо в аудите": {
        "test_shadowed_key_is_named_in_the_audit",
    },
}


def run_tests() -> tuple[int, set[str]]:
    proc = subprocess.run(  # nosec B603 — аргументы литеральные, внешнего ввода нет
        [str(PY), "-m", "pytest", *TESTS, "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = proc.stdout + proc.stderr
    failed = set(re.findall(r"FAILED [^\s:]+::[^\s:]+::(\w+)", out))
    failed |= set(re.findall(r"FAILED [^\s:]+::(test_\w+)", out))
    # Ошибка сбора (сломанный импорт после заплаты) — не «умерли все», а брак
    # инъекции: без этой строки он выглядел бы как блестящее подтверждение.
    if "error" in out.lower() and "ERROR collecting" in out:
        failed.add("<ОШИБКА СБОРА — заплата сломала импорт>")
    return proc.returncode, failed


def main(argv: list[str] | None = None) -> int:
    wanted = set(argv or [])
    mismatches = 0
    for title, path, patch in INJECTIONS:
        if wanted and title.split(maxsplit=1)[0] not in wanted:
            continue
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        try:
            original = path.read_text(encoding="utf-8")
            broken = patch(original)
            if broken == original:
                print(f"{title}: ЗАПЛАТА НЕ ПРИМЕНИЛАСЬ — инъекция недействительна")
                mismatches += 1
                continue
            path.write_text(broken, encoding="utf-8")
            _code, failed = run_tests()
        finally:
            shutil.copy2(backup, path)
            backup.unlink(missing_ok=True)
        expected = EXPECTED.get(title, set())
        extra, missing = failed - expected, expected - failed
        if extra or missing:
            mismatches += 1
        print(f"{title}: {'СОВПАЛО' if not extra and not missing else 'РАСХОЖДЕНИЕ'} умерли={len(failed)}", flush=True)
        if missing:
            print(f"    выжили вопреки прогнозу: {sorted(missing)}")
        if extra:
            print(f"    умерли сверх прогноза:   {sorted(extra)}")

    code, failed = run_tests()
    print(f"\nконтроль (без слома): exit={code} умерли={sorted(failed) or 'НИКТО'}")
    print(f"расхождений с прогнозом: {mismatches}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
