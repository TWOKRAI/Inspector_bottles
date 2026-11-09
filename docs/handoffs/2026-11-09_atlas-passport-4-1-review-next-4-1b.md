# Handoff: Атлас — 3.2 и 6.3 влиты, 4.1 на ревью, дальше 4.1b → 4.2a

Дата: 2026-11-09. План `plans/2026-11-06_atlas-passport/plan.md`. Пуш не делался — ведёт чат «Git · push и уборка».
Предыдущий: `docs/handoffs/2026-11-09_atlas-passport-forma-pasporta-next-3.2.md`.
Для кого: следующая сессия лида. Первая строка ответа владельцу: «Атлас · <имя сессии>». Ответы по-русски, числа, непустой раздел «что оставил открытым».

## Что в `main` (проверено git, `b7a835f46`)

| что | коммит |
|---|---|
| Task 3.2: `ceiling`, `pattern`/`glob` в трассе, предупреждения `verify-set`, колонка «файл (справка)» (84 теста, матрица 30/30, ревью APPROVED) | `10d50e315` |
| Task 6.3: `ship.md` ×2 и README Lifecycle п. 3; статусы 3.2 и 6.3 DONE в `plan.md` (16 282 из 16 384 байт) | `39c5bcd67` |
| `holdout.json` (5 вопросов, независимый автор, `verify-set` 11 записей, проблем 0, предупреждений 0) | `e5bc22a35` |
| `origin.json` (5 вопросов «почему так», Kill-3, `verify-set` проблем 0) | `b7a835f46` |

## Не влито: Task 4.1 (ветка `feat/atlas-4-1-facts-links`, worktree `.claude/worktrees/atlas-4-1`)

Коммиты: INTERFACE `935352163`, RED `8598d4b30` (10 тестов слепого tester), GREEN `a0d1fd9f7`. 454 passed, 6 skipped. Гейты A/B на 4343 `.py`: время 1,37× A1 (≤ 2×), файл БД кэша 3,31× (≤ 4×; формат тела сжат — исходный был 6,36×, мой приказ teamlead), `build_links` 0,64 с. Матрица инъекций 31 из 31 (скрипт `scratchpad/inject41/`, выжила только проба `d.get("strs", [])` — тест 5 ключ `strs` не охраняет).
**Ревью стадии 5 (reviewer sonnet, `aec81156950fc418a`) запущено — вердикт в `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/f8e98ab0-504b-47c5-8acb-c1cccd047512/scratchpad/4.1-review-r1.md`** (если файла нет — ревью не дошло, запускать заново по брифу из `tasks/4.1.md`). После APPROVED (и правок по находкам через teamlead `a72f852256fdaa766`): перебазировать ветку на актуальный `main`, влить fast-forward (см. «Слияние»), `tasks/4.1.result.md` уже в коммите.

## Следующие шаги (по порядку)

1. Вердикт ревью 4.1 → правки → слияние.
2. **4.1b** (`tasks/4.1b.md`, Middle+, developer sonnet, 2 REDS, stage 0 APPROVED): `Links.of(...)["bases"]`. Только после слияния 4.1 (оба правят `links.py`). По задаче tester не стоит в цепочке; правило проекта «tester один раз на механизм» — решить (рекомендация: слепой tester на 2 REDS дёшев).
3. **4.2a** (Senior+): INTERFACE developer → слепой tester → teamlead; вход: `4.1.result.md`, `4.1b.result.md`, `3.2.result.md`. Приёмка: `ceiling k0` по паспорту ≥ 7/8 до живого прогона; Q7 держится на `used_by` у `ConfigFileWatcher` (не проверено).
4. 4.2b, 4.3, 5.1 по цепочке. 5.1: `holdout.json` готов.
5. **6.1 — 2026-11-10** (не раньше): перед стартом выровнять её запись владельца с 6.3 — дата и цитата в `## Итог` старого `plans/2026-10-04_atlas/plan.md` (сейчас 6.1 пишет без цитаты в `K1.1.result.md`). Затем 6.2a/b/c только если kill №2 сработал.

## Ждёт слова владельца (живые прогоны не запускать без слова)

1. Повтор C0 на `r1` по V3 (3 сессии Haiku, ≈10 мин) + строка П8 («каждый названный `file:line` — в `locations`») — вместе, перед 5.1.
2. Прогон Kill-3 (7.2b; `origin.json` готов; ≤ $3, зонд ≤ $0,2). Расхождение с предпосылкой плана: в истории `repo_sha` **нет трейлеров `Decision:`** (0 на `10d50e315`) — набор меряет `grep-read+git` на старых коммитах; записать в `7.2b.result.md`, 7.3 не обосновывать трейлерами.
3. Справка `atlas` ×3 на `k0` (+~180k Haiku) — после 4.2a.
4. Порог строк плана 18 303 (с тестами): сейчас `scripts/atlas` 22 697 после 4.1 — решать на закрытии плана.

## Долги (в планах не заведены — `plan.md` на пределе)

