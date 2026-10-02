---
date: 2026-10-02
topic: prompt-audit и правка .claude (STE-80, последние модели, правила по пилотам v2/v3)
machine: Windows
branch: main (HEAD 6f88d6e3c), всё НЕ закоммичено
---

## Session goal
Владелец попросил: (1) применить совет Карпаты (объяснения в стиле ASD-STE100, ~80%), (2) улучшить `.claude`, (3) прогнать `/claude-api prompt-audit` и исправить найденное, (4) всегда брать последние модели (сейчас Opus 5.5, Sonnet 5.5), (5) провести честное ревью и закрыть хвосты.

## Done
- **STE-80:** `project-rules` §9 (источник `.claude/plugins/dev/skills/project-rules/SKILL.md` + зеркало) и абзац в `.claude/CLAUDE.md`. Определение: 8 жёстких правил + «Relaxations», без словаря STE.
- **Модели:** линтер `lint_agents.py` знает Opus 5.5 / Sonnet 5.5 / Fable 5.1; шаблоны и `sci-*` агенты на алиасах; судья evals без `temperature` и без закрепления; `pipeline.md` без `reviewer_model: claude-opus-4-9`. Тестов в `test_lint_agents_models.py` — 48, поведенческие тесты проверены инъекцией поломки (E/F/C/D совпали с предсказанием).
- **Ложные утверждения исправлены:** пустой путь pytest, `src/`/`tests/`/«gitignored» в таблице layout, `preferredLanguage`, «vault zones», порог «тривиальной задачи» (теперь 1–3 файла, <~80 строк), «pytest-timeout везде», «движок сам не коммитит», tester «пропуск разрешён», роль reviewer «после каждой задачи».
- **ponytail снова skills-only:** ключ `hooks` удалён из `.claude/plugins/ponytail/.claude-plugin/plugin.json`, три записи убраны из `.claude/settings.json` (36 строк, только удаления). Композер читает `plugin.json.hooks`, флага `hooks:false` в `enabled.yaml` он не знает.
- **`dev.md`** слит из источника и зеркала (основа — источник сида; из зеркала — строки ролей и `graph_slice`); обе копии идентичны.
- **Правила по пилотам v2/v3 (по вердикту Fable):** стадия 0 «Spec review» в таблице запуска; метрика (`total_tokens` против cache-read) и исключение в `team-protocol` §6; «fresh» у тестера; заметки по моделям теперь в одном месте (`executor-brief.md`, перебазированы на 5.5), `team-brief.md` ссылается на них и несёт форму сообщения-дозова.
- Ревью: Fable (cto) вынес **ACCEPT WITH CONDITIONS, лучше HEAD, откатывать нечего**; его 2 MEDIUM и 4 LOW применены.

## What did NOT work
- `plugin sync` недоступен: команда зовёт `claude-kit-claude`, его нет в PATH. `claude-kit sync` не запускал: перезапишет `.claude/` из сида.
- Флаг `hooks: false` в `enabled.yaml` не читается композером (проверено по исходнику 1.1.0). Композер сида 1.2.0 на машине не запускался: фикс ponytail подтверждён чтением кода, не реальным sync.
- Первая версия правки «планы без даты» была неверной: инструменты (`plans/README.md`, `manager.md`, `/dev:plan`) требуют дату. Откатил, вопрос отдан владельцу.
- Heredoc в Bash схлопывает `\\` и даёт смешанные окончания строк (CRLF/LF): тексты с обратными слэшами писать через Write; после дописывания через shell проверять `git ls-files --eol`.
- Первое ревью запущено без явного `model`; фактическая модель не подтверждена. Теперь правило: `model` в каждом вызове Agent (память `explicit-model-per-agent-role`).

## Key decisions made
- Текстом режима (`dev.md`) владеет проект, не сид (Fable: overlay сида перезаписывает локальные правки по умолчанию, 2026-09-20 уже стёр строку `graph_slice`). После `claude-kit upgrade` сверять `dev.md` с `git diff`.
- Дозов агента: на правки и ревью раунда 2 (≤10 вызовов); целую следующую подзадачу на том же агенте считать provisional, пока не замерен cache_read.
- Память: решение владельца — на Windows пишем в Windows-папку (`~/.claude/projects/<hash>/memory/`), на Mac — в Mac-папку; общее через `docs/claude/memory/`. На Windows `autoMemoryDirectory` убран из локального `.claude/settings.local.json` и файл скрыт `skip-worktree` (в коммиты не идёт). Проверить в новой сессии, что автопамять пишет в Windows-папку.
- Не добавлял: п.5 (отклонение v3 «ревьюер спеки ревьюил код», n=1) и п.7 (метод замера) из предложений Fable.

