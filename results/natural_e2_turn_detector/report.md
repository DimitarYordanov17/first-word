# natural_e2_turn_detector

192 clip-runs, 0 errors

| variant | S1+S3 e2e p50 / p95 | S1+S3 end-of-turn p50 | S2 cut-off rate | S4 end-of-turn p50 | S5 stopped | S5 stop p50 | S6 false stops |
|---|---|---|---|---|---|---|---|
| baseline | 1795 / 2127 | 647 | 7/18 | - | - | - | - |
| audio | 1741 / 2086 | 578 | 12/18 | - | - | - | - |
| none | 1733 / 1982 | 577 | 18/18 | - | - | - | - |
| audio_own_defaults | 1681 / 1972 | 578 | 10/18 | - | - | - | - |
