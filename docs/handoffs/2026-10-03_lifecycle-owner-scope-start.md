# Старт плана lifecycle-owner-scope — промт для новой сессии

Ты — лид трека **lifecycle-owner-scope** (единый механизм владения ресурсами фреймворка). План стоит **первым в
очереди** по решению владельца 2026-10-03 (`plans/queue/ORDER.md` §0, полоса Ж). Задача этой сессии — Ф0, начиная с
Task 0.1.

## Где работать
- Ветка `feat/lifecycle-owner-scope`, worktree `.claude/worktrees/lifecycle` (от main `8b0eeac41`, коммит плана `23d4f25df`).
  Работай только в нём; в общее дерево и в `.claude/worktrees/t5-lead` (сессия транспорта) не пиши.
- venv: основной `.venv` проекта, `PYTHONPATH=<корень worktree>`; GUI-тесты с `QT_QPA_PLATFORM=offscreen`.
- Перед стартом: `git -C .claude/worktrees/lifecycle log --oneline -1` и `git log --oneline -1 main` — если main ушёл,
  влей main в ветку (формат `merge: main (<sha>) в feat/lifecycle-owner-scope — <зачем>` + Why/Layer/Refs).

## Прочитать в таком порядке
1. `plans/2026-10-03_lifecycle-owner-scope/DESIGN.md` — архитектура ред. 3: интерфейсы (§2.1), владельцы (§2.2),
   процесс с барьерами (§2.3), Qt (§2.4), сток (§2.5), аудит модулей (§2.6), стражи G1–G10 (§3), решения (§4),
   границы (§5), **открытое (§6)**.
2. `plans/2026-10-03_lifecycle-owner-scope/plan.md` — 25 задач, соседи, Ф0 расписана, остальные фазы — контуром.
3. `plans/lifecycle-stop-ownership.md` — соседний живой план (межпроцессная половина останова, ADR-PMM-031,
   ADR-SRM-015/016). Новый план его продолжает, не дублирует.
4. Страница для владельца: `docs/diagrams/lifecycle/lifecycle-system.html` (артефакт
   https://claude.ai/artifact/JJcjxRywjNACNU3xS8vdXc).
5. Материалы дискуссии 2026-10-03 (вне репозитория, только чтение):
   `C:/Users/INNOTECH/AppData/Local/Temp/claude/d--PROJECT-INNOTECH-Inspector-vision-Inspector-bottles/6d614d70-a994-4b5a-8029-f6b0933d60b8/scratchpad/lifecycle/`
   — `report_subscriptions.md`, `report_threads.md`, `report_gui.md` (разведка с file:line), `cto_verdict_r1.md`,
   `cto_verdict_r2.md`, `reviewer_r1.md`, `reviewer_r2.md`, `reviewer_r2_sec6.md`; прототипы `rv/lifetime_proto2.py`,
   `rv/qt_lifetime_proto2.py`, `rv/cto_barrier_e1.py`, демо `rv/demo_r2.py`, `rv/demo_r2b.py`. Прототипы — доказательство
   формы, не код для копирования: в них найдены дефекты (E5b, второй путь `Handle.close`, `self` у join текущего потока).
   Если папки уже нет — DESIGN.md самодостаточен.

## Что сделать в этой сессии
1. **Task 0.1 — спек.** Расписать полный текст задачи в `plans/2026-10-03_lifecycle-owner-scope/task-0.1.md`
   (формат Task X.Y: Level / Assignee / Goal / Files / Steps / Acceptance / Out of scope) из plan.md и DESIGN §2.1, §4.
2. **Ревью спека** — `reviewer`, `MODE: plan`, синхронно (`run_in_background: false`), на одном файле task-0.1.md.
3. **Независимый tester** — в отдельном worktree на коммите ДО реализации, только по acceptance; запретные пути
   назвать в промте. Для 0.1 (интерфейсы, ADR) тесты — контракт сигнатур и DTO; основная масса G1 — у Task 0.2.
4. **Реализация** — `teamlead` (Senior), в промте: не коммитить без трейлеров, не пушить, лимит 2 итерации.
5. **Инъекции** — сам, против обоих наборов тестов, предсказания до прогона.
6. **Ревью** — `reviewer` синхронно, находки «вход → наблюдаемый выход».
7. Статус задачи — в строке «Порядка выполнения» plan.md (`[DONE <дата> — <sha>]`), проверка
   `python scripts/plans_progress/plans_progress.py --check --root .`.
Далее 0.2 (`Scope` + G1 — самая важная задача фазы, Senior+), затем 0.3 ∥ 0.4, затем 0.5.

## Правила, которые нельзя потерять
- Решение владельца: **один механизм у всех**, у каждой функции один владелец, связь через интерфейсы
  (`base_manager/interfaces.py`), без костылей. Тестовая «уборка мусора вместо кода» — костыль; страж только находит
  и называет.
- Не изобретать заново то, что уже принято в `lifecycle-stop-ownership`: срок останова — продолжение ADR-PMM-031
  (одна функция `stop_budget`), эскалация terminate→kill — одна, метка ReaderGone сохраняется (DESIGN П1–П4).
- Имя `ProcessHandle` занято (`shared_resources_module/handles/process_handle.py:147`) — адаптер останова зовётся
  `ChildProcessStop`.
- Удалённые реестры (ключ — имя процесса/клиента) на `Subscribers` не мигрируют; мигрирует их локальная сторона.
- Каталог: «Никогда не писать "невозможно/гарантировано" без воспроизведения рядом».
- Коммиты: Conventional + `Why:` + `Layer:` + `Refs: plans/2026-10-03_lifecycle-owner-scope/plan.md`; стейджить явные
  пути; `git show --stat` после каждого коммита; слияние в main — только лид, формат `merge: суть` + Why/Layer/Refs,
  по слову владельца.
- qex 2026-10-03 был недоступен (Ollama не запущена) — сверить свежесть `get_indexing_status` перед первым
  `search_code`; числа — только грепом.

## Связи с другими сессиями
- **Транспорт** (`feat/transport-f5`, worktree `t5-lead`): Task 5.5d SUPERSEDED этим планом (`d1dc783a6`).
  Предложено владельцу (не подтверждено): 5.8a, 5.8b, 5.11 транспорта ждут Ф0 этого плана и строятся сразу на
  `spawn` / `attach_qt` / `Subscribers`. Если владелец подтвердит — сообщить сессии транспорта SHA закрытой Ф0.
- **observability-closure** Ф4 правит `observability_wiring.py` — сверка на входе Ф3 (не Ф0).
- `lifecycle-stop-ownership` Ф2 («перемерить 20 стопов после L-6»): условие L-6 по тексту выполнено (фаза 4
  транспорта в main) — запускать после Ф1 этого плана; правка их плана (сузить Task 3.1, удалить хук
  `_before_observability_teardown`) — отдельным `docs(plans)` коммитом на старте Ф1.

## Известное открытое (DESIGN §6) — Ф0 его проверяет тестами
барьер через `cancel()`/`Handle.close()`; гонка стока (потеря последней строки 1/5 при выходе по флагу); recorder
незакрытых корней (E5b); `os._exit` при выживших; проверка Qt-предка при освобождении; оценки `EXIT_MARGIN` /
`INFRA_RESERVE`; пересчёт 85/39/59 грепом в Task 0.5; флаг `active` без лока держится на GIL 3.12.

Гейт фреймворк-тестов до Ф5 падает ~1 из 4 прогонов аварийно (известная причина, этот план её лечит) — при красном
гейте с `Fatal Python error: Aborted` повтор с записью, не «зелёный по второй попытке» молча.
