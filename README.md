# SUPERPAC

An adaptive, opponent-modelling game AI for a Pac-Man-like multiplayer grid
tournament. It watches every rival, builds a separate behavioural model of
each one, maintains competing hypotheses about what algorithm each is running,
forecasts several possible futures, and picks moves that stay good even when
those forecasts are wrong.

---

## Read this first: there were no game files

**This repository was empty.** No starter code, no example players, no engine,
no rules document, no enums — zero commits, zero remote refs. The brief says
*"do not implement against an imagined API"*, and that instruction is taken
literally here rather than quietly ignored.

Three things follow from it, and they shape the whole design:

1. **Every rule that could plausibly differ is a parameter**, not a hard-coded
   assumption. `RuleSet` (`superpac/game/rules.py`) holds all of them —
   collision semantics, turn order, scoring, termination, wrap-around
   tunnels. The engine, the evaluator and the AI all read their behaviour
   from that object.
2. **The host API is discovered at run time, not assumed.** `StateExtractor`
   (`superpac/game/adapter.py`) sniffs whatever object the tournament hands
   it — dict, attribute object, ASCII grid, numeric grid, wall set, `(x, y)`
   pairs, `(row, col)` pairs, flat cell ids — and caches the schema after the
   first turn. It even *calibrates* the axis order from evidence instead of
   guessing (see below).
3. **SUPERPAC is benchmarked across every rule variant**, not just the most
   likely one, so a wrong guess costs a constructor argument rather than the
   tournament.

### Rules ledger

| Status | Item |
|---|---|
| **KNOWN** | Nothing. The repository contained no game files of any kind. |
| **ASSUMED** | Shared grid; walls; food worth 1 point; 2–6 players; simultaneous moves in randomised order; contact between players eliminates both ("Highlander"); match ends on last pellet, sole survivor, or turn limit; ~100 ms per move; full visibility of the board; the player object survives across turns. |
| **UNKNOWN** | The actual method names and signatures; the state object's shape; whether players are eliminated at all; whether scores or survival decide the winner; the real time limit; allowed libraries; map size; whether opponents are even visible. |

Everything in the ASSUMED row is a field on `RuleSet` or a branch in the
adapter. **When the teacher's files arrive, the whole re-targeting job is:**

```bash
# 1. Discover the real API - run this once against the real engine:
python -c "from submission.superpac import inspect_api; print(inspect_api(state))"

# 2. Pin what it reports in StateExtractor / RuleSet, then re-verify:
python -m unittest discover -s superpac/tests -t .
python scripts/bench.py rules --games 40
```

No AI code changes. That separation is the single most important architectural
decision in the project.

---

## Architecture

```
                   host engine (unknown API)
                             |
              StateExtractor  <- sniffs + calibrates the API
                             |
                        GameState                MapGraph (static, built once)
                             |                    BFS - all-pairs distances
                             |                    dead ends - pocket mouths
                             |                    junctions - articulation points
                             v
   +---------------------------------------------------------------+
   |  OpponentRegistry: one independent model per rival             |
   |                                                                |
   |   HypothesisEnsemble (11 competing theories, fixed-share)      |
   |     greedy | greedy+escape(theta) | hunter | avoider |         |
   |     momentum | priority | n-gram | context | cycle |           |
   |     periodic | random                                          |
   |   ModeClassifier   COLLECT/ATTACK/ESCAPE/EXPLORE/RANDOM/END    |
   |   PredictionScorer accuracy - log loss - Brier - confidence    |
   +---------------------------------------------------------------+
                             |
        forecasts ---> ThreatMap        TerritoryAnalysis
        (per-rival      P(occupied      who reaches each
         position       at t+1..t+H)    pellet first
         beliefs)             |                |
                              v                v
                         TurnFields (food potential, trap risk, mobility)
                              |
                       StrategyManager -> EXPANSION | HARVEST | TERRITORY |
                              |            DENIAL | INTERCEPT | SURVIVAL |
                              |            ENDGAME_LEADING | ENDGAME_TRAILING
                              v
                          Planner
                    anytime iterative deepening
                    one beam per opening move
                    discrete scenarios for step 1
                    expected value blended with CVaR
                              |
                              v
                         legal action
```

### The ideas that actually matter

**One model per opponent, never a shared average.** In a four-player game the
three rivals are usually three different programs. Averaging them produces a
prediction that describes none of them.

**Fixed-share hypothesis weighting.** A plain Bayesian product collapses onto
one hypothesis and can never recover — fatal against a bot that switches
strategy at turn 40. After each update a small share of the weight is
redistributed uniformly, so a hypothesis that has been wrong for fifty turns
can climb back within a few observations. This is the difference between
adapting and being stuck.

**An honest ignorance hypothesis.** `UniformHypothesis` is always in the mix.
Against a genuinely random bot it wins, the mixture flattens, confidence
drops to ~0.19, and the planner switches from exploitation to robust play.
Measured confidence tracks measured accuracy across the whole range — see the
table below.

