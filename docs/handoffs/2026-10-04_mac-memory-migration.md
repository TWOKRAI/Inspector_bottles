# Переход Mac на канон памяти — инструкция

Для владельца и агента сессии на Mac. Решение владельца 2026-10-04: обе машины работают с одним каноном памяти `docs/claude/memory/`. Mac переходит позже, по команде владельца.

## Что изменилось на Windows (main, merge `6421c2560`)

- Канон памяти — `docs/claude/memory/` в git. Индекс `MEMORY.md` весит 7,2 КБ (было 33,5 КБ).
- Уроки разложены по пяти файлам `CRAFT-*.md` по триггеру. Индекс ведёт к каждому из 249 файлов за один переход.
- В архиве `_archive/` лежит 181 файл. Найти старое имя: `docs/claude/memory/_archive/INDEX.md`.
- Ручной записи в две копии больше нет. Локальная папка Claude Code стала кэшем канона.
- Личное (`user`) и машинное (`reference` этой машины) хранятся только в локальной папке и в git не попадают.
- Команды `/core:memory:*` берут путь из `memory_dir` в `.claude/modes/_stack.md`. Сейчас там `docs/claude/memory`.

## Шаги на Mac

1. Подтянуть main: `git pull`. Проверить, что `docs/claude/memory/MEMORY.md` весит около 7 КБ.
2. Не запускать `plugin doctor --fix` и `claude-kit upgrade --apply`, пока не закрыт хвост «баннер и doctor на `memory_dir`» (план Атласа, «Открытые вопросы»). Сейчас doctor вернёт `autoMemoryDirectory` на `.claude/memory`.
3. Сверить 36 файлов `.claude/memory/` с каноном. Ничего не копировать поверх, только через diff:
   ```bash
   for f in .claude/memory/*.md; do b=$(basename "$f")
     if   [ -f docs/claude/memory/$b ];          then cmp -s "$f" docs/claude/memory/$b || echo "DIFF $b"
     elif [ -f docs/claude/memory/_archive/$b ]; then echo "ARCHIVED $b"
     else echo "ONLY_MAC $b"; fi; done
   ```
   - `DIFF`: перенести в канонический файл только новые факты с Mac, руками. Канон — база.
   - `ARCHIVED`: файл ушёл в архив или слит. Если на Mac есть новые факты, дописать их в выжившего: он назван в `_archive/INDEX.md`.
   - `ONLY_MAC`: проектный урок добавить в канон и поставить ссылку в `MEMORY.md` или `CRAFT-by-module.md`. Личное оставить локально.
4. Переключить `autoMemoryDirectory` в `.claude/settings.local.json` на локальный кэш вне репозитория. Это та же схема, что на Windows. Затем заполнить кэш из канона: `cp docs/claude/memory/*.md <кэш>/` и `cp -R docs/claude/memory/_archive <кэш>/`. Личные файлы держать в кэше, их строки добавить в раздел «Только эта машина» в конце кэшевого `MEMORY.md`.
5. `.claude/memory/` больше не канон. Когда его уникальное содержимое перенесено, заменить папку на `README.md` с одной строкой «канон — docs/claude/memory/». Это делается отдельным коммитом с `Refs: plans/2026-10-04_atlas/plan.md`.
6. Проверка:
   ```bash
   PYTHONUTF8=1 python .claude/plugins/core/scripts/memory_lint.py --json --repo-root . docs/claude/memory
   ```
   Должно быть `dead-link 0`. Ещё одна проверка: `wc -c docs/claude/memory/MEMORY.md` даёт не больше 8192.

## Ловушки

- `cp` поверх затирает другую сторону молча: см. урок `feedback_dual_write_by_copy_destroys_the_other_side`. Сначала diff.
- `robocopy /MIR` и `rsync --delete` в кэш не использовать: они удаляют личные файлы.
- После каждого слияния памяти в main кэш обновляется так же: diff, потом копирование. Автоматики пока нет.
