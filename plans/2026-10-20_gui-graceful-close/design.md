# Design: gui-graceful-close

Спецификация к [`plan.md`](plan.md): факты по коду, целевое поведение, контракт хода, черновик, соседи, риски.

## Текущее состояние (по коду `main` = `a5485097a`)

**Путь крестика (режим запуска со встроенным GUI):**
- `MainWindow.closeEvent` — `multiprocess_prototype/frontend/windows/main_window.py:286-297`: при dirty-графе зовёт
  `confirm_discard_topology_changes` (:294 → :300-345), «Отмена» → `event.ignore()`, иначе геометрия и
  `super().closeEvent` — **окно закрывается сразу**.
- Диалог — общий helper `confirm_unsaved_changes`, `frontend/widgets/dialogs/unsaved_changes.py:27-76`
  (Сохранить default / Не сохранять / Отмена; в режиме `INSPECTOR_GUI_UNATTENDED` — авто-ответ «discard», :55-57).
  Заголовок жёсткий: «Несохранённые правки графа» (:61).
- Закрытие последнего окна завершает `app.exec()` (`frontend/app.py:919-920`); `aboutToQuit` ставит
  `process._stop_requested` (`app.py:1132-1134`).
- `GuiProcess.run` (`frontend/process.py:305-327`) после выхода из Qt зовёт `_request_system_shutdown` (:342-367):
  взводит общий `system_stop_event`, при его отсутствии — fallback IPC `system.shutdown`. Тесты:
  `frontend/tests/test_gui_process.py:629` (`test_sets_system_stop_event_when_available`), :648 (`test_fallback_ipc_when_no_event`).
- Итог: **окно уже скрыто, когда система только начинает гаситься.**

**Путь стопа, начатого не из GUI (`backend_ctl`, harness, скрипт):**
- `_cmd_system_shutdown` — `process_manager_module/process/process_manager_process.py:666-680`: взводит общий
  `system_stop_event` и свой `stop_event`, отвечает сразу `{"success": True, "message": "Shutdown initiated"}`.
  Параметров нет, режима «принудительно» нет.
- Ребёнок узнаёт о стопе в `_run_lifecycle` раннера (`process_manager_module/runner/process_runner.py:176-200`) —
  **только после возврата `process_instance.run()`**. У `GuiProcess` `run()` блокирован Qt-циклом, поэтому раннер
  GUI стоп-событий не видит. Safety-таймер GUI (`app.py:1115-1129`, период 1 с) смотрит только
  `process.should_stop()` = `_stop_requested` (`process_module/core/process_module.py:1044-1046`), который извне никто
  не ставит. **Гипотеза H2** (проверяет Task 0.1): на стопе, начатом не из GUI, встроенный GUI живёт до `terminate`
  от PM через `pm_graceful_s` = 5 с.
- Комментарий `app.py:1120-1126` («здесь НЕ показываем dirty-подтверждение») опирается на то, что `app.quit()` не
  зовёт `closeEvent`. **Гипотеза H1** (Task 0.1): в Qt 6 (`PySide6 6.10.3` в `.venv`) `QGuiApplication.quit()` сначала
  шлёт close-события окнам верхнего уровня; при dirty-графе стоп, начатый бэкендом, повиснет на модальном вопросе.

**Почему ход остановки сейчас показать нечем (CTO D4):**
- Корень процесса — `planes | transport | work` (`process_module/core/process_module.py:370-390`), закрытие LIFO.
  В `work` регистрируются хуки и плагины, затем записи наследника `_own_work`, затем **последним** `_WorkersStop`
  (`process_module.py:274-278`; класс — `process_module/lifecycle/process_lifecycle.py:176-200`). Значит воркеры
  закрываются **первыми**.
- `message_processor` — воркер `worker_manager` (`process_module/threads/system_threads.py:38-39`); единственный читатель
  каналов PM system/state/observability. Он гаснет **до** детей: `_own_work` PM (`process_manager_process.py:3537-3543`)
  кладёт `summary` и `children` раньше `_WorkersStop`. `GenericProcessManagerApp._own_work` кладёт `state_store` и
  watcher'ы ещё до них (ADR-PMM-036, `process_manager_module/DECISIONS.md:1706-1735`) — SSM тоже закрывается раньше детей.
