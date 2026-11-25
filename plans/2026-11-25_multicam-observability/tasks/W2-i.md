# Task W2-i: один путь записи — `set_config` будит подписчиков поля

- **Статус:** [PENDING] · **Level:** Senior · **Assignee:** teamlead
- **Блокер:** решение CTO Р2 (вариант «провести через `set_field_value`», рекомендация лида) — до ответа не стартует
- **Module contract:** public-api-change (поведение `PluginBase.cmd_set_config` для всех плагинов с регистром)
- **Dependencies:** нет по файлам; по смыслу — до W2-j (тот же путь записи получает запрет прогона)
- **Gate:** `machine_gate.sh light <session>` по файлам TESTS; радиус `multiprocess_framework/modules/process_module/tests` (heavy — окно лида)
- **Files:** `multiprocess_framework/modules/process_module/plugins/base.py`, `multiprocess_framework/modules/process_module/tests/test_set_config_notifies_subscribers.py`
- **Acceptance:** блок ACCEPTANCE
- **Handoff:** teamlead (REDS в брифе, красный прогон до правки src, break-injection) -> reviewer (стадия 5, opus)

Основание: `cmd_set_config` (`base.py:1896-1931`) пишет `reg.apply_values` напрямую — подписчики `RegistersManager` не будятся, ответ `ok applied`, прибор прежний (Р2 волны 1; инспектор GUI шлёт `set_config`, `command_catalog.py:268-282`). Два пути записи — костыль (аудит ч.2 §6); один путь = один механизм уведомления.

TASK: W2-i — `cmd_set_config` записывает через `RegistersManager.set_field_value`, если регистр плагина в нём есть   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: teamlead
CHAIN: lead -> you -> reviewer (стадия 5)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. В `cmd_set_config`: `registers = getattr(ctx, "registers", None)`; `registers` есть и `registers.get_register(self.name) is reg` -> путь менеджера, иначе прежнее тело без изменений.
  2. Путь менеджера, всё или ничего: сначала проверка ВСЕГО пакета на копии (`reg.model_copy(deep=True).apply_values(known)`); отказ -> прежний ответ `{"status": "error", "error": err}`, ничего не записано. Успех -> по полю `ok, err = registers.set_field_value(self.name, field, value)` в порядке ключей `known`; отказ поля после успешной проверки копии (гонка) -> ответ `{"status": "error", "error": err, "applied": {…уже записанные…}}` и одна ERROR `[<plugin> set_config] запись прервана на поле <field>: <err>`.
  3. Ответ успеха прежний (`applied` — сохранённые значения из регистра, `skipped`); строка INFO прежняя.

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. multiprocess_framework/modules/process_module/plugins/base.py — `cmd_set_config`
  2. multiprocess_framework/modules/process_module/tests/test_set_config_notifies_subscribers.py — новый

REDS (predicted red tests):
  - multiprocess_framework/modules/process_module/tests/test_set_config_notifies_subscribers.py::test_set_config_wakes_field_subscriber (настоящий `RegistersManager`, подписка на поле -> колбэк вызван с сохранённым значением)
  - multiprocess_framework/modules/process_module/tests/test_set_config_notifies_subscribers.py::test_set_config_batch_refusal_writes_nothing_and_notifies_nobody
  - multiprocess_framework/modules/process_module/tests/test_set_config_notifies_subscribers.py::test_without_manager_old_path_kept (охранный)
  - multiprocess_framework/modules/process_module/tests/test_set_config_notifies_subscribers.py::test_camera_exposure_via_set_config_reaches_session (`camera_device` плагин + фейк-порт: `set_config {exposure_time}` -> в журнале фейка новая `ExposureTime`)

ACCEPTANCE (every number with its command):
  - `<py> -m pytest -q --tb=short multiprocess_framework/modules/process_module/tests/test_set_config_notifies_subscribers.py` -> exit 0
  - `<py> -m pytest -q --tb=short -k "set_config" multiprocess_framework/modules/process_module/tests Services/camera_device/tests Services/code_reader/tests` -> exit 0; полный радиус — у лида
  - `ruff check -q` по двум путям -> 0

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short multiprocess_framework/modules/process_module/tests/test_set_config_notifies_subscribers.py

OUT OF SCOPE: перевод инспектора GUI на `register_update` (prototype, после решения); запрет прогона (W2-j).
TRAPS: `set_field_value` зовёт и `send_callback` (каналы `control_*`) — так и должно быть, это тот же путь, что `register_update`. Тест 4 импортирует `Services` из теста framework — разрешено только в тестах (слой); если правило `sentrux` запрещает и тестам — тест 4 переносится в `Services/camera_device/tests` (стоп и вопрос лиду, файл вне FILES).
HANDOFF IN: решение CTO Р2.
REPORT: STATUS (DONE|BLOCKED), files, команды и вывод по ACCEPTANCE, красные до/после, раздел «Что оставил открытым / ненадёжно».
