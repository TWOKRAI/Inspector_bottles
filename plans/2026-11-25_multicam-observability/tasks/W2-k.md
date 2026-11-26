# Task W2-k: проект авторизации команды на стороне бэкенда (роль, обход запрета прогона, аудит)

- **Статус:** [PENDING] · **Level:** Senior+ · **Assignee:** teamlead
- **Блокер:** решения владельца Р-W2-5, Р-W2-6, Р-W2-7, Р-W2-8; согласование с `plans/2026-11-21_observability-signal-contracts` Task 2.2 (рукопожатие `hello {token, protocol_version, role}`) и Task 2.3 (роль сессии на хосте) — они владеют ролью соединения
- **Module contract:** n/a (проектный документ; код — задачами W2-k1…, которые пишутся по этому документу)
- **Dependencies:** решения выше; W2-j (признак `run_locked`)
- **Gate:** документ принят CTO (вердикт), затем владельцем
- **Files:** `plans/2026-11-25_multicam-observability/design-authz.md`
- **Acceptance:** блок ACCEPTANCE
- **Handoff:** teamlead -> cto (вердикт по документу) -> лид -> владелец

Факты (проверено лидом и планировщиком 2026-11-25, дерево `mco-plan2` = `e929be0d3`):
- Токен — аутентификация СОЕДИНЕНИЯ, не авторизация команды: первая строка `hello {token}`, токен в файле `~/.multiprocess_framework/ctl_<порт>.token` (0600), граница доверия — чтение профиля пользователя ОС; процессы того же пользователя вне модели угроз (ADR-RTR-017 п.1). Порт закрыт без токена (ADR-PMM-052); роли — «не здесь» (ADR-PMM-052 п.4 -> OSC 2.3).
- В бэкенде роль не проверяется нигде: `git grep -E "access_level|is_admin|\brole\b|user_role|AccessLevel"` по `command_module`, `process_module`, `router_module`, `registers_module`, `process_manager_module` (без тестов) — только `role` проводов `sender/receiver` и `current_access_level=0` по умолчанию в `RegistersManager.validate_field_value` (`manager.py:302`); `FieldMeta.access_level` проверяется статически против уровня 0 (`field_meta.py:370-372,407-408`).
- Пользователи, роли (`dev/admin/operator/viewer`), bcrypt и аудит есть в `Services/auth` (без Qt), но экземпляр `AuthManager` создаётся только в процессе GUI (`multiprocess_prototype/frontend/app.py:697`); аудит пишет `AuditMiddleware` шины действий GUI (Auth-008). MCP о пользователе не знает.
- Запрет прогона — обёртка `_run_guarded` в ребёнке (`base.py:1835-1849`), видит только аргументы команды, не конверт сообщения.

TASK: W2-k — один документ: кто доказывает роль, где она проверяется, как запертая команда выполняется администратором, что пишется в аудит   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: teamlead
CHAIN: you -> cto (вердикт) -> лид -> владелец

DESIGN (decided by the lead — you type it, you do not derive it):
  1. Документ отвечает по рекомендациям лида (раздел «Решения» плана), каждую — с альтернативами и ценой: (а) роль ставит ТОЛЬКО хост: PM для сессий `backend_ctl` (по OSC 2.3) и для GUI — по входу, проверенному на хосте (`Services/auth` в процессе PM или в своём процессе `auth`), а не по заявлению GUI; (б) роль доезжает до ребёнка в конверте команды, который клиент не может подделать (штамп хоста), а не в `data`; (в) обход запрета прогона: команда/поле с запретом выполняется при роли `admin` и явном `override_run_lock: true`, отказ и обход пишутся в аудит; (г) опасные действия — двухшаговое подтверждение (`confirm_id` с жизнью 30 с) и для администратора; (д) dev без токена: только `BACKEND_CTL_DEV_ROLE=admin` в окружении бэкенда, WARNING при старте, `principal "dev-env"` в каждой записи аудита, отказ вне loopback.
  2. Аудит: одна запись на каждую команду записи и на каждый отказ по роли/запрету — кто (`principal`, канал `gui|mcp|dev-env`, `session_id`), когда (UTC), что (команда, цель, поле; значения секретов не пишутся), исход. Где хранится — `observability.db` (у неё уже есть хранение аудита 1 год, `system.yaml:75-78`) или `Services/auth` SQLite (Auth-003, Auth-006 append-only); документ выбирает одно и объясняет.
  3. Разбивка на задачи W2-k1…: не больше 6 файлов на задачу, вертикальный срез первым (одна запертая команда `release_device`: MCP-сессия admin -> штамп хоста -> обход в ребёнке -> запись аудита -> ответ).

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. plans/2026-11-25_multicam-observability/design-authz.md — новый

REDS: n/a — проектный документ, кода нет; контракт-тесты — в задачах W2-k1…

ACCEPTANCE (every number with its command):
  - документ есть и отвечает на (а)-(д) и п.2 — проверка: `grep -c -E "^## " plans/2026-11-25_multicam-observability/design-authz.md` -> не меньше 7
  - каждая ссылка на код в документе — путь и строка, перечитанные автором (пометки как в аудите: [код]/[гипотеза])
  - `python scripts/plans_ledger.py brief W2-k --plan plans/2026-11-25_multicam-observability` -> exit 0

TESTS: n/a — документ; проверка — вердикт CTO

OUT OF SCOPE: код; TLS и не-localhost (`gui-service` 2.2, В-1); версия протокола (OSC 2.2).
TRAPS: не строить вторую систему ролей рядом с OSC 2.3 — документ берёт роль соединения оттуда и добавляет только то, чего там нет (GUI-пользователь, обход запрета, аудит). «Полный доступ администратора» не означает обход аудита и подтверждения.
HANDOFF IN: решения Р-W2-5…Р-W2-8.
REPORT: STATUS (DONE|BLOCKED), путь документа, список задач W2-k1…, раздел «Что оставил открытым / ненадёжно».
