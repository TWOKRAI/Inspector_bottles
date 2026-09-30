> Часть плана [`transport-single-policy`](plan.md), Ф4 — [`phase-4-redesign.md`](phase-4-redesign.md) (факты, порядок задач).

### Task 4.8 — Отчёт о мощностях (черновик, 2026-09-30, декомпозировать после 4.5)
**Level:** Senior+ · **Assignee:** teamlead · **Layer:** backend_ctl + scripts
**Goal:** стенд (симулятор + рецепт) выдаёт ответ «хватит ли этой машины и если нет — что именно
докупить или разделить», а не «дропнуто N кадров». Цель владельца — [[project-capacity-planning-goal]]:
закладывать мощности в бюджет ДО покупки железа.

**Замысел (на полях 4.5, без новых счётчиков на горячем пути):**
1. **Бюджет кадра:** `1/fps` → по каждому этапу (транспорт, `queue_wait_ms`, `plugin_ms` каждого плагина,
   отправка) — доля бюджета и запас. Узкое место — этап с наименьшим запасом.
2. **Класс ограничения** по уже собираемым полям:
   - процесс держит ≈ 1.0 ядра, остальные свободны → упор в Python/GIL одного процесса → распараллелить
     этап или переписать горячий участок на другом языке;
   - все ядра машины заняты → железо (CPU) или разделение по машинам;
   - транспорт/байты SHM доминируют → пропускная способность памяти → меньше копий, меньше разрешение;
   - пейсер `late` при свободном CPU → камера/сеть.
3. **Экстраполяция:** прогон на 2–3 частотах (напр. 30/60/100 fps) → при какой частоте запас этапа
   уходит в ноль; «сколько ядер / машин нужно на целевую частоту».
4. **Форма результата:** таблица в отчёте стенда + вывод одной строкой («узкое место — плагин X,
   GIL-bound, 1 процесс; нужно 2 параллельных экземпляра или 2-й ПК»).

**Открыто:** GPU-нагрузка (ML-плагины) в полях 4.5 не учтена; сеть камер (GigE) — нет счётчика.

#### Решение владельца 2026-09-30: одна команда на любой машине, 4.8a — до 4.7

Замеры делаются на рабочем ноутбуке, а мерить нужно будет и другое железо (линия — Orin NX, Linux ARM). Поэтому
4.8 — это прежде всего **переносимый инструмент**, а не отчёт этого стенда. Разрез:

**4.8a — bench v0 (сразу после закрытия 4.5, до 4.7; ею же меряется эффект 4.7):**
`python -m scripts.capacity_bench [--profile quick|full] [--tests] [--baseline <sha>]`.
1. **Паспорт машины:** CPU (модель, ядра физ./лог.), частота, RAM, GPU, ОС, Python, cv2, commit — в шапку отчёта.
2. **Самопроверка часов CPU:** 2 с нагрузки на одно ядро; прибор обязан показать 1.0 ± 5 %, иначе отчёт помечен
   «CPU-числа на этой машине ненадёжны». Windows — `QueryProcessCycleTime` / `~MHz` (как `cpu_clock.py`),
   Linux — `/proc/<pid>/stat` (там счёт по времени точный, в отличие от тиков Windows).
3. **`--tests`:** быстрый радиус фреймворка — «сборка живая».
4. **Матрица стенда:** рецепты В РЕПОЗИТОРИИ (не во временных папках сессий; сейчас `if_100_1080.yaml` живёт
   только в scratchpad позапрошлой сессии), профиль quick: 480p25 и 1080p100 по 30 с; full: 480p/1080p × 25/60/100.
   По каждому процессу: fps, ядра снаружи и `state.cpu` изнутри, `plugin_ms`, `queue_wait_ms`, `transport_ms`,
   `pacer_late`, байты SHM, stale/torn.
5. **Отчёт:** `reports/bench/<host>_<дата>.{md,json}`; `--baseline <sha>` — A/B в одном окне (протокол стенда).
6. Портативность: без `winreg`/`ctypes` на Linux, без путей Windows; стенд-worktree и замок — по протоколу
   `feedback_shared_stand_and_tests_protocol.md`.

**4.8b — выводы (после 4.7):** бюджет кадра по этапам, класс ограничения, экстраполяция по частотам и строка-вывод
(пп. 1–4 выше).

---

### Task 4.8a — bench v0: декомпозиция (2026-09-30, вечер)
**Level:** Middle+ (Sonnet) · **Assignee:** developer; слепые тесты — tester (Sonnet); ревью — reviewer (Opus)
**Layer:** scripts · **Ветка:** `feat/t48a-capacity-bench` от `feat/qr-code-reader`
**Goal:** одна команда `python -m scripts.capacity_bench` на любой машине (Windows x86, Linux ARM) даёт отчёт
«паспорт + самопроверка часов + матрица стенда по процессам» в `reports/bench/`.

