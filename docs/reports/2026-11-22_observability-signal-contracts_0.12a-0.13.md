# Отчёт: токен порта управления и зонд приёмки — 0.12a, 0.12b, 0.13

**Суть.** Порт `backend_ctl` теперь закрыт токеном: клиенты читают его из файла порта (0.12a), сервер без токена отвечает `auth_required` и поставляет токен (0.12b), зонд приёмки не даёт ложного FAIL и проверяет остановленного писателя (0.13). Порядок «клиенты → сервер» выдержан.

**Итог.** Ветка `refactor/observability-signal-contracts`, 12 коммитов `a0aa28ae9…4e87c8a9c` поверх main `e1cd3f85e` (в main не слито, ждёт слова координатора). Ревью стадии 5 по каждой задаче — APPROVED во 2-м раунде; ветковое ревью Opus — APPROVED.

**Проверка.**
- Стенд `inspection_full`: PASS 45 из 52, FAIL 0 (порог ≥ 45); S2, S5, SF1 — PASS; SF1: стоп `processor` 12 с, три читателя `stale`, pid не сменился.
- 0.12b руками на живом бэкенде: клиент с чистым env подключился (7 процессов); без токена — `token file not found: <путь>`; сырой TCP без `hello` → `auth_required` + EOF.
- Тесты: `backend_ctl/tests` 1049 passed / 72 skipped; `router_module/tests` 789 passed; зонд 35 passed; `backend/tests` + `Services/robot_comm/tests` — 1 красный (`test_rig_restart_retries_until_port_free`, Errno 48), красный и на main; `validate.py`, `sentrux check`, `ruff` — чисто.
- Инъекции: 0.12a — раунд 2 покрыл все свойства, I11 вскрыл пробел теста; 0.12b — J1–J10, K1–K3 (расхождений нет, 3 лишних красных существующих тестов); 0.13 — I1–I10, 8 из 10 совпали (I5a, I10 — нюансы в `reports/0.13.injection-predictions.md`).

**Проблемы → решение.** (1) Офлайн-прогон писал токены в настоящий `~/.multiprocess_framework` → autouse-изоляция HOME в `backend_ctl/tests` и `process_manager_module/tests`, отключается при `--backend-live`/`headless_backend`/`harness_smoke`. (2) Окно «порт слушает, токена нет» → fail-closed, закреплено тестом. (3) Читатель `frame_bridge` шёл без токена → `token_provider`. (4) Фейк `state.get_subtree` и зонд оба читали форму ответа неверно (`subtree` вместо `value`) → ловит ревью; фейк приведён к форме сервера. (5) Предсказание (a) по 0.12 (`oversize`) **не сбылось**: ≈450 строк src против сметы 250; зонд 0.13 +≈270 против ≈150 → бюджет пересмотрен в `plan.md` (закладывать ×1.5–2 для механизмов IPC/безопасности).

**Агенты.** `teamlead` (opus) — 0.12a и 0.12b (оба по ~230k); `developer` (sonnet) — 0.13 (~190k, два захода); `reviewer` — sonnet xhigh на каждую задачу (~210–260k), Opus на ветку (~200k); haiku `junior` — инъекции K1–K3, I2–I10; `tech-writer` — документация токена (~70k). Ни один не превысил порог замены (~400k).

**Открыто.** (1) Изоляция HOME вне двух каталогов тестов (`app_module`, `examples/minimal_app`, `apps/line_sim`, `Plugins/sim`, `Services/device_hub`) — решение владельцу/координатору. (2) Windows и Linux не проверялись (SIGSTOP на Windows — `UNVERIFIED` по коду). (3) Флейк `TestGate::test_setup_gate_open_via_config` (`port: 0` → 8765) — не мой файл, строка координатору. (4) Один прогон стенда, запас SF1 по возрасту узкий (13.95 с при пороге рестарта 15 с). (5) Относительный `BACKEND_CTL_TOKEN_FILE`; pid ПМ из `supervision_status` в зонде; обратная ссылка ADR-RTR-017 — `OPEN_QUESTIONS`. (6) Вопросы владельцу В-5, В-6, В-7 и «седьмая строка» пилота стадии 0 — не отвечал.

**Дальше.** Заявка координатору `docs/handoffs/2026-11-22_N-0.12a-0.13-merge-request.md`; слияние — по его слову; затем `contract.lock` раз при закрытии плана (решение координатора) и tech-writer по README/STATUS statistics/router при слиянии.

**Подробно.** `plans/2026-11-21_observability-signal-contracts/tasks/0.13.result.md`, `docs/reviews/2026-11-22_task-0.13-lead-stand.md`, `reports/{0.12a,0.12b,0.13}.review-stage5.md`, `reports/branch-review-0.12a-0.13.md`, `reports/*injection-predictions.md`, `docs/claude/OPEN_QUESTIONS.md` (последние записи).
