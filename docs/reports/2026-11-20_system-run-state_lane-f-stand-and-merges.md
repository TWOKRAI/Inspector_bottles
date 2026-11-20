# Run-state, полоса Ф — слияния S3doc, S5, S6 (2.2c), 2.9b, правка паузы 2.2 и стенд на сим-линии (2026-11-20)

Автор: лид полосы Ф (сессия inspector-bottles-f1). План: `plans/2026-10-27_system-run-state/plan.md`. Продолжение отчёта `docs/reports/2026-11-20_system-run-state_lane-f-merges.md` (слияния 2.7+2.9, П3, 2.2). Ничего не запушено.

## 1. Что влито в main (радиус на слитом дереве)

| Что | Коммит слияния | Ревью | Радиус |
|---|---|---|---|
| S3doc (stop_allowed, README PM «Работа системы», `--autostart`) | `295815b19` | экспресс Sonnet: замечания закрыты | validate.py чисто; light backend_ctl 108 passed (дерево ветки) |
| S6 = 2.2c (readiness камеры) | `15049c249` | Sonnet APPROVED (ранее), слепое Opus APPROVED | `Services/camera_device/tests` 443 passed, 10 skipped; `test_readiness.py` 72 passed; validate чисто |
| Решение владельца по `run_locked_commands` (release_device, take_device) | `80183fc99` | — | docs |
| S5 (пульт: гейт, stop_allowed, набор степеней) | `b778b9503` | Sonnet APPROVED, слепое Opus APPROVED | 3 файла пульта 137 passed (22 красных до кода); 144 passed с каталогом chrome/tests; validate чисто; sentrux 43 правила |
| Правка паузы 2.2: стоп роботам на каждом вызове (вариант (а), решение владельца) | `097fdaa6e` | слепое Opus APPROVED (4 minor/nit закрыты) | `Plugins/hub/device_hub/tests` 566 passed; `Services/device_hub/tests` 1123 passed, 6 skipped, 2 красных `test_no_private_driver_state` (как на базе); 3 файла паузы 77 passed |
| 2.9b (ключ `readiness` боевого рецепта) | `7410b16eb` | Sonnet APPROVED (REDS и инъекции J1–J3 по предсказанию) | 13 файлов 170 passed (169 до); validate чисто |
| OPEN_QUESTIONS, 4 пачки | `ac1e72379`, `239904a80`, `3ac226a23`, настоящий коммит | — | docs |

Слепой tester до кода был у S5 (22 красных на базе из 137); у S6, 2.9b, паузы — по плану своих задач. 2.8 не начиналась (решение владельца: сначала стенд).

## 2. Стенд на сим-линии (macOS, main 1c64bde1c и 7410b16eb)

Подробности и сырые данные: scratchpad `f/stand/` (`report-lead.md`, `stage2/`, `stage2s4b/`). Числа:
- 2.7 п.1 автостарт: `running` без `run_start`, 1 строка «автостарт» в логе PM, 302 с без переходов — да. П.2 стоп: `ready` за 0,844 с — да. П.3 fault→ack: fault 2,85 с, ack→ready 0,069 с — да. П.5 `run_stop_timeout_s: 2`: 8 замеров 2,046…2,532 с, строго в допуске 4 из 8 (превышение ≤ 0,032 с). П.6 листья — да. П.4: кадры источника в ready +0 за 10 с, в running +250 — да.
- 2.9b п.6: с ключом `run_start` → `not_ready`, `check_function` «модель не загружена…»; без ключа → `running` — да.
- 2.7d: `release_device` и `take_device` отказаны в running (`error: "running"`), после стопа выполняются; при `run_gate` true и false — да. Relay GUI не измерен.
- 2.2: стоп ленты и робота записаны, эхо получено, `ready` за 1,13 с; стоп ленты через мост ≈ 0,57 с (один прогон, > 0,5 с).
- S4b (а) висящий такт при `conn_stale_s: 3,0`: fault за 3,15 / 3,18 / 3,15 с (≤ 4,0), связь `connected` — да (путь S4b только при задержке 1500 мс). (б) `tick_fails_limit` — невозможно на сим-роботе v2; (в) повтор `pause` — не измерено.
- П3: 4 подписчика, потерь нет, задержка маркера 53–86 мс без роста; leaf-подписка 1 дельта 511 Б, ответ 283 Б. Предупреждения «разрыв revision» ≈ 4,2/с одинаковы до и после П3 (ADR-SS-015), регресса П3 нет.
- Soak 10 мин: 594 опроса, 0 ошибок, 0 переходов, 0 fault.