**Periodicity from the minimum gap, not the mean.** A periodic bot whose
anomaly happens to pick its dominant action is *invisible* that turn, so
observed gaps are always the true period times some integer — never a
fraction. Averaging raw gaps reports 18 for a true period of 15; folding every
gap onto the smallest observed one recovers 15 exactly.

**Trap risk is a race, not a depth.** A ten-cell pocket with every rival on
the far side of the map is safe; a two-cell one with a rival at its mouth is
fatal. `MapGraph` labels each dead-end cell with the mouth you must return
through, and the evaluator prices the race between our escape time and the
rival's arrival time.

**Discrete scenarios for the immediate step.** The threat map's smooth
occupancy probabilities are right for distant futures and wrong for the next
move: dying is all-or-nothing, and a move with a 25% death chance is far worse
than its average suggests. Step 1 is evaluated against concrete joint rival
assignments, producing a distribution of outcomes that is then blended as
expected value and conditional value at risk.

---

## Results

All figures from `scripts/bench.py`; 160 games per cell, seats rotated, `+-`
is a 95% confidence half-width.

### Against three disjoint opponent populations

| bot | train | validation | holdout | survival | ms/move |
|---|---|---|---|---|---|
| **SUPERPAC** | **52.5%** | **75.0%** | **67.8%** | 97–99% | 4.2 |
| greedy_escape | 42.5% | 61.3% | 56.2% | 95–99% | 0.05 |
| cluster | 38.8% | 51.2% | 40.0% | 43–50% | 0.21 |
| defensive | 26.2% | 55.0% | 45.0% | 95–96% | 0.05 |
| greedy | 32.5% | 46.2% | 40.0% | 40–44% | 0.00 |

The holdout population is bots the optimiser never saw. SUPERPAC leads there
too, which is the result that matters. Its holdout figure is from a 360-game
re-measurement (95% CI [61.0, 74.6]); the baselines are from 160 games each.

**What the optimiser did not achieve**: 5,376 matches of evolutionary weight
search produced *no significant win-rate improvement* over the hand-set
defaults on either population (+1.1 points on validation, −1.1 on holdout,
both z = ±0.23). Three separate intermediate signals said otherwise — the
optimiser's own validation pass, the promotion duel, and a first 80-game
benchmark that appeared to show an 8.7-point collapse. All three were noise.
The tuned weights ship because they are better on score and survival and won
the only variance-controlled paired comparison, not because they are proven
better. `docs/RESULTS.md` has the full account.

### Opponent prediction quality

Measured by an observer riding along in real matches (`training/prediction_bench.py`).

| archetype | top-1 accuracy | log loss | confidence | identified as |
|---|---|---|---|---|
| greedy | 100.0% | 0.18 | 0.82 | greedy_food |
| greedy_escape | 98.1% | 0.23 | 0.80 | greedy_escape |
| defensive | 97.8% | 0.23 | 0.80 | greedy_escape |
| mode_switch | 96.4% | 0.26 | 0.72 | greedy_food |
| aggressive | 95.7% | 0.30 | 0.78 | hunter |
| pattern | 94.8% | 0.20 | 0.84 | cycle |
| noisy_greedy (10% noise) | 92.1% | 0.39 | 0.73 | greedy_food |
| periodic | 90.4% | 0.42 | 0.69 | cycle |
| fixed_priority | 90.0% | 0.26 | 0.77 | cycle |
| intercept | 80.1% | 0.62 | 0.57 | greedy_food |
| cluster | 79.6% | 0.66 | 0.59 | greedy_food |
| stochastic | 48.0% | 1.16 | **0.28** | random |
| random | 31.6% | 1.25 | **0.19** | random |

31.6% against a uniform-random bot over ~3.2 legal moves is the theoretical
ceiling — you cannot predict a coin flip, and the confidence column shows
SUPERPAC knows it.

### Recovering a rival's hidden parameters

`GreedyEscapeBot` flees when a rival comes within `threshold`. That number is
never exposed; it has to be inferred from observed flight.

| true threshold | recovered (modal) | exact runs | posterior |
|---|---|---|---|
| d <= 1 | **1** | 8/8 | 0.56 |
| d <= 2 | **2** | 6/8 | 0.65 |
| d <= 3 | **3** | 6/8 | 0.68 |
| d <= 4 | **4** | 8/8 | 0.74 |
| d <= 6 | **6** | 8/8 | 0.86 |

### Robustness to the unknown rules

The rules are unknown, so being strong under one reading of them is not enough.
Win rate under every `RuleSet` variant (`python scripts/bench.py rules`):

| ruleset | what changes | SUPERPAC | greedy | defensive |
|---|---|---|---|---|
| default / highlander | contact kills both | **81.2%** | 58.3% | 56.2% |
| tunnels | wrap-around sides | **81.2%** | 58.3% | 56.2% |
| no_stay | standing still illegal | **79.2%** | 56.2% | 60.4% |
| survivor | higher score survives contact | **68.8%** | 62.5% | 31.2% |
| blocking | moves into occupied cells refused | **68.8%** | 62.5% | 22.9% |
| peaceful | contact harmless | **66.7%** | 62.5% | 18.8% |
| sequential | players move one at a time | **62.5%** | 54.2% | 56.2% |

