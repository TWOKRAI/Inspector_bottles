# Стенд фазы А, синтетика gui_overload_synth — сырые числа (замер НЕ завершён)

Дерево gfp-integ-a (f56051a16), рецепт gui_overload_synth, боевой вход frontend/run.py с окном (GuiProcess, qt-probe 9142 жив). Сэмплер: 2026-11-24_stand-phase-a-synth-sampler.py (BackendDriver). Сырые jsonl рядом: *-run1-aborted, *-run2-aborted, *-run3-aborted.

## Прогон 1 (колонки: ступень, dt с, RSS gui МБ, ядра gui, frames_in/с, shown/с, superseded/с, max_frame_age_ms, pump_busy_share, qt_pending, shm_bytes_read МБ/с, frame_stale_drops, свободная RAM МБ)
```
S1 dt= 13.8 rss=  1014 cpu=0.30 in/s=  50.0 shown/s= 29.3 sup/s=  20.7 age= 21.1 busy=0.13 qp=0 shmMB/s= 222.3 stale=63 free=1548
S1 dt= 13.8 rss=  1019 cpu=0.24 in/s=  50.0 shown/s= 29.3 sup/s=  20.7 age= 22.1 busy=0.11 qp=0 shmMB/s= 222.0 stale=63 free=1514
```

## Прогон 2 (колонки: ступень, dt с, RSS gui МБ, ядра gui, frames_in/с, shown/с, superseded/с, max_frame_age_ms, pump_busy_share, qt_pending, shm_bytes_read МБ/с, frame_stale_drops, свободная RAM МБ)
```
S1 dt= 13.7 rss=  1027 cpu=0.25 in/s=  50.0 shown/s= 29.4 sup/s=  20.6 age= 20.5 busy=0.11 qp=0 shmMB/s= 222.4 stale=0 free=1885
S1 dt= 13.7 rss=  1027 cpu=0.25 in/s=  50.0 shown/s= 29.5 sup/s=  20.6 age= 20.7 busy=0.12 qp=0 shmMB/s= 222.5 stale=0 free=1920
S1 dt= 13.8 rss=  1027 cpu=0.25 in/s=  50.0 shown/s= 29.4 sup/s=  20.6 age= 20.8 busy=0.12 qp=0 shmMB/s= 222.8 stale=0 free=1845
S1 dt= 13.8 rss=  1027 cpu=0.25 in/s=  49.9 shown/s= 29.3 sup/s=  20.6 age= 21.0 busy=0.13 qp=0 shmMB/s= 221.7 stale=0 free=1873
S1 dt=  4.7 rss=  1027 cpu=0.31 in/s=  50.0 shown/s= 29.5 sup/s=  20.4 age= 28.7 busy=0.13 qp=0 shmMB/s= 221.3 stale=0 free=1770
S1 dt=  0.3 rss=  1027 cpu=0.41 in/s=  48.9 shown/s= 28.7 sup/s=  20.1 age= 28.7 busy=0.13 qp=0 shmMB/s= 255.8 stale=0 free=1770
S2 dt= 11.5 rss=  1027 cpu=0.30 in/s=  49.7 shown/s= 29.1 sup/s=  20.6 age= 39.0 busy=0.17 qp=0 shmMB/s= 220.5 stale=0 free=1663
S2 dt= 10.0 rss=  1027 cpu=0.24 in/s=  50.0 shown/s= 29.4 sup/s=  20.6 age= 21.7 busy=0.11 qp=0 shmMB/s= 222.4 stale=0 free=1979
S2 dt= 10.0 rss=  1019 cpu=0.23 in/s=  50.0 shown/s= 29.4 sup/s=  20.6 age= 27.0 busy=0.11 qp=0 shmMB/s= 222.5 stale=0 free=1913
S2 dt= 10.0 rss=  1015 cpu=0.26 in/s=  50.0 shown/s= 29.4 sup/s=  20.6 age= 22.2 busy=0.12 qp=0 shmMB/s= 222.5 stale=0 free=1810
S2 dt= 10.0 rss=  1015 cpu=0.24 in/s=  50.0 shown/s= 29.5 sup/s=  20.6 age= 21.5 busy=0.12 qp=0 shmMB/s= 222.5 stale=0 free=1906
S2 dt= 10.0 rss=  1020 cpu=0.25 in/s=  50.0 shown/s= 29.2 sup/s=  20.8 age= 83.5 busy=0.12 qp=0 shmMB/s= 222.5 stale=0 free=1945
S2 dt= 10.0 rss=  1015 cpu=0.27 in/s=  49.9 shown/s= 29.4 sup/s=  20.5 age= 31.4 busy=0.11 qp=0 shmMB/s= 222.5 stale=0 free=1859
S3 dt= 11.3 rss=  1015 cpu=0.27 in/s=  49.9 shown/s= 29.3 sup/s=  20.5 age= 32.2 busy=0.22 qp=0 shmMB/s= 221.3 stale=0 free=1813
S3 dt= 10.0 rss=   997 cpu=0.23 in/s=  50.0 shown/s= 29.4 sup/s=  20.6 age= 20.3 busy=0.10 qp=0 shmMB/s= 222.9 stale=0 free=1858
S3 dt= 10.0 rss=   992 cpu=0.25 in/s=  50.0 shown/s= 29.4 sup/s=  20.6 age= 20.0 busy=0.11 qp=0 shmMB/s= 222.5 stale=0 free=1939
S3 dt= 10.0 rss=   993 cpu=0.24 in/s=  49.8 shown/s= 29.2 sup/s=  20.6 age= 20.0 busy=0.12 qp=0 shmMB/s= 221.6 stale=0 free=1830
S3 dt= 10.0 rss=   997 cpu=0.25 in/s=  50.0 shown/s= 29.5 sup/s=  20.6 age= 20.8 busy=0.12 qp=0 shmMB/s= 222.5 stale=0 free=1882
S3 dt= 10.0 rss=   997 cpu=0.29 in/s=  50.0 shown/s= 29.4 sup/s=  20.6 age= 20.8 busy=0.13 qp=0 shmMB/s= 222.5 stale=0 free=1854
S3 dt= 10.0 rss=   997 cpu=0.24 in/s=  50.0 shown/s= 29.4 sup/s=  20.5 age= 20.8 busy=0.13 qp=0 shmMB/s= 222.5 stale=0 free=1875
S4 dt= 11.4 rss=   997 cpu=0.29 in/s=  49.8 shown/s= 29.1 sup/s=  20.6 age= 38.8 busy=0.13 qp=0 shmMB/s= 221.4 stale=0 free=1755
S4 dt= 10.0 rss=   997 cpu=0.26 in/s=  50.0 shown/s= 29.3 sup/s=  20.7 age= 21.1 busy=0.12 qp=0 shmMB/s= 222.5 stale=0 free=1567
S4 dt= 10.0 rss=   992 cpu=0.28 in/s=  50.0 shown/s= 29.4 sup/s=  20.6 age= 23.5 busy=0.14 qp=0 shmMB/s= 222.9 stale=0 free=1118
```

