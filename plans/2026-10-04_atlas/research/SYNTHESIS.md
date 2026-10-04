# Ревизия планов и единая система знаний — сводка (2026-10-04)

Основание: `main` = `03952a020`. Шесть отчётов агентов Sonnet (только чтение) + мои проверки.
Отчёты: `D_observability.md`, `E_tooling_gui.md`, `O1_sources.md`, `O2_backbone.md`, `O3_git_freshness.md` (эта папка);
отчёт групп A–C (37 планов) пришёл текстом — его выжимка в §1.

---

## 1. Ревизия 61 плана — итог

### 1.1 Вердикты

| Вердикт | Шт. | Планы |
|---|---|---|
| Живые сейчас | 6 | lifecycle-owner-scope (Ж), layer-render (С), robot-protocol-v2 (Р), transport-single-policy (5.8s), plans-progress-dashboard (М), commit-mechanism (М) |
| Следующий | 1 | letters-retrain (0.4 ничего не ждёт; Ф1 открывает layer-render 6.3) |
| Ждут триггера | 11 | camera-robot-calibration, robot-calibration, robot-place-pose, device-tree-recipe, word-layout, qr-code-reader (железо / визит), storage-stack-embedded-first, lifecycle-stop-ownership (Ж1), backend-ctl-review-remediation (Ж), framework-architecture-rework (окно codemod), dataset-annotation (DRAFT, О-2 не утверждён) |
| Отложены владельцем | 6 | observability-closure, otel-export (за Ж); gui-service, gui-constructor, frontend-constructor, pipeline-node-timing (О-16) |
| В архив: сделаны | 26 | line-sim, line-sim-layer-editor, line-sim-belt-look, sim-lateral-offset, undo-restores-selection, dataset-circle-capture, draw-mode-rework, code-reader-sdk, lifecycle-graceful-stop, constructor-master (после сверки F8-6), supervisor-×3, depends-on-readiness, truth-holes-closure, observability-roadmap, observability-unified-routing, observability-review-remediation, observation-port, telemetry-stage6, telemetry-coherence-remediation, telemetry-dashboard, telemetry-publish-control, gui-telemetry-read-model, pult-control-panel, pipeline-color-inspection |
| В архив: поглощены | 11 | letter-robot-cycle, constructor-maturity, backend-ctl-proof-discipline, sql-insert-many-atomic, current-path, framework-layer-grouping, observability-f1-hardening, observability-dx, telemetry-delivery-simplification, telemetry-pull-on-demand, proto-frontend-carve |

Итого: 61 → **7 живых + 11 ждущих + 6 отложенных = 24**, в архив **37**.

### 1.2 Перед архивацией обязательно (иначе пропадёт)
- В `plans/queue/backlog.md` нет хвостов, которые ORDER §4.3 обещает туда перенести (grep пуст). Перенести:
  roadmap 9.1–9.3 (fingerprint ошибок, fd-перехват stderr, JSON-сток), observability-dx Д.1, Д.2, Б.3; line-sim 4.1, 4.2, 5.5;
  code-reader 3 пункта «Открыто по коду»; pult 5.4; constructor-master F8-4, F8-5; robot-calibration F4/F5 → T5.4/T5.5 v2;
  долг «источники на железе» (lifecycle-graceful-stop).
- Ветка `origin/docs/line-sim-red4-input` держит `plans/line-sim/decisions.md` (решения 09-22). Забрать до О-15.
- `plans_ledger.py close` откажет трём планам без даты в имени (NO_DATE_IN_NAME) — их через `git mv`.

### 1.3 Находки, важные для системы
- **Шапки врут в 9+ планах** (robot-protocol-v2, lifecycle-owner-scope 0/25 в main при идущей Ф0, sim-lateral-offset, observation-port, unified-routing…).
- **Счётчик врёт по ≥8 планам**: задачи заголовками `### Task X` парсер видит как pending; draw-mode-rework, belt-look — 0/0 при DONE.
- **Хеш `[DONE hash]` не сверяется с git** — план может объявить DONE несуществующим хешем.
- **Блок прогресса в ORDER отстаёт** от git (commit-mechanism «3 из 8» против 4 из 10).
- **Противоречие о данных робота v2**: `data/robot/<id>/` (шапка device-tree-recipe) против `devices.yaml` (О-7).
- **Возможный двойной счёт**: канва layer-render 5.3 и line-sim-layer-editor 1.3h-b.

