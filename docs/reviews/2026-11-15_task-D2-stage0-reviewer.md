# Task D2 — стадия 0, ревью брифа (MODE: plan)

Рецензент: reviewer. База: worktree r2-d2, HEAD a1996b24b. Код не правился, не коммитился.
Объём чтения: plan.md, tasks/D2.md, tasks/D2.acceptance.md, pid_registry.py (целиком), system_launcher.py:372-410,483,512,583,
runner/process_runner.py:355-370 (в брифе путь без `runner/`), backend_ctl/harness.py:57-61,390-410,460-510, app_module/env.py,
base_manager/utils/app_identity.py, tests/test_pid_registry*.py, test_f2_task27..., scripts/lifecycle_guards/{tables.py:401,g6.py}.

## Вердикт: CHANGES REQUESTED (стадия 0, итерация 1 из 2)

Опыты (scratchpad, ничего в дереве не менялось):
- Э1 `_reap_file` с логом из DESIGN п.5 «как написано»: жертвы pid 11050 и 11051, последняя запись реестра — мёртвый 999999 →
  лог `убит pid=999999 (python3.12)` дважды. Имя жертвы — `python3.12`, не `sleep`.
- Э2 две настоящие копии пакета (cp -R, 29 МБ каждая, импорт 0,7 с) через PYTHONPATH → разные `__file__`; сегодня обе дают одно имя
  `AppOne_system_pids.jsonl` (C1 красный до правки — достижимо). Копия-симлинк: `__file__` — ссылка, `.resolve()` → настоящий каталог worktree.
- Э3 реапер в цикле против процесса, пишущего себя в тот же файл: писатель убит (rc -9), реапер вернул killed=1; файл не повреждён (0 битых строк).
- Э4 macOS (регистронезависимая ФС): `Inspector_system_pids.jsonl` существует как `inspector_...`; `==` по имени False, `resolve()==` False, `samefile` True.
- Э5 `python -m scripts.lifecycle_guards check` на HEAD: 0 findings; в pid_registry.py ровно один `.kill()` (R4 allowlist count=1).

## Замечания (path:line → правка текста брифа)

1. [major, tests/spec] D2.md:34 (DESIGN п.5). `pid` в строке лога — утёкшая переменная цикла `for pid, ct in entries` (pid_registry.py:171);
   в цикле `for p in victims` (:184) её нет → лог называет pid ПОСЛЕДНЕЙ записи реестра (Э1). Тест с одной жертвой это скроет.
   Правка: п.5 переписать: «порядок: `name = p.name()` (try, иначе "?") → `p.kill()` → `killed += 1` → `log(f"... pid={p.pid} ({name})")` в отдельном try; ровно один вызов `.kill()` без аргументов
   (R4: tables.py:401 count=1, ратчет ловит и больше, и меньше)». В ACCEPTANCE добавить `python -m scripts.lifecycle_guards check` (0 findings).
   D2.acceptance.md:20 (C7): добавить «≥2 жертвы и последняя запись реестра — иной pid (мёртвый); каждая жертва названа своим pid в своей строке; pid последней записи не встречается ни в одной строке «убит»».
2. [major, tests] D2.acceptance.md:20 (C7) «имя процесса (`sleep`)». На Windows бинарника `sleep` нет, а процесс, записавший себя через `register_self`, — python (Э1: `python3.12`).
   Правка: «ожидаемое имя = `psutil.Process(pid).name()`, снятое тестом ДО реапа (ОС-оракул, не код под тестом); литерал `sleep` убрать».
3. [major, tests] D2.acceptance.md:6-8 (правила) — две дыры достижимости:
   а) подмена `tempfile.gettempdir` через monkeypatch не переходит в subprocess → C1/C3/C4 писали бы в настоящий temp. Добавить: «в env каждого subprocess — `TMPDIR`=`TEMP`=`TMP`=каталог теста»;
   б) «две копии пакета» — настоящие (`shutil.copytree(..., ignore=ignore_patterns("__pycache__","tests"))` из каталога текущего пакета, на этапе теста), НЕ симлинки: `_checkout_root` делает `resolve()`, симлинк-копии схлопнутся в один тег (Э2);
   в) живость жертвы мерить `Popen.poll() is None`, а не `psutil.pid_exists/is_running` (убитый, но не пожатый ребёнок — зомби, «жив»); таймаут subprocess с реапом ≥ 30 с (`psutil.wait_procs` ждёт до 3 с на зомби).
