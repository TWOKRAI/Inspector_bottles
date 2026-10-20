# L-9 остаток: стенд, окно inspector-bottles-07, 15:28-15:49
Деревья: head = l9-residual (a5485097a), control = l9-control (a5485097a + 4 файла из 12f7ae007, без pump_inbound). Оригинал stand_t53r2.py без правок, чистые прогоны без инструментации; tap-серия отдельно.
Зависание = stop_reply_s >= 4.5 или supervision `crashed` или `not reported/lost` в логах (verdict не используется: OK и у зависших).
Блоки: control s3 x5, head s3 x5, control s3 x5, head s3 x5; head s2 x5, control s2 x5; head s3 tap x3. Каталоги прогонов: head_s3_tap_r<N> (не tap_head_s3_r<N>).
Логи процессов каждого прогона: <run>/logs/, grep: <run>/grep.txt, время и загрузка: <run>/meta.txt.

## control s2: hung 0 of 5 | stop_reply_s min/max 0.812/1.032 | runs with 'not reported/lost': 0 | runs with 'did not stop in' (child): 0 (launcher-level: 0)
| run | reply_s | status after reply (+3 s) | lost | dns child/launcher | hung | time, load |
|---|---|---|---|---|---|---|
| r1 | 0.828 | stopped (stopped) | 0 | 0/0 | no | 15:43:42-15:44:20 cpu=42% ram=88% |
| r2 | 1.015 | stopped (stopped) | 0 | 0/0 | no | 15:44:21-15:44:53 cpu=16% ram=83% |
| r3 | 1.032 | stopped (stopped) | 0 | 0/0 | no | 15:44:54-15:45:28 cpu=15% ram=84% |
| r4 | 1.031 | stopped (stopped) | 0 | 0/0 | no | 15:45:29-15:46:02 cpu=61% ram=86% |
| r5 | 0.812 | stopped (stopped) | 0 | 0/0 | no | 15:46:04-15:46:39 cpu=62% ram=87% |

## control s3: hung 4 of 10 | stop_reply_s min/max 0.86/5.078 | runs with 'not reported/lost': 4 | runs with 'did not stop in' (child): 4 (launcher-level: 0)
| run | reply_s | status after reply (+3 s) | lost | dns child/launcher | hung | time, load |
|---|---|---|---|---|---|---|
| r1 | 0.985 | stopped (stopped) | 0 | 0/0 | no | 15:28:54-15:29:45 cpu=19% ram=84% |
| r2 | 0.922 | stopped (stopped) | 0 | 0/0 | no | 15:29:46-15:30:22 cpu=25% ram=85% |
| r3 | 5.062 | crashed (crashed) | 1 | 1/0 | YES | 15:30:23-15:30:55 cpu=25% ram=84% |
| r4 | 0.922 | stopped (stopped) | 0 | 0/0 | no | 15:30:57-15:31:29 cpu=16% ram=84% |
| r5 | 0.86 | stopped (stopped) | 0 | 0/0 | no | 15:31:31-15:32:04 cpu=16% ram=84% |
| r6 | 5.062 | crashed (crashed) | 1 | 1/0 | YES | 15:34:57-15:35:29 cpu=19% ram=81% |
| r7 | 5.062 | crashed (crashed) | 1 | 1/0 | YES | 15:35:30-15:36:03 cpu=16% ram=82% |
| r8 | 0.969 | stopped (stopped) | 0 | 0/0 | no | 15:36:05-15:36:36 cpu=18% ram=82% |
| r9 | 0.906 | stopped (stopped) | 0 | 0/0 | no | 15:36:37-15:37:10 cpu=16% ram=81% |
| r10 | 5.078 | crashed (crashed) | 1 | 1/0 | YES | 15:37:11-15:37:42 cpu=21% ram=81% |

## head s2: hung 0 of 5 | stop_reply_s min/max 0.937/1.078 | runs with 'not reported/lost': 0 | runs with 'did not stop in' (child): 0 (launcher-level: 0)
| run | reply_s | status after reply (+3 s) | lost | dns child/launcher | hung | time, load |
|---|---|---|---|---|---|---|
| r1 | 1.078 | stopped (stopped) | 0 | 0/0 | no | 15:40:51-15:41:25 cpu=24% ram=88% |
| r2 | 0.937 | stopped (stopped) | 0 | 0/0 | no | 15:41:27-15:41:58 cpu=17% ram=87% |
| r3 | 1.032 | stopped (stopped) | 0 | 0/0 | no | 15:41:59-15:42:32 cpu=25% ram=86% |
| r4 | 0.968 | stopped (stopped) | 0 | 0/0 | no | 15:42:34-15:43:07 cpu=16% ram=86% |
| r5 | 0.938 | stopped (stopped) | 0 | 0/0 | no | 15:43:08-15:43:41 cpu=24% ram=89% |

## head s3: hung 0 of 10 | stop_reply_s min/max 0.875/1.047 | runs with 'not reported/lost': 0 | runs with 'did not stop in' (child): 0 (launcher-level: 0)
| run | reply_s | status after reply (+3 s) | lost | dns child/launcher | hung | time, load |
|---|---|---|---|---|---|---|
| r1 | 0.922 | stopped (stopped) | 0 | 0/0 | no | 15:32:05-15:32:41 cpu=35% ram=86% |
| r2 | 0.875 | stopped (stopped) | 0 | 0/0 | no | 15:32:42-15:33:16 cpu=22% ram=84% |
| r3 | 0.985 | stopped (stopped) | 0 | 0/0 | no | 15:33:17-15:33:50 cpu=15% ram=83% |
| r4 | 1.047 | stopped (stopped) | 0 | 0/0 | no | 15:33:51-15:34:22 cpu=25% ram=82% |
| r5 | 0.922 | stopped (stopped) | 0 | 0/0 | no | 15:34:23-15:34:56 cpu=17% ram=81% |
| r6 | 0.875 | stopped (stopped) | 0 | 0/0 | no | 15:37:43-15:38:16 cpu=16% ram=82% |
| r7 | 0.984 | stopped (stopped) | 0 | 0/0 | no | 15:38:17-15:38:48 cpu=16% ram=81% |
| r8 | 0.953 | stopped (stopped) | 0 | 0/0 | no | 15:38:49-15:39:22 cpu=16% ram=81% |
| r9 | 0.984 | stopped (stopped) | 0 | 0/0 | no | 15:39:24-15:40:08 cpu=37% ram=78% |
| r10 | 1.047 | stopped (stopped) | 0 | 0/0 | no | 15:40:09-15:40:45 cpu=42% ram=85% |

## head s3 (tap): hung 0 of 3 | stop_reply_s min/max 0.875/1.062 | runs with 'not reported/lost': 0 | runs with 'did not stop in' (child): 0 (launcher-level: 0)
| run | reply_s | status after reply (+3 s) | lost | dns child/launcher | hung | time, load |
|---|---|---|---|---|---|---|
| r1 | 1.047 | stopped (stopped) | 0 | 0/0 | no | 15:47:01-15:47:41 cpu=31% ram=89% |
| r2 | 0.875 | stopped (stopped) | 0 | 0/0 | no | 15:47:42-15:48:17 cpu=14% ram=85% |
| r3 | 1.062 | stopped (stopped) | 0 | 0/0 | no | 15:48:19-15:48:53 cpu=18% ram=82% |