## Прогон 3 (колонки: ступень, dt с, RSS gui МБ, ядра gui, frames_in/с, shown/с, superseded/с, max_frame_age_ms, pump_busy_share, qt_pending, shm_bytes_read МБ/с, frame_stale_drops, свободная RAM МБ)
```
S1 dt= 10.0 rss=  1026 cpu=0.25 in/s=  50.0 shown/s= 29.4 sup/s=  20.5 age= 21.2 busy=0.12 qp=0 shmMB/s= 222.4 stale=6 free=1564
S1 dt= 10.0 rss=  1030 cpu=0.24 in/s=  50.0 shown/s= 29.3 sup/s=  20.7 age= 21.0 busy=0.11 qp=0 shmMB/s= 222.5 stale=6 free=1547
S1 dt= 10.0 rss=  1026 cpu=0.26 in/s=  50.0 shown/s= 29.4 sup/s=  20.6 age= 21.6 busy=0.18 qp=0 shmMB/s= 222.5 stale=6 free=1514
S1 dt= 10.0 rss=  1002 cpu=0.30 in/s=  50.0 shown/s= 29.4 sup/s=  20.6 age= 22.3 busy=0.15 qp=0 shmMB/s= 222.5 stale=6 free=1034
```

## Прогон 4 (рецепт как есть, 4 источника, 200 кадр/с, прогрев 30 с + 5 мин по 10 с; сэмплер sampler2, без стопа)
```
warm  dt=10.4 guiRSS= 1038 cpu=0.93 in/s= 192.6 shown/s= 94.9 sup/s=  97.4 age= 29.7 busy=0.54 qp=0 pend=2 held=7864320 shm= 792.0MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3287
warm  dt=10.0 guiRSS= 1035 cpu=1.03 in/s= 199.9 shown/s= 98.6 sup/s= 101.3 age= 26.2 busy=0.64 qp=0 pend=3 held=12529920 shm= 821.2MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3322
meas  dt=10.0 guiRSS= 1036 cpu=0.97 in/s= 199.7 shown/s= 98.3 sup/s= 101.5 age= 25.5 busy=0.52 qp=0 pend=2 held=7864320 shm= 817.2MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3236
meas  dt=10.0 guiRSS= 1033 cpu=0.95 in/s= 199.8 shown/s= 98.4 sup/s= 101.2 age= 47.8 busy=0.53 qp=0 pend=4 held=17195520 shm= 818.3MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3163
meas  dt=10.0 guiRSS= 1041 cpu=1.03 in/s= 197.8 shown/s= 97.4 sup/s= 100.4 age= 26.4 busy=0.51 qp=0 pend=4 held=17195520 shm= 810.9MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3020
meas  dt=10.0 guiRSS= 1040 cpu=0.90 in/s= 199.9 shown/s= 98.5 sup/s= 101.4 age= 24.9 busy=0.50 qp=0 pend=4 held=17195520 shm= 820.3MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3063
meas  dt=10.0 guiRSS= 1041 cpu=0.93 in/s= 200.1 shown/s= 98.7 sup/s= 101.4 age= 30.8 busy=0.51 qp=0 pend=3 held=12529920 shm= 820.4MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3320
meas  dt=10.0 guiRSS= 1041 cpu=0.90 in/s= 199.9 shown/s= 98.6 sup/s= 101.3 age= 22.4 busy=0.51 qp=0 pend=3 held=12529920 shm= 818.7MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3438
meas  dt=10.0 guiRSS= 1038 cpu=1.02 in/s= 200.0 shown/s= 98.2 sup/s= 101.8 age= 89.9 busy=0.52 qp=0 pend=3 held=12529920 shm= 819.6MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3462
meas  dt=10.0 guiRSS= 1032 cpu=0.90 in/s= 199.8 shown/s= 98.7 sup/s= 101.2 age= 25.7 busy=0.51 qp=0 pend=2 held=7864320 shm= 820.4MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3450
meas  dt=10.0 guiRSS= 1037 cpu=0.89 in/s= 200.0 shown/s= 98.4 sup/s= 101.5 age= 21.7 busy=0.51 qp=0 pend=3 held=12529920 shm= 819.6MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3457
meas  dt=10.0 guiRSS= 1034 cpu=0.90 in/s= 199.2 shown/s= 98.2 sup/s= 101.0 age= 22.1 busy=0.52 qp=0 pend=4 held=17195520 shm= 816.2MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3408
meas  dt=10.0 guiRSS= 1041 cpu=0.89 in/s= 200.0 shown/s= 98.5 sup/s= 101.5 age= 23.8 busy=0.51 qp=0 pend=4 held=17195520 shm= 820.5MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3444
meas  dt=10.0 guiRSS= 1040 cpu=0.90 in/s= 200.0 shown/s= 98.6 sup/s= 101.4 age= 24.8 busy=0.51 qp=0 pend=4 held=17195520 shm= 820.8MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3452
meas  dt=10.0 guiRSS= 1041 cpu=0.94 in/s= 200.0 shown/s= 98.7 sup/s= 101.3 age= 25.3 busy=0.56 qp=0 pend=3 held=12529920 shm= 819.1MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3462
meas  dt=10.0 guiRSS= 1041 cpu=0.97 in/s= 199.9 shown/s= 98.0 sup/s= 101.9 age= 30.0 busy=0.51 qp=0 pend=3 held=12529920 shm= 818.8MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3319
meas  dt=10.0 guiRSS= 1037 cpu=0.94 in/s= 199.9 shown/s= 98.3 sup/s= 101.6 age= 21.2 busy=0.52 qp=0 pend=3 held=12529920 shm= 819.5MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3252
meas  dt=10.0 guiRSS= 1037 cpu=0.99 in/s= 199.9 shown/s= 98.2 sup/s= 101.7 age= 27.7 busy=0.54 qp=0 pend=3 held=12529920 shm= 819.9MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3284
meas  dt=10.0 guiRSS= 1042 cpu=0.92 in/s= 199.1 shown/s= 98.2 sup/s= 101.0 age= 22.0 busy=0.52 qp=0 pend=3 held=12529920 shm= 817.1MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3332
meas  dt=10.0 guiRSS= 1041 cpu=0.92 in/s= 199.8 shown/s= 98.6 sup/s= 101.1 age= 23.7 busy=0.51 qp=0 pend=4 held=17195520 shm= 818.3MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3299
meas  dt=10.0 guiRSS= 1041 cpu=0.90 in/s= 200.0 shown/s= 98.5 sup/s= 101.6 age= 22.9 busy=0.51 qp=0 pend=3 held=12529920 shm= 819.2MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3444
meas  dt=10.0 guiRSS= 1046 cpu=1.06 in/s= 200.0 shown/s= 98.3 sup/s= 101.6 age= 31.3 busy=0.59 qp=0 pend=4 held=17195520 shm= 821.5MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3393
meas  dt=10.0 guiRSS= 1041 cpu=0.93 in/s= 200.1 shown/s= 98.5 sup/s= 101.6 age= 21.2 busy=0.54 qp=0 pend=3 held=12529920 shm= 819.6MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3271
meas  dt=10.0 guiRSS= 1037 cpu=0.94 in/s= 199.8 shown/s= 98.5 sup/s= 101.3 age= 21.1 busy=0.53 qp=0 pend=4 held=17195520 shm= 820.8MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3140
meas  dt=10.0 guiRSS= 1041 cpu=0.98 in/s= 200.0 shown/s= 98.7 sup/s= 101.3 age= 23.1 busy=0.52 qp=0 pend=3 held=12529920 shm= 819.6MB/s stale=0 mwdrop=0 torn=0 evict=0 free=2996
meas  dt=10.0 guiRSS= 1038 cpu=1.02 in/s= 199.8 shown/s= 98.7 sup/s= 101.1 age= 22.6 busy=0.53 qp=0 pend=3 held=12529920 shm= 819.1MB/s stale=0 mwdrop=0 torn=0 evict=0 free=2709
meas  dt=10.0 guiRSS= 1041 cpu=1.06 in/s= 199.3 shown/s= 98.2 sup/s= 101.0 age= 23.2 busy=0.54 qp=0 pend=4 held=17195520 shm= 816.2MB/s stale=0 mwdrop=0 torn=0 evict=0 free=2711
meas  dt=10.0 guiRSS= 1038 cpu=1.08 in/s= 199.9 shown/s= 98.6 sup/s= 101.5 age= 23.1 busy=0.56 qp=0 pend=3 held=12529920 shm= 819.2MB/s stale=0 mwdrop=0 torn=0 evict=0 free=2716
meas  dt=10.0 guiRSS= 1042 cpu=1.12 in/s= 199.8 shown/s= 97.7 sup/s= 102.1 age= 35.3 busy=0.50 qp=0 pend=3 held=12529920 shm= 818.8MB/s stale=0 mwdrop=0 torn=0 evict=0 free=2431
meas  dt=10.0 guiRSS= 1037 cpu=1.06 in/s= 199.9 shown/s= 98.4 sup/s= 101.4 age= 22.0 busy=0.54 qp=0 pend=4 held=17195520 shm= 820.0MB/s stale=0 mwdrop=0 torn=0 evict=0 free=2533
meas  dt=10.0 guiRSS= 1046 cpu=1.09 in/s= 199.9 shown/s= 98.1 sup/s= 101.8 age= 24.4 busy=0.52 qp=0 pend=4 held=17195520 shm= 819.5MB/s stale=0 mwdrop=0 torn=0 evict=0 free=2512
meas  dt=10.0 guiRSS= 1019 cpu=1.12 in/s= 199.9 shown/s= 98.4 sup/s= 101.5 age= 21.2 busy=0.54 qp=0 pend=4 held=17195520 shm= 819.1MB/s stale=0 mwdrop=0 torn=0 evict=0 free=2808
meas  dt=10.0 guiRSS= 1020 cpu=1.06 in/s= 200.1 shown/s= 98.4 sup/s= 101.7 age= 21.1 busy=0.53 qp=0 pend=4 held=17195520 shm= 820.8MB/s stale=0 mwdrop=0 torn=0 evict=0 free=3339
pre_frames {'gui': 861, 'ProcessManager': 741, 'devices': 171, 'camera_0': 169, 'camera_1': 169, 'camera_2': 169, 'camera_3': 168}
warm {'gui': 1038, 'ProcessManager': 741, 'devices': 172, 'camera_0': 210, 'camera_1': 205, 'camera_2': 204, 'camera_3': 203}
meas {'gui': 1020, 'ProcessManager': 723, 'devices': 170, 'camera_0': 204, 'camera_1': 208, 'camera_2': 201, 'camera_3': 201}
MEAS window dt 300.0 n 31 gui rss 1036 -> 1020 min/max 1019 1046
avg cpu 0.978 shown/s 98.37 in/s 199.79 sup/s 101.41 shm MB/s 819.0 age max 89.87909999996191 free min 2431
```
Панель FPS (qt_find_widget): 3 снимка, показано 100,0/98,0/98,0 с (camera_0 30,0/29,0, camera_1 30,0/29,0, camera_2 20,0, camera_3 20,0), вытеснено 101-102/с, Latency 19,0-21,0 мс.
RSS до кадров (run_start не отдан): gui 861, PM 741, devices 171, camera_0-3 168-169 МБ. Свежий python: 14; +numpy 27; +cv2 35; +pydantic 42; +PySide6.QtCore 49; +QtWidgets 53; +torch 559 МБ.