### 1.4 Предлагаемый порядок (владелец 10-04 принял порядок §1; ниже — он же, очищенный)
1. **Ж** lifecycle-owner-scope — Ф0 (0.3 ∥ 0.4 → 0.5), затем Ф1.
2. **С** layer-render — 6.2 → 6.3 (∥ 3.1); затем letters-retrain 0.4 → Ф1.
3. **Р** robot-protocol-v2 — переписать спек T2.3+T2.4 одним шагом (О-10), новый слепой тестер; RED `red/robot-v2-t23` не сливать, взять как вход. Оформить GATE-0 (О-1).
4. **Ф** transport 5.8s → (5.8a/5.8b/5.11 после Ж) → 5.12.
5. **М** dashboard 5.5 → 5.6 (+4.1 один парсер); commit-mechanism 2.1 → 2.3 → 2.2. Дальше обе полосы вливаются в план «Атлас» (§3).
6. Заполнители: dataset-annotation (после О-2), storage-stack.

---

## 2. Что показали замеры системы знаний (O1, O2, O3, E)

| Факт | Число | Источник |
|---|---|---|
| Коммитов за 60 дней | 2051, пик 204/день | O3 |
| Трейлеры `Why`/`Layer`/`Refs` | 98 / 98 / 93 % | O3 |
| `git %(trailers)` видит `Refs` | 0 из 198 (последние 200) | O2; причина подтверждена мной: `Co-Authored-By` отделён пустой строкой → git видит только последний абзац |
| Номер задачи в коммите | 21–37 % | O3 |
| Слияния, задевающие 2+ / 3+ модулей | 72 / 43 % | O3 |
| Модулей на задачу плана (медиана) | 5 | O3 |
| Жизнь влитой ветки (медиана) | ~1 час, 91 % ≤ 1 дня | O3 |
| Документ модуля тронут в том же коммите, что код | 50 % | O3 |
| Модулей с документом старше кода > 30 дней | 15–18 из 44–57 | O1, O3 |
| Худший | `config_module`, 154 дня, 22 коммита кода | O1, O3 |
| Число модулей в документах | 25 / 27 / 25 при факте 27 | O1 |
| Копии памяти | 3 «канона»; 156 из 416 общих файлов различаются | O1 |
| Дома ADR | 3, `/dev:adr` пишет в несуществующий | O1 |
| `Layer:` реально проверяется хуком | нет: `commit-layers.txt` пуст | O1 |
| Грузится в каждую сессию | ~91 КБ из 5 файлов | O1 |
| graphify: md-узлов / рёбер док→код / тестов | 6540 / 33 из 62206 / 0 | O2 |
| qex индексирует `docs/`, `plans/` | нет (`.ignore`) | O2 |
| Парсеров статуса планов | 2 (ledger 3266 строк, progress 2150) | O2, E |
| Git-хуки в облачном clone | нет; гарантированный гейт — только GitHub CI | O2 |

**Ветка на модуль — нет** (O2 и O3 независимо). Задача плана задевает в медиане 5 модулей; модульные ветки дали бы
сведение 3–5 веток на задачу и свою версию документов и графа в каждой — единой истины не будет.

---

## 3. Дизайн: «Атлас» — одна система знаний

### 3.1 Принципы
1. **Истина — файлы в git.** Всё остальное — производное.
2. **Что выводится — не пишется руками**: списки, счётчики, статусы, связи, «последний handoff», таблицы модулей.
3. **Свежесть считается из git, а не штампами.** Возраст документа = коммиты в его зоне после его последней правки.
   Штампов `verified_at` не пишем (запись в общий файл — ловушка двух писателей). Статичная привязка `covers:` — только
   там, где документ лежит не в папке модуля (карты, диаграммы); она меняется редко.
