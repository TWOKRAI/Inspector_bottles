# Выборочная проверка разметки пилота stage 0 (лид, 2026-11-07)

> По просьбе координатора: noise = 0 в четырёх строках подряд необычно, а размечал агент, не лид. Лид проверил 8 замечаний, отмеченных `real`, по коду (`git show 75f818845:…`, текущее дерево). Результат: все 8 подтверждены, ни одно не оказалось noise.

| Замечание | Модель | Проверка | Итог |
|---|---|---|---|
| 4.1: тест `test_atlas_does_not_import_framework` зелёный с рождения | Sonnet п.4, Opus п.9 | `git grep -E '^\s*(from\|import)\s+(multiprocess_framework\|Services\|Plugins)' 75f818845 -- 'scripts/atlas/*.py'` → пусто | real |
| 4.1: `threads` закреплён тестом A1 в форме `(имя, строка)` | оба | `test_scan.py:331`: `threads == (("worker-1", 11), ("self.label", 12))` | real |
| 4.1: «поднять SCANNER» ломает закреплённый формат | Opus п.1 | `test_scan.py:505`: `re.fullmatch(r"1-[0-9a-f]{12}", scan_mod.SCANNER)` | real |
| 4.1: правило `.schedule` даёт ложный `watch` на живом коде | оба | `Plugins/control/robot_control/plugin.py:328`: `self._ctx.scheduler.schedule(fire_at, float(last_ts)+transit_s, count, …)` — ≥ 2 аргументов | real |
| 4.1: классификация `tc` в `ast_graph.py` расходится с A1 | Opus п.3 | `ast_graph.py:87`: `inner = "tc" if (is_tc and kind == "hard") else kind` | real |
| 4.2a: у `command_specs`/`CommandSpec` нет читателя и нет кода | Sonnet п.1, Opus п.2 | `git grep -E 'command_specs\|CommandSpec\b' -- '*.py'` → пусто; `scan.py:89` держит `commands: tuple[str,...]` (только имена) | real |
| 4.2a: флагов `--rev`, `--exclude-from`, `--root` в атласе нет | Sonnet п.7, Opus (абзац «флаги 4.3») | `__main__.py:43`: есть только `--ref` | real |
| 4.2a: `interface.all` по `__init__.py` юнита даёт ложный факт | Opus п.6 | `config_module/__init__.py:16-25` — `ConfigFileWatcher` в `__all__` нет; он в `config_module/tools/__init__.py:21` | real |

Ограничения проверки: выборку (8 из ~55 замечаний) выбирал лид из пунктов с самым проверяемым доказательством, поэтому она смещена в сторону сильных; слабые «minor» (причины решений, break-injection) не проверялись и могли бы оказаться noise при строгой разметке. Ни одно замечание не воспроизводилось прогоном: проверялись только цитаты кода.
