# Win-E: harness pid_registry_checkout на Windows (pid лаунчера venv и pid потомка)

Файл: `multiprocess_framework/modules/process_manager_module/tests/test_pid_registry_checkout_acceptance.py`.
Патч: `C:/Users/INNOTECH/AppData/Local/Temp/claude/65f734dde6ea3dc7/ad054591-efb3-40e2-a684-2e0d7b7b2962/scratchpad/patches/wf-e1.patch`.

## Что сделано
- Хелпер (`_CHILD_SOURCE`) первым делом пишет `os.getpid()` в файл из `HARNESS_PID_FILE` (tmp + `os.replace`).
- `Harness.spawn` передаёт путь `logs/<n>_<cmd>.pid`, ждёт файл (`_wait_real_pid`, 30 с) и кладёт `proc.real_pid`.
- `wait_registered`, C3, C4, C7, C9, C10 и `_stale_registry` (C5/C6) сравнивают `real_pid`.
- Фикстура `procs`: пока лаунчер жив, `os.kill(real_pid)` потомка, затем `p.kill()`.

## Проверки
- Импорт: `...\Inspector_bottles--wf-b\multiprocess_framework\__init__.py`.
- Красный до правки: C3 `1 failed in 41.33s`.
- Лаунчер завершается вместе с потомком: зонд `launcher_probe.py` -> `poll before: None`, `poll after killing child: 9 after 0.05s`.
- 5 тестов по одному: C3 `1 passed 14.15s`, C4 `1 passed 11.63s`, C7 `1 passed 14.68s`, C9 `1 passed 38.16s`, C10 `1 passed 16.78s`.
- Весь файл: `18 passed, 3 warnings in 79.51s`; G3 = 0, G4 = 0.
- Висящие python-процессы (`Win32_Process`, `child.py` / `wf-b`): 0.
- `ruff check` и `ruff format --check`: чисто.

## Открыто
- `os.kill(real_pid)` в `procs` защищён лишь условием `p.poll() is None` (лаунчер жив): при смерти потомка между проверкой и kill теоретически возможен переиспользованный pid; окно микроскопическое.
- Если лаунчер убить отдельно, потомок остаётся жить (в тестах никто так не делает).
