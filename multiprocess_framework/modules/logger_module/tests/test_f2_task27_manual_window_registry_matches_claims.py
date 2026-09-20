# -*- coding: utf-8 -*-
"""Task 2.7 плана observability-closure (добор ревью Ф1) — независимый тестер.

Критерий приёмки 3 (текст задачи, передан координатором; план
``phase-2-one-policy.md`` и реализация мне не показаны):

    «Сторож реестра REPLACED_MANUAL_WINDOWS: девятая ручная копия окна голоса,
    заведённая в файле, которого нет в _WATCHED, делает сторож КРАСНЫМ. Сегодня
    она проходит незамеченной. Расхождение "реестр 6 / комментарий 8" устранено —
    тест требует, чтобы число в реестре и число в заявлении совпадали, и падает
    при их расхождении.»

**Существующий сторож УЖЕ есть** —
``test_windowed_voice_injection_guards.py::TestTheManualWindowCountLivesInExactlyOnePlace``
— но его ``_WATCHED`` сознательно ограничен ТРЕМЯ файлами (``windowed_voice.py``,
``observability_config.py``, ``health/state.py``). Этот файл не дублирует его
(имена и текст ошибок разные, чтобы через месяц можно было отличить, что именно
нашло что), а расширяет ОХВАТ до заявления критерия: сканирует ВЕСЬ дерево
``multiprocess_framework`` — «нет ненаблюдаемых файлов» по построению, а не по
перечню.

## Число, которое я СЧИТАЛ САМ (а не взял из плана)

``grep -rniE "ручн.*копи|копи.*ручн" --include=*.py . | grep -v "tests[\\/]"`` из
корня ``multiprocess_framework/`` (ветка ``tests`` вычтена той же логикой, что у
``_scan_manual_copy_claims`` ниже — иначе счёт включает и этот файл, и соседний
узкий сторож) даёт РОВНО 5 строк с обоими стемами на одной строке; из них с
числительным-словом на ГРАНИЦЕ слова — РОВНО ОДНА:
``modules/router_module/core/router_manager.py:320`` — «а не из константы:
восемь ручных копий одного и того же 5.0 по дереву». Реестр
(``len(REPLACED_MANUAL_WINDOWS)``, прочитан напрямую) — 6. 8 != 6 — расхождение
РЕАЛЬНОЕ и живёт в БОЕВОМ файле (не в тесте, не в докстринге истории), не
требует инъекции, чтобы показать себя.

(Без границы слова тот же грep даёт на этой строке ЕЩЁ и ложное совпадение
«семь» — «восемь» СОДЕРЖИТ «семь» подстрокой (во-СЕМЬ-ь); сканер ниже требует
``\b`` вокруг числительного именно поэтому.)

(Отдельно, вне области этого теста и вне списка ``Files`` задачи: та же ошибка
«восемь» повторена в ``docs/claude/memory/project_observability_closure_progress.md:72``
— это НЕ ``.py``-файл фреймворка и НЕ упомянут в ``Files`` задачи 2.7, поэтому
не входит в сканируемое дерево ниже; называю в отчёте координатору отдельно.)

## Почему матчер требует ОБА стема на одной строке, а не только «ручн»

Первая версия матчила только стем ``ручн`` (методология узкого сторожа) и ловила
ЛОЖНЫЕ срабатывания — собственный докстринг узкого сторожа
(``test_windowed_voice_injection_guards.py:284``: «...вручную минимум семь раз»
при шести перечисленных...») ЦИТИРУЕТ старые (уже исправленные) редакции как
ИСТОРИЮ бага, а не заявляет текущее число. Требование «``копи`` НА ТОЙ ЖЕ
СТРОКЕ» отсеивает этот класс (в цитате нет слова «копи» на строке с
числительным) и оставляет ровно тот же единственный боевой хит.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

import multiprocess_framework as _mpf
from multiprocess_framework.modules.logger_module.core.windowed_voice import (
    REPLACED_MANUAL_WINDOWS,
)

#: Числительные словом, которые могут заявлять число ручных копий. «Один/одна» —
#: сознательно не в списке (тот же довод, что у узкого сторожа: живёт в этих
#: текстах законно, например «ни одна не настраиваемая»).
_NUMERAL_VALUES = {
    "два": 2,
    "две": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "семь": 7,
    "восемь": 8,
    "девять": 9,
    "десять": 10,
}


def _framework_root() -> Path:
    return Path(_mpf.__file__).resolve().parent


def _scan_manual_copy_claims(root: Path) -> List[Tuple[Path, int, str, int, str]]:
    """Каждая строка ``*.py`` под ``root``, где на ОДНОЙ строке встречаются стем
    «ручн», стем «копи» И числительное-слово. Возвращает
    ``(файл, номер_строки, слово, значение, текст_строки)`` на каждое совпадение.

    Без ограничения списком файлов — это и есть расширение охвата сторожа до
    заявления критерия (пункт 3 задачи 2.7).

    **Каталоги ``tests`` пропускаются сознательно** — тем же доводом, что у узкого
    сторожа (``test_windowed_voice_injection_guards.py``, класс
    ``TestTheManualWindowCountLivesInExactlyOnePlace``): файлы про ЭТОТ САМЫЙ
    сторож/находку законно ЦИТИРУЮТ исторические (уже исправленные) числа как
    нарратив, а не заявляют текущее число. Без исключения этот же сканер,
    направленный на ``multiprocess_framework`` целиком, ловит СОБСТВЕННЫЙ
    докстринг этого файла (там для отчёта человеку названы и 6, и 7, и 8) —
    подтверждено прогоном при написании теста. Критерий задачи говорит про
    «боевой комментарий» (``router_manager.py``) — тесты вне этого класса.
    """
    hits: List[Tuple[Path, int, str, int, str]] = []
    for path in sorted(root.rglob("*.py")):
        if "tests" in path.relative_to(root).parts[:-1]:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            if "ручн" not in low or "копи" not in low:
                continue
            for word, value in _NUMERAL_VALUES.items():
                # Граница слова обязательна: «восемь» СОДЕРЖИТ «семь» как
                # подстроку (во-СЕМЬ) — без \b пара слов совпала бы на одной
                # строке и дала бы ложный второй хит на том же самом заявлении.
                if re.search(rf"\b{word}\b", low):
                    hits.append((path, lineno, word, value, line.strip()))
    return hits


class TestManualWindowCountAgreesEverywhereInTheTree:
    """Расширенный сторож: НИ ОДНА строка дерева не имеет права назвать число
    ручных копий, расходящееся с ``len(REPLACED_MANUAL_WINDOWS)`` — независимо от
    того, входит её файл в узкий ``_WATCHED`` соседнего теста или нет."""

    def test_every_manual_copy_claim_in_the_framework_tree_matches_the_registry(self) -> None:
        actual = len(REPLACED_MANUAL_WINDOWS)
        hits = _scan_manual_copy_claims(_framework_root())

        assert hits, (
            "сканер не нашёл НИ ОДНОГО заявления числа ручных копий во всём дереве — "
            "подозрительно пусто (см. инвентарь в докстринге модуля: ожидался как "
            "минимум router_manager.py:320); возможно, сканер сломан, а не находка чиста"
        )

        mismatches = [
            f"{path.relative_to(_framework_root().parent)}:{lineno} говорит «{word}» ({value}), "
            f"реестр REPLACED_MANUAL_WINDOWS называет {actual}: {text!r}"
            for path, lineno, word, value, text in hits
            if value != actual
        ]
        assert mismatches == [], (
            "число снятых ручных копий окна расходится между REPLACED_MANUAL_WINDOWS "
            f"(={actual}) и текстом дерева — узкий сторож _WATCHED (3 файла) этого не "
            "видит:\n" + "\n".join(mismatches)
        )

    def test_the_registry_itself_has_no_internal_duplicates(self) -> None:
        """Дополнительный факт про то же самое число: реестр — единственный источник,
        и он обязан быть внутренне непротиворечив (без дублей имён)."""
        names = [name for name, _task in REPLACED_MANUAL_WINDOWS]
        assert len(names) == len(set(names)), f"дубль имени в реестре: {names}"


class TestWidenedScanCatchesFilesOutsideTheNarrowWatchList:
    """Проверка МЕХАНИКИ широкого скана: ЛЮБОЙ файл с неверным заявлением обязан
    попасть в отчёт, а не только тот единственный, что сегодня реально нарушает
    (``router_manager.py``). Без этого широкий охват доказан одним удачным
    совпадением, а не общим свойством сканера.

    **Это не находка, а самопроверка инструмента** — фикстура заведомо зелёная:
    декой-файл существует только внутри ``tmp_path`` этого теста, поэтому
    сканер обязан его поймать по построению. Называю это прямо, а не выдаю за
    вторую находку (см. отчёт координатору).
    """

    def test_a_ninth_manual_copy_claim_in_an_unwatched_file_is_caught(self, tmp_path: Path) -> None:
        decoy_dir = tmp_path / "some_brand_new_module" / "core"
        decoy_dir.mkdir(parents=True)
        decoy_file = decoy_dir / "unrelated_mechanism.py"
        decoy_file.write_text(
            "# для нового держателя окна пришлось завести девять ручных копий, пока не подключили общий реестр\n",
            encoding="utf-8",
        )
        # Файл ЗАВЕДОМО не входит в узкий _WATCHED соседнего теста (тот видит
        # только 3 захардкоженных пути внутри БОЕВОГО дерева) — здесь он вообще
        # вне дерева фреймворка, что и моделирует «девятую копию в
        # ненаблюдаемом месте» буквально.

        hits = _scan_manual_copy_claims(tmp_path)

        matching = [h for h in hits if h[0] == decoy_file and h[2] == "девять"]
        assert matching, (
            f"широкий скан не заметил заявление в НЕвходящем в узкий _WATCHED файле "
            f"{decoy_file} — все найденные совпадения: {hits!r}"
        )
