# Контракт готовности run-state для лида полосы К (камера)

Для кого: лид К (`Services/camera_device`, плагины камеры). Что даёт: как плагин камеры подключается к готовности
(run-state, main `8ff4fd151`). Пути — от корня дерева; `файл:строка` — по этому коммиту. Источник истины — код и ADR-PM-061/062
(`multiprocess_framework/modules/process_module/DECISIONS.md:4381`, `:4444`), не этот текст. Пути ниже сокращены: `PM_MOD` =
`multiprocess_framework/modules/process_module`.

Состояние камеры в main: `readiness()` у `camera_device` НЕ переопределён (`rg readiness Services/camera_device/*.py` — 0 строк),
`pause()/resume()` нет. Таблица состояний 2.2c — только в спеке (`plans/2026-10-27_system-run-state/tasks/2.2.md:36`), кода нет.

## 1. Хук `readiness(ctx)`

- Сигнатура: `def readiness(self, ctx: PluginContext) -> list[dict]`, умолчание `[]` (`PM_MOD/plugins/base.py:1574`).
- Возврат: список `{"severity": <из шкалы>, "reason": <str>}` (`base.py:1577-1584`). Шкала `failure | check_function |
  out_of_spec | maintenance` (`PM_MOD/health/schema.py:126`); блокируют готовность только `failure` и `check_function` (`schema.py:128`).
  Пустой список — плагин готов.
- Поля `node` (`<процесс>.<плагин>`) и `source` (`"readiness"`) добавляет оркестратор, не плагин
  (`PM_MOD/generic/plugin_orchestrator.py:629-631`). Лишние ключи элемента (например `id`) оркестратор отбрасывает: из элемента берутся
  только `severity` и `reason` (`plugin_orchestrator.py:597-618`). Поля `id`/`code` у причины НЕТ — механизма нет; ADR-PM-061 откладывает
  `code` на «после 1.0» (`DECISIONS.md:4397`).
- Текст: короткий, без значений входа (серийные номера, пути, `last_error` — в журнал); длиннее 200 символов обрезается
  (`schema.py:130`, `plugin_orchestrator.py:631`). Причин не больше 32, блокирующие остаются первыми (`plugin_orchestrator.py:642-654`).
- Требования (`base.py:1586-1590`): быстро, без IO, без замков, не бросает. Для камеры (спека 2.2.md:16) нельзя брать `plugin._lock`,
  `plugin._session_lock`, `_ensure_session`, `session.params*` (берут замок); можно читать голые атрибуты `session.state`.
- Кто зовёт: поток `readiness_snapshot`, такт 0,5 с (`PM_MOD/core/process_module.py:40`, `:1112`, `:1146`), не heartbeat. Хук зовётся
  только у плагина в `RUNNING` или `PAUSED`; иначе оркестратор сам пишет `failure` «плагин не поднят (<состояние>)»
  (`plugin_orchestrator.py:376-381`). Хук идёт и на паузе.
- Исключение -> `failure` «readiness() упал: <ТипИсключения>» без текста; текст в журнал, один раз на серию; память политики
  сбрасывается (`plugin_orchestrator.py:557-566`). Не `list` или элемент не `dict` с `str`-причиной и допустимой `severity` ->
  `failure` «readiness() вернул неверную форму» (`:567-573`, `:597-618`). Оба отказа политику (п.2) не проходят.
- Пример (камера, по спеке 2.2c; в main кода нет):
  ```python
  def readiness(self, ctx):
      session = getattr(self, "_session", None)
      st = session.state if session is not None else "idle"
      if st == "grabbing":
          return []
      if st == "opening":
          return [{"severity": "check_function", "reason": "камера открывается"}]
      ...  # остальные состояния — таблица 2.2.md:36
  ```

## 2. Политика узла `readiness: {hold_s, severity}` (рецепт)

- Место: в `config` плагина (вложенная форма) или плоско в элементе `plugins` — обе сводятся к `ctx.config`
  (`plugin_orchestrator.py:147-168`; при совпадении ключей вложенный `config` побеждает, `:166`). Читается `ctx.config.get("readiness")`
  (`:588`). Ключ на уровне узла (рядом с `plugins:`) в `ctx.config` не попадает и молча игнорируется (`DECISIONS.md:4450-4451`).
  ```yaml
  plugins:
    - plugin_class: Services.camera_device.plugin_base.CameraDevicePlugin
      plugin_name: camera_device
      config:                       # вложенная форма; плоская: ключи прямо в элементе
        readiness:
          hold_s: 2.0
          severity: {out_of_spec: check_function}
  ```