- Итог: всё окно фазы детей PM не отвечает ни на `supervision.status`, ни на сокет `backend_ctl` (сокет закрывается в
  `transport` после детей, `process_manager_process.py:3545-3555`, но разбирать его входящие некому). Ещё одно
  следствие: `pump_inbound` (Task 1.8) на пути раннера не работает (`DECISIONS.md:1799`), значит класс L-9 на системном
  стопе ничем не защищён.

**Что уже есть и годится как канал:**
- `supervision.status` (`process_manager_process.py:694-746`): на процесс `alive` (живой `is_alive()` из реестра в
  момент запроса), `pid`, `status` (из снимка монитора — **на стопе устаревает**: монитор на паузе, ADR-PMM-036).
  Доступен обеим дверям — внутренней (`CommandSender`) и сокету (`backend_ctl/driver.py:1042`, Пульт
  `frontend_module/bridge/remote_command_sender.py:176`).
- Асинхронный запрос из GUI без блокировки главного потока — `ProcessManagerProxy._dispatch_async` + `RequestRunner`
  (`frontend/bridge/process_manager_proxy.py:154-158`). `shutdown_system()` (:112-118) — fire-and-forget, вызывающих 0.
- Пуш-дельты стора: GUI подписан на `system.**` и `processes.**` (`frontend/process.py:128-133`); PM публикует через
  `ProcessMonitor._publish_state` / `_emit_supervisor_event` (`process_manager_module/monitor/process_monitor.py:290-345`).
- Источники несохранённого: граф — `TopologySession.dirty` (`multiprocess_prototype/domain/topology_session.py:48`),
  сохранение — `_save_active_topology` (`app.py:793-805`, передаётся в `set_topology_session`, `app.py:806`);
  системные настройки — `SystemSettingsPresenter.is_dirty()`/`save()`
  (`frontend/widgets/tabs/settings/system/presenter.py:138`, :79), сигнал `SettingsTab.dirty_changed` (`settings/tab.py:42`).
  Сегодня при закрытии спрашивают только про граф; несохранённые настройки теряются молча.
- Экспорт/импорт графа редактора: `PipelinePresenter.export_topology_with_positions()` и
  `load_topology_from_file()` (`frontend/widgets/tabs/pipeline/presenter.py:346-358`; загрузка ставит `mark_edited`).
- Принудительного стопа нет: в `backend_ctl/mcp_tools.py` инструмента остановки нет (grep `shutdown` → 0 совпадений по
  смыслу), driver умеет только общий `system_command` (`backend_ctl/driver.py:669`); `harness.stop()`
  (`backend_ctl/harness.py:471`) — закрыть драйвер + `_shutdown_with_watchdog` + kill дерева.
- Сроки: `stop_budget()` (`process_manager_module/core/stop_budget.py:73-96`) — work 3,0 / PM graceful 5,0 / с эскалацией
  7,0 / спавнер 8,5 с. Grace ребёнка при смерти родителя — 1,5 с (`process_runner.py:30`, `_on_parent_death` :83-111).

## Целевое поведение (UX)

Все тексты — по конвенции владельца (`docs/claude/memory/feedback_dialog_conventions.md`): стандартные кнопки,
кнопка по умолчанию — безопасный исход.

### A. Крестик, всё сохранено
1. Окно не закрывается (`event.ignore()`), GUI шлёт `system.shutdown {"mode": "graceful", "initiator": "gui"}`.
2. ≤ 300 мс — окно-модальный диалог «Остановка системы» поверх главного окна, без кнопки «Отмена» (стоп необратим).
3. Строки по процессам: «`camera_0` — работает / останавливается / остановлен / остановлен принудительно / убит /
   не остановился»; строка фазы: «Подготовка к остановке: `<шаг>`» → «Остановка процессов» → «Остановка интерфейса»;
   счётчик «Прошло 1,8 с». Опрос `supervision.status` каждые 250 мс, срок запроса 1,0 с.
4. Все процессы, кроме `gui`, `alive = false` с известным `outcome` → строка «Система остановлена» 300 мс → окно
   закрывается, процесс `gui` выходит сам (он в последней волне, Task 1.3).

### B. Крестик, есть несохранённое
1. Один диалог на все источники: заголовок «Несохранённые изменения», текст
   «Есть несохранённые изменения:\n• граф топологии (рецепт `<slug>`)\n• системные настройки\nСохранить их перед
   остановкой системы?»; кнопки «Сохранить» (default) / «Не сохранять» / «Отмена».
