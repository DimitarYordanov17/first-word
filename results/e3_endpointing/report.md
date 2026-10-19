# e3_endpointing

480 clip-runs, 0 errors

| variant | S1+S3 e2e p50 / p95 | S1+S3 end-of-turn p50 | S2 cut-off rate | S4 end-of-turn p50 | S5 stopped | S5 stop p50 | S6 false stops |
|---|---|---|---|---|---|---|---|
| baseline | 1748 / 2118 | 642 | 6/126 | 3001 | - | - | - |
| dynamic | 1742 / 2161 | 640 | 6/126 | 3001 | - | - | - |

## S2 cut-off rate by pause length

| variant | 200 ms | 300 ms | 400 ms | 500 ms | 600 ms | 800 ms | 1000 ms |
|---|---|---|---|---|---|---|---|
| baseline | 0/18 | 0/18 | 0/18 | 0/18 | 3/18 | 0/18 | 3/18 |
| dynamic | 0/18 | 0/18 | 0/18 | 0/18 | 3/18 | 0/18 | 3/18 |
