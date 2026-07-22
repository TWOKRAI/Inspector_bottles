# Handoff — backend_ctl proof-discipline, заход 2026-07-22 (Фазы 1-2 закрыты)

> Ветка: `fix/backend-ctl-proof-discipline` · План: [`plans/backend-ctl-proof-discipline.md`](../../plans/backend-ctl-proof-discipline.md) — единственный активный план инструмента.
> Предыдущий handoff: [`2026-07-21-handoff-backend-ctl-proof-discipline.md`](2026-07-21-handoff-backend-ctl-proof-discipline.md).
> Продолжать: с раздела «Что делать дальше» — Фаза 3.

## Состояние на момент передачи

| Проверка | Значение |
|---|---|
| `backend_ctl` unit (`-m "not harness_smoke"`) | **514 passed** (вход захода 504) |
| `backend_ctl` live | reconnect 3/3; три новых live-плеча Task 1.1b 3/3×3; `test_fencing_live` — известный входной красный (Task 5.1) |
| `scripts/validate.py` | чист (exit 0) |
| `driver.py` | 1322 строки (было 1645) |
| `mcp_tools.py` | 1249 строк (было 1581) |
| Новые файлы | `backend_ctl/registers.py` (466), `backend_ctl/dispatch.py` (371) |
| MCP `tools/list` | 49 (бит-в-бит, реальный subprocess-смоук) |

## Закрыто этим заходом

**Фаза 1 — довесок Task 1.1b** (`59d22375`), закрыл 4 резидуала Fable-ревью Фазы 1:
- **G-5**: `ProcessCapabilities` получил строгий край (`missing` + `_read_list`) — последняя обёртка `protocol.py` вне контракта `missing`.
- **ingest_active**: `ingest_patterns` в `telemetry_snapshot`/`telemetry_history` — провенанс ПОКРЫТИЯ подписки, не только присутствия; докстринги честны.
- **Фикс 3** (`unknown_metric` live) — harness_smoke-тест, 3/3.
- **Фикс 4** — переформулирован ПО ЗАМЕРУ: живой `reached=0` недостижим через публичный API (адресная доставка publish — fire-and-forget, `_send_child_command` возвращает факт постановки в очередь, битое имя даёт `reached=1`). И посылка ревью (Fable), и первая ревизия были неверны. Тест стал характеризацией границы; BCTL-ADR-007 дополнен вторым экземпляром класса «плечо OFF недостижимо».

**Живой прогон webcam_sketch 2026-07-22** (память `project_live_findings_webcam_2026_07` обновлена, `ffa28a02`):
- Потеря never-drop **подтверждена до цифры**: `4205 − 1197 − 42 = 2966 = errors` (дельта-тождество 2/2), **64.5%** отправок PM теряется, устойчиво (~67 ошибок/с). Получатель — `gui`, шторм `state.changed` в переполненную never-drop системную очередь.
- **Открытый блокер #1 прошлого handoff РАЗРЕШЁН** (мнимое противоречие глубины очереди): глубина читается нормально — `introspect_router_stats("gui").channels.gui_system.queue_size = 60/100`. Ранний «0» — артефакт `introspect_queues` (под затором сам гибнет с «no channel resolved»). Надёжные инструменты под затором: sender `queue_system_evict_blocked` (потеря) + `router_stats.channels.<proc>_system.queue_size` (бэклог). **Это разблокирует фикс потери в `plans/transport-single-policy.md`.**
- Ценность Фазы 1 доказана вживую: все 12+ счётчиков RouterStats, аномалия `router_errors`, честный `introspect_failed`/`counter_missing` у неотзывчивого gui. Старый инструмент был слеп.

**Фаза 2 — санкционированный сплит, закрыта и отревьюена:**

| Task | Коммит | Суть |
|---|---|---|
| 2.1 | `1e8627e3` | вынос регистрового аппарата D.5 в `registers.py` (RegisterOps); driver.py 1645→1322 |
| 2.2 | `cbcfd868` | вынос диспетчеризации в `dispatch.py`; mcp_tools.py 1581→1249; `build_registry()` под `@lru_cache` |
| ревью | — | Reviewer(Opus): оба сплита побайтово бит-в-бит, lru_cache безопасен (5 потребителей read-only), инварианты D.5 сохранены; вердикт APPROVE |
| minor-фикс | `1965ba3b` | стейл-ссылка в докстринге `test_transport_guard.py` (единственная находка ревью) |

**Отклонение (принято, записано):** driver.py 1322 > цели Task 2.1 ≤1200. Причина — неудаляемая публичная API-поверхность (6 обёрток-делегатов + 2 back-compat property, ~70 строк; их зовут mcp_tools и тесты, Out-of-scope запрещает переименование). Цель ≤1200 добьётся при **отложенном выносе telemetry-блока** из driver.py (~135 строк, раздел «Отложено с блокерами: следующий рост фасада»). Не форсировать вынос несвязанного кода ради цифры.

## ⚠️ ВАЖНО для Фаз 3-6: номера строк в плане УСТАРЕЛИ после сплита