**Files (новые):** `scripts/capacity_bench/{__init__,__main__,passport,cpu_probe,matrix,recipe,fields,report,run_case}.py`,
`scripts/capacity_bench/recipes/stand.yaml` (закреплённая копия `backend/topology/inspection_full.yaml`),
`scripts/capacity_bench/README.md`, `scripts/capacity_bench/tests/`; строка `scripts/capacity_bench/tests` в
`testpaths` корневого `pyproject.toml`. `seed_stand45.py` удаляется (его заменяет `run_case.py`).

#### 4.8a — публичный API (контракт для слепых тестов)
1. `passport.collect_passport(repo: Path) -> dict` — ключи ровно: `host, cpu_model, cores_physical,
   cores_logical, freq_mhz, ram_gb, gpu, os, python, cv2, commit, commit_dirty`. Никогда не бросает: неизвестное →
   `None`. `commit` — полный 40-hex SHA HEAD репозитория `repo`; `commit_dirty` — есть ли незакоммиченные правки в
   отслеживаемых файлах. `gpu` — строка имени (через `nvidia-smi --query-gpu=name`), если `nvidia-smi` нет в PATH →
   `None`. `cores_logical == os.cpu_count()`.
2. `cpu_probe.ProcessCpu(pid)` — CPU **чужого** процесса снаружи: `.read_seconds() -> float` (CPU-секунды всех
   потоков с момента старта процесса), `.method: str` ∈ `{"cycles", "proc_stat", "psutil"}`. Windows → `cycles`
   (`QueryProcessCycleTime` / реестр `~MHz`), Linux → `proc_stat` (`/proc/<pid>/stat`, utime+stime / `SC_CLK_TCK`),
   иначе `psutil`. `ctypes`/`winreg` импортируются только внутри Windows-ветки.
   `cpu_probe.parse_proc_stat(text: str) -> tuple[int, int]` — (utime, stime) в тиках, поля 14 и 15; имя процесса
   (поле 2) может содержать пробелы и скобки — считать поля после ПОСЛЕДНЕЙ `)`.
   `cpu_probe.clock_selfcheck(seconds=2.0, tolerance=0.05, probe=ProcessCpu) -> dict` — запускает дочерний
   процесс с busy-циклом на одном ядре, меряет его через `probe` снаружи; ключи `measured` (ядра, float), `ok`
   (`abs(measured - 1.0) <= tolerance`), `method`. Дочерний процесс гарантированно завершён к возврату.
   `cpu_probe.py` и `run_case.py` не импортируют `scripts.*` — только stdlib и psutil (их запускают против
   чужого дерева, см. п. 7).
3. `matrix.cases(profile: str) -> list[tuple[int, int, int]]` — (высота, fps, секунды). `quick` →
   `[(480, 25, 30), (1080, 100, 30)]`; `full` → `480/1080 × 25/60/100`, 30 с, в порядке высота, затем fps.
   Иное имя → `ValueError`.
4. `recipe.render_recipe(height: int, fps: int, out_dir: Path) -> Path` — берёт `recipes/stand.yaml`, пишет
   вариант в `out_dir`. Высота 480 → камера 640×480, 1080 → 1920×1080, иное → `ValueError`. После записи
   перечитывает YAML и проверяет, что у камеры ширина/высота/`source_target_fps` равны запрошенным, иначе
   `RuntimeError` (затравка тихо не подставляла значения, если база менялась).
5. `fields.extract_fields(levels: dict) -> dict` — из ответа `introspect_telemetry(proc)["levels"]` формата
   `{"workers": {<worker>: {...}}, "state": {"fps", "cpu": {"cores"}, "plugin_ms": {..}, "shm": {..}}}`. Ключи
   результата: `hz` (= `state.fps`), `inner_cores` (= `state.cpu.cores`), `plugin_ms` (dict), `queue_wait_ms`,
   `transport_ms` (из того воркера, где поле есть; если в нескольких — максимум), `pacer_late` (сумма по
   воркерам), `shm` — только `bytes_written, bytes_read, bytes_mapped, stale_drops, torn_reads`. Отсутствующее →
   `None` (`plugin_ms` → `{}`), не бросает. Примеры входа — реальные ответы стенда `a0457ee8`:
   processor `workers.data_receiver.transport_ms=26.6`, `workers.pipeline_executor.queue_wait_ms=1097.9`,
   `state.plugin_ms={"color_mask": 11.5, "blob_detector": 1.9}`, `state.cpu.cores=1.69`, `state.fps=58.1`;
   camera `workers.source_producer_camera_service.pacer_late=456`, у него нет `queue_wait_ms`/`transport_ms`.
