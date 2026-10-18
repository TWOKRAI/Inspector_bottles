# Передача: план `camera-device-service` готов к ревью р.2 и к волне W1 (2026-10-18)

Автор: `manager` (Opus), раунды 1–3 плана. Ветка сейчас `feat/code-reader-gui`, HEAD `078b96ff3`; ничего не закоммичено,
не запушено. Лидер новой сессии — `teamlead` (Opus), эффорт high.

## 1. Что сделано

- План `plans/2026-10-18_camera-device-service/` (layout v2): `plan.md` (14 КБ), `tasks/<id>.md` × 42 (каждый ≤ 7,9 КБ),
  `wave-protocol.md`, `decisions.md` (Р1–Р14, ADR), `design.md` (точки коммита, T5.3, дефекты хаба, риски, открытое),
  `matrix.md` (таблица задач, советы, связи), `amendments.md` (открытие + раунд 3).
- Ревью плана р.1 (`docs/reviews/2026-10-18_camera-plan-review.md`, CHANGES REQUESTED): B1–B8, A1–A17, R-a..R-g внесены
  (раунд 3). Нужен раунд 2 ревью плана (последний: на 3-й — `cto`).
- Гейты (через `machine_gate.sh light camera-plan`): `plans_ledger.py status --check --plan plans/2026-10-18_camera-device-service/plan.md`
  -> `0/42, —, ledger status DRAFT`, exit 0; `plans_progress.py --json` -> `done 0, total 42, unknown 0`; `--queue` — 35 пунктов,
  `OWNER_QUEUE_*` нет; `--check` по плану — только `BRANCH_MISSING` (ветки ещё нет). `plans_ledger.py brief` собирается.
- `code-reader-gui`: статусы 2.1/2.2a DONE, 2.2b SUPERSEDED, `phase-2.md` разделён (`phase-2-history.md`); связи — строкой в 7 соседних планах.
- Очередь владельца `plans/queue/ORDER.md`: строки 23–35 по волнам (W1 — пилот режима волн).

## 2. Решения владельца (2026-10-18, финальные)

1. Ядро `Services/camera_device/` + два вендорских сервиса; FieldMeta `apply`/`enabled_if` во framework; старое API `hikvision` без алиасов; риск убийства принят, T14 делаем; дизайн универсальный; `device_hub` — зеркало (P1).
2. Ревью плана принято целиком (B1–B8, A1–A17, R-a..R-g); Q1 — К4' без хаба; Q2 — цель P0 = 2 MVS по serial (`hikvision_dual.yaml`).
3. Приоритеты P0/P1/P2 (поле `Priority` в каждой задаче); P0 первым.
4. Режим исполнения — волны (`wave-protocol.md`), только для этого плана; W1 — пилот.
5. «Хаб как источник настроек» — план не меняется, вопрос открыт.
6. Если Opus (лидер или ревьюер) не справился за 2 итерации — на 3-й зовут `cto` (Fable).

## 3. Режим волн и роли (кратко; полностью — `wave-protocol.md`)

| Роль | Модель | Где |
|---|---|---|
| Лидер сессии | `teamlead` Opus 5.5, high | spec, ACCEPTANCE, прогнозы инъекций, merge, коммиты; исполнение делегирует |
| Код и тесты | `developer`, `tester` — Sonnet 5.5 | слепой `tester` до кода — только 1.1, 1.3, 1.5, 2.1, 2.2, 2.3a, 2.4, 4.2a |
| Стадия 0 | `reviewer` Sonnet 5.5 | только 1.1, 1.3, 1.5, 2.1, 2.2, 2.3a, 2.4, 4.2a, 4.6a |
| Ревью | `reviewer` Opus 5.5 | один на волну; сразу после 2.1, 2.2, 2.4, 4.2a; раунд 2 — тот же agentId |
| Механика | Haiku 5.5 (`junior`/`Explore`) | матрица инъекций (механизмы 1.1, 2.1, 2.2, 2.4), инвентаризации, дифф 3.3/4.3, числа стенда |
| Арбитр | `cto` Fable | только вердикты, эскалация на 3-й итерации Opus |

Лестница: Sonnet -> (Sonnet стадия 0) -> Opus -> `cto` -> владелец; формат `ESCALATION -> <роль>` (вопрос / пробовали / блок / файлы).
Обрыв Sonnet (~30 ходов) — дозвать тем же agentId; два обрыва на задаче — разбить и к Opus.
Граница волны: `/clear` + handoff `docs/handoffs/<дата>_camera-wave<N>.md` с таблицей agentId и метриками пилота.

## 4. agentId прежних агентов

| Роль | agentId | Статус для повторного вызова |
|---|---|---|
| manager (план, раунды 1–3) | `aff38867066ea8cbc` | дозывать для правок плана по ревью р.2 |
| reviewer ревью ядра (Q1–Q9, F1–F22) | `a601009026526c97d` | контекст ядра |
| investigator хаба | `a2c5c5e1d0eeb1a00` | контекст `device_hub` |
| reviewer плана р.1 | `af260db1652113da1` | раунд 2 ревью плана — им же (`SendMessage`) |

Тестеры и ревьюеры кода по механизмам этого плана ещё не запускались — все «свежие».

## 5. Дерево и коммит плана

Чужие грязные — НЕ трогать: `README.md`, `multiprocess_prototype/app.yaml`, `multiprocess_prototype/recipes/letter_robot_sim.yaml`,
`docs/handoffs/2026-10-14_coordinator.md`. Порядок:

