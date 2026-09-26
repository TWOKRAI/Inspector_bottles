# Ф4 — Пульт: виджет ручек с адресами `backend_ctl`

Часть плана [`plan.md`](plan.md). Ветка `feat/gui-constructor-f4`. Решение владельца 2026-09-26
(`constructor-layers.md` → «Пульт»), дизайн — [`design-shell-layout.md`](design-shell-layout.md) §6.

**Цель фазы:** ручки из разных областей собираются в одном виджете `fw.pult`; ручка = адрес + описание; один адрес
у GUI, `backend_ctl` и агентов; «Вынести на Пульт» из любого поля регистра; несколько Пультов; наборы ручек — в
раскладке рабочего места; `Services/control_panel` адресует так же, `local` остаётся в рецепте.

Канон запуска — шапка [`phase-1-boot-split.md`](phase-1-boot-split.md).

**Предусловия из gui-service:** каталог регистров от бэкенда (1b.2a — DONE), копии регистров из описания
(1b.2b-pre — DONE), вердикт бэкенда до формы (**1b.2c — PENDING**, нужен Task 4.2), правила регистра описанием
(1b.2d — желательно: без него ручка мягче оригинала на `list`/`dict`).

---

### Task 4.1 — `KnobAddress`: один адрес для GUI, `backend_ctl` и агентов

- **Статус:** [PENDING] · **Level:** Middle · **Assignee:** developer
- **Handoff:** tester (RED, worktree) → developer → reviewer
- **Goal:** строка адреса `reg:<process>/<register>/<field>` | `cmd:<process>/<command>` | `state:<path>` разбирается и
  собирается обратно; `backend_ctl` принимает её там, где сегодня принимает тройку.
- **Design:** `design-shell-layout.md` §6.1. Совпадение с `set_register(process, register, field, value)`
  (`backend_ctl/registers.py:103`). Экранирование `/` в именах не вводить: сначала грепом проверить, есть ли имена
  процессов/регистров/полей с `/` (если есть — эскалация, не выдумывать синтаксис). **Module contract:** new-lite
  (`frontend_module/knobs/address.py`, Qt-free).
- **Files:** 1. НОВЫЙ `frontend_module/knobs/__init__.py`; 2. НОВЫЙ `…/knobs/address.py`; 3. НОВЫЙ тест; 4.
  `backend_ctl/registers.py` (тонкая перегрузка: адрес строкой → тройка); 5. `backend_ctl/README.md` (строка про адрес).
- **Acceptance:**
  - [ ] `str(parse(s)) == s` для `reg:camera_0/CameraRegisters/exposure`, `cmd:robot/draw`, `state:processes.camera_0.fps`.
  - [ ] `parse("reg:a/b")` → ошибка с текстом «ожидалось process/register/field»; неизвестная схема `foo:x` → ошибка
        с перечнем схем.
  - [ ] `backend_ctl` на живом `minimal_app` или прототипе: запись по строке адреса и по тройке дают один и тот же
        `register_update` (сравнение словарей, спай на драйвере).
  - [ ] `grep -l PySide6 frontend_module/knobs/address.py` → пусто.
- **Break-injection (лид):** `str()` теряет схему → предсказание: падает round-trip; `backend_ctl` путает `register`
  и `field` местами → падает сравнение словарей.
- **Dependencies:** нет (можно раньше фазы, если освободится писатель).

---

### Task 4.2 — `fw.pult`: модель ручки и отрисовка через движок форм

- **Статус:** [PENDING] · **Level:** Middle+ · **Assignee:** developer
- **Handoff:** tester (RED, worktree) → developer → reviewer
- **Goal:** общий виджет фреймворка `fw.pult` (`multi_instance=True`): `params.knobs: list[KnobSpec]` из раскладки;
  контрол по описанию регистра каталога (`FieldInfo` → слайдер/поле/тумблер/выбор); значение — из состояния; правка —
  команда; отказ бэкенда — откат с текстом.
- **Design:** `design-shell-layout.md` §6.1–§6.2; `design-connection-context.md` §3.1–§3.2. Ручка не держит ссылку на
  виджет-источник. Наборы ручек сохраняются в раскладке рабочего места (`INSPECTOR_CONFIG_DIR/layouts/<role>.yaml`),
  не в рецепте. **Module contract:** new-lite (`frontend_module/knobs/spec.py` Qt-free + `pult_widget.py` Qt).
- **Files:** 1. НОВЫЙ `frontend_module/knobs/spec.py`; 2. НОВЫЙ `…/knobs/pult_widget.py`; 3.
  `frontend_module/host/fw_pack.py` (регистрация `fw.pult`); 4. `frontend_module/host/layout.py` (сохранение
  `params` экземпляра); 5. НОВЫЙ `…/knobs/tests/test_pult.py`.
- **Acceptance:**
  - [ ] Два экземпляра `fw.pult` с ручкой на один `reg:` адрес и исходная форма регистра: правка в одном → оба
        Пульта и форма показывают новое значение ≤ 1 с (через состояние, не через ссылку виджет→виджет).
  - [ ] Удаление ручки из Пульта не меняет форму-источник и второй Пульт (их подписки живы).
  - [ ] Отказ бэкенда на значение (фейковый бэкенд отвечает `success: false`) → ручка откатилась к прежнему, текст
        ошибки показан (связь 1b.2c).
  - [ ] Раскладка с Пультом сохранена и открыта заново → тот же набор ручек в том же порядке; файл рецепта не изменён
        (хеш до/после).
  - [ ] `ctx` Пульта не имеет `legacy_deps` (ассерт).