2. «Отмена» → ничего не происходит: окно на месте, система работает, `system.shutdown` не послан.
3. «Сохранить» → сохраняются все источники; провал любого → сообщение об ошибке (как сейчас, `main_window.py:333-344`),
   стоп **не** начинается. Успех → путь A.
4. «Не сохранять» → путь A, черновик не пишется (пользователь отказался явно).

### C. Процесс завис
- Если к `deadline_at + 1,0 с` (из `supervision.status.system_stop`, при отсутствии — 6,0 с от начала) кто-то жив:
  в диалоге появляется строка «Не остановились за 6 с: `devices`, `storage`.» и кнопки «Подождать ещё» (default) /
  «Закрыть принудительно».
- «Подождать ещё» — ещё 5,0 с, потом вопрос снова.
- «Закрыть принудительно» → `system.shutdown {"mode": "force", "deadline_s": 0.5}`; диалог ждёт итогов не дольше 3,0 с,
  затем закрывается в любом случае; выжившие — строка WARNING в лог GUI.
- То же на шаге «Подготовка к остановке» (например «домой» робота), если шаг идёт дольше заявленного срока; текст
  кнопки тот же, под ней строка «Шаг `<имя>` будет прерван».

### D. Второй крестик (или Alt+F4) во время остановки
- Без вопроса = «Закрыть принудительно» (C). Во время диалога сохранения крестик закрывает этот диалог = «Отмена».

### E. Стоп начат не из GUI (`backend_ctl`, harness, скрипт, принудительный режим)
- GUI узнаёт о стопе по дельте `system.stop.phase` (пуш, подписка `system.**` уже есть) **или** по общему
  `system_stop_event` (опрос 200 мс в safety-таймере, путь на случай мёртвого PM).
- Никаких вопросов. Есть несохранённое — сразу (до показа диалога) черновик восстановления + строка INFO
  «черновик несохранённых правок сохранён: `<путь>`»; несохранённые системные настройки — строка WARNING
  «несохранённые системные настройки потеряны (черновик v1 хранит только граф)».
- Тот же диалог хода (A), с подзаголовком «Остановка начата извне: `<initiator>`». Кнопки C — те же.

### F. Бэкенд упал, пока диалог открыт
- 3 неудачных опроса подряд (≥ 0,75 с) → строка «Бэкенд перестал отвечать — окно закроется через 1 с», закрытие.
  Жёсткий потолок даёт раннер: при смерти PM `_on_parent_death` выходит через 1,5 с (`process_runner.py:83-111`), поэтому
  черновик (если был нужен) пишется в момент обнаружения стопа (E), а не в конце.

### G. GUI упал
- До отправки `system.shutdown` — система продолжает работать (как сегодня; рестарт `gui` — политика супервизора).
- После отправки — стоп идёт без GUI: PM владеет стопом, `gui` в последней волне просто уже мёртв (`outcome`
  `exited`/`killed`, Task 1.10). Периодического автосохранения на случай падения GUI этот план не делает (вопрос 5).

### H. Подключаемый GUI (Пульт, будущий)
- Крестик: «Остановить систему» / «Только отключиться» (default) / «Отмена». «Только отключиться» — закрыть сокет,
  бэкенд жив. «Остановить систему» — путь A через сокет. Делает план gui-service (Task 3.1 ниже — только контракт).

## Контракт хода остановки PM → GUI

Новых каналов нет: расширяются ответ `supervision.status` и ключи стора `system.*`.

**`supervision.status` — новое поле верхнего уровня (Task 1.2):**

```
"system_stop": null | {
    "phase": "pre_stop" | "children" | "last_wave" | "done",
    "mode": "graceful" | "force",
    "initiator": "<sender команды system.shutdown> | event | parent_death | unknown",
    "started_at": <time.time()>,
    "deadline_at": <time.time()>,        # конец graceful-окна текущей фазы
    "pre_stop_step": "<имя шага>" | null
}
```

**На процесс — два новых поля:** `outcome` (`null | "exited" | "terminated" | "killed" | "survived"` — источник Task 1.10
`lifecycle-stop-ownership`, здесь только проброс) и `stop_wave` (`"main" | "last"`). Правило для потребителя: на стопе
верить `alive` и `outcome`, **не** `status` (снимок монитора на паузе).

