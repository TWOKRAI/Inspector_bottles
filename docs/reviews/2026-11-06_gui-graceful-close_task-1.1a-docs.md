# 1.1a docs-проход: порядок закрытия корня PM (tech-writer, 2026-11-06)

STATUS: DONE

## Изменённые места
- `app_module/orchestrator.py`, докстринг `_own_work`: было «СНАЧАЛА дети PM (super()) ... LIFO закрывает watcher'ы и SSM РАНЬШЕ детей» -> стало: super() кладёт только сводку; дети в `_own_work_late`; порядок закрытия work по ADR-PMM-040. Код не тронут.
- `process_module/README.md` (схема ~1015): после схемы добавлена оговорка, что схема для обычного процесса, а записи `_own_work_late` закрываются между `plugins-stop` и `workers`. Строка 7: в перечень точек наследника добавлен `_own_work_late` (ADR-PM-059).
- `process_module/DECISIONS.md`: ADR-PM-055 и ADR-PM-057 — только пометка «порядок уточнён ADR-PMM-040 / ADR-PM-059»; старый текст не переписан. Новый ADR-PM-059 в конце файла (контракт крюка).
- `process_manager_module/README.md` и `STATUS.md` — не менялись: порядок закрытия относительно `workers` там не описан (README:7 и STATUS:28-30 — про область `work/children`, это верно).

## sync / validate
- `python -m scripts.sync` — exit 0, файлов не изменил.
- `python scripts/validate.py` — 2 FAIL: «память: ошибки тегов», «память: индекс BY-MODULE*.md устарел». На чистом HEAD (git archive в scratchpad) те же 2 FAIL — до меня, к docs не относятся.

## Интерпретации
- Схему README ~1015 не переписывал: для обычного процесса она верна («plugins-stop первым» тоже). Добавил оговорку, не правку.
- Номер ADR-PM-059 взят как следующий после ADR-PM-058 (grep по дереву — занятых нет).

## Открыто / ненадёжно
- Утверждение ADR-PM-059 «единственный наследник с переопределением — ProcessManagerProcess» проверено только grep по `_own_work_late` в process_manager_process.py; полный перебор подклассов ProcessModule не делался.
- Хук doc-size-guard: `process_module/README.md` 74,8 КБ при бюджете 32 КБ — старый долг, не трогал.
- `process_module/DECISIONS.md` имеет старый ADR-PM-001..: шапка/оглавление не генерируется sync-ом, ручных правок в них нет.
