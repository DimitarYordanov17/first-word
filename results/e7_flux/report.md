# e7_flux

432 clip-runs, 0 errors

| variant | S1+S3 e2e p50 / p95 | S1+S3 end-of-turn p50 | S2 cut-off rate | S4 end-of-turn p50 | S5 stopped | S5 stop p50 | S6 false stops |
|---|---|---|---|---|---|---|---|
| baseline | 1762 / 2064 | 642 | 6/126 | - | - | - | - |
| flux | 2021 / 2621 | 858 | 0/126 | - | - | - | - |

## S2 cut-off rate by pause length

| variant | 200 ms | 300 ms | 400 ms | 500 ms | 600 ms | 800 ms | 1000 ms |
|---|---|---|---|---|---|---|---|
| baseline | 0/18 | 0/18 | 0/18 | 0/18 | 3/18 | 0/18 | 3/18 |
| flux | 0/18 | 0/18 | 0/18 | 0/18 | 0/18 | 0/18 | 0/18 |