4. [major, spec — ГОНКА, пропущено] D2.acceptance.md после :23 добавить два критерия; D2.md п.7 — абзац в ADR «Остаточное».
   C9 (одновременный старт разных checkout). Копии A и B. Подготовка: в реестре A — живая «своя» жертва A-хвоста (через `register_self` из дочернего A), в реестре B — живая жертва B-хвоста.
   Два subprocess (A и B) стартуют по барьеру (файл-флаг) и делают `reap_and_reset(); register_self(); sleep`; 10 повторов. Ожидание за повтор: возврат каждого = 1 (убит ровно свой хвост);
   новая запись A и новая запись B живы (`poll() is None`); `_read_entries(A)` содержит только pid процесса A, `_read_entries(B)` — только pid B; все непустые строки обоих файлов разбираются как JSON.
   Красен до правки (общий файл), зелёный после. Инъекция: `tag=""` (константа) → красны C1, C3, C9.
   C10 (один checkout, два запуска одного приложения, КРИТЕРИЙ ГРАНИЦЫ). Инварианты, которые верны: нет исключений; каждая непустая строка файла — валидный JSON; в файле нет pid процесса чужого checkout.
   НЕ утверждать: «второй запуск не убивает первый» — это неверно (Э3), D2 этого не лечит. В ADR записать механизм: реестр не отличает «хвост прошлого запуска» от «живого параллельного запуска»;
   `register_self` между `_read_entries` и `_reset_file` (pid_registry.py:128-129, 157-203) стирается — потерянная запись, после жёсткого убийства сирота не будет реапнут.
   В пределах одного запуска перекрытия нет: `_prepare_pid_registry` (system_launcher.py:483/512) идёт до spawn детей.
   Эти два критерия кладутся в слепой файл, а не в REDS разработчика (REDS остаются 9 ≤ 10).
   Общее состояние, которое D2 НЕ покрывает (назвать в ADR одной строкой, проверка не проводилась): имена SHM (`_cleanup_shm_at_startup`, system_launcher.py:411+), порт backend_ctl, каталог логов.
5. [major, architecture] D2.md:31-33 (п.3-4) и plan.md:32 — остаточный межчекаутный путь убийства. `legacy_pid_file_path` (pid_registry.py:56-70) для любого приложения, кроме `inspector`,
   по-прежнему реапает И УДАЛЯЕТ `inspector_system_pids.jsonl` (:131-147). Этот файл пишет код до D4 — а старых worktree в `git worktree list` десятки; живой сосед на старой ветке теряет процессы при старте D2-checkout.
   Решение 4 закрывает только `MPF_APP_NAME=inspector` (на него ничего не ставит: launch.py:637 даёт «Inspector Bottles»). Правка текста брифа (минимум): в ADR записать как названную границу с причиной
   («реестр до D4: сосед на ветке до D4 не поддерживается»), и зафиксировать тестом C6b: приложение `AppOne`, `inspector_system_pids.jsonl` с живой жертвой → жертва убита, файл удалён (поведение «разовой миграции» явное, не случайное).
   Решение «не менять реапер легаси» переживает задачу — лид сообщает владельцу одной строкой (эскалации к cto не требуется, это ограничение скоупа плана, не конфликт).
6. [major, quality] D2.md:32 (п.4) — сравнение «имя совпадает с `_unscoped_default_name()`» строковое; на регистронезависимой ФС (Windows, macOS) `MPF_APP_NAME=Inspector` даёт `Inspector_system_pids.jsonl` ≠ `inspector_system_pids.jsonl` по `==`,
   но это один файл (Э4) → легаси не отсечётся и живой реестр D4-имени реапается. Правка: «сверять `os.path.samefile(legacy, Path(tempfile.gettempdir())/_unscoped_default_name())`, если оба существуют; иначе `os.path.normcase` имён»;
   тест (пропуск на регистрозависимой ФС): `MPF_APP_NAME=Inspector`, файл `inspector_system_pids.jsonl` с живой жертвой → после `reap_and_reset()` жива.
7. [minor, spec] Что C5 не доказывает: после D2 никто не читает `AppOne_system_pids.jsonl` вообще, поэтому C5 зелёный и без п.3-4. Доказательство п.4 несёт только C6 и `test_inspector_app_unscoped_file_is_not_legacy`.
   Правка: в брифе предсказания инъекций — «снять проверку п.4 → красны C6 и dev-тест `inspector`; C5 остаётся зелёным». C5 переименовать в «пин: файл D4-имени чужого приложения не тронут».
