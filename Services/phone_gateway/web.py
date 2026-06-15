"""HTML-страница для телефона.

Самодостаточная (inline CSS+JS), без внешних ресурсов — телефону не нужен
интернет, только локальная сеть. Две независимые секции:
    ФОТО  — выбрать/снять и отправить (POST /frame, сырые байты картинки)
    СЛОВО — ввести и отправить (POST /word, текст UTF-8)

Картинка шлётся как raw body (fetch с Blob) — без multipart, поэтому на сервере
не нужен разбор форм (модуль cgi удалён в Python 3.13).
"""

from __future__ import annotations

_PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Инспектор — отправка с телефона</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, system-ui, "Segoe UI", Roboto, sans-serif;
         background: #14161a; color: #e7e9ee; -webkit-text-size-adjust: 100%; }
  header { padding: 18px 16px; background: #1d2026; border-bottom: 1px solid #2a2e36; }
  header h1 { margin: 0; font-size: 18px; }
  header p { margin: 4px 0 0; font-size: 13px; color: #9aa0ad; }
  .card { margin: 14px; padding: 16px; background: #1d2026; border: 1px solid #2a2e36;
          border-radius: 14px; }
  .card h2 { margin: 0 0 12px; font-size: 15px; color: #c9cdd6; }
  input[type=file], input[type=text] {
    width: 100%; padding: 14px; font-size: 16px; border-radius: 10px;
    border: 1px solid #3a3f4a; background: #0f1115; color: #e7e9ee; }
  button { width: 100%; margin-top: 12px; padding: 15px; font-size: 17px; font-weight: 600;
    border: none; border-radius: 10px; background: #3b82f6; color: #fff; cursor: pointer; }
  button:active { background: #2f6fd6; }
  .status { margin-top: 10px; font-size: 14px; min-height: 20px; }
  .ok  { color: #4ade80; }
  .err { color: #f87171; }
  .preview { margin-top: 12px; max-width: 100%; border-radius: 10px; display: none; }
  footer { padding: 10px 16px 26px; font-size: 12px; color: #6b7280; text-align: center; }
</style>
</head>
<body>
<header>
  <h1>Отправка на ПК-инспектор</h1>
  <p>Телефон и ПК в одной сети. Фото и слово отправляются отдельно.</p>
</header>

<div class="card">
  <h2>📷 Фотография</h2>
  <input type="file" id="photo" accept="image/*" onchange="showPreview()">
  <img id="preview" class="preview" alt="">
  <button onclick="sendPhoto()">Отправить фото</button>
  <div id="photoStatus" class="status"></div>
</div>

<div class="card">
  <h2>🔤 Слово / фраза (режим букв)</h2>
  <input type="text" id="word" inputmode="text" autocapitalize="characters"
         placeholder="например: РОБОТ или ДВА СЛОВА">
  <button onclick="sendWord()">Отправить слово</button>
  <div id="wordStatus" class="status"></div>
</div>

<footer>Инспектор · phone_gateway</footer>

<script>
function setStatus(id, text, ok) {
  var el = document.getElementById(id);
  el.textContent = text;
  el.className = "status" + (ok === true ? " ok" : ok === false ? " err" : "");
}
function showPreview() {
  var f = document.getElementById("photo").files[0];
  var img = document.getElementById("preview");
  if (!f) { img.style.display = "none"; return; }
  img.src = URL.createObjectURL(f);
  img.style.display = "block";
}
async function sendPhoto() {
  var f = document.getElementById("photo").files[0];
  if (!f) { setStatus("photoStatus", "Сначала выберите или снимите фото", false); return; }
  setStatus("photoStatus", "Отправка…", null);
  try {
    var r = await fetch("/frame", { method: "POST",
      headers: { "Content-Type": f.type || "image/jpeg" }, body: f });
    var j = await r.json();
    if (r.ok && j.ok) setStatus("photoStatus", "Готово: " + j.width + "×" + j.height + " px", true);
    else setStatus("photoStatus", "Ошибка: " + (j.error || r.status), false);
  } catch (e) { setStatus("photoStatus", "Сеть недоступна: " + e, false); }
}
async function sendWord() {
  var w = document.getElementById("word").value.trim();
  if (!w) { setStatus("wordStatus", "Введите слово", false); return; }
  setStatus("wordStatus", "Отправка…", null);
  try {
    var r = await fetch("/word", { method: "POST",
      headers: { "Content-Type": "text/plain; charset=utf-8" }, body: w });
    var j = await r.json();
    if (r.ok && j.ok) setStatus("wordStatus", "Принято: " + j.word, true);
    else setStatus("wordStatus", "Ошибка: " + (j.error || r.status), false);
  } catch (e) { setStatus("wordStatus", "Сеть недоступна: " + e, false); }
}
</script>
</body>
</html>
"""


def render_page() -> str:
    """Вернуть HTML-страницу для телефона."""
    return _PAGE