- Допустимо (`PM_MOD/health/readiness_policy.py:74-97`): `hold_s` — число (не `bool`), конечное, в `[0, 10.0]` (`HOLD_MAX_S`, `:43`);
  `severity` — словарь пар `<из>: <в>`, обе стороны из шкалы п.1; других ключей нет. Умолчание — `hold_s: 0.0`, `severity: {}`,
  нет ключа: поведение не меняется (`:57-58`, `:76-77`).
- `severity` переназначает степень СОБСТВЕННЫХ причин плагина (текст и порядок не меняются) и действует на ВСЕ причины своей
  степени у узла (`DECISIONS.md:4392-4397`). Причины фреймворка (п.1) переназначению не подлежат.
- `hold_s`: потеря показывается как `out_of_spec` до `hold_s` секунд, если узел до неё был чист непрерывно не меньше `hold_s`
  (`readiness_policy.py:116-121`). Узел, ни разу не бывший чистым (boot), не удерживается: START на boot не слабеет. Разрыв между
  наблюдениями больше `OBSERVATION_GAP_MAX_S` обнуляет «был чист» (`:48`, `:110-111`).
- Негодный ключ: политика не применяется, причины узла остаются как есть, первой добавляется `failure` «политика readiness в рецепте
  негодна» с `source: "config"` (`plugin_orchestrator.py:575-578`, текст — `readiness_policy.py:50`); одна ERROR на плагин с названием
  правила (`:588-593`). Узел не готов.
- Разбор один раз при первом УСПЕШНОМ вызове хука, кэш до `boot()` (`:176`, `:587`): смена ключа без перезапуска процесса не
  действует, ошибка ключа видна только после успешного хука.
- Ремап `failure`/`check_function` в неблокирующую степень делает причину неблокирующей — защиты в коде нет (`DECISIONS.md:4421`).

## 3. Ключ `run_locked_commands`

- Место — то же `config` плагина (обе формы); пример: `config: {run_locked_commands: [release_device, take_device]}`.
- Значение — список (или кортеж) строк; имена только из `commands` плагина (`Services/camera_device/plugin_base.py:141-145`:
  `take_device`, `release_device`, `get_status`). Читается один раз при регистрации команд (`base.py:1775`, разбор `:1808-1832`).
- В момент вызова команда при взведённом `ctx.services._run_active` отдаёт `{"status": "error", "error": "running", "message":
  "сначала ОСТАНОВИТЬ"}`, метод не вызывается (`base.py:1835-1847`). Флаг: `True` ровно при `running` без хода системного
  стопа (`PM/process/process_manager_process.py:1187-1205`; `PM` = `multiprocess_framework/modules/process_manager_module`); кладёт раннер
  (`PM/runner/process_runner.py:427`); нет атрибута — команда исполняется (`base.py:1843-1845`). Флаг ставится и при `run_gate: false`
  (`process_manager_process.py:336`).
- Негодное: не список строк -> `run_locked_invalid = True`, ERROR, запрета нет; имена вне `commands` -> `run_locked_invalid = True`,
  ERROR, остальные имена запрещены (`base.py:1819-1832`). `run_locked_invalid` -> причина `failure` с `source: "config"`
  «<плагин>: неверный run_locked_commands» первой в списке причин узла: узел не готов, START отказан `not_ready`
  (`plugin_orchestrator.py:544-552`, `base.py:43-45`). Причина идёт и при упавшем `readiness()`.
- `set_config` вне объёма: его регистрирует база мимо `commands` (`base.py:1791-1810`); имя в списке = «нет таких команд» = узел не
  готов. Правки регистров (`register_update`, поля `apply="live"`, `registers_base.py:110`) этот ключ не закрывает
  (`DECISIONS.md:4476`).
- Прямые вызовы не блокируются: запирается обёртка зарегистрированной команды, а `start()` и `shutdown()` камеры зовут
  `self.cmd_take_device`/`self.cmd_release_device` напрямую (`plugin_base.py:309`, `:314`) — автозахват и закрытие при стопе работают.

## 4. «Модель не загружена» как причина readiness

- Механизм есть, правок фреймворка не нужно, но он на узле `ml_inference`, не камеры: хук `Services/ml_inference/plugin/plugin.py:325-346`
  отдаёт `out_of_spec` «модель не загружена: кадры идут без распознавания» (не блокирует). Блокирующей её делает политика на узле
  `ml_inference`: `config: {readiness: {severity: {out_of_spec: check_function}}}` (спека 2.9.md:164, решение владельца 2026-11-16).