## Прогон 5 (дерево T5 gfp-t5-dev, тот же протокол, sampler3) против прогона 4 (до T5)
Метод: 31 замер meas по 10 с, дельты по timestamp. Сырое: ...-raw-4src.jsonl (до), ...-raw-t5.jsonl (T5).

| Метрика | прогон 4 (до T5) | прогон 5 (T5) |
|---|---|---|
| RSS gui до кадров / старт meas / конец / дрейф, МБ | 861 / 1036 / 1020 / −17 | 819 / 983 / 988 / +5 |
| gui ядер: среднее / окон >1,0 / максимум | 0,978 / 11 из 31 / 1,12 | 0,574 / 0 из 31 / 0,95 |
| shown/с суммарно (среднее; мин-макс) | 98,4 (97,4-98,7) | 98,5 (95,9-98,9) |
| панель FPS по слотам (снимки) | 30/30/20/20 и 29/29/20/20 | 30/28/20/20, 29/29/20/20, в конце 26/25/18/18 (87/с, вытеснено 90/с) |
| superseded/с | 101,4 | 101,3 |
| max_frame_age_ms: типично (медиана) / максимум / окон >150 | 23,7 / 89,9 / 0 | 21,4 / 69,8 / 0 |
| shm_bytes_read, МБ/с (среднее; мин-макс) | 819,0 (810,9-821,5) | 410,3 (399,5-412,5) |
| stale / torn / restore_failures | 0 / 0 / ключа нет | 0 / 0 / 0 |
| middleware_dropped | 0 | 0 |
| recv_middleware_count / send_middleware_count | не снято | 2 / 2 |
| pump_busy_share: среднее / мин-макс / окон >0,5 | 0,525 / 0,50-0,59 / 30 из 31 | 0,442 / 0,36-0,87 / 3 из 31 |
| qt_pending max; pending; bytes_held max | 0; 2-4; 17,2 МБ | 0; 0-4; 0 |
| свободная RAM, минимум (МБ) | 2431 | 1153 |
| RSS соседей конец vs до кадров | PM 723 (741), devices 170 (171), камеры 201-208 (168-169) | PM 742 (741), devices 173 (171), камеры 204-211 (169-170) |

