# Хендофф: transport-single-policy Ф4, шаги 0–2 — 2026-09-30

**Ветка:** `feat/qr-code-reader` (основная). **План:** [`phase-4-redesign.md`](../../plans/transport-single-policy/phase-4-redesign.md) — читать первым.
**Предыдущий хендофф:** [`2026-09-29_transport-f4-handoff.md`](2026-09-29_transport-f4-handoff.md).

## Состояние

| Task | Состояние | Где |
|---|---|---|
| 4.4 ссылка на кадр | **REQUEST_CHANGES, итерация 1 из 2**, не слита | ветка `feat/t44-frame-ref`, worktree `.claude/worktrees/t44-impl`, HEAD `ee5e269a` |
| 4.5 наблюдаемость | не начата | — |
| 4.6 cv_threads | ✅ слита `939be356` | `feat/qr-code-reader` |
| 4.7 один режим | не начата, ждёт 4.4 и 4.5 | — |

## Следующий шаг — 4.4, итерация 2

Дать developer (Sonnet, решение владельца: реализация Sonnet, проверка Opus) исправления по
[ревью](../reviews/2026-09-30_task-4.4-review.md) (лежит в ветке `feat/t44-frame-ref`):

1. **major 1:** в `PipelineExecutor._run_batch` перед `_send_results` положить view-тикеты батча в каждый выходной item
   (`SHM_VIEWS_KEY`). Тест — плагин, пересобирающий dict (шаблон — `scratchpad/rev44/repro44_exec.py`).
2. **major 2:** copy-then-check в `strip_and_write`: перед `_inputs_still_valid` копировать ndarray верхнего уровня с
   `not flags.owndata`. Тест — кроп 8×8 от view, перезапись после двери.
3. **minor 3–8:**
   - `on_send` снимает ссылки чужого owner;
   - докстринги (5 мест + `read_ref`);
   - единица счётчика у executor;
   - `_stale_drops` под lock;
   - `pack_images` возврат с маской;
   - дедуп в `remote_frame_source` до копии.

Потом:
- инъекции лида по двум новым свойствам + прогон старой матрицы (`scratchpad/inject44.py` — пути в scratchpad этой
  сессии, при утере восстановить по списку патчей в плане);
- ревью, итерация 2 — тот же reviewer;
- merge `feat/t44-frame-ref` → `feat/qr-code-reader`. Ветка отстаёт от основной на 4.6: сливать с `--no-ff`, конфликт
  возможен в `docs/sessions/*` (union).

## Ловушки

- **Стенд доказал только путь копии.** При флагах по умолчанию zero-copy выключен, `_shm_views` пуст: проверку
  executor'а и дверь отправки стенд не выполнял ни разу. В 4.7 (zero-copy всегда) — стенд с пиксельной меткой
  обязателен.
- **Хук пиксельной метки** (`scratchpad/hook44/sitecustomize.py`, основа — `fable_audit/hook`) ставит патч опросом:
  первые ~20 кадров идут без метки, отсюда ложный «чужой» кадр. Для приёмочного теста патчить синхронно. `PYTHONPATH`
  — только Windows-пути, иначе `sitecustomize` молча не грузится.
- **`cv_threads` и прочие extras-only ключи** пишутся в рецепте под `extras:`. Плоский ключ молча уходит в `metadata`
  (drift-guard `TestExtrasShorthandDriftGuard`).
- **CPU:** калибровать частоту тактов в покое (под нагрузкой завышение ~12 %) — учесть в 4.5.
- **QR-камера** `MV-ID3013PM-06M` (192.168.1.1) на аппаратном триггере DI_0: без импульса кадров нет. Для 60 fps —
  непрерывный режим в IDMVS (пока бэкенд держит прибор, IDMVS не подключится). Рецепт стенда: `scratchpad/qr_sdk_60.yaml`
  (`reader_sdk` → `consumer` без плагинов → `gui`).
- **Разрешения:** `git checkout --` и `rm -rf` в этой сессии отклонялись — откатывать через Edit или байтовой записью,
  новые папки вместо удаления.
- **В дереве чужие незакоммиченные файлы памяти** (`.claude/memory/*`, `.claude/agent-memory/tester/*`) — не
  стейджить. Моя запись `feedback_cv_threads_tuning.md` + строка в `MEMORY.md` тоже там, закоммитить вместе с ними.
- **Документация разошлась с окружением:** в venv cv2 **5.0.0**, в CLAUDE.md указан 4.13.

## Скрипты сессии (scratchpad `7aa18311…/scratchpad`, временные)

- `stand44.py` — стенд: пиксельная метка против счётчиков, env `PROCS`, `FABLE_DIR`.
- `stand46.py` — такты CPU по процессам при `cv_threads` N.
- `inject44.py`, `inject46.py` — матрицы инъекций.
- `mk_qr.py`, `qr_probe.py` — QR-стенд и проба состояния плагина.
- `prev/` — копия скриптов прошлой сессии: `cpu_truth.py`, `if_100_1080.yaml`, `fable_audit`.