8. [minor, architecture] D2.md:27 (п.1) — шов `Path(multiprocess_framework.__file__)`: `__file__` может быть `None` (namespace/frozen) → `TypeError` из `pid_file_path()`
   (`clear()` вычисляет путь вне try, pid_registry.py:208). Правка: «если `__file__` пуст — тег от `str(Path(__file__).resolve().parent)` самого pid_registry; не исключение».
   Названные границы для ADR: macOS — `resolve()` не нормализует регистр (Э4), один checkout под двумя написаниями пути = два реестра (хвосты не реапнуты, но и чужих не убиваем);
   PyInstaller onefile (`version.py:46` и TECH_STACK_2026.md:323 допускают frozen) — `_MEIPASS` новый на каждый запуск → хвосты не реапаются никогда (не проверял на сборке).
   Добавить в ACCEPTANCE `sentrux check .`: п.1 вводит `import multiprocess_framework` из подмодуля (ребро к корню-фасаду) — не проверял, даст ли цикл.
9. [minor, spec] FILES (D2.md:41-48): добавить (а) `multiprocess_framework/docs/observability/NEW_MODULE_RECIPE.md:264-265` — фраза «pid-файл называется `<app>_system_pids.jsonl`» станет ложной;
   (б) в п.6 назвать `multiprocess_framework/docs/ADR_REGISTRY.md` (его пишет `scripts/sync`). Лиду (не subagent): `docs/claude/memory/project_concurrent_backends_trap.md:12-13` называет старое имя реестра.
   Номер ADR — следующий свободный на момент слияния (сейчас ADR-PMM-045 последний, DECISIONS.md:2477): файл общий с полосой Ф, при коллизии лид перенумеровывает, затем `python -m scripts.sync`.
10. [minor, quality] Дрейф ссылок: D2.md:11 `:150` → фактически :151; plan.md:12 `:119-160` → reap_and_reset 116-154, `_reap_file` 157-193; D2.md:14 `:56-73` → 56-70; D2.md:36 путь `process_runner.py` → `runner/process_runner.py`.
    REDS: дубль по смыслу — обновлённый `test_legacy_not_reported_when_it_is_the_current_file` и новый `..._inspector_app_unscoped_file_is_not_legacy`; развести: первый проверяет `legacy_pid_file_path() is None` и `pid_file_path() != legacy_file`, второй — что живая жертва файла пережила `reap_and_reset`.

## Ответы на вопросы

(1) Имя единообразно: PM считает один раз (system_launcher.py:403) и пишет в ОБЕ ручки (:404-405); дети идут через `register_self()` → `pid_file_path()` → env (process_runner.py:363-365); `clear()` на стопе — та же функция (:583-585).
    harness дефолт не использует: ставит свой `inspector_pids_harness_{pid}_{port}.jsonl` в обе ручки (harness.py:408-410) и чистит по подстроке `_harness_{pid}_{port}` (:502-504) — новое имя его не ломает;
    `test_pid_file_env_pair_matches_the_framework` сверяет только кортеж ключей. `git grep -n "_system_pids"`: читателей старого имени по имени нет — только pid_registry.py, его тесты и документы (DECISIONS.md:2340,2345 — история, не править; NEW_MODULE_RECIPE.md:265; app_identity.py:7 — историческая строка; память).
    Единственное место, где путь считается заново, — процесс, не унаследовавший env; он берёт ту же функцию и тот же тег, если импорт пакета идёт с того же пути.
(2) Шов верен для editable/PYTHONPATH (тег = откуда реально грузится код; Э2). Риски — замечание 8; «две копии» достижимы только как настоящие копии (замечание 3).
    Чужой путь пакета: worktree без PYTHONPATH с editable-установкой основного checkout импортирует основной пакет → тег основного; смоук приёмки должен печатать `multiprocess_framework.__file__` реального запуска.
(3) Дыры — замечания 5, 6, 7. (4) Гонка — замечание 4. (5) FILES/REDS — замечания 9, 10: REDS 7+2=9 ≤ 10; `process_manager_process.py`, `spawner.py`, `system_launcher.py` вне FILES — конфликта с полосой Ф по файлам нет;
    общий горячий файл — DECISIONS.md модуля. (6) R4-запись tables.py:401 не трогать, пока `.kill()` один (Э5); `scripts.sync` пишет ещё docs/ADR_REGISTRY.md; validate.py и sync не запускались.

## Что я не проверил / ненадёжно