**Стор (пуш, только смена фазы — 4 записи за стоп):** `system.stop.phase`, `system.stop.mode`, `system.stop.initiator`,
`system.stop.started_at` через `ssm.handle_state_set` (тот же путь, что `_publish_state` монитора). Цена при отсутствии
стопа — 0.

**Условие жизни канала (Task 1.1):** `message_processor`, роутер, SSM и сокет `backend_ctl` PM живы до конца фазы
`children` и `last_wave`. Ответ `supervision.status` на стопе ≤ 300 мс.

**`system.shutdown` — аргументы (Task 1.4):** `mode` (`graceful` по умолчанию), `deadline_s` (только `force`, по
умолчанию 1,0, диапазон 0,1–5,0), `initiator` (по умолчанию `sender` сообщения). Ответ сразу:
`{"success": True, "accepted": True, "mode": ..., "phase": ...}`; повтор во время стопа: `graceful` → `accepted: False,
"reason": "already_stopping"`, `force` → эскалация текущего стопа.

## Черновик восстановления

- **Где:** `<каталог манифеста>/.recovery/` — каталог `resolve_manifest_path()` (`multiprocess_prototype/main.py:41-47`);
  строка `.recovery/` в `.gitignore` (вопрос 6 — альтернатива `%APPDATA%`).
- **Что (v1 — только граф):** пара файлов с общим стемом `topology_<slug>_<YYYYmmdd-HHMMSS>`:
  - `.yaml` — `PipelinePresenter.export_topology_with_positions()`; формат тот, что читает `load_topology_from_file`
    (круговой тест — REDS Task 2.2);
  - `.meta.json` — `{"format": "inspector.recovery/1", "created_at": "<ISO>", "reason": "system_stop | backend_lost",
    "initiator": "<из system_stop>", "recipe_slug": "<slug|null>", "recipe_file": "<путь|null>",
    "recipe_sha256": "<хеш файла рецепта на момент черновика|null>", "sources": ["topology"],
    "settings_lost": <bool>}`.
- Запись атомарная (`tmp` + `os.replace`), на главном потоке Qt, ≤ 50 мс; хранится 5 последних, старшие удаляются при записи.
- **Когда пишется:** только путь без диалога (E, F) и только при `TopologySession.dirty`. Не пишется при «Не сохранять».
- **Восстановление:** при старте GUI, после `window.show()` (`QTimer.singleShot(0, …)`), если в `.recovery/` есть черновик:
  «Найден черновик несохранённых правок графа от 20.10.2026 14:32 (рецепт `<slug>`, причина: остановка по команде
  `<initiator>`).» — «Восстановить» (default) / «Удалить» / «Позже». «Восстановить» → `load_topology_from_file` (граф
  dirty и diverged, в рецепт не записан), файлы черновика удаляются. Хеш рецепта сменился — дописать строку «Рецепт
  изменился после черновика». `INSPECTOR_GUI_UNATTENDED` — вопроса нет, строка INFO, черновик остаётся.

## Порядок остановки и точка «домой»

Graceful: **(GUI) сохранить → (PM) шаги `pre_stop` («домой» и т. п.) → взвести `system_stop_event` → волна `main` →
волна `last` (GUI) → PM выходит.** Force: шаги `pre_stop` пропускаются (идущий — прерывается), срок волн = `deadline_s`.

Точка `pre_stop` (Task 1.4) — декларативный список команд в конфиге PM, пустой по умолчанию:
`pre_stop: [{"process": "<имя>", "command": "<команда>", "args": {}, "timeout_s": <число>}]`. PM шлёт каждую команду
ребёнку запросом и ждёт ответ до `timeout_s` **вне `message_processor`**; таймаут/ошибка → WARNING и следующий шаг (стоп
не блокируется). Какие команды и что делает «домой» — полоса Р2, T5.3e (вердикт CTO D3(3)); этот план логики робота не
содержит.

## Соседи — кто чем владеет

