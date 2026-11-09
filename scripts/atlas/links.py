"""Индекс связей над фактами v2: кто использует символ, кто его вызывает, кто наследует, кто тестирует (Task 4.1).

Purpose: из `dict[str, FileFacts]` (ровно то, что отдаёт `scan(...).facts`: ключ — posix-путь файла от корня
    репозитория, значение — факты файла, включая поля v2 `defs`, `calls`, `test_defs`) строит индекс, который
    отвечает на вопрос «что известно о символе `путь::qualname`». Индекс считается заново при каждом вызове
    `build_links`, кэша нет (кэш `links` вне Task 4.1). Паспорт (Task 4.2a) читает только `Links.of`.
Public API: Links, build_links.
Stability: lite

Pre: `facts` — отображение путь -> `FileFacts`; файлы с `error` или `v2_error` вкладывают пустые списки и не мешают
    остальным. Пустой `facts` допустим. Модуль не читает диск и git, не импортирует `multiprocess_framework`,
    `Services`, `Plugins` (сторож R1) и не бросает на пустых или неполных фактах.
Post: `build_links(facts)` детерминирован: тот же `facts` -> тот же ответ `of`, порядок записей в разделах —
    по `(where, line)`. `Links.of(ident)` не меняет индекс.

Идентификатор `ident` = `"<путь>::<qualname>"`: `scripts/x.py::Cls.method`, `scripts/x.py::func`.
Символ без записи в `defs` файла -> `of(...) is None`.

Ответ `of(ident)` — словарь; ключи-разделы (пустой раздел — `[]`, не отсутствующий ключ, кроме `structural`):

  - `used_by` — импорты символа: файлы, чей `from <модуль> import <имя>` (или `import <модуль>` при
    обращении `m.<имя>`) указывает на файл символа. Запись: `{"where": "путь:строка", "how": "import",
    "scope": .., "enclosing": ..}`; `where` — файл-импортёр и строка импорта (`ImportRec.line`); `enclosing` у импорта —
    `"<module>"`.
  - `call_sites` — разрешённые вызовы (name-call) из `CallFact`: голое имя в своём файле; голое имя по
    from-импорту символа; `m.f()` по импорту модуля `m`; `self.m()` внутри класса символа. Запись:
    `{"where": "путь:строка", "how": "name-call", "scope": .., "enclosing": qualname, "same_file": bool}`;
    `same_file` — вызов в файле самого символа (F2). `enclosing` — ближайший def/class вызова.
  - `call_sites_unresolved` — число (int) вызовов с совпавшим именем, которые не отнесены ни к одному символу
    (`x.m()` по произвольному получателю): счётчик «не видно», а не список.
  - `subclasses` — наследники (`how: "import"`): классы, чей `DefFact.bases` называет символ-класс
    и чей файл его импортирует. Запись как у `used_by`, но `where` — `"путь:строка"` строки `class` наследника
    (`DefFact.line`), `enclosing` = qualname наследника.
  - `structural` — структурные двойники протокола/ABC: `{"required": [имена], "twins": [qualname с путём]}`
    или `None`. Обязательные имена — все неприватные (без `_` в начале) не-dunder методы класса-основы;
    меньше двух таких -> `None` (в ответе строка «слишком общий протокол» в ключе `note`). Двойник — класс
    с неприватным именем, имеющий все обязательные методы и НЕ наследующий основу. Раздел только у классов.
  - `tests` — тесты символа (`how: "test-body"`): функции из `test_defs`, в чьём теле символ назван
    (`CallFact.name` == имя символа) и чей файл импортирует файл символа. Запись:
    `{"where": "путь:строка", "how": "test-body", "scope": "test", "enclosing": qualname_теста}`; счёт тестов —
    `len(...)`.

Поле `scope` у каждой записи (кроме счётчика): `"test"`, если путь `where` совпал с `(^|/)tests/` или имя файла
`test_*.py`, `*_test.py`, `conftest.py` (шире `_TEST_FILE` A1: помощники внутри `tests/` тоже тест); иначе
`"prod"` (каталог `testing/` — поставляемые двойники, не тесты).

Что НЕ разрешается (граница «не видно» паспорта): вызовы и импорты по алиасу (`import m as x`, `from m import f
as g`); символы, видимые только через реэкспорт `__init__.py`; динамические вызовы (`getattr`, строки).
Такие вызовы в `call_sites` не попадают и в `call_sites_unresolved` не считаются.

Не входит: `bases` — цепочка основ с глубиной (Task 4.1b); `command_specs` (Task 4.2a).
"""

from __future__ import annotations

from scripts.atlas.scan import FileFacts

__all__ = ["Links", "build_links"]


class Links:
    """Индекс связей; создаётся `build_links`. Нейтральный каркас INTERFACE: пока ничего не знает."""

    def __init__(self) -> None:
        self._facts: dict[str, FileFacts] = {}

    def of(self, ident: str) -> dict | None:
        """Связи символа `"путь::qualname"` (разделы — в докстринге модуля).

        Pre: `ident` — строка вида `путь::qualname`.
        Post: символ найден в `defs` файла -> словарь разделов; не найден, или `ident` неверной формы -> None.
        Не бросает.
        """
        return None


def build_links(facts: dict[str, FileFacts]) -> Links:
    """Строит индекс связей по фактам файлов (`scan(...).facts`); без кэша, без чтения диска.

    Pre: `facts` — `{путь: FileFacts}`; пустой словарь допустим.
    Post: возвращает `Links`; на любых входных фактах не бросает.
    """
    return Links()
