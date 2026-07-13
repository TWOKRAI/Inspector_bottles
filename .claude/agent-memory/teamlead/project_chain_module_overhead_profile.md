---
name: chain-module-overhead-profile
description: ChainRunnable.execute несёт ~2µs/батч фикс-overhead — >45% на пустых плагинах, но <1.3% на реальной CV-работе; синтетический микробенч вводит в заблуждение
metadata:
  type: project
---

`ChainRunnable.execute` (chain_module) несёт фиксированный overhead ~2µs/батч:
ChainContext + ChainResult (dataclass'ы с default_factory-списками) + per-step
`_is_cross_process`/`_collect_side_results` (по 5 hasattr на шаг) — заложено под
CV-кадры (ms-масштаб), не под µs-дешёвый проход.

Замер C6(d) (bench в scratchpad, old list-loop vs chain-based):
- пустые синтетические плагины: throughput **-47%…-67%** (worst case overhead);
- реальная работа звена: 50µs/звено → **-1.25%**, 200µs → -0.36%, 1ms → -0.03%.

**Why:** микробенч на ПУСТЫХ плагинах преувеличивает overhead в разы и даёт
ложный «>5% blocker», хотя на настоящих CV-плагинах (сотни µs–ms) деградация
FPS <1.3%. Кроссовер под 5% наступает уже при мизерной работе звена.
**How to apply:** при C6(e) (пул worker_module) и любой обёртке chain вокруг
дешёвого payload — мерить на РЕАЛИСТИЧНОЙ работе звена, не только на пустышках;
не откатывать движок по синтетическому числу. Тело chain.py менять нельзя было
(скоуп = только type hints), поэтому overhead неустраним из адаптера —
fast-path (кэш ChainRunnable + пропуск pre-loop при отсутствии bypass) снимает
лишь часть. Прод-рецепты phone_sketch/hikvision headless не бутятся
([[hardware_recipes_no_headless_boot]]) — реалистичный synthetic-work бенч и есть
прокси для recipe-FPS.
