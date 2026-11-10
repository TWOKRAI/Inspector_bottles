# Форма `atlas map` (Task 4.2b-2): ключи, образцы, срез

Источник для `tasks/4.2b-2.md` (там DESIGN, FILES, REDS). Д1 - `docs/reports/2026-11-06_cto-atlas-path-verdict.md` §4; ключи
class|function|method - докстринг модуля `scripts/atlas/passport.py` (таблица ключей). Реестр - `modules_for(Tree(root, sha))`
(89 строк на `1dc6c71b7`; ключи строки: `id,layer,parent,paths,purpose,tier,docs`), не `load_modules()`.

## 1. Цель и конверт

- Цель (с `\` -> `/`): строка реестра с таким `id` -> `kind: unit`; иначе путь `.py` из `tree.oids()` вне `--exclude` -> `kind: file`;
  иначе код 2, stderr `atlas map: not found` (без значения входа). Каталог - `not found`. `kind` - вид вывода, не ключ строки.
- Конверт: `passport: 1`, `kind`, `id` (юнит - id строки; файл - путь), `path` (юнит - `paths[0]` как в реестре; файл - путь),
  `line: null`, `sha`, `scanner`. JSON - список из одного объекта (как `ref`).
- Члены юнита - файлы `.py` без `--exclude` с `modules.resolve(path, rows) == id` (вложенный юнит не входит). Prod -
  `links._scope(path) == "prod"` (приватный, тот же пакет, импорт как есть); test-файлы идут только в `checks.tests`.

## 2. Ключи шести разделов (постоянны, как у `ref`; значение для unit | file)

| ключ | unit | file |
|---|---|---|
| `purpose.text` | `purpose` строки реестра | `FileFacts.doc` (первая непустая строка докстринга модуля); без докстринга `""` и `doc_missing: true` (как 4.2a) |
| `purpose.declared_at`, `.called_from` | `null` | `null` |
| `purpose.called_from_more` | `0` | `0` |
| `interface.layer` | id юнита | `modules.resolve(path)` (`other` -> `"other"`, как 4.2a) |
| `interface.all` | `list(FileFacts.all)` у `init` (правило `frozen`), иначе `null`; нет кандидата `init` - в тексте `all: не искали`, кандидат без `__all__` - `—` | `null` |
| `interface.signature` | `null` | `null` |
| `interface.members` | `[{name: путь prod-файла, signature: null, where: "путь:1", top: [qualname без `_`], doc: FileFacts.doc или ""}]` | `[{name: qualname, signature, where}]`, верхний уровень, имена на `_` тоже |
| `links.used_by` | `[{name: id юнита-импортёра, where: min по (путь, строка), how: "import", count: число операторов}]` | то же, цель - файл (реэкспорт через `__init__` у файла не виден); импортёры вне самого файла и вне `__init__.py` его цепочки пакетов; импортёры своего юнита - группой с id своего юнита |
| `links.call_sites`, `subclasses`, `bases`, `structural`, `uses`, `call_sites_unresolved` | `null` | `null` |
| `runtime.threads`, `.io`, `.commands` | записи prod-файлов (как `_runtime`: `where`, поля записи) по `(путь, строка)`; `commands` - `[]`, если нет | то же по одному файлу |
| `runtime.processes` | `null` | `null` |
| `checks.findings` | `null` | `null` |
| `checks.tests` | `[{name: путь тест-файла, where: "путь:1", count: число test-функций файла}]` по `resolve`, только `count > 0` | `null` |
| `status.tier` | `tier` строки (`core`/`optional`, `None` -> `null`) | шапка файла `Tier:`, как у `ref` |
| `status.doc_missing` | `true`, если среди `docs` строки нет `README.md` (`docs: []` -> `true`) | `purpose.text == ""` |
| `status.dynamic` | сумма `command_specs_dynamic` по prod-файлам | `command_specs_dynamic` файла (без `call_sites_unresolved`) |
| `status.stale` | пути цели (prod-файлы, `used_by.where`, тест-файлы), правило 4.2b-1 | пути файла и `where` паспорта |
| `status.frozen` | шапки `init`: `paths[0] + "__init__.py"`, если `paths[0]` оканчивается на `/`; сам `paths[0]`, если он `__init__.py`; только если `init` есть в фактах, иначе `[]` (ред. лида 2026-11-10, ревью стадии 5 р.2) | цепочка файла (4.2b-1) |

- `top` юнита - верхний уровень `class`/`def` без `_`; `members` файла - то же с `_`; сигнатура - формат `reference._sig` (без `self`, `-> T` после скобок).
- `used_by`: операторы импорта (`scan.ImportIndex(facts).resolve(путь, запись)`, `status == "internal"`) в prod-файлах вне членов
  цели, у которых хотя бы одна цель - член юнита, ВКЛЮЧАЯ `__init__.py` (импорт через реэкспорт учитывается; `links.of` по `top`
  не годится: `links.py:48` реэкспорт не разрешает - на `process_module` 79 против 388 операторов). Группа по
  `modules.resolve(путь импортёра)`, `count` - число операторов; порядок `(-count, name)`.
- Порядок файлов юнита: `(-число таких операторов с целью в файле, путь)`.

## 3. Текст

`== <kind> <id> ==`; вторая строка `<path>; sha <sha>; scanner <scanner>` (без `:line`). Печатаются только ключи, у которых у `map`
есть источник; ключи, всегда `null` у `map` (`declared_at`, `called_from`, `signature`, `call_sites`, `subclasses`,
`bases`, `structural`, `uses`, `call_sites_unresolved`, `processes`, `findings`), - только в JSON. Пустое - `—`;
`links: найдено N (формы: import); не видно: динамика, аннотации, упоминания`, `N` = сумма `count`, строки «из продукта/из тестов» нет;
`used_by: K` - число групп. `status:` и `  stale:`, `  frozen:` - литералы 4.2b-1 п. 4, но `stale` при > 5 путях -
`  stale: a.py, b.py, c.py, d.py, e.py; ещё 3` (первые 5, JSON полный). Полный литерал юнита `u` (`paths: ["u/"]`, три prod-файла,
`u/__init__.py` с `__all__`, два импортёра `v` ×2 и `w` ×1, один тест-файл с 2 тестами; `--budget 22` - полный текст 23 строки, метка среза входит в бюджет, поэтому 1 член из 3; `<…>` - подстановка; ред. лида 2026-11-10: «2 из 3» при метке в бюджете недостижимо):

```
== unit u ==
u/; sha <sha>; scanner <scanner>
purpose: <purpose строки реестра>
interface: layer u
  all: A, B
  members:
    u/a.py — <doc члена>  (A, B)
    показано 1 из 3; все: --all members
links: найдено 3 (формы: import); не видно: динамика, аннотации, упоминания
  used_by: 2
    v — v/x.py:3 (import) ×2
    w — w/y.py:5 (import) ×1
runtime:
  threads: —
  commands: —
  io: —
checks:
  tests: 1
    u/tests/test_a.py — u/tests/test_a.py:1 ×2
status: tier core; doc_missing нет; dynamic —
  stale: —
  frozen: —
```
Текст члена юнита - ключ `doc` записи (`—`, если `""`). Файл без неприватного `top` - строка без скобок. Член файла: `  class ConfigFileWatcher  :196`; `  def load(path: str) -> Config  :40`;
`  async def run() -> None  :7`. `top` - до 6 имён через запятую, остаток `+N`.

## 4. Срез и бюджет

- `--budget N` (по умолчанию 60) - строки на цель. Минимум: строки образца п. 3 без записей списков, `purpose`, `status`/`stale`/`frozen`,
  по одной записи на непустой список, метки среза. Остаток - поровну вниз по спискам `members`, `used_by`, `tests`, `threads`, `io`
  (без приоритета; `_alloc` и `render_text` берут имена среза по `kind`: `MAP_SHOW_ALL`; `ref --all members` остаётся кодом 2).
- Метка `показано K из N; все: --all <раздел>`; `--all` (повторяемый): `members`, `used_by`, `tests`, `threads`, `io`; `--full` сильнее
  `--budget` и `--all`; JSON не режется. Не режутся `commands`, `frozen`, `stale` (кроме `ещё N`).
- Ориентир, не пин (прототип ревьюера): `config_module` - members 17, used_by 7 групп, tests 12 с `count > 0`, threads 2, io 1; `process_module` -
  331 файл, 64 prod, 13 групп; числа result - из реализации.
