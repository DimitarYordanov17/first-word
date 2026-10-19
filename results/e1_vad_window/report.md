# e1_vad_window

720 clip-runs, 0 errors

| variant | S1+S3 e2e p50 / p95 | S1+S3 end-of-turn p50 | S2 cut-off rate | S4 end-of-turn p50 | S5 stopped | S5 stop p50 | S6 false stops |
|---|---|---|---|---|---|---|---|
| baseline | 1819 / 2250 | 657 | 8/126 | 3001 | - | - | - |
| vad_0_4 | 1861 / 2311 | 505 | 10/126 | 3001 | - | - | - |
| vad_0_3 | 1808 / 2321 | 501 | 13/126 | 3001 | - | - | - |

## S2 cut-off rate by pause length

| variant | 200 ms | 300 ms | 400 ms | 500 ms | 600 ms | 800 ms | 1000 ms |
|---|---|---|---|---|---|---|---|
| baseline | 0/18 | 0/18 | 0/18 | 2/18 | 3/18 | 0/18 | 3/18 |
| vad_0_4 | 0/18 | 0/18 | 2/18 | 2/18 | 3/18 | 0/18 | 3/18 |
| vad_0_3 | 0/18 | 0/18 | 4/18 | 3/18 | 3/18 | 0/18 | 3/18 |