SUPERPAC leads in all seven, and its margin is largest exactly where the
ruleset is most punishing. Note how badly `defensive` degrades once contact
stops being lethal (18.8% under `peaceful`): a strategy tuned to one reading
of the rules falls apart under another, which is the failure mode this sweep
exists to catch.

### Timing

Budget is 62% of the host's stated limit (`TIME_SAFETY`), with an anytime
search that always holds a valid answer. On a 100 ms limit: **3.4 ms mean,
4.4 ms worst observed** in the shipped single-file build, zero faults, zero
timeouts across every benchmark run. Profiling drove a 24% cut in turn time by
memoising position scores the beam was recomputing thousands of times per turn
(`docs/RESULTS.md`).

The headroom is deliberate — a tournament machine may be slower than this one,
and a timed-out turn is worth less than a mediocre move.

## A note on the measurements

One entry in `docs/RESULTS.md` matters more than the win rates: **the duel
harness was biased, and it produced a wrong conclusion before it was caught.**
Rotating two entrants through every seat is not enough to make a comparison
fair — the other players end up arranged differently around each — and two
byte-identical bots came out 10.9 percentage points apart. A conclusion had
already been drawn and written down from that harness.

It was found by asking the harness something whose answer was known in
advance: compare a configuration against *itself*. It should tie; it did not.
That check is now a test, and it deliberately uses distinct fillers, because
the earlier version used four identical bots — which tie trivially and prove
nothing about seat balance.

Where a result here is uncertain, it says so. Three weights ship at small
defaults with their value marked **unknown** rather than claimed, because the
only measurement that spoke to them was taken with the broken harness.

---

## Documentation

| file | what is in it |
|---|---|
| `docs/GAME_API.md` | what the API sniffer handles, and the exact procedure for re-targeting when the teacher's files arrive |
| `docs/RESULTS.md` | every measurement, including the three that went against the design and the one that was wrong |
| `docs/ROADMAP.md` | what was built per phase, what was deliberately not built, and what to do next |

### Adversarial search: what actually beats it

`scripts/adversarial.py` searches bot-parameter space for configurations that
beat the champion. Of 28 sampled, four qualified — and **every one of them is
a pure harvester**:

| counter-strategy | SUPERPAC win rate |
|---|---|
| `cluster_6` (dense-pocket collector) | **20.0%** |
| `noisy_greedy_0.02` (near-pure greed) | 40.0% |
| `intercept_3` | 50.0% |
| `mode_switch_(15-35)` | 60.0% |

Not one of them fights. Every *aggressive* configuration tested lost 100% of
its games, as did every scripted, periodic and fixed-priority bot.

That agrees with the failure analysis (zero losses from elimination, 100%
survival, every loss on points) and with what the optimiser did to the weights
(`mobility` cut 56%). Three independent methods, one answer: **the remaining
weakness is harvesting throughput, not survival, prediction or planning.**

## Layout

```
superpac/
  game/       rules, map graph, state, host-API adapter
  ai/         superpac agent, evaluator, planner, strategy, territory, threat
  opponents/  per-rival models, hypothesis ensemble, periodicity, n-gram,
              context policy, latent modes, prediction scoring
  simulation/ reference engine, map generator, tournament driver
  bots/       13 baseline opponents spanning deterministic to stochastic
  training/   benchmarks, weight optimiser, adversarial search, self-play
  tests/      82 tests
scripts/      bench.py, evolve.py, adversarial.py, build_submission.py,
              profile_agent.py, demo.py
submission/   superpac.py - the single-file tournament build
```

`ai/threat.py` is the one module not in the brief's suggested tree; threat
maps needed a home of their own rather than being buried in the evaluator.

## Running things

```bash
python -m unittest discover -s superpac/tests -t .    # 82 tests, ~2s

python scripts/bench.py baseline --games 40           # vs all three populations
python scripts/bench.py rules    --games 30           # across every RuleSet variant
python scripts/evolve.py --generations 10             # tune weights
python scripts/adversarial.py --rounds 32             # hunt for counter-strategies
python scripts/build_submission.py                    # -> submission/superpac.py
python submission/superpac.py                         # self-test the bundle

python scripts/demo.py --turns 3                      # watch it think
python scripts/profile_agent.py                       # per-phase timing
```

## The submission

`submission/superpac.py` is self-contained: standard library only, no package
imports, tuned weights embedded. The training framework, simulator, bot
population and benchmarks are deliberately left out — dead weight in a
submission is just more surface area to fail on.

It exposes many entry points (`Player`, `Bot`, `Agent`, `get_move`,
`choose_action`, `move`, `next_move`, `act`, `__call__`, plus module-level
functions) because the real API is unknown. Underneath, all of them route
through the same sniffing adapter.

Verified working through three different host dialects — `(x, y)` dicts,
`(row, col)` numeric grids, and flat integer cell ids — with the axis order
auto-detected in each case, legal moves every turn and zero faults.

### Two guarantees

1. **A legal action, always.** Every subsystem is guarded and degrades to a
   simpler layer, ending at a fallback that needs only the map.
2. **The clock is respected.** Anytime search, safety margin, microsecond
   fallback path.
