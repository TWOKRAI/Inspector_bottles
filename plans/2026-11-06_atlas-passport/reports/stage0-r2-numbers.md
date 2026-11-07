# Stage 0 раунд 2 — числа для таблицы §3 пилота (для координатора)

Передано файлом по просьбе координатора; сам файл `docs/reports/2026-10-26_stage0-eval.md` лид полосы не правит.

Условия: 10 ревьюеров `reviewer` на `model: "sonnet"`, `MODE: plan`, по одному на Task (6.2, 6.2a, 6.2b, 6.2c — одним ревьюером на группу). Дерево — коммит 6de731784. Пилот «sonnet и opus дважды» в р.2 НЕ повторялся: только sonnet, один раз на Task. Opus не запускался.

| Task | вердикт р.2 | major | minor | вердикт р.1 |
|---|---|---|---|---|
| 4.1 (пилот №4) | APPROVED | 0 | 7 | CHANGES REQUESTED (sonnet и opus) |
| 4.2a (пилот №6) | CHANGES REQUESTED | 3 | 8 | CHANGES REQUESTED (sonnet и opus) |
| 4.4 | CHANGES REQUESTED | 1 | 6 | CHANGES REQUESTED |
| 4.4b | CHANGES REQUESTED | 2 | 10 | — (выделена из 4.4) |
| 1.2 | CHANGES REQUESTED | 2 | 7 | CHANGES REQUESTED |
| 6.2 + 6.2a/b/c (группа) | CHANGES REQUESTED | 4 (+1 вне группы, в 6.1) | 14 | CHANGES REQUESTED (6.2) |
| 7.2 | CHANGES REQUESTED | 5 | 5 | CHANGES REQUESTED |
| 7.2b | CHANGES REQUESTED | 6 | 8 | — (выделена из 7.2) |
| 7.3 | CHANGES REQUESTED | 5 | 11 | CHANGES REQUESTED |
| 7.3b | CHANGES REQUESTED | 4 | 6 | — (выделена из 7.3) |
| итого | 1 APPROVED / 9 CHANGES | 32 (+1) | 82 | |

Как считалось: по меткам `major`/`minor` в тексте вердиктов (`reports/*.review-r2.md`); где ревьюер не ставил метку (4.4: пп. 2–7 «minor», п. 1 «major»; 4.1: N1–N7 «minor»), счёт по его же заголовкам. Метки ревьюера, не лида.

Что НЕ измерено:
- real/noise в р.2 не размечены (в р.1 разметка была, noise = 0); выборочной проверки замечаний р.2 по коду лид не делал.
- Часть замечаний ревьюеры сами пометили «advisory» (не воспроизведены): ничего из них не запускалось.
- Сколько из замечаний р.2 новые (внесены правками р.1), а сколько пропущены в р.1 — не посчитано. Заметно по тексту: из 4.2a пп. 1–3, 7.2 пп. 1, 5, 6 — не упомянуты в р.1; из 4.4/4.4b — часть перешла из р.1 разрезом.
- `missed-by-both` (пропущено и sonnet, и opus) дописывается после ревью ветки и стенда — не сейчас.