- Ничего из gate не запускалось: `python scripts/validate.py` («≤ 2 ошибок памяти»), `python -m scripts.sync --check`, `sentrux check .`, тесты каталога process_manager_module — вывода нет.
- Windows-поведение выведено рассуждением, не прогоном (машина — macOS): `Path.resolve()` нормализует регистр, `sleep` отсутствует, зомби-семантика `psutil` иная.
- Порядок «`MPF_APP_NAME` ставится до `_prepare_pid_registry`» (launch.py:637 vs run) не прослежен до конца; на выводы не влияет (путь резолвится один раз и идёт детям через env).
- Общее состояние вне реестра (SHM, порт, логи) — только названо, глубина не изучалась. Заморозка PyInstaller — по двум упоминаниям в документах, не по сборке.
- Э3 показывает убийство живого писателя в одном файле, но не воспроизводит потерю записи между чтением и усечением — она следует из чтения кода.

---

# Раунд 2 (последний) — бриф ред. 2, коммит 001dc569b

Вердикт: APPROVED при трёх механических правках текста (A, B, C ниже) и трёх правках слепого файла (D, E, F); повторного круга они не требуют, проектных решений не меняют.

| № | Статус | Где |
|---|---|---|
| 1 pid в логе | закрыт | D2.md:36-37 (`p.pid`, порядок name→kill→killed→log, один `.kill()`); acceptance:22 (≥2 жертвы, хвостовой мёртвый pid) |
| 2 имя `sleep` | закрыт | acceptance:11,22; D2.md:69 |
| 3 TMPDIR/копии/poll | закрыт | acceptance:8-10 (copytree, не симлинк; TMPDIR/TEMP/TMP; poll()). Замер: реап жертвы-ребёнка теста = 3,03 с (зомби) |
| 4 гонка | закрыт с правками D-F | acceptance:25-27 (C9, C10); D2.md:40-41 (ADR б) |
| 5 легаси не-inspector | закрыт, согласован с решением лида | D2.md:19-20 (факт 7), :40 (ADR б), acceptance:21 (C6b), REDS:61 (пин) |
| 6 samefile | закрыт | D2.md:34-35; REDS:59. normcase-запасной ход почти недостижим (если легаси существует, samefile срабатывает) — безвреден |
| 7 C5 | закрыт | acceptance:19; предсказание инъекции — в файл лида, не в бриф |
| 8 `__file__ is None` | закрыт | D2.md:30-31 (`__path__[0]`, запасной корень). Придирки: запасной корень даёт НОВОЕ общее имя `<slug>_<тег "unknown-checkout">_...`, а не «прежнее»; деградация молчаливая |
| 9 FILES | закрыт кроме пути | NEW_MODULE_RECIPE (#5), номер ADR — ок; путь см. C |
| 10 дрейф | закрыт в D2.md | plan.md:12 всё ещё `:119-160` (стало 116-154); дубль REDS по смыслу словами не разведён |

Новые дыры: A) D2.md:65 `python scripts/lifecycle_guards` — argparse «required: command»; верно `python -m scripts.lifecycle_guards check` (на HEAD 0 findings).
B) D2.md:64 «sentrux check . — те же 2 нарушения»: на HEAD a1996b24b в r2-d2 вывод «43 rules checked… All rules pass», Quality 6900 (2 нарушения не воспроизведены) — написать «остаётся All rules pass».
C) D2.md:42,50: `docs/ADR_REGISTRY.md` не существует; файл — `multiprocess_framework/docs/ADR_REGISTRY.md` (git ls-files).
D) acceptance:25 `multiprocessing.Barrier` недостижим между независимыми `subprocess` с разным PYTHONPATH: оставить файл-сигнал (+ рукопожатие «готов» до сигнала).
E) acceptance:27 C10: код возврата −9 (убит соседом; воспроизведено) допустим, Traceback в stderr — нет.
F) acceptance:22: искать pid границей числа `(?<!\d)PID(?!\d)` (pid 1234 — подстрока 12345); C9: 10 повторов × (3,0 с реап + 0,7 с импорт) ≥ 37 с — снизить до 3 повторов либо задать общий таймаут ≥ 120 с.
REDS: новых 8 + 2 обновлённых = 10 ≤ 10 (+1 зелёный пин не считается). `test_case_insensitive_fs_same_file_is_not_legacy` красен до правки только если проверяет выживание жертвы при реапе; утверждение `legacy_pid_file_path() is None` на Windows зелёное и до правки.

Не проверял: кода D2 нет — эффект нового `import multiprocess_framework` из подмодуля на sentrux не оценён; validate.py и sync не запускались; Windows не запускался; C9/C10 не исполнялись (поведение выведено из чтения и замера на macOS).
