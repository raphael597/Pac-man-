# Game API analysis and integration guide

## What was actually available

Nothing. At the time of writing this project the repository contained:

```
$ git log
fatal: your current branch has no commits yet
$ git ls-remote origin
(no refs)
$ find . -type f -not -path './.git/*' | wc -l
0
```

No starter code, no example players, no engine, no rules document, no
screenshots, no enums, no constants. The brief's section 62 describes what to
do *when* the teacher's files are provided; they were not, so section 2's
fallback applies instead:

> If some rules are unavailable, isolate those assumptions behind clean
> interfaces so they can later be changed easily.

That is what this document is about: exactly which interfaces, and exactly
what to change.

## Strategy: discover, do not assume

Guessing one API and hard-coding it would put the assumption in a thousand
places. Instead there are exactly **two** places where the outside world
touches SUPERPAC.

### 1. `RuleSet` — what the game rules are

`superpac/game/rules.py`. Every rule that could plausibly differ is a field:

| field | what it decides | default |
|---|---|---|
| `allow_stay` | is standing still legal | `True` |
| `collision_mode` | `elimination` / `block` / `pass` / `swap_block` | `elimination` |
| `head_on_resolution` | `both` / `none` / `higher_score` / `mover` | `both` |
| `simultaneous` | all move then resolve, or one at a time | `True` |
| `turn_order_random` | is the acting order reshuffled | `True` |
| `food_value`, `food_respawn` | pellet economy | `1.0`, `False` |
| `kill_bonus`, `survival_bonus`, `step_cost` | other scoring terms | `0.0` |
| `max_turns`, `end_on_last_food`, `end_on_one_survivor` | termination | `400`, `True`, `True` |
| `highlander_wins` | does a sole survivor win outright | `True` |
| `wrap_x`, `wrap_y` | side tunnels | `False` |
| `time_limit_ms` | per-move budget | `100.0` |

Nothing outside this file hard-codes any of them. `RULE_VARIANTS` holds eight
named combinations, and `scripts/bench.py rules` scores SUPERPAC under all of
them — so the project can demonstrate it is not tuned to one guess.

### 2. `StateExtractor` — what the host object looks like

`superpac/game/adapter.py`. It sniffs the object the host passes in and
converts it to a `GameState`, caching the discovered schema after the first
turn so the cost is paid once.

Handled without configuration:

| dimension | variants supported |
|---|---|
| container | `dict`, attribute object, or both merged |
| map | list of strings, list of lists, newline string, nested dict, numeric grid (`1` = wall), or an explicit `walls`/`blocked` set |
| positions | `(x, y)`, `[x, y]`, `{'x':…,'y':…}`, `.x`/`.y` objects, `complex`, flat `y*width+x` ids |
| axis order | `(x, y)` **or** `(row, col)` — calibrated, not assumed |
| players | flat roster + `my_id`, or "me plus a list of opponents" |
| food | position list, boolean mask, or `.`/`o` characters read off the grid |
| naming | ~12 candidate names per field, plus case/underscore-insensitive matching |
| actions | returned as int, `"NORTH"`, `"north"`, or `(dx, dy)` |

#### The axis calibration

`(x, y)` versus `(row, col)` is the classic silent failure in grid games: it
does not crash, it just plays a mirrored game badly. Rather than guessing,
the adapter uses an invariant — *every position the host reports must land on
a walkable cell* — and scores both interpretations against it:

```
axis calibration chose (row, col): 8/8 valid vs 2/8 for (x, y)
```

The winner is cached. On a symmetric map where both readings agree, the choice
is harmless by construction.

## When the real files arrive

### Step 1 — find out what the API really is

The submission ships a one-shot diagnostic. Call it once from inside the real
engine:

```python
from superpac import inspect_api          # or: from superpac.game.adapter import describe_host_state
print(inspect_api(state))                 # `state` = whatever the engine hands your player
```

It dumps every attribute/key it can see, then reports what the sniffer made of
it:

```
type: GameState
  .width int = 21
  .board list = [['#', '#', ...], ...]
  .pellets set = {(1, 1), (1, 2), ...}
  ...
--- sniffer result ---
Schema(size=21x15, swap_axes=True, flat_ids=False, grid='board', ...)
  grid found under 'board' as 15 rows x 21 cols
  axis calibration chose (row, col): 24/24 valid vs 3/24 for (x, y)
  walkable cells: 166
<GameState t=0 me=0@(1, 3) food=160 scores=[0.0, ...] alive=[True, ...]>
```

If that last line is right, **you are already done** — the sniffer works and
no code change is needed.

### Step 2 — pin the schema (recommended even if sniffing works)

Sniffing is the safety net, not the plan. Once the API is known, remove the
guesswork:

```python
extractor = StateExtractor(rules=REAL_RULES)
extractor.schema = Schema.pinned(width=21, height=15, swap_axes=True,
                                 grid_name="board", action_style="name")
```

### Step 3 — set the real rules

```python
REAL_RULES = RuleSet(
    collision_mode="elimination",   # or whatever the teacher's engine does
    head_on_resolution="both",
    simultaneous=True,
    time_limit_ms=100.0,
    max_turns=300,
)
```

### Step 4 — mirror the engine and re-verify

Update `superpac/simulation/engine.py` if the real resolution order differs
from any variant already supported, then:

```bash
python -m unittest discover -s superpac/tests -t .   # 82 tests
python scripts/bench.py rules --games 40             # sanity across variants
python scripts/evolve.py --generations 10            # re-tune for the real rules
python scripts/build_submission.py                   # rebuild the single file
python submission/superpac.py                        # self-test
```

**No AI code changes at any step.** The opponent models, planner, evaluator and
strategy layer never see a host object or a rule constant — they read
`GameState` and `RuleSet`.

## Which parts of the brief's architecture apply, and which changed

| brief section | status |
|---|---|
| 4–7 world model, map graph, territory, clusters | as specified |
| 8–17 opponent modelling | as specified, plus fixed-share weighting so a mid-match strategy switch is recoverable |
| 18–20 forecasts, scenarios, robust decisions | as specified; scenarios are *enumerated* top-K rather than sampled (deterministic, no sampling noise) |
| 21–23 threat, contest, turn order | as specified; threat lives in `ai/threat.py` rather than inside the evaluator |
| 24 interception | implemented as a weight, **left at zero by default** — it did not pay for itself in benchmarks (section 56 says delete what does not measure) |
| 25–27 exploitation, active learning, randomness detection | as specified |
| 28–32 strategy, survival, mobility, dead ends, multiplayer | as specified; dead-end handling extended from *depth* to the **race for the pocket mouth**, which is what actually decides whether a pocket is a trap |
| 33–37 evaluation, search, anytime, performance, fallback | as specified |
| 38–47 simulator, bots, benchmarking, optimisation, adversarial league | as specified |
| 53 final tournament file | `submission/superpac.py`, self-contained, weights embedded |

The one structural deviation from the suggested tree is `ai/threat.py`; the
brief's layout had no home for time-aware threat maps and burying them in the
evaluator would have made both harder to test.
