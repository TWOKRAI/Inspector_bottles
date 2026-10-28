## Основной прогон: числа «ПОСЛЕ»

| сценарий | N | min | median | max | p99 | зависаний | not reported/lost | did not stop in | порог ПОСЛЕ | вердикт |
|---|---|---|---|---|---|---|---|---|---|---|
| S5 | 10 | 2.922 | 4.999 | 5.234 | 5.234 | 0 | 0 | 0 | рестарт < 5,0; выход дерева < 2,0 (10/10); activate < 5,0 | **FAIL** |

Причины FAIL:
- S5: shutdown #8 (run 1): 2.92 с >= 2.0
- S5: shutdown #9 (run 2): 5.17 с >= 2.0
- S5: shutdown #10 (run 3): 5.23 с >= 2.0
- S5: shutdown #11 (run 4): 5.22 с >= 2.0
- S5: shutdown #12 (run 5): 5.01 с >= 2.0
- S5: shutdown #13 (run 6): 5.06 с >= 2.0
- S5: shutdown #14 (run 7): 4.94 с >= 2.0
- S5: shutdown #15 (run 8): 4.98 с >= 2.0
- S5: shutdown #16 (run 9): 4.56 с >= 2.0
- S5: shutdown #17 (run 10): 4.95 с >= 2.0