## 3. Что осталось открытым / ненадёжно

1. **Task 2.8 (S1+П2) не начата.** Решение владельца: сначала стенд; стенд на сим-линии выполнен, но окно heavy на железе и условия CTO (стенд четырёх вкладок с GUI, рассылка ≤ +10 %, инъекции красные) не выполнены; слепого tester и ветки нет. П3 остаётся слитым.
2. **Не сделано из acceptance/handoff:** коммит B 2.1 (`run_gate: true` + golden + литерал `True`; ждёт S3c′, S5 — слиты, и условий: live recipe_service ×2, `test_frame_bridge_live`, start_run до apply), 2.6, 2.4 (живая приёмка), 2.5; таблица «что готово» координатору — только числами этого отчёта.
3. **Стенд на симе — не железо:** нет настоящего GUI (измерен бэкенд, не `StateProxy.bind` в Qt), нет камеры Hikvision (`opening/grabbing` не измерены), сим-робот v2 без инъекций `fault.*`; все замеры, кроме п.5, одиночные. `tick_fails_limit = 3` стендом не уточнён (M3), повтор `pause` не измерен, soak без нагрузки очереди дисков.
4. **Решения владельца ждут:** холодный старт: hub «сдался после 3 попыток», автопереподключения нет (ACCEPTANCE 2.2 «≤ 16 с» не выполнен); камера в `stopping` при `auto_start` не блокирует START (варианты (а)/(б) в OPEN_QUESTIONS); Р1 (подпись при `run_gate: false`) и Р2 (`stop_allowed` через `bool()` или `is not False`); ложные «разрыв revision» — убирать или принять (ADR-SS-015); В10, В4 пульта, итог SOFT/HARD/HALT, «fault на ходу» — умолчания лида приняты координатором, владельцу показываются итоговым списком.
5. **Три красных вне run-state** (`test_gui_process`, `test_headless_process`, `test_system_dashboard`): координатор влил `fix/lane-D2-reds-on-main` (C-94…C-98) — на новом main не перепроверены мной.
6. **Урок про Qt** (`isHidden()` у непоказанного дочернего виджета) не записан в память: индекс `docs/claude/memory/MEMORY.md` 8993 байт при лимите 8 КБ; решение по индексу — вне полосы. Урок про ложные разрывы revision — в OPEN_QUESTIONS.
7. Хвосты правок: `process_manager_process.py:1723` (описание `system.run.status` без `stop_allowed`/`ack_allowed`), README PM 46 КБ при бюджете 32 КБ, `tasks/2.8.md:322` (повтор затравки не в S5), ADR-PMM-049 «Известная цена» после S5 устарела; плана `plan.md` и `ORDER.md` строки статусов 2.7/2.9/2.2/S5/2.9b не обновлены (ORDER не правится, plan.md — лиду отдельно).
8. История коммита 2.7d: строка `Decision:` с двумя ADR в одной строке не переписывалась.

## 4. Таблица agentId (эта часть сессии)

| Роль / задача | agentId |
|---|---|
| docs-writer: S3doc / reviewer Sonnet (экспресс) | ab2a3a52b38c5c012 / a306684373f6209db |
| Opus слепо: S6 (2.2c) / S5 / пауза 2.2 | af803426ecc6ea2d7 / afb5c27d9e8d1f2f0 / a95a077bbd610a163 |
| manager: спека S5 / reviewer Sonnet стадия 0 S5 | a0934b79d6b6df39a / a9111d026bfbd96db |
| tester слепой S5 / developer S5 / reviewer Sonnet S5 | ae46949453a197f0a / aae5bbd7a00d95c51 / ada3181f8d3a60822 |
| developer 2.9b / reviewer Sonnet 2.9b | a809a0213f119d29c / a9197acddae3a4c19 |
| developer паузы 2.2 (a8a33e75ac92f093a, тот же, что 2.2) | a8a33e75ac92f093a |
| test-runner: 2.2c / S5 / пауза / 2.9b | af41e5d19ebe8fa06 / a462b2708083999a5 / a768cb28759769cfa / a7b01b06fdaa94ff1 |
| стенд: серии 1–2 / S4b / investigator resync | a80244b5cfdaa356a / a86078b18e9fba454 / a481112f5c7cd66c9 |

Источник: сессия `inspector-bottles-f1`, scratchpad `f/` (вердикты, отчёты агентов, сырые данные стенда).