| План | Что там про это | Что берём | Что отдаём | Граница / конфликт |
|---|---|---|---|---|
| [`lifecycle-stop-ownership`](../lifecycle-stop-ownership.md) Task 1.9 (в спецификации) | FIFO жизненного цикла PM вне `message_processor`, отложенный ответ, `system.shutdown` мимо FIFO; инварианты I1–I4 (ADR-PMM-038) | I1 (один владелец стопа: FIFO отклоняет очередь на `system_stop_event`), I4 (`supervision.status` жив на одиночном стопе), исполнитель для ожидания шагов `pre_stop` | требование: шаги `pre_stop` идут до `system_stop_event`, FIFO в это время отклоняет новые команды жизненного цикла с `reason: "system_stopping"` | **общий файл `process_manager_process.py`**: наши Task 1.1–1.4 начинаются после слияния 1.9 в `main` |
| то же, Task 1.10 (в спецификации) | `outcome` = `exited \| terminated \| killed \| survived` в ответе стопа и в `supervision.status` | поле `outcome` как есть | — | Task 1.2 только пробрасывает; если 1.10 не пишет `outcome` для системного стопа (путь корня) — эскалация CTO |
| то же, вердикт CTO D4 | «приёмный поток и сокет переживают фазу детей — правка корня PM, не Task 1.9» | — | **это наша Task 1.1** | — |
| [`lifecycle-owner-scope`](../2026-10-03_lifecycle-owner-scope/plan.md) (Ж) | корень процесса `planes \| transport \| work`, ADR-PMM-036; Ф5 — окна и рестарт UI | корень как механизм | новый крюк корня `_own_work_late` (Task 1.1) | правка `process_module.py` шага 6a — сверить с открытыми задачами Ж (Ф2/Ф5); golden-тест порядка корня меняется |
| [`2026-09-22_gui-service`](../2026-09-22_gui-service/phase-3-multi-backend.md) Task 3.3 | «закрытие окна Пульта не гасит бэкенд, отдельная команда “остановить систему”» (:159) | сокетный `supervision.status`, `RemoteCommandSender` | диалог H и контракт хода — Task 3.1 | расхождение: там крестик молча отключается; владелец 2026-10-20 — спросить. Нужна поправка в 3.3 |
| [`robot-protocol-v2`](../robot-protocol-v2/plan.md) T5.3e (полоса Р2) | «домой» робота — команда устройству до `process.stop` | — | точка `pre_stop` и правило «force пропускает» | логика «домой» и её срок — там |
| [`observability-closure`](../observability-closure/plan.md) | правит `process_manager_process.py` | — | — | общий файл — маленькие коммиты, `git log main..` соседа перед мержем |

Обратные ссылки: строка добавлена в `plans/2026-09-22_gui-service/phase-3-multi-backend.md` (Task 3.3). В
`lifecycle-stop-ownership.md` и `plans/queue/ORDER.md` строку добавляет лид — первый файл сейчас правит автор Task 1.9.

## Риски

1. **H1 подтвердится** — любой `app.quit()` при dirty повиснет на вопросе: в Task 1.1 весь выход идёт только через
   `CLOSING`; любой новый вызов `app.quit()` в обход координатора — регресс (REDS 8 Task 1.1 его ловит).
2. **Общие файлы:** `process_manager_process.py` (LSO 1.9/1.10, observability-closure), `process_module.py` (Ж). Порядок:
   1.9 → 1.1; маленькие коммиты; перед мержем `git log main..` соседей.
3. **`message_processor` жив в фазе детей** — новое: команды исполняются во время стопа. Защита — отказ спавна
   (ADR-PMM-030) и I1 Task 1.9. Побочный плюс: каналы PM вычерпываются на системном стопе (класс L-9 там закрывается);
   минус — возможны новые гонки «команда vs стоп», которых раньше не было по построению.
4. **SSM жив дольше** — дельты стора уходят детям, которые уже выходят (метки ReaderGone, ADR-SRM-016): возможен рост
   строк `buffered dropped`; мерить в A10.
5. **Срок 1,5 с после смерти PM** — черновик может не успеть при медленном диске; пишется в момент перехода, ≤ 50 мс.
6. **Бюджет волны `last`** удлиняет внешние сроки спавнера на 2,0 с только при наличии `gui`-окна; пороги тестов harness
   не затронуты (там headless), стенды с окном — затронуты.
7. **`outcome` для системного стопа** — если Task 1.10 даёт его только в ответе `process.stop`, Task 1.2 блокируется до
   решения CTO.
8. **Расхождение с gui-service 3.3** («крестик Пульта молча отключается») — нужна поправка владельцем gui-service.
9. **Режим unattended** авто-отвечает «Не сохранять» на крестике — живые приёмки, которые его ставят, не проверяют вопрос B.