- 3.2 (`tasks/3.2.result.md`): `finditer` в правиле «а», тест на `предупреждений 0`, имя файла в `ОШИБКА`, предфильтр `_reachable`.
- 6.3 (`tasks/6.3.result.md`): README «Archive-on-done» (170–178), зеркало `plans-readme.template.md:17`, `ship.md:61` ссылается на несуществующий тест, брошенный план с открытыми задачами.
- 4.1: три буквальных прочтения (`subclasses` без наследника в том же файле; `tests` с `scope` всегда `test`; `used_by` у методов `[]`); `call_sites_unresolved` шумный (`os.path.join`); алиасы `as` не видны (`ImportRec` без алиаса) — идут в `unresolved`.
- holdout: Q3 (`parallel.py:74` vs `:113`), Q2 (`:173` vs `:179`), Q1/Q5 могут быть слишком лёгкими, нет вопросов про команду/регистр. origin: Q4 (несколько коммитов `C-79`), двойники-зеркала у Q1/Q2.
- Карта плана (`atlas-plan-map.html`, https://claude.ai/artifact/TF96ex9ALuBf9RXjSfCAHn) не обновлена под 3.2, 6.3, 4.1.

## Слияние в `main` и ловушки сессии

- Перед слиянием: `git branch --show-current` в основном дереве. Если там `main` — перебазировать ветку на `main` и `git merge --ff-only <ветка>` прямо в основном дереве (файлы ветки не пересекаются с грязными файлами владельца). Если там чужая ветка — detached worktree + `git merge --ff-only` + `git update-ref refs/heads/main <новый> <старый>`, но ТОЛЬКО если `main` нигде не выведена (`git worktree list | grep '\[main\]'`); иначе `update-ref` ломает индекс того дерева (так случилось с 6.3, владелец выровнял `git restore`). Память: `.claude/memory/feedback_primary_tree_may_sit_on_another_branch.md`.
- `Agent(isolation: worktree)` берёт HEAD основного дерева — оно может стоять на чужой ветке; создавать свои worktree (`git worktree add -b <ветка> .claude/worktrees/<имя> <sha>`).
- Хук lint-brief: DESIGN ≥ 3 отдельных строк или `BRIEF-OVERRIDE: <причина>`; `plans_ledger.py brief <id> --plan <путь>` требует поле `TESTS`; для слепого tester — `BRIEF-OVERRIDE`.
- Субагенты всегда уходят в фон; коммитит лид (protect-branch). Разрешение `git restore` в сессии лида отклоняется — такие команды владелец запускает сам.
- Незакоммиченное владельца в основном дереве (не трогать): `.claude/memory/MEMORY.md`, `feedback_cto_spawn_explicit_fable.md`, `docs/reports/2026-10-26_stage0-eval.md`, три новых файла памяти, `docs/handoffs/2026-11-09_status-to-1.0-and-start-prompts.md`.

## Таблица агентов (SendMessage только по agentId)

| Роль | agentId |
|---|---|
| 3.2: слепой tester / developer / haiku-матрица / reviewer | `ae9c8f73dc9cabadb` / `a9ef2e0374caabe41` / `aa99ae224e47ce356` / `a393c30eb42f7bb43` |
| 4.1: INTERFACE developer / слепой tester / teamlead GREEN / haiku-матрица / reviewer | `a2fb62f314e901d42` / `a872f225f7f85de57` / `a72f852256fdaa766` / `a2bf093a63fbb2885` / `aec81156950fc418a` |
| 6.3: stage 0 reviewer / developer / express reviewer | `aef6ed3c4a5de3b63` / `adfbb8520f3e5f79c` / `aba7ab06782f43215` |
| авторы наборов: holdout / origin | `a530503fc383b3805` / `a77c625dfba55e66d` |

## Рабочие деревья (уборка — чат «Git · push и уборка»)

Влиты, можно удалять: `atlas-3-2`, `atlas-6-3`, `atlas-holdout`, `atlas-origin` (ветки `feat/atlas-3-2-ceiling`, `feat/atlas-6-3-close-docs`, `feat/nav-holdout-set`, `feat/nav-origin-set`). Не влиты: `atlas-4-1` (4.1), `atlas-4-1-tester` (ветка `test/atlas-4-1-blind`, содержимое уже в `atlas-4-1`, удалять можно).

## Что оставил открытым / ненадёжно

- Вердикт ревью 4.1 неизвестен; перемер гейтов A/B ревьюером не получен.
- Решения лида по 4.1 (алиасы, формат `twins`/`note`, `where`, `daemon`, `unresolved`) приняты без владельца; прочтения исполнителя не проверены на реальных данных ревью.
- Допущение в 6.3: «дата и цитата в `## Итог`» — моё, слово В2 места не задавало.
- CI на GitHub и Windows не проверены. `scripts/validate.py`: 2 красных по памяти (теги, `BY-MODULE`) были на `main` до нас.

## Фраза для старта нового чата

«Продолжай по `docs/handoffs/2026-11-09_atlas-passport-4-1-review-next-4-1b.md`. Сначала вердикт ревью 4.1 и слияние, затем 4.1b → 4.2a. 2026-11-10 — Task 6.1. Живые прогоны и повтор C0 — только по моему слову. Спрашивай с рекомендациями.»
