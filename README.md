# agent-evals

## What this is

## How to run

## Results

### Overall score

| Configuration | Dev overall | Held-out overall |
|---|---|---|
| M1b | 15/31 | 22/60 |
| M2 | 12/31 | 20/60 |
| normalize-quotes | 12/31 | 20/60 |
| normalize-quotes+final-from-result | 16/31 | 19/60 |
| normalize-quotes+final-from-result+precision-only | 19/31 | 24/60 |

### Score by difficulty

| Configuration | Difficulty | Dev | Held-out |
|---|---|---|---|
| M1b | easy | 15/15 | 21/26 |
| M1b | medium | 0/9 | 0/16 |
| M1b | hard | 0/7 | 1/18 |
| M2 | easy | 12/15 | 16/26 |
| M2 | medium | 0/9 | 0/16 |
| M2 | hard | 0/7 | 4/18 |
| normalize-quotes | easy | 12/15 | 16/26 |
| normalize-quotes | medium | 0/9 | 0/16 |
| normalize-quotes | hard | 0/7 | 4/18 |
| normalize-quotes+final-from-result | easy | 11/15 | 13/26 |
| normalize-quotes+final-from-result | medium | 5/9 | 0/16 |
| normalize-quotes+final-from-result | hard | 0/7 | 6/18 |
| normalize-quotes+final-from-result+precision-only | easy | 14/15 | 19/26 |
| normalize-quotes+final-from-result+precision-only | medium | 5/9 | 0/16 |
| normalize-quotes+final-from-result+precision-only | hard | 0/7 | 5/18 |

### Tokens

| Configuration | Dataset | Avg tokens_in | Avg tokens_out | Tokens per correct |
|---|---|---|---|---|
| M1b | dev | 136.6 | 21.8 | 327.5 |
| M1b | held-out | 136.7 | 24.2 | 439.0 |
| M2 | dev | 1153.4 | 85.7 | 3200.9 |
| M2 | held-out | 1220.1 | 99.3 | 3958.1 |
| normalize-quotes | dev | 863.0 | 62.3 | 2390.4 |
| normalize-quotes | held-out | 1220.1 | 99.3 | 3958.1 |
| normalize-quotes+final-from-result | dev | 899.4 | 71.8 | 1881.6 |
| normalize-quotes+final-from-result | held-out | 1260.5 | 107.4 | 4319.7 |
| normalize-quotes+final-from-result+precision-only | dev | 879.9 | 67.1 | 1545.2 |
| normalize-quotes+final-from-result+precision-only | held-out | 1225.5 | 101.0 | 3316.2 |

### Failure types (agent configurations only)

| Configuration | Dataset | no_submit_text | ran_out_of_steps | gave_up_after_errors | silent_wrong | wrong_after_recovery |
|---|---|---|---|---|---|---|
| M2 | dev | 5 | 4 | 3 | 4 | 3 |
| M2 | held-out | 7 | 11 | 8 | 9 | 5 |
| normalize-quotes | dev | 4 | 1 | 3 | 4 | 7 |
| normalize-quotes | held-out | 7 | 11 | 8 | 9 | 5 |
| normalize-quotes+final-from-result | dev | 4 | 1 | 3 | 4 | 3 |
| normalize-quotes+final-from-result | held-out | 6 | 11 | 9 | 9 | 6 |
| normalize-quotes+final-from-result+precision-only | dev | 4 | 1 | 3 | 4 | 0 |
| normalize-quotes+final-from-result+precision-only | held-out | 7 | 11 | 8 | 9 | 1 |

## What broke

## Next steps