- **Break-injection (лид):** ручка обновляет значение по сигналу от формы-источника, а не из состояния →
  предсказание: падает тест «удаление ручки / второй Пульт» или тест «через состояние»; сохранять ручки в рецепт →
  падает тест хеша рецепта.
- **Dependencies:** 4.1; 2.1 (раскладка); gui-service **1b.2c**.

---

### Task 4.3 — «Вынести на Пульт» у любого поля регистра

- **Статус:** [PENDING] · **Level:** Middle · **Assignee:** developer
- **Handoff:** tester (RED, worktree) → developer → reviewer
- **Goal:** контекстное меню поля регистра в движке форм (`frontend_module/forms`) → «Вынести на Пульт ▸ <Пульты>»
  публикует `fw.pult.add_knob{address, label}`; выбранный Пульт добавляет ручку; Пультов нет — предложение создать
  (новый док в текущем окне).
- **Design:** `design-shell-layout.md` §6.2; шина интерфейса — Task 3.2. Движок форм знает адрес поля (процесс,
  регистр, поле) — проверить чтением до правки; если адреса у формы нет, это находка и эскалация, не обход.
  **Module contract:** impl-only.
- **Files:** 1. файл(ы) контекстного меню движка форм `frontend_module/forms/…` (назвать после чтения, ≤ 2);
  2. `frontend_module/knobs/pult_widget.py` (подписка на событие); 3. `frontend_module/host/fw_pack.py`
  (объявление события); 4. тест.
- **Acceptance:**
  - [ ] Форма регистра прототипа (любая вкладка настроек) → пункт меню есть у каждого поля; выбор Пульта →
        ручка с адресом `reg:<process>/<register>/<field>` этого поля.
  - [ ] Два Пульта → подменю из двух заголовков; ручка попадает только в выбранный.
  - [ ] Ноль Пультов → создан док `fw.pult` в текущем окне с этой ручкой.
- **Break-injection (лид):** событие рассылается всем Пультам → предсказание: падает только тест «только в
  выбранный».
- **Dependencies:** 4.2, 3.2.

---

### Task 4.4 — `Services/control_panel`: адреса `backend_ctl` вместо `target_plugin_index`

- **Статус:** [PENDING] · **Level:** Senior · **Assignee:** teamlead
- **Handoff:** tester (RED, worktree) → teamlead → reviewer
- **Goal:** контролы `param`/`monitor`/`action` ноды `control_panel` адресуют через `KnobAddress`; старые рецепты с
  `target_process` + `target_plugin_index` + `target_field`/`target_command` читаются и переводятся; `local` не
  меняется и остаётся в рецепте.
- **Design:** `design-shell-layout.md` §6.3. Перевод индекса в имя регистра — по каталогу плагинов процесса (1b.2a).
  Неоднозначность (индекс не даёт одного регистра) — громкая ошибка загрузки рецепта с именем контрола, не догадка.
  Запись рецепта — только в новой форме (решение, меняющее формат рецепта: ADR в `Services/control_panel/DECISIONS.md`).
  **Module contract:** public-api-change (`ControlSpec` — публичный тип сервиса).
- **Files:** 1. `Services/control_panel/controls.py`; 2. `Services/control_panel/plugin/plugin.py`; 3.
  `Services/control_panel/DECISIONS.md`; 4. `Services/control_panel/README.md`; 5. тесты сервиса; 6. вкладка
  `multiprocess_prototype/frontend/widgets/tabs/services/control_panel/` — только чтение/запись новой формы.
- **Acceptance:**
  - [ ] Рецепт со старыми полями (`source: param`, `target_process: robot`, `target_plugin_index: 0`,
        `target_field: speed`) загружается; `ControlSpec.address` == `reg:robot/<Registers>/speed` (имя регистра —
        из каталога фейкового процесса, литерал в тесте).
  - [ ] Сохранение → в YAML есть `address`, нет `target_plugin_index`.
  - [ ] Индекс вне диапазона / два регистра с полем `speed` → ошибка с `id` контрола.
  - [ ] `source: local` — сериализация до/после задачи побайтно равна.
  - [ ] Все рецепты репозитория с нодой `control_panel` (`grep -rl "control_panel" multiprocess_prototype/recipes`
        — число в отчёте) загружаются без ошибки.
- **Break-injection (лид):** перевод индекса берёт первый регистр процесса без проверки поля → предсказание: падает
  тест неоднозначности; писать старые поля при сохранении → падает тест YAML.
- **Dependencies:** 4.1; 1b.2a (DONE).

---

## Открыто по фазе

- Набор ручек **без GUI**: владелец хочет, чтобы тот же набор был доступен через `backend_ctl`. Адрес общий (4.1), но
  наборы живут в раскладке рабочего места — файле клиента. Нужна ли команда `backend_ctl`, читающая раскладку
  (`knobs list <layout>`), или агенту достаточно адресов — вопрос владельцу, в `plan.md` → «Открытые вопросы».
- Веб-пульт ленты (`pult_web`, `apps/line_sim`) становится Пультом с адресами бэкенда `line_sim` — не в этом плане;
  точка посадки — `fw.pult` на подключении `line_sim` после Ф3.
