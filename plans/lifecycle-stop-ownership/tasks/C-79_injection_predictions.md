# C-79 — прогноз инъекций (лид, записано до реализации и до прогона)

Наборы: A = test_blueprint_pick_nan_acceptance.py (N[distinct,same,fps,collector-nested,io_peek-in-list,in-list], W1 real_conflict_text, W2 nan_against_number, W3 nan_typed_against_number, T list_against_tuple, E[4], typed_wins),
H = test_blueprint_pick_nan_hazards.py (H1[as_is,pickled], H2, H3[depth,nan-vs-1.0,tuple], H4, H8i[as_is,pickled], H8ii), R9 = test_per_child_stop_window_acceptance.py -k nan-recipe.
Прогон A+H+R9. Если автор разобьёт H на другие имена — сверять по смыслу, расхождение называть. Расширения — журнал целиком.

| № | Инъекция | Свойство | Ожидаемые красные |
|---|---|---|---|
| I1 | убрать ветку NaN верхнего уровня | 1 | N[distinct,fps,collector-nested,io_peek-in-list,in-list], H1[pickled], H3[depth,tuple], H8i[pickled]; N[same], H1[as_is], H8i[as_is] зелёные (тождество) |
| I2a | убрать ветку dict | 2 | N[collector-nested,io_peek-in-list], H1[pickled], H3[depth] |
| I2b | убрать ветку list/tuple | 2 | N[in-list,io_peek-in-list], H3[depth,tuple] |
| I2c | убрать только tuple | 2 | H3[tuple] |
| I3 | NaN равен любому числу (or вместо and) | 3 | W2, W3, H3[nan-vs-1.0] |
| I4a | убрать type(a) is type(b) | 4 | T |
| I4b | убрать сравнение ключей | 4 | H2 |
| I4c | убрать сравнение длины | 4 | H2 |
| I5 | при конфликте вернуть extras | 5 | typed_wins |
| I6 | I13: снять перенос ключа STOP_WINDOW_KEY | 6 | R9[nan-recipe], H8i[as_is,pickled] |
| I7 | убрать if a is b | 7 | H4 |
| I8 | сменить слово в тексте реестра «негоден» | H8 | H8ii |
