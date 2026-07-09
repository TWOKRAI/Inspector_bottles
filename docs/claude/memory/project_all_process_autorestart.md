---
name: project-all-process-autorestart
description: "Авто-рестарт ВСЕХ процессов + уведомления упал/восстановился + chain-health. МЕХАНИЗМ-ЧАСТЬ ИСПОЛНЕНА Ф4-добор (8ac43361, ADR-PMM-015): default-on + supervisor-события. Хаб+chain-health → Ф5."
metadata: 
  node_type: memory
  type: project
  originSessionId: 82ad289c-65e8-4577-b5ec-2891866a2fd0
---

**МЕХАНИЗМ-ЧАСТЬ ИСПОЛНЕНА (2026-07-09, Ф4-добор, коммит 8ac43361, ADR-PMM-015).**
(1) **Default-on:** PM без `restart_policy` в конфиге строит `RestartPolicy(enabled=True)`
→ все non-protected процессы авто-рестартятся по умолчанию (было disabled; protected
gui/PM skip; per-process рецепт перекрывает; окно give-up Ф3.6 ловит crash-loop). Откат
`FW_AUTORESTART=0`. (2) **Громкие supervisor-события:** `ProcessMonitor._emit_supervisor_
event` → `processes.<name>.supervisor.{event,reason,attempt,at}` в StateStore (GUI) + лог;
события crashed/unresponsive/restarting(k/N)/gave_up(счётчик)/recovered. **recovered — по
возврату heartbeat** (не статус-переход: после рестарта prev=crashed не проходит промоушен).
Дедуп crash-loop = окно give-up (≤N restarting + одно gave_up). Live `test_autorestart_all_
live` (kill preprocessor БЕЗ policy → GREEN воскрешение+recovered; RED FW_AUTORESTART=0 →
мёртв). **ОСТАЁТСЯ на Ф5 (ObservabilityHub 5.15/5.16):** хаб-агрегация трёх сигналов
(ошибки/supervisor/stats) в одну GUI-панель + **chain-level health** (агрегат «конвейер
здоров/деградировал» + факт что данные ТЕКУТ, не только running) + нюансы (потеря in-memory
ML/калибровки при рестарте; лавина при смерти общей зависимости → depends_on 3.9). [[project-constructor-master-progress]]

**Идея владельца (2026-07-08):** сделать ВСЕ процессы конвейера автовосстанавливаемыми
(не только source/hub из G1) + уведомлять при падении/восстановлении. Логика: конвейер
работает только целиком — частичная живучесть = ложная надёжность.

**Оценка (согласована как направление, не запускать до Ф4-чата):**
- Механизм ГОТОВ (Ф3.6): политика per-process, окно N/T, give-up, health. Включить для
  всех = в основном конфиг, не новый код.
- **Риск маскировки багов СНЯТ решением владельца (2026-07-08): «громко ВСЕГДА».**
  Авто-рестарт везде БЕЗ dev/prod-флага — вместо этого каждый рестарт/падение громко
  уведомляет+логирует → баг не прячется даже при авто-рестарте (виден поток ошибок в GUI).
  Разные пороги give-up по типу (железо щедро, вычисление мало) — опционально оставить.
- **Единственная оговорка к «громко всегда» — дедупликация от crash-loop потопа:** не «тихо»,
  а счётчик — «процесс X упал ×47 за 30с → сдался» вместо 47 строк. Механизмы есть (throttle
  health-репортов, окно give-up Ф3.6) — применить на пути hub→GUI.
- Нюансы: потеря in-memory состояния при рестарте (прогрев ML-весов/калибровки → пауза
  в цепочке); лавина рестартов при смерти общей зависимости → пригодится depends_on (3.9 опц).

**АРХИТЕКТУРА (модель владельца = ObservabilityHub Ф5.15/5.16):** каждый процесс
ErrorManager+LoggerManager+StatsManager → общий ObservabilityHub (тег процесса на записи,
каналы errors/logs/stats) → GUI панель ошибок/сообщений. Три сигнала, один хаб, одна панель:
1. **Ошибки процесса** (ErrorManager) — «что сломалось».
2. **События супервизора** «упал/рестартится/восстановился/сдался» — «что с жизнью процесса»
   (переходы уже известны в process_monitor.py `_handle_dead_process`/`_try_auto_restart`/
   успешный рестарт — вывести отдельным событием в hub+UI).
3. **Chain-level health** — агрегат «конвейер здоров/деградировал/лежит» из per-process
   health + факта что данные ТЕКУТ (не только «running»). Иначе все зелёные, а кадров нет.

**Размещение:** механизм-часть (default-on авто-рестарт + громкое уведомление) — Ф3-добор/Ф4;
хаб + дедуп + chain-health — Ф5 (ObservabilityHub). Это материализация видения владельца
«модуль=устройство со своими выходами ошибок/статистики» в общую приборную панель. Связь: [[project-topology-fencing-token]],
[[project-constructor-master-progress]].
