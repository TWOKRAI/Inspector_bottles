# Plugins/hub/device_hub — Решения

## ADR-PH-001: Крэш процесса devices = ручной рестарт

**Статус:** принято (2026-06-11)
**Контекст:** Процесс `devices` помечен `protected: true` в base.yaml. RestartPolicy фреймворка (`restart_policy.py`) по умолчанию disabled=False, но даже при включении — ProcessMonitor ЯВНО пропускает protected-процессы:

```python
# process_monitor.py:504-514
if process_name in protected:
    self.process._log_warning(f"Process '{process_name}' protected — авто-рестарт ({reason}) пропущен")
    return
```

Это by-design: terminate живого protected (GUI, devices) = крах ядра. Protected-процессы управляются launcher'ом.

**Решение:** НЕ включать restart_policy для devices. Крэш protected-процесса = ручной рестарт приложения. GUI-индикация «hub мёртв» — через `quality: bad` по всем устройствам (supervisor перестаёт tick'ать → ts стареет → quality деградирует).

**Альтернатива (отвергнута):** Сделать devices non-protected + включить restart. Отвергнуто: non-protected → replace_blueprint убивает devices при переключении рецепта → потеря соединений, что противоречит always-on семантике.

**Следующий шаг:** Если потребуется авто-рестарт protected — нужна доработка framework: отдельная ветка в ProcessMonitor для protected (re-spawn, а не terminate+recreate), либо supervisor на уровне SystemLauncher. Задача за пределами текущей фазы.

## ADR-PH-002: Корень данных — корень репозитория; прежнее место — предупреждение

**Статус:** принято (2026-11-15)
**Контекст:** `_PROJECT_ROOT` в `plugin.py` считался как `parents[4]` — каталог НАД репозиторием, тогда как остальные плагины `Plugins/<группа>/<имя>/plugin.py` берут `parents[3]`. Относительный `registry_path: data/devices.yaml` и каталог `data/robot` (T5.3c: `resolved.parent / "robot"`) попадали в `<над корнем>/data/`, общий для всех worktree в `.claude/worktrees/`.
**Решение:** `_PROJECT_ROOT = parents[3]` (`device_hub` -> `hub` -> `Plugins` -> корень), без поиска маркеров. Данные автоматически НЕ переносятся: при отсутствии реестра и `robot/` по новому пути и наличии любого из них по прежнему (`_PROJECT_ROOT.parent / registry_path`) `configure` пишет одно предупреждение (`ctx.log_warning`) с обоими путями; владелец переносит `devices.yaml` и `robot/` вручную. Проверка зовётся, когда путь пришёл из корня проекта (не `INSPECTOR_DATA_DIR`); для абсолютного пути она вхолостую: прежнее место совпадает с новым; `OSError` при проверке логируется и не роняет запуск. Однократность — следствие: после первого сохранения реестр существует.
**Альтернатива (отвергнута):** автоматическая копия со старого места — тихая запись в данные владельца и риск затереть чужой реестр; поиск маркеров корня (`.git`, `pyproject.toml`) — лишний слой при равной функции.
**Следствие:** без ручного переноса GUI покажет пустой реестр; предупреждение видно только в логе процесса.

## См. также

- ADR-DH-014 (`Services/device_hub/DECISIONS.md`): итог основной остановки всех роботов — в ответе `robot_park_all` на исполнителе `device_io`; стоп хаба — в хуке `DeviceHubPlugin.request_stop` (C-60.b). Реализация в этом плагине: `plugin.py` (`request_stop`, `cmd_robot_park_all`, `command_options`).
