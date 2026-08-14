---
name: feedback-probe-liveness-is-not-render
description: "Три маркера живости qt-mcp-зонда доказывают дорогу, а не рендер — окно стенда «невидимо», рендер берётся только ref-грабом"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 00c91112-14e6-485e-a1b2-581d3c8c71a1
  modified: 2026-08-14T06:24:56.245Z
---

Строка `qt-mcp probe installed on localhost:9142` в логе, порт в LISTENING и ответ
`qt_list_windows` доказывают, что **дорога** qt-mcp жива. Рендер они не доказывают:
на GUI-стенде окно живёт «невидимым», поэтому `qt_snapshot` отдаёт `Widgets: 0`,
`qt_list_windows` с дефолтным `skip_hidden=true` отвечает «нет окон», а
`qt_screenshot(full_window=true)` падает с ошибкой `'image'`.

Рендер снимается **только ref-грабом**: `qt_find_widget` → `qt_screenshot(ref=…)`
возвращает настоящий кадр. Найдено ревью Task 2.3 `telemetry-stage6` (2026-08-14):
я закрыл чекбокс «рендер снят» тремя маркерами зонда, хотя сам кадр брал ref-грабом —
доказательство было верным, а названный маркер неверным.

**Why:** маркер живости транспорта и маркер результата — разные вещи; подменив один
другим, следующий прогон закроет чекбокс, ни разу не посмотрев на картинку. Ровно
тот же класс, что [[feedback-qt-mcp-flag-value-is-compared-verbatim]], где рендер не
проверялся три раунда.

**How to apply:** в приёмке называть маркером рендера ref-граб и говорить, какая
вкладка на кадре. Маркеры зонда держать отдельной строкой как проверку дороги Т-4.
См. также [[feedback-single-marker-verdict-lies]], [[feedback-qt-mcp-smoke-verification]].