4. **Производное — только на `main`, одним писателем** (post-merge / CI). В ветках — только проверки.
5. **Заменяет, а не добавляет.** Мерило успеха — меньше копий и дешевле вход агента в задачу.

### 3.2 Компоненты (что из чего растёт)

| Компонент | Что делает | Растёт из |
|---|---|---|
| `modules.yaml` | путь → модуль, слой, ярус, документы модуля | `MODULE_TIERS.md` (контракт-тест уже есть) + sentrux-слои |
| Формат коммита v2 | трейлеры одним блоком; `Task: <slug>#<id>`; область заголовка = id модуля (подставляется по путям); `Docs: n/a (<причина>)` | **commit-mechanism Ф2** (2.1 валидатор, 2.2 документы) |
| Ядро реестра `scripts/atlas/` | `Node{kind,id,path,status,edges,findings}`, находки + база-храповик, контракт `--json` | **ядро, вынутое из `plans_progress`** (dashboard Ф4) |
| Адаптеры | plans (= `plans_progress`), modules, docs, adr, defects/decisions, tests (AST-импорты), commits (git log + трейлеры), memory | новые, маленькие; plans — существующий |
| Обогащение графа | рёбра `commit→plan`, `commit→module`, `doc→covers`, `test→tests`, `plan→touches→module` пост-обработкой `graph.json` без LLM | graphify (post-commit уже есть) |
| Проверки | жёсткие: битые ссылки, `Refs`/`Task` на несуществующее, DONE-хеш не в `main`, дубли фактов; мягкие: долг свежести | `docs_verify` (19 проверок) обобщается; `link_check` |
| Виды | HTML-атлас (stdlib, офлайн): модуль → планы → ADR → тесты → коммиты → свежесть; вкладка «Планы» = нынешний дашборд; CLI-карточка `atlas card <модуль>` для агентов; `chunks.jsonl` для BM25/qex | `plans_progress --html`, `scripts.sync` (маркеры) |
| Запуск | post-commit диспетчер (уже в плагине core, не установлен) + GitHub CI на `main` + SessionStart в облаке | `.claude/plugins/core/hooks/git/post-commit.sh` |

### 3.3 Поток
`git commit` (ветка) → хук проверяет формат и обязательства, ничего не пишет →
слияние в `main` → CI / post-merge: `atlas build` → `atlas check` → `atlas render` + `graphify update` + `chunks.jsonl` →
владелец открывает HTML, агент зовёт `atlas card <модуль>` перед работой.

### 3.4 Что удаляем и сводим (заменяет, а не добавляет)
- Память: один канон `docs/claude/memory` в git; локальная — кэш, наполняемый скриптом с diff. Ручной dual-write снять.
- `COMMIT_GUIDE` ×2 → один; `commit-layers.txt` наполнить (или снять слово «обязателен»).
- ADR: один дом — `DECISIONS.md` модулей/фреймворка; починить `/dev:adr`; удалить `docs/decisions/`.
- Планы: один дом `plans/`; из глобального `~/.claude/CLAUDE.md` убрать `workspace/plans`, `apps/*/plans`.
- Генерировать вместо ручного: таблицы модулей и ярусов, счётчик тестов в STATUS, указатель «последний handoff», `.mmd`-обзоры.
- Архив (`reviews` 308, `sessions` 106, `handoffs` 77, `audits` 33) — вне горячего слоя, доступ по ссылке из узла.
- Два парсера планов → один (dashboard 4.1).

### 3.5 Порядок работ («Атлас», предварительно)
- **А0 — без LLM, локально (мои/ваши лимиты):** правка шаблона трейлеров (одним блоком) + `Task:` в commit-mechanism 2.1/2.2;
  dashboard 4.1 (один парсер); замер базовых чисел: цена входа агента в задачу, доля устаревших документов.