6. `report.write_report(result: dict, out_dir: Path) -> tuple[Path, Path]` — `<host>_<YYYY-MM-DD>.md` и `.json`
   (host — из `result["passport"]["host"]`, дата — сегодняшняя); если файл есть — суффикс `_2`, `_3`…, старый не
   перезаписывается. JSON — `result` как есть. Markdown: паспорт (с `commit`), строка самопроверки, по каждому
   кейсу таблица «процесс × поля». Если `selfcheck.ok` ложно — литерал `CPU-числа на этой машине ненадёжны`;
   если `tests` не `None` и `tests.rc != 0` — литерал `сборка не прошла тесты`. Схема `result`:
   `{"passport": {...}, "selfcheck": {...}, "tests": None | {"rc", "passed", "failed", "duration_s"},
   "profile": str, "cases": [{"height", "fps", "secs", "sha", "tree": "candidate" | "baseline",
   "total_ext_cores", "processes": {<имя>: {"ext_cores", **extract_fields(...)}}}]}`.
7. `run_case.py` — отдельный скрипт: `python <bench>/run_case.py --recipe R --secs N --port P --out J`, cwd и
   `PYTHONPATH` = меряемое дерево. Поднимает `backend_ctl.harness.BackendHarness` того дерева, 10 с прогрева, N с
   замера: снаружи `ProcessCpu` по pid каждого процесса рецепта, `system_overview`/`introspect_status` раз в 2 с,
   в конце `introspect_telemetry` → `extract_fields`. `h.stop()` в `finally`. Пишет JSON кейса в `J`.
8. CLI `python -m scripts.capacity_bench [--profile quick|full] [--tests] [--baseline <sha>] [--port 8775]
   [--out reports/bench] [--dry-run]`. Порт по умолчанию **8775** (8765/8766/8092 заняты соседями).
   `--dry-run` — паспорт, самопроверка, список кейсов, отчёт; стенд не поднимается. `--tests` — pytest по
   `multiprocess_framework/modules/shared_resources_module/tests`, `.../process_module/tests`,
   `scripts/capacity_bench/tests` (`-q`), итог в `result["tests"]`; падение тестов не отменяет замер.
   `--baseline <sha>` — `git worktree add --detach` во временный каталог, для каждого кейса сначала база, потом
   кандидат (текущее дерево), worktree удаляется в `finally`. Неизвестный профиль → rc 2 (argparse).

#### 4.8a — acceptance
- [ ] `python -m scripts.capacity_bench --profile quick --dry-run --out <tmp>` → rc 0 меньше чем за 20 с, в `<tmp>`
      появились `.md` и `.json`, в JSON `passport.commit` = `git rev-parse HEAD`, `cases` пуст, `selfcheck.ok` true.
- [ ] Самопроверка на этой машине: `measured` в 1.0 ± 0.05; с подменённым `probe`, завышающим на 20 %, — `ok`
      ложно и в отчёте литерал про ненадёжные CPU-числа.
- [ ] `ProcessCpu` на дочернем процессе: busy 2 с → 1.0 ± 0.05 ядра; `time.sleep` 2 с → < 0.05.
- [ ] `parse_proc_stat` на строке с именем `(python (x) y)` возвращает верные utime/stime.
- [ ] Модули пакета импортируются при `sys.modules["winreg"] = None` (имитация Linux).
- [ ] `render_recipe` — значения проверены по разобранному YAML; 720 → `ValueError`; испорченная база (нет поля
      разрешения) → `RuntimeError`, а не тихий файл.
- [ ] `extract_fields` на двух образцах выше даёт литералы; пустой dict → все `None`, `plugin_ms == {}`.
- [ ] Второй `write_report` в тот же день даёт `_2`, первый файл не тронут.
- [ ] **Живьём (лид, режим measure по протоколу стенда):** `--profile quick` на `.claude/worktrees/stand` даёт числа
      того же порядка, что и затравка на `a0457ee8` (processor 1080p100: `queue_wait_ms` ≈ 1100, `color_mask` ≈ 11.5);
      `--baseline a0457ee8` отрабатывает A/B и удаляет свой worktree.

**Out of scope:** выводы 4.8b (бюджет кадра, класс ограничения, экстраполяция); GPU-нагрузка и сеть камер;
управление `stand.lock` из инструмента (замок держит лид руками); Linux-прогон на реальном Orin.
