---
name: feedback-commit-trailer-no-wrap
description: Commit-msg hook требует Why:/Layer: trailers на ОДНОЙ физической строке каждая — перенос строки внутри значения ломает парсер трейлеров
metadata:
  type: feedback
---

Trailer-строки (`Why:`, `Layer:`, `Refs:`, `Tested:`, ...) в commit-сообщении
ДОЛЖНЫ быть одной физической строкой каждая — никаких переносов внутри
значения, даже если текст длинный.

**Why:** `scripts/validate_commit/validate_commit.py::parse_message` определяет
"trailer-блок" как последний абзац (между пустыми строками), где ВСЕ строки
матчат `^([A-Z][A-Za-z\-]*): (.+)$`. Если `Why:`-значение перенесено на вторую
физическую строку (например ради читаемости `git log`), эта вторая строка не
матчит regex (не начинается с `Key: `) → весь абзац перестаёт считаться
trailer-блоком → hook падает с "Missing required trailers: ['Layer', 'Why']"
даже когда обе строки визуально присутствуют в сообщении. Наступил на эти же
грабли дважды подряд в одной сессии (2026-07-13, задача G.6) — commit
отклонялся, хотя Why/Layer выглядели написанными.

**How to apply:** при составлении commit-сообщения через HEREDOC — держать
`Why:`/`Layer:`/`Refs:`/`Tested:`/`Risk:`/`Reversible:`/`Rejected:` каждую
СТРОГО в одной строке, сколь угодно длинной. Если нужно сослаться на несколько
пунктов — перечислять через запятую внутри той же строки, не переносить.
Перед `git commit -F` можно быстро проверить парсером:
`python3 -c "import sys; sys.path.insert(0,'scripts/validate_commit'); import validate_commit as v; print(v.validate(open('msg.txt').read()).ok)"`
— дешевле, чем ловить commit-hook reject.

См. также [[project_commit_format]] (обязательные трейлеры Why/Layer, общее
описание hook'а).