- **А1 — ядро:** `modules.yaml` + ядро реестра из `plans_progress` + адаптеры modules/commits/docs + `atlas check` (мягко).
- **А2 — виды:** HTML-атлас, `atlas card`, `chunks.jsonl`; dashboard Ф4.2–4.4 и Ф6 вливаются сюда.
- **А3 — граф:** рёбра док→код и тесты в graphify пост-обработкой.
- **А4 — тираж в облаке:** карты подсистем и README/STATUS 15–18 устаревших модулей по шаблону, каждая сессия = PR.
- **А5 — сведение:** память, ADR, COMMIT_GUIDE, генерируемые таблицы; удаление дублей.
- **А6 — гейт:** долг свежести из «показать» в «блок» по данным 2–3 недель; seed-пакет для claude_seed (ядро без адаптеров Inspector).

---

## 4. Облачный кредит ($250 Max, до 4 ноября) — куда

Облако = Linux, clone с GitHub, нет Windows-стенда, Ollama, git-хуков. Годится всё, что: читает код и git, пишет
документы/скрипты/тесты, проверяется pytest и CI.

| Работа | Где | Модель | Оценка |
|---|---|---|---|
| А0 (шаблон трейлеров, 4.1, замер) | локально | — | вне кредита |
| А1 ядро + адаптеры (спек → тестер → разработчик) | облако, 2–3 сессии | Sonnet; ревью Opus | ~$25–40 |
| А2 HTML + card + chunks | облако, 2 сессии | Sonnet | ~$15–25 |
| А3 рёбра графа | облако, 1 сессия | Sonnet | ~$10 |
| А4 карты/README по 15–18 модулям | облако, 8–12 параллельных сессий | Sonnet | ~$60–100 |
| Ревью рискованных модулей (`router`, `shared_resources`, `state_store`, `config`) | `/code-review ultra` | — | 3 бесплатных запуска |
| CTO: приёмка дизайна и фаз | локально / облако | Fable | ~$10–20 |
| Запас на повторы | — | — | ~$40 |

Цифры — оценки до калибровки. Первая облачная сессия — пилот с замером расхода.

---

## 5. Вопросы владельцу (собраны из отчётов, с рекомендацией)

1. Архивировать 37 планов одним коммитом после переноса хвостов в backlog — **да**.
2. Закрыть старые решения №2, №3, №5, №13, №14, №15 как исполненные — **да**.
3. №4 канонизация двух рецептов — **да, после dry-run**; №7 `chain_module` = core — **да**; №6 воркеры — **при Ж Task 1.3**.
4. framework-architecture-rework: запарковать как видение, 2.1 `record_metric` вынуть малой задачей — **да**.
5. Ветку на модуль не делаем; короткие ветки на задачу + `modules.yaml` — **да**.
6. Добавить в commit-mechanism 2.1/2.2: трейлеры одним блоком + `Task:` — **да** (дёшево, те же файлы). Область = модуль и `Docs:` — после `modules.yaml`.
7. dashboard: стоп на 5.6 + 4.1; Ф4.2–4.4 и Ф6 вливаются в «Атлас» — **да**.
8. Память: один канон в git, ручной dual-write снять — **да**.
9. Блокировать коммит без обновления документа — **нет**; сначала показывать 2–3 недели, блок только при изменении публичной поверхности.
10. Где данные робота v2 — решить при спеке T5.2, противоречие в шапке device-tree-recipe поправить.

## 6. Вопросы к CTO
1. Ядро реестра: вынуть из `plans_progress` (рекомендация) или новый пакет с нуля, читающий его `--json`?
2. Свежесть только из git без штампов — достаточно, или для карт нужен явный `verified_at`?
3. graphify как носитель связей (пост-обработка `graph.json`) или реестр держит свои рёбра, а graphify — только код?
4. Порядок А0–А6 и бюджет §4: где риск съесть проект; что вычеркнуть.
5. Как измерять успех: «цена входа агента» и «доля устаревших документов» — достаточные метрики?

## 7. Что ненадёжно в этой сводке
- Вердикты по ~10 планам средней надёжности (тела не читались: qr-code-reader, letter-robot-cycle, word-layout и др.).
- Числа «устаревания» по дате коммита искажены массовыми правками (codemod, ruff, переформат 10-03/04).
- Оценки облачной стоимости — до калибровки; работа Claude-хуков и `plans_progress` на Linux не проверена.
- Отчёт A–C существует только как текст в моей сессии; выжимка здесь — моя.
