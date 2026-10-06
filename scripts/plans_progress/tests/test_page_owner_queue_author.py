# ruff: noqa: E501  -- литералы-фикстуры и ожидания в одну строку
"""Тесты автора на внутренние опасности колонки «Очередь владельца» (Task 6.2: `aside#owner-queue` на странице).

Приёмку пишет независимый тестер (test_acceptance_page_owner_queue.py). Здесь — места, видимые по устройству:
ссылка идёт на якорь того `Plan`, что вернул `find_by_slug` (архивный дубль, архивный `b-plan` против живого
`2026-10-01_b-plan`), план вне ORDER и закрытый §4.3, экранирование заметки и ячейки плана, `\\|` в заметке,
задача закрытого плана, блок с CRLF, план без задач, хвост карточки в числах пункта-плана.

Страница строится CLI (`--html`, subprocess с timeout) на фикстуре из `tmp_path`; чип «в работе» — напрямую через
`to_html` с готовыми `Plan` (настоящий git здесь не нужен: его проверяет приёмка). Ожидания — литералы.
У каждого теста в докстринге названа охраняемая строка кода; проверено вписыванием обратного изменения.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "plans_progress.py"
_spec = importlib.util.spec_from_file_location("plans_progress_page_owner_queue_under_test", _MOD_PATH)
pp = importlib.util.module_from_spec(_spec)
sys.modules["plans_progress_page_owner_queue_under_test"] = pp
_spec.loader.exec_module(pp)

CALL_TIMEOUT = 120
BEGIN = "<!-- owner-queue:begin -->"
END = "<!-- owner-queue:end -->"
HEAD = "| # | План | Задача | Заметка |"
SEP = "|---|---|---|---|"


def plan_md(*tasks: tuple[str, str, str]) -> str:
    lines = ["# План", "", "- **После:** —", "", "## Порядок выполнения", ""]
    lines += [f"- Task {tid}: {title} [{status}]" for tid, title, status in tasks]
    return "\n".join(lines) + "\n"


def order_md(rows: tuple[str, ...], rows41: tuple[str, ...] = (), rows43: tuple[str, ...] = (), nl: str = "\n") -> str:
    """ORDER.md с §4.1, пустым §4.2, §4.3 и блоком очереди в конце; `nl` — перевод строки всего файла."""
    out = [
        "# Порядок работ и контроль планов",
        "",
        "## 4. Контроль планов",
        "",
        "### 4.1 Активные — в работе или следующие",
        "",
        "| План | Полоса | Статус | Следующий шаг |",
        "|---|---|---|---|",
        *[f"| [{n}](../{n}/plan.md) | Ж | статус | шаг |" for n in rows41],
        "",
        "### 4.2 Ждут триггера — не трогать до условия",
        "",
        "| План | Остаток | Триггер |",
        "|---|---|---|",
        "",
        "### 4.3 Закрыты или поглощены — кандидаты в `_archive/`",
        "",
        "| План | Факт |",
        "|---|---|",
        *[f"| [{n}](../{n}/plan.md) | DONE |" for n in rows43],
        "",
        BEGIN,
        HEAD,
        SEP,
        *rows,
        END,
        "",
    ]
    return nl.join(out)


def page_of(tmp_path: Path, files: dict[str, str], order: str) -> str:
    """Собирает дерево, зовёт `--html`, возвращает текст страницы."""
    root = tmp_path / "repo"
    for rel, text in {**files, "plans/queue/ORDER.md": order}.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
    out = tmp_path / "page.html"
    env = {**os.environ, "PYTHONUTF8": "1"}
    cp = subprocess.run(
        [sys.executable, str(_MOD_PATH), "--root", str(root), "--html", str(out)],
        capture_output=True,
        timeout=CALL_TIMEOUT,
        env=env,
        encoding="utf-8",
    )
    assert cp.returncode == 0, cp.stderr[:400]
    return out.read_text(encoding="utf-8")


def aside_of(page: str) -> str:
    start = page.index('<aside id="owner-queue">')
    return page[start : page.index("</aside>", start) + len("</aside>")]


def lis_of(page: str) -> list[str]:
    """Строки `<li …>…</li>` колонки по порядку (разметка колонки — по одному `<li>` на строку)."""
    return [ln for ln in aside_of(page).split("\n") if ln.startswith("<li ")]


# =========================================================================== якоря: тот Plan, что нашёл find_by_slug


def test_archived_duplicate_name_links_to_live_card(tmp_path):
    """Охраняет `anchors[id(plan)]` в `_owner_queue_html`: живой `a-plan` и архивный `a-plan` — две карточки.

    Пункт `a-plan` находит живой (живой раньше архивного): ссылка на `plan-a-plan`, числа живого (1 из 2),
    не `plan-a-plan-archive` и не числа архивного (1 из 1).
    """
    files = {
        "plans/a-plan/plan.md": plan_md(("1.1", "Первый", "DONE"), ("1.2", "Второй", "PENDING")),
        "plans/_archive/a-plan/plan.md": plan_md(("1.1", "Старый", "DONE")),
    }
    page = page_of(tmp_path, files, order_md(("| 1 | a-plan | | |",)))
    assert lis_of(page) == [
        '<li data-n="1" data-kind="plan" data-plan="a-plan"><a href="#plan-a-plan">a-plan</a> · <span class="tally">1 из 2 · 50%</span></li>'
    ]
    assert page.count('id="plan-a-plan"') == 1
    assert page.count('id="plan-a-plan-archive"') == 1


def test_archived_b_plan_beats_live_dated_name_and_links_to_its_own_anchor(tmp_path):
    """Охраняет выбор `Plan` и `anchors[id(plan)]`: `find_by_slug` берёт точное имя раньше имени с датой.

    Архивный `b-plan` и живой `2026-10-01_b-plan`: пункт `b-plan` -> архивный (точное имя), его якорь
    `plan-b-plan`, числа архивного (1 из 1), пункт закрыт (архив). Карта «слаг -> якорь живого» дала бы
    `plan-2026-10-01_b-plan`.
    """
    files = {
        "plans/2026-10-01_b-plan/plan.md": plan_md(("2.1", "Шаг Б", "PENDING"), ("2.2", "Шаг Б2", "PENDING")),
        "plans/_archive/b-plan/plan.md": plan_md(("1.1", "Старый", "DONE")),
    }
    page = page_of(tmp_path, files, order_md(("| 1 | b-plan | | |",)))
    assert lis_of(page) == [
        '<li data-n="1" data-kind="plan" data-plan="b-plan" data-closed="1"><s><a href="#plan-b-plan">b-plan</a> · <span class="tally">1 из 1 · 100%</span></s></li>'
    ]
    assert page.count('id="plan-b-plan"') == 1
    assert "Очередь владельца · открыто 0 из 1" in aside_of(page)


def test_unlisted_and_closed_43_plans_link_to_their_own_cards(tmp_path):
    """Охраняет `anchors[id(plan)]` для планов вне очереди §4.1: `d-plan` не в ORDER (`#unlisted`), `e-plan` в §4.3.

    Ссылки есть у обоих; карточка `d-plan` лежит в секции `unlisted`, `e-plan` — в `details#archive`.
    """
    files = {
        "plans/d-plan/plan.md": plan_md(("1.1", "Д", "PENDING")),
        "plans/e-plan/plan.md": plan_md(("5.1", "Э", "PENDING")),
    }
    page = page_of(tmp_path, files, order_md(("| 1 | d-plan | | |", "| 2 | e-plan | 5.1 | |"), rows43=("e-plan",)))
    assert lis_of(page) == [
        '<li data-n="1" data-kind="plan" data-plan="d-plan"><a href="#plan-d-plan">d-plan</a> · <span class="tally">0 из 1 · 0%</span></li>',
        '<li data-n="2" data-kind="task" data-plan="e-plan" data-task="5.1" data-closed="1"><s><a href="#plan-e-plan">e-plan</a> · <b>5.1</b> Э<span class="st">ожидает</span></s></li>',
    ]
    assert page.index('<section id="unlisted">') < page.index('id="plan-d-plan"') < page.index('<details id="archive">')
    assert page.index('<details id="archive">') < page.index('id="plan-e-plan"')


def test_plan_name_with_dot_links_to_sanitized_anchor(tmp_path):
    """Охраняет `anchors[id(plan)]` в `_owner_queue_html`: якорь не строится из имени плана.

    Слаг очереди допускает `.`, а `assign_anchors` заменяет символы вне `[A-Za-z0-9_-]` на `-`: у плана
    `v2.1-plan` карточка `plan-v2-1-plan`, ссылка `#plan-v2-1-plan`; `#plan-v2.1-plan` не ведёт никуда.
    """
    page = page_of(
        tmp_path, {"plans/v2.1-plan/plan.md": plan_md(("1.1", "Шаг", "PENDING"))}, order_md(("| 1 | v2.1-plan | | |",))
    )
    assert lis_of(page) == [
        '<li data-n="1" data-kind="plan" data-plan="v2.1-plan"><a href="#plan-v2-1-plan">v2.1-plan</a> · <span class="tally">0 из 1 · 0%</span></li>'
    ]
    assert page.count('id="plan-v2-1-plan"') == 1


# =========================================================================== экранирование и разбор ячеек


def test_note_and_plan_cell_are_escaped_in_text_and_attribute(tmp_path):
    """Охраняет `_e(...)` у `data-plan`, текста плана и `q-note`: `<`, `>`, `&`, `"` не попадают в разметку сырыми."""
    rows = ('| 1 | z&"q"<i> | | <script>alert(1)</script> & "n" |',)
    page = page_of(tmp_path, {"plans/a-plan/plan.md": plan_md(("1.1", "А", "PENDING"))}, order_md(rows))
    assert "<script" not in page
    assert lis_of(page) == [
        '<li data-n="1" data-kind="plan" data-plan="z&amp;&quot;q&quot;&lt;i&gt;" data-known="0">z&amp;&quot;q&quot;&lt;i&gt; '
        '<span class="chip warn" data-chip="queue-problem">⚠ в ячейке «План» нужно ровно одно имя плана, сейчас: z&amp;&quot;q&quot;&lt;i&gt;</span> '
        '<span class="q-note">— &lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;n&quot;</span></li>'
    ]


def test_escaped_pipe_in_note_stays_inside_the_note(tmp_path):
    """Охраняет `(?<!\\\\)` в `_queue_cells`: `\\|` не граница ячейки, в колонке — `до | после` одной заметкой."""
    page = page_of(
        tmp_path,
        {"plans/a-plan/plan.md": plan_md(("1.1", "А", "PENDING"))},
        order_md((r"| 1 | a-plan | | до \| после |",)),
    )
    assert lis_of(page) == [
        '<li data-n="1" data-kind="plan" data-plan="a-plan"><a href="#plan-a-plan">a-plan</a> · <span class="tally">0 из 1 · 0%</span> '
        '<span class="q-note">— до | после</span></li>'
    ]


def test_crlf_order_file_gives_the_same_column(tmp_path):
    """Охраняет разбор строк блока: ORDER.md с CRLF даёт ту же колонку (заголовок и два пункта), без `\\r` в разметке."""
    files = {"plans/a-plan/plan.md": plan_md(("1.1", "А", "DONE"), ("1.2", "А2", "PENDING"))}
    rows = ("| 1 | a-plan | 1.2 | первая |", "| 2 | a-plan | 1.1 | вторая |")
    page = page_of(tmp_path, files, order_md(rows, nl="\r\n"))
    assert "\r" not in aside_of(page)
    assert "<h2>Очередь владельца · открыто 1 из 2</h2>" in aside_of(page)
    assert lis_of(page) == [
        '<li data-n="1" data-kind="task" data-plan="a-plan" data-task="1.2"><a href="#plan-a-plan">a-plan</a> · <b>1.2</b> А2<span class="st">ожидает</span> <span class="q-note">— первая</span></li>',
        '<li data-n="2" data-kind="task" data-plan="a-plan" data-task="1.1" data-closed="1"><s><a href="#plan-a-plan">a-plan</a> · <b>1.1</b> А<span class="st">готово</span></s> <span class="q-note">— вторая</span></li>',
    ]


# =========================================================================== числа плана


def test_plan_without_tasks_shows_zero_of_zero(tmp_path):
    """Охраняет `_tally(plan.done, plan.total)` у пункта-плана: план без задач — `0 из 0`, без процентов."""
    page = page_of(tmp_path, {"plans/n-plan/plan.md": plan_md()}, order_md(("| 1 | n-plan | | |",)))
    assert lis_of(page) == [
        '<li data-n="1" data-kind="plan" data-plan="n-plan"><a href="#plan-n-plan">n-plan</a> · <span class="tally">0 из 0</span></li>'
    ]


def test_plan_item_tally_has_no_card_tail_for_deferred_task(tmp_path):
    """Охраняет `_tally(...)` без хвоста карточки: у плана с отложенной задачей число — только `done из total`.

    Хвост «отложено» бывает у `span.tally` карточки; в колонке его нет, а у пункта-задачи — `span.st` «отложено».
    """
    files = {"plans/a-plan/plan.md": plan_md(("1.1", "Раз", "DONE"), ("1.2", "Два", "DEFERRED"))}
    page = page_of(tmp_path, files, order_md(("| 1 | a-plan | | |", "| 2 | a-plan | 1.2 | |")))
    first, second = lis_of(page)
    assert (
        first
        == '<li data-n="1" data-kind="plan" data-plan="a-plan" data-closed="1"><s><a href="#plan-a-plan">a-plan</a> · <span class="tally">1 из 1 · 100%</span></s></li>'
    )
    assert (
        second
        == '<li data-n="2" data-kind="task" data-plan="a-plan" data-task="1.2" data-closed="1"><s><a href="#plan-a-plan">a-plan</a> · <b>1.2</b> Два<span class="st">отложено</span></s></li>'
    )
    assert "отложено" not in first


# =========================================================================== чип «в работе»: только открытые пункты


def _mem_plan(name: str, status: str, active: list[dict]) -> pp.Plan:
    p = pp.Plan(name=name, rel=f"plans/{name}/plan.md", archived=False, tier="queue")
    p.tasks = [pp.Task("1.1", "Шаг", status)]
    p.active = active
    return p


def _entry(branch: str) -> dict:
    return {"branch": branch, "worktree": "D:/wt", "sessions": 1, "agents": 2, "last_signal": "2026-10-03T11:55:00"}


def test_task_item_of_closed_plan_is_struck_and_has_no_active_chip(tmp_path):
    """Охраняет `not item["closed"]` перед `_active_chip` в `_owner_queue_html`.

    Закрытый план `z-plan` с записью `active` на карточке: пункт-задача его закрытой задачи зачёркнут и без чипа
    «в работе»; пункт открытого плана `y-plan` с такой же записью чип получает (контроль).
    """
    order = tmp_path / "ORDER.md"
    order.write_text(
        "\n".join([BEGIN, HEAD, SEP, "| 1 | z-plan | 1.1 | |", "| 2 | y-plan | | |", END, ""]), encoding="utf-8"
    )
    closed, opened = _mem_plan("z-plan", "done", [_entry("feat/z")]), _mem_plan("y-plan", "pending", [_entry("feat/y")])
    view = pp.build_queue_view([closed, opened], order)
    page = pp.to_html([closed, opened], [], tmp_path, owner_queue=view)
    first, second = lis_of(page)
    assert first.startswith('<li data-n="1" data-kind="task" data-plan="z-plan" data-task="1.1" data-closed="1"><s>')
    assert 'data-chip="active"' not in first
    assert 'data-chip="active" data-active="feat/y"' in second
    assert 'data-chip="active" data-active="feat/z"' in page  # чип закрытого плана на его карточке остался


def test_no_order_markers_gives_no_column_and_markers_without_table_give_problem(tmp_path):
    """Охраняет `build_queue_view`: нет ни одного маркера -> `None`; маркеры без таблицы -> проблема, а не `None`."""
    order = tmp_path / "ORDER.md"
    order.write_text("# нет блока\n", encoding="utf-8")
    assert pp.build_queue_view([], order) is None
    assert pp.build_queue_view([], tmp_path / "нет-файла.md") is None
    order.write_text(f"{BEGIN}\nпусто\n{END}\n", encoding="utf-8")
    assert pp.build_queue_view([], order) == {"problem": "в блоке нет таблицы с колонкой «План»", "entries": []}
