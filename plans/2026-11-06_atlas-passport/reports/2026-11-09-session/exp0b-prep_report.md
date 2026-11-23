# 3.1-prep: отчёт (опыт 0b, подготовка)

Worktree: /Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/atlas-3-1 (ветка feat/atlas-exp-0b от main a63f5cbc1).
Не коммитил. Живых прогонов не было, только --dry-run.

## Сделано
1. scripts/nav_bench/conditions/reference-only.json (по образцу map-only.json, набор ключей совпадает).
2. docs/arch-map/_bench/k0_reference.json на диске worktree, неотслеживаемый; размер 57 068 -> 56 341 байт.
   Оригинал для сверки: scratchpad/exp0b-prep/k0_reference.orig.json. Список вычеркнутого: scratchpad/exp0b-prep/struck.json.
3. Dry-run обоих условий: код 0 (полный вывод: scratchpad/exp0b-prep/dryrun.txt).
4. Тесты nav_bench: 74 passed.

## Вычеркнуто (3 записи; ревью E2: docs/reviews/2026-11-06_task-map-E2-review.md @930c5f2a3)
- F1: ConfigFileWatcher.spec.io `[{op: watches, path_expr: self._handler, line: 238}]` -> `[]`.
- F2: write_companion.spec.call_sites `[backend_ctl/probes/probe_5_11_r3_watcher_cost.py:77]` -> `[]`, call_sites_total 1 -> 0,
  line2 "использует меня 1" -> "использует меня 0". same_file_calls=1 оставлен (факт верный, скрыт был сам вызов).
- F7: IConfigObserver.spec.structural_matches (5 шт.: _TransportProbe, Check, _Release, Arrivals, RateSampler; total 8) -> `[]`,
  structural_total 8 -> null. IConfig->Config в IConfig.structural_matches оставлен.
Формат файла сохранён: json indent=1, ensure_ascii=False; пересборка нетронутого оригинала даёт байт-в-байт тот же файл.

## Бенч
- Копия k0 (repo_sha 1dc6c71b7): готовой нет. В $TMPDIR/nav_bench лежит только копия другого sha (35e68f3d5...), её не трогал.
  Копии соберутся при первом живом прогоне уже из правленого эталона: reference-only -> .../1dc6c71b7-aa996b301a, reference -> .../1dc6c71b7-200d2046f0.
- В архиве 1dc6c71b7 пути docs/arch-map нет (git ls-tree пуст): в копии единственный файл арх-карты — сам эталон.
- git status --porcelain: `?? docs/arch-map/` и `?? scripts/nav_bench/conditions/reference-only.json` (-uall: docs/arch-map/_bench/k0_reference.json). Tracked-правок нет. .gitignore не менял.
- Преддоказательство окружения: multiprocess_framework.__file__ = .../.claude/worktrees/atlas-3-1/multiprocess_framework/__init__.py.
- Тесты: gate light atlas-exp0b, `74 passed, 1 warning` (DeprecationWarning legacy_sync, не наш), код 75 не было.

## Что оставил открытым / ненадёжным
- «Вычеркнуть» понято как обнуление поля, а не удаление записи/цели. Выбор для F7: structural_total = null (как в фиксе ревью), не 0;
  для F2: call_sites_total = 0 и line2 переписан на 0 (иначе строка-сводка несла бы вычеркнутое). Если лид хотел другое (0 вместо null,
  оставить line2) — правка в трёх местах скриптом, 1 минута.
- F2 после правки говорит «вызовов 0» при том, что реальный вызов есть (observability_companion.py:275). Примечание в самом эталоне
  «0 не значит не используется» осталось. Q9 («кто пишет файл») этим эталоном по построению не отвечается.
- meta.note эталона по-прежнему гласит «сгенерировано скриптом; не править руками» — файл правлен руками. Не менял, чтобы не вводить
  в промпт лишний текст; результат 3.1 должен это отметить.
- Промпт бенча (общий для всех условий) велит ставить «sure», только если «opened that place yourself»; в reference-only код открыть
  нельзя, поэтому честный агент даст «unsure». Если score.py учитывает confidence в hits — «только эталон» будет занижен. Я score.py не
  открывал; проверить до go.
- Я не проверял, что неудаляемых следов F1/F2/F7 нет в других полях (grep по _handler, _TransportProbe, probe_5_11 — чисто, остальные
  совпадения _handler — имена методов register_*_handler).