1. Раунд 2 ревью плана (`reviewer` opus, `MODE: plan`, agentId `af260db1652113da1`) -> APPROVED -> слово владельца.
2. `git checkout -b feat/camera-device-service` — ДО коммита плана (хук `Refs:`).
3. `python scripts/plans_ledger.py add 2026-10-18_camera-device-service --status DRAFT` — строка ledger сейчас `0/39`, станет `0/42`.
4. Коммит `docs(plans):` явными путями (`git commit -F <файл> -- <пути>`), `Refs: plans/2026-10-18_camera-device-service/plan.md`:
   `plans/2026-10-18_camera-device-service/` (все файлы), `plans/README.md`, `plans/queue/ORDER.md`, `plans/code-reader-gui.md`,
   `plans/code-reader-gui/phase-2.md`, `plans/code-reader-gui/phase-2-history.md`, `plans/camera-robot-calibration.md`,
   `plans/code-reader-sdk.md`, `plans/dataset-circle-capture.md`, `plans/device-tree-recipe.md`, `plans/lifecycle-stop-ownership.md`,
   `plans/robot-protocol-v2/plan.md`. Отдельным `docs(reviews):`/`docs(design):` — входы: `docs/design/camera-device-architecture.md`,
   `docs/reviews/2026-10-18_camera-services-unification-review.md`, `docs/reviews/2026-10-18_device-hub-camera-integration.md`,
   `docs/reviews/2026-10-18_camera-plan-review.md`, этот handoff. После коммита — `git show --stat HEAD`.
5. `approve`: `python scripts/plans_ledger.py approve plans/2026-10-18_camera-device-service` после слова владельца.

## 6. Команды gate

- `bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light|medium|heavy <session> <cmd…>`;
  `--timed medium` — `multiprocess_framework/`, `Services/device_hub/` (своё окно); exit 75 — пропуск гейтом, не красный.
- Задача: `python scripts/plans_ledger.py brief --plan plans/2026-10-18_camera-device-service <id>` -> бриф агенту.

## 7. Ловушки (из `CLAUDE.md`, памяти и плана)

- Агенты не коммитят и не пушат (в каждом брифе); `git add` только явные пути; трейлеры одним абзацем.
- Модель агента — явно (`developer`/`tester` sonnet, `reviewer` по роли, `junior` haiku); reviewer/tester — `run_in_background: false`.
- Ожидаемые значения — литералы; зависающий тест — в daemon-потоке с дедлайном; вердикт без воспроизведения — совет.
- Стенд останавливать по PID; прибор отпускается ~10 с; IDMVS закрыт, VPN выключен, ПК `192.168.1.100/24`.
- `test_letter_robot_sim_diff.py` красный от чужой правки — не наш.
- T5.3 `robot-protocol-v2` и 4.6b–4.6d правят одни файлы хаба — один писатель.
- Отступление от «ревью после каждой задачи» — решение владельца только для этого плана (`plan.md`, «Режим исполнения»).

## 8. СТАРТОВЫЙ ПРОМПТ (вставить как есть)

```
Ты — лидер сессии (teamlead, Opus 5.5, effort high) по плану plans/2026-10-18_camera-device-service/plan.md.
Репозиторий D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles. Прочитай по порядку: docs/handoffs/2026-10-18_camera-wave1-start.md,
plans/2026-10-18_camera-device-service/plan.md, wave-protocol.md, design.md. Режим — волны (решение владельца, только для этого плана);
W1 — пилот: 0.1, 0.2, 0.3, затем 1.5, 0.4, 1.1. Роли: код и тесты — Sonnet; стадия 0 — reviewer sonnet только у 1.1 и 1.5 в W1;
слепой tester до кода — у 1.1 и 1.5; ревью — один Opus reviewer на волну; инъекции — только 1.1 (FieldMeta), прогон Haiku по твоим
прогнозам. Если Opus не закрыл задачу или спор за 2 итерации — на 3-й зови cto (Fable) одним сообщением ESCALATION с фиксированным SHA.
Сначала: (1) раунд 2 ревью плана — SendMessage reviewer af260db1652113da1 (MODE: plan, фиксированный путь плана); (2) после APPROVED
и слова владельца — ветка feat/camera-device-service ДО коммита, plans_ledger.py add, docs(plans) коммит явными путями (handoff §5);
(3) W1 по wave-protocol.md: брифы через plans_ledger.py brief, не больше 3 писателей, все тесты через machine_gate.sh (session camera-w1).
Чужие грязные файлы не трогать (handoff §5). Агенты не коммитят и не пушат. Лидер не пишет код — делегирует. На границе W1: метрики
пилота (токены по моделям, дефекты ревью волны, переделки, обрывы Sonnet, вызовы cto) в amendments.md и handoff, затем /clear.
Ответы владельцу — по-русски, отчёт с непустым «Что оставил открытым».
```

## 9. Что открыто

- H1–H6 не проверены (камер нет); `MV_CC_Initialize` — 0.3; две DLL в процессе `devices` — 4.6b; перечисление при занятом приборе — 0.5/6.2.
- Ревью р.2 плана не пройдено; бюджет ~9M — оценка без замера, пилот W1 его меряет.
- Глоб `processes.*.state.plugins.*` и семантика `sync` у `StateProxy.subscribe` — проверяет 4.6a.
- Отвергает ли register `hikvision` лишние ключи (связь 4.2a <-> 4.3) — стадия 0 4.2a.
- Хаб как источник настроек — вопрос владельцу, план не меняет.
- Ссылки на старый путь `plans/camera-device-service.md` в `docs/` (handoff 2026-10-17, ревью, design) не правлены.