## Нужно решение владельца (в `docs/claude/OPEN_QUESTIONS.md`)
1. Имя плана: с датой (документы и `/dev:plan`) или без (корневой `CLAUDE.md`, `_stack.md:40`, 58 из 62 планов).
2. Пересмотреть `module-contract` (раскладка `src/<package>/…` не совпадает с проектом) и qex-модель по машинам (Mac: 8b/4096 — не проверено).
3. Продуктовые дефекты из чата gui-service 1b.2d (не про `.claude`): утечка `user:pass@` в журнал при успешной записи (`registers_module/core/manager.py:222`, `process_module/plugins/base.py:1655`); откат отвергнутого значения не проверен в `camera_service/plugin.py:331,417` и `process_module/plugins/base.py:1420`.

## Next step
Закоммитьте после явного «да» владельца. План коммитов (каждому нужны `Why:` и `Layer: infra`, пути добавлять явно, не `git add -A`):
1. `chore(claude): правила и тексты — STE-80, стадия 0, метрика дозова, ложные факты` — `CLAUDE.md`, `.claude/CLAUDE.md`, `project-rules` и `team-protocol` (источник + зеркало), `dev.md`/`spec.md` (обе копии), `team.md`, `reviewer.md`, `pipeline.md`, `eval.md` (обе копии), `executor-brief.md`, `team-brief.md`, `FRAMEWORK_RULES_EXTRACT.md`, `OPEN_QUESTIONS.md`.
2. `chore(claude): последние модели — линтер, тесты, шаблоны, sci-агенты, evals` — `lint_agents.py`, `test_lint_agents_models.py`, `_template.md`, `agent.template.md`, `lint-agents.md` (обе копии), 9 файлов `sci-*.md`, `evals/README.md`, `signal_noise.md`.
3. `chore(claude): ponytail снова skills-only` — `enabled.yaml`, `plugin.json`, `settings.json`, `WIRING.ru.md`.
4. `docs(claude): память — модели и явный model` — `feedback_always_latest_models.md`, `feedback_explicit_model_per_agent_role.md` + оба `MEMORY.md`; **плюс запись соседнего чата** `feedback_pydantic_assignment_keeps_rejected_value.md` (обе папки) — я обещал чату `inspector-bottles-00` взять её в свой коммит; отдельным пунктом в тексте.
Этот handoff — в коммит 1 или отдельным `docs(handoffs)`.

## Агенты (дозывать только по agentId)
| Роль | agentId | Модель | Замечание |
|---|---|---|---|
| reviewer, раунд 1 | `a27e927600f5b2d93` | в файле `opus`, факт не подтверждён | 238k, вердикт MIXED→лучше, 9 дефектов (исправлены) |
| cto (суперревьювер) | `a8be1f9acb9929f17` | fable | 2 запуска, 296k; ACCEPT WITH CONDITIONS; дозвать только для приёмки следующей фазы |

Соседи: `inspector-bottles-00` (gui-service 1b.2d) — не делает stash/checkout/reset/`add -A` в корне; ждёт моего коммита памяти.

## Предупреждения для следующих чатов
- **ponytail остаётся активным только в сессиях, начатых до правки;** новые чаты запускаются уже без него. Проверка: в начале сессии не должно быть `PONYTAIL MODE ACTIVE`. Если появится — композер вернул хук: открыть `settings.json`/`plugin.json`.
- Не запускать `claude-kit upgrade` / `claude-kit sync` не сверив `dev.md` и `plugin.json` ponytail.
- Независимый tester на эти правки не запускался; проверка — только тесты линтера (48), `validate.py`, `lint_agents.py` и ревью Fable.
- Незакоммиченные: 45 изменённых файлов + 4 новых memory-файла в `.claude/memory/` и `docs/claude/memory/` (+ `feedback_qex_full_rebuild_runbook.md` — не мой).

## Files changed
`git status`: 45 изменённых (+407/−184) и `??` memory-файлы; полный список — `git diff HEAD --stat`.