План писался до сплита. driver.py (1645→1322) и mcp_tools.py (1581→1249) сжались, часть кода переехала. **Перед любой Фазой 3-6 — re-grep, не доверять номерам плана:**
- **Record-handlers переехали `mcp_tools.py` → `dispatch.py`** (Task 4.2 приговор recorder'у ссылался на mcp_tools — теперь ищи в dispatch.py: `RECORD_HANDLERS`, `_record_*`, `_serve_replay`, `resolve_record_path`).
- `debug_session`/`debug_stop` (Task 4.1) — остались в `driver.py`, но номер ~1429 сдвинулся. `grep -n "def debug_session\|def debug_stop" backend_ctl/driver.py`.
- Регистровый аппарат (`_set_register_confirmed` и т.д.) — теперь `registers.py::RegisterOps`, не driver.py.
- Task 3.1 (`introspect.memory` RSS) — **framework**, `process_module/commands/builtin_commands.py` (`_cmd_introspect_memory`), сплитом НЕ затронут, но номер ~654 сверить.
- Task 3.2 (`effective_hz`) — `overview.py`, сплитом не затронут.

## Что делать дальше — Фаза 3 (конкретно)

Порядок из плана: `3.1 параллельно (framework-файлы); 3.2 после 2.2` (2.2 закрыт → 3.2 разблокирован).

1. **Task 3.1 — RSS в `introspect.memory`** (developer/Sonnet, **Layer: framework**): секция `os: {rss, vms, pid}` через psutil по своему pid, best-effort (нет psutil → None); `MemoryStats.os_memory` в protocol.py; упростить `g7_soak_probe._rss_mb`. Приёмка: live `introspect_memory("ProcessManager").os_memory["rss"] > 0` + unit с подменой импорта. Это закрывает дыру памяти `project_backend_ctl_gaps_2026_07` (introspect.memory не отдаёт RSS).
2. **Task 3.2 — `effective_hz` per-process в `system_overview`** (developer/Sonnet): пробросить из уже собираемого `introspect_status` в per-process сводку + аномалия `hz_degraded`. Приёмка: пара unit (аномалия срабатывает/молчит) + ответ под byte-cap на fake-своде 7 процессов.
3. **После Фазы 3 — живой прогон webcam_sketch** (требование владельца). NB: Фаза 2 была behavior-neutral (бит-в-бит), поэтому живой прогон после неё показал бы то же — не гонялся сознательно. Фаза 3 добавляет реальные сигналы (RSS, effective_hz) → живой прогон после неё осмыслен: проверить, что RSS>0 и hz виден на живой раскладке.

Дальше: Фаза 4 (приговоры `debug_session`/`debug_stop` — удаление; recorder — условный приговор с датой 2026-08-31), Фаза 5 (переформа fencing-теста в три плеча), Фаза 6 (live-тесты флагманских фич + доки + CAPABILITIES-regen — ПОСЛЕДНЕЙ).

## Грабли захода — не наступать снова

- **Субагенты офлоадят live-тесты в фоновый Monitor и виснут.** Developer Task 1.1b завис ДВАЖДЫ, ожидая Monitor-нотификацию, которая не приходила (он уже был приостановлен). Сработало правило «2 итерации → эскалация»: координатор забрал верификацию+коммит на себя. **В брифах исполнителям: гонять pytest СИНХРОННО, не через Monitor.** (Задавал явно teamlead'у 2.1 и developer'у 2.2 — они не спотыкались.)
- **Ревьюер (Fable) тоже подвержен «правдоподобное ≠ проверенное».** Его посылка «опечатка метрики → reached=0» оказалась эмпирически неверной (живой замер: reached=1). Требование live-ненуля для сигнала — верное, но КОНКРЕТНЫЙ способ его достичь надо проверять замером, а не принимать из ревью. Класс — память `feedback_plausible_is_not_verified`.
- **`pytest backend_ctl -q` собирает ВСЁ, включая live** (backend_ctl вне `testpaths`, в conftest нет deselect harness_smoke). Для чистого unit — **`-m "not harness_smoke"`**; для live — `-m harness_smoke` одиночным прогоном. Первый прогон захода смешал их и дал ложные «падения» (fencing + live).
- **sentrux `session_start` требует `scan` первым** («No scan data»). Для within-module рефактора скан дорогой — sentrux-дельту по Фазе 2 сознательно пропустил, полагаясь на тестовый+live якорь. Если нужна — сначала `mcp__sentrux__scan`.
- **MCP-сервер backend_ctl держит код на момент старта сессии.** Живой `system_overview` через MCP показал `missing`/`counter_missing` (Task 1.1, был в ветке до сессии), но НЕ показал бы G-5 довесок (`59d22375`, того же дня). Проверять свежайшие правки — перезапуском MCP-сервера или прямым `BackendDriver`.
- **Graceful-stop-debt жив:** `system.shutdown` погасил PM+сокет, но лаунчер/GUI висел ~30с (память `project_graceful_stop_debt`). Снял точечным `TaskStop` запущенного таска (не глобальный kill).

## Коммиты захода (ветка `fix/backend-ctl-proof-discipline`, в main НЕ влито)

```
1965ba3b docs(backend_ctl): стейл-ссылка после сплита (находка ревью Ф2)
cbcfd868 refactor(backend_ctl): вынести dispatch.py + кэш реестра (Task 2.2)
93ea56c7 docs(agent-memory): лессон teamlead back-compat property
1e8627e3 refactor(backend_ctl): вынести registers.py (Task 2.1)
ffa28a02 docs(memory): живой прогон 2026-07-22, потеря 64.5%, блокер снят
59d22375 fix(backend_ctl): довесок Task 1.1b (G-5 + ingest_patterns + Фикс 3/4)
5429436e docs(agent-memory): лессоны захода
```

## Merge в main

**Не влито сознательно.** Открытые вопросы до merge: план не закрыт (Фазы 3-6 впереди), `test_fencing_live` красный (снимет Task 5.1). Merge — по закрытии плана либо по явному решению владельца слить закрытые Фазы 1-2 раньше.
