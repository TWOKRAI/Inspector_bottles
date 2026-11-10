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
| `interface.all`, `.signature` | `null` | `null` |
| `interface.members` | `[{name: путь prod-файла, signature: null, where: "путь:1", top: [qualname]}]` | `[{name: qualname, signature, where}]` |
| `links.used_by` | `[{name: id юнита-импортёра, where: первый "путь:строка", how: "import", count}]` | как у unit по символам файла |
| `links.call_sites`, `subclasses`, `bases`, `structural`, `uses`, `call_sites_unresolved` | `null` | `null` |
| `runtime.threads`, `.io`, `.commands` | записи prod-файлов (как `_runtime`: `where`, поля записи) по `(путь, строка)`; `commands` - `[]`, если нет | то же по одному файлу |
| `runtime.processes` | `null` | `null` |
| `checks.findings` | `null` | `null` |
| `checks.tests` | `[{name: путь тест-файла, where: "путь:1", count: число test-функций файла}]` по `resolve`, только `count > 0` | `null` |
| `status.tier` | `tier` строки | шапка файла, как у `ref` |
| `status.doc_missing` | `true`, если из `docs` строки нет файла в дереве | `purpose.text == ""` |
| `status.dynamic` | сумма `command_specs_dynamic` по prod-файлам | `command_specs_dynamic` файла (без `call_sites_unresolved`) |
| `status.stale` | пути цели (prod-файлы, `used_by.where`, тест-файлы), правило 4.2b-1 | пути файла и `where` паспорта |
| `status.frozen` | шапки `init = paths[0] + "__init__.py"`, только если `paths[0]` оканчивается на `/` и `init` есть в фактах, иначе `[]` | цепочка файла (4.2b-1) |

- `top` и `members` файла - верхний уровень `class`/`def`, имя не на `_`; сигнатура - формат `reference._sig` (без `self`, `-> T` после скобок).
- `used_by` юнита: `links.of("путь::qualname")["used_by"]` для символов `top`, записи `scope: prod` вне членов юнита,
  группа по `modules.resolve(путь импортёра)`; порядок `(-count, name)`.
- Порядок файлов юнита: `(-внешних prod used_by, путь)`.

## 3. Текст

`== <kind> <id> ==`; вторая строка `<path>; sha <sha>; scanner <scanner>` (без `:line`); шесть разделов с заголовками как у `ref`;
пустое - `—`, `null` - `не искали`; `status:` и строки `  stale:`, `  frozen:` - литералы 4.2b-1 п. 4, но `stale` при > 5 путях - `  stale: a.py, b.py, c.py, d.py, e.py; ещё 3` (первые 5 по порядку, JSON полный). Раздел `links` и прочие
ключи печатаются все, как у `ref` (`call_sites: не искали` и т. д.). Образец показывает ФОРМУ строк, не данные: `<…>` - подстановка,
числа и порядок берёт фикстура (RED 4 - временный репо из 3 файлов с литералами tester'а):

```
== unit config_module ==
multiprocess_framework/modules/config_module/; sha <sha>; scanner <scanner>
purpose: Управление конфигурациями в рантайме: схемы, контейнер, менеджер; сюда — менять загрузку и хранение конфигов
interface: layer config_module
  members:
    <путь файла> — <FileFacts.doc>  (<top через запятую>)    # файл без неприватного top - без скобок
    показано 1 из 17; все: --all members
links: найдено 20
  used_by: 7
    <id юнита> — <первый where: min по (путь, строка)> (import) ×<count>
    показано 1 из 7; все: --all used_by
```
Член файла: `  class ConfigFileWatcher  :196`; `  def load(path: str) -> Config  :40`; `  async def run() -> None  :7`. `top` - до 6 имён через запятую, остаток `+N`.

## 4. Срез и бюджет

- `--budget N` (по умолчанию 60) - строки на цель. Минимум: конверт, шесть заголовков, `purpose`, строки `status`/`stale`/`frozen`,
  по одной записи на непустой список, метки среза. Остаток - поровну вниз по спискам `members`, `used_by`, `tests`, `threads`, `io`
  (без приоритета; `_alloc` и `render_text` берут имена среза по `kind`: `MAP_SHOW_ALL`; `ref --all members` остаётся кодом 2).
- Метка `показано K из N; все: --all <раздел>`; `--all` (повторяемый): `members`, `used_by`, `tests`, `threads`, `io`; `--full` сильнее
  `--budget` и `--all`; JSON не режется. Не режутся `commands`, `frozen`, `stale` (кроме `ещё N`).
- Ориентир, не пин (прототип ревьюера): `config_module` - members 17, used_by 7, tests 12 с `count > 0`, threads 2, io 1; фиксированных
  строк 26, минимум 35, `--full` 68; `process_module` - 331 файл, 64 prod, 345 верхних символов, 13 групп. Числа result - из реализации.