Последние два окна T5: pump_busy 0,86-0,87, ядер 0,63-0,95, shown/с 98,1-95,9, свободная RAM 1667 и 1153 МБ. introspect_plugins gui: 66 плагинов каталога (по категориям processing/source/sink/...), failed_imports {}.

## Прогон 6 (повтор прогона 5 на gfp-t5-dev, свободная RAM перед стартом 4338 МБ; сырое ...-raw-t5-run2.jsonl)
31 замер meas: RSS gui 981 → 972 (−9), ядер 0,549 (макс 0,89, окон >1,0: 0), shown/с 98,45 (94,9-99,0), shm 410,1 МБ/с, age медиана 22,3 / макс 33,7, pump_busy 0,431 (0,35-0,85, окон >0,5: 6), stale/torn/restore 0/0/0, middleware_dropped 0, qt_pending 0, свободная RAM минимум 1469. Панель: 29/29/20/20 и 30/30/20/20, вытеснено 101-102/с.
Последние 2 окна (ядер / shown/с / age / busy / free): прогон 6: 0,76/97,8/23,6/0,53/1786 и 0,58/98,5/20,9/0,43/1760; прогон 5: 0,63/98,1/38,8/0,86/1667 и 0,95/95,9/27,1/0,87/1153; прогон 4: 1,12/98,4/21,2/0,54/2808 и 1,06/98,4/21,1/0,53/3339.
