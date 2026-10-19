# e2_turn_detector

960 clip-runs, 0 errors

| variant | S1+S3 e2e p50 / p95 | S1+S3 end-of-turn p50 | S2 cut-off rate | S4 end-of-turn p50 | S5 stopped | S5 stop p50 | S6 false stops |
|---|---|---|---|---|---|---|---|
| baseline | 1822 / 2287 | 643 | 6/126 | 3001 | - | - | - |
| audio | 1993 / 3895 | 579 | 3/126 | 3001 | - | - | - |
| none | 1846 / 2335 | 577 | 76/126 | 577 | - | - | - |
| audio_own_defaults | 2142 / 3503 | 579 | 4/126 | 2501 | - | - | - |

## S2 cut-off rate by pause length

| variant | 200 ms | 300 ms | 400 ms | 500 ms | 600 ms | 800 ms | 1000 ms |
|---|---|---|---|---|---|---|---|
| baseline | 0/18 | 0/18 | 0/18 | 0/18 | 3/18 | 0/18 | 3/18 |
| audio | 0/18 | 0/18 | 0/18 | 1/18 | 1/18 | 1/18 | 0/18 |
| none | 0/18 | 1/18 | 7/18 | 14/18 | 18/18 | 18/18 | 18/18 |
| audio_own_defaults | 0/18 | 0/18 | 1/18 | 0/18 | 2/18 | 1/18 | 0/18 |
