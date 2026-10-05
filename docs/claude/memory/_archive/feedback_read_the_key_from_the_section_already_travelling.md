---
name: feedback-read-the-key-from-the-section-already-travelling
description: Новый ключ конфига читать из секции, которая УЖЕ едет к процессу, а не заводить свой — иначе его надо класть в каждой дороге сборки
metadata:
  type: project
---

Ф8.5 (2026-08-09). Спека предлагала завести плоский ключ `observability_documents` в
`proc_dict["config"]` и честно предупреждала о ловушке: конструкторов `BlueprintAssembler`
**два** — boot (`launch.py`) и switch (`orchestrator_hooks.py`). Забудешь второй — плоскость
исчезает после горячей смены рецепта, молча.

Решение оказалось дешевле спеки: ключ положен ВНУТРЬ секции `observability`
(`ObservabilityConfig.documents`) и читается из разрешённых слоёв
(`process_observability_layers(svc).resolve()["documents"]`). Секция уже едет к каждому
процессу обеими дорогами (`observability_app` = L1, `observability_override` = L2) —
поэтому **ассемблеры не правились вовсе**, и ловушка исчезла вместе с правкой.

**Why:** каждая новая точка раскладки конфига — это ещё одно место, которое можно забыть,
и забывается оно на редкой дороге (switch, hot-swap), где дефект не воспроизводится
тестами сборки. Ключ, приехавший внутри уже существующей секции, наследует все её дороги
даром. Побочная выгода: он автоматически становится настраиваемым рецептом (L2) и
командой (L3), и попадает в provenance.

**How to apply:** прежде чем заводить новый ключ `proc_dict`, спросить — есть ли секция,
которая УЖЕ доезжает туда, куда нужно, и чей смысл ключ разделяет. Если да, класть внутрь
неё и добавлять поле в её Pydantic-схему (без поля `model_dump(exclude_unset=True)`
**молча выбросит** ключ — extra-ключи схема принимает, но не хранит). Смежное:
[[feedback-defect-fixed-on-one-path-only]], [[feedback-config-delivery-shape-differs]],
[[feedback-model-copy-does-not-validate]].