- Пока 2.9b `[PENDING]` (`tasks/2.9b.md:3`): ключ в боевых рецептах не стоит (`rg readiness *.yaml` — 0 совпадений в дереве рецептов).
- Ограничение: политика переназначает причины только СВОЕГО узла. Плагин камеры причину чужого узла `ml_inference` не получает; камера
  не знает про модель. Межузловой причины «модель не загружена» на узле камеры механизма нет; нужен новый механизм фреймворка
  (причина из чужого узла) — в К его не заводить.
- Цена ремапа: узел с ≥ 2 причинами `out_of_spec` — форма негодна по замыслу (нужен `code`); `reload_model` в `running` даст `fault`
  (`2.9.md:246`, живьём не проверено).

## 5. Что К делает и чего не делает

Делает (только в `Services/camera_device`, плагины камеры, тесты К):
- `readiness()` по таблице 2.2c; ключи `run_locked_commands` / `readiness` кладёт в рецепты камеры только после решения владельца (п.6).
- Пауза: `pause()/resume()` у камеры не вводятся (решение К, 2.2.md:37 (г)): при ОСТАНОВИТЬ камера снимает дальше, цена — USB/CPU на паузе.
  Если решите ввести: хук идёт на потоке сверки (0,05 с), параллельно `produce()`, идемпотентен, не дольше замка 2,0 с; упавший хук ->
  `failure` «pause() упал», повтор раз в 1,0 с (`base.py:1549-1560`, `plugin_orchestrator.py:50-53`). Образец — `Plugins/hub/device_hub/plugin.py:429`
  (`pause`, срок 1,5 с, `:66-67`).
- `run_gated`: ключ в `config` источника, умолчание `True` — `SourceProducer` не зовёт `produce()` при снятом `run_event`
  (`PM_MOD/generic/generic_process.py:361-364`, `PM_MOD/generic/source_producer.py:155-157`). `False` (превью) — кадры идут и в `ready`; тогда
  `pause()` плагину не зовётся (`plugin_orchestrator.py:472-478`). Сеанс камеры при `run_gated: true` продолжает снимать — гейтится
  только `produce()`.

Не трогает:
- Файлы PM (`multiprocess_framework/modules/process_manager_module/process/process_manager_process.py`, `.../launcher/spawner.py`) пишет
  только полоса Ф. Нужна правка PM — запрос лиду Ф.
- `PM_MOD/` (оркестратор, база плагина, политика) и ADR-PM-061/062 — framework, не К.
- Старый `Services/hikvision_camera` (2.2.md:94), `ml_inference` (хозяин другой).

## 6. Открытое (решения владельца, на которые контракт опирается)

- Список `run_locked_commands` для камеры: решение владельца 2026-11-20: `release_device` и `take_device` (2.7d.md:6, этап 2; ключ в рецепты камеры кладёт К). Цена: при
  запрете `release_device` оператор не освободит камеру на ходу; relay-кнопка GUI отказа не видит (`success: True`, только WARNING в
  журнале ребёнка, `DECISIONS.md:4472-4475`). Без ключа `release_device` в `running` проходит -> `check_function` «камера не запущена» -> `fault`
  (2.2.md:37 (б)).
- Период снимка 0,5 с (`process_module.py:40`) — выбор разработки, не замер. `OBSERVATION_GAP_MAX_S = 2.5` (`readiness_policy.py:48`) — РАСЧЁТ
  (0,5 с + все `readiness()` процесса + `_send_lock`, запас 2,0 с), не замер на стенде; вырастет период — `hold_s` молча перестанет работать.
- Значения `hold_s` для камеры не заданы; решает soak 10 мин (2.9.md:229): пока 0, ключ не ставить.
- `opening` может быть бесконечным (нет таймаута `opening -> error`): START блокируется вечно; замер на железе, Delta ≈ 2026-11-22 (2.2.md:37 (в)).
- Таблица 2.2c в коде не реализована; набор состояний сеанса зафиксирован К на 28720c500 (2.2.md:36) — сверить с `session.py` перед кодом.
- Не проверено: сохраняет ли GUI-редактор рецептов вложенный `readiness` при пересохранении (2.9.md:245; прецедент — вкладка «Система» затирала `run_gate`).

Источник: код main 8ff4fd151
