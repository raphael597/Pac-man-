# Measurements

Every number here comes from a script in this repository. Where a result went
against expectation, it is recorded as it came out — the point of building the
benchmark harness was to be told things, not to confirm things.

## Tournament performance

`python scripts/bench.py baseline --games 40` — 160 games per cell, seats
rotated, `+-` is a 95% confidence half-width on the win rate.

| bot | train | validation | holdout | survival | ms/move |
|---|---|---|---|---|---|
| **SUPERPAC** | **52.5% ±10.9** | **71.2% ±9.9** | **67.5% ±10.3** | 96–98% | 5.3 |
| greedy_escape | 42.5% ±10.8 | 61.3% ±10.7 | 56.2% ±10.9 | 95–99% | 0.05 |
| cluster | 38.8% ±10.7 | 51.2% ±11.0 | 40.0% ±10.7 | 43–50% | 0.21 |
| defensive | 26.2% ±9.6 | 55.0% ±10.9 | 45.0% ±10.9 | 95–96% | 0.05 |
| greedy | 32.5% ±10.3 | 46.2% ±10.9 | 40.0% ±10.7 | 40–44% | 0.00 |

The **holdout** column is the one that matters: those bots were never seen by
the optimiser. SUPERPAC leads it by 11.3 points over the strongest baseline.

### What the benchmark taught us about the game

The first tournament run (13 bots, 120 games) produced a result worth
recording, because it reshaped the evaluation function:

| bot | win rate | avg score | survival |
|---|---|---|---|
| defensive | 60.5% | 47.2 | **94.7%** |
| cluster | 53.7% | **68.6** | 43.9% |
| aggressive | 3.2% | 20.1 | **6.5%** |

`cluster` collects 45% more food than `defensive` and still wins less often.
Under an elimination ruleset where a sole survivor wins outright, **staying
alive dominates scoring**, and hunting is close to suicide. That is why
`death` carries a weight two orders of magnitude above `food`, and why the
survival override exists at all. It was not an intuition; it was a table.

## Opponent prediction

`superpac/training/prediction_bench.py` — an observer rides along in real
matches and models every other player.

| archetype | top-1 accuracy | log loss | confidence | identified as |
|---|---|---|---|---|
| greedy | 100.0% | 0.18 | 0.82 | greedy_food |
| greedy_escape | 98.1% | 0.23 | 0.80 | greedy_escape |
| defensive | 97.8% | 0.23 | 0.80 | greedy_escape |
| mode_switch | 96.4% | 0.26 | 0.72 | greedy_food |
| aggressive | 95.7% | 0.30 | 0.78 | hunter |
| pattern | 94.8% | 0.20 | 0.84 | cycle |
| noisy_greedy (10%) | 92.1% | 0.39 | 0.73 | greedy_food |
| periodic | 90.4% | 0.42 | 0.69 | cycle |
| fixed_priority | 90.0% | 0.26 | 0.77 | cycle |
| intercept | 80.1% | 0.62 | 0.57 | greedy_food |
| cluster | 79.6% | 0.66 | 0.59 | greedy_food |
| stochastic | 48.0% | 1.16 | **0.28** | random |
| random | 31.6% | 1.25 | **0.19** | random |

Two things to note:

* **31.6% against uniform-random is the ceiling**, not a failure — with ~3.2
  legal moves on these maps a coin flip cannot be beaten. The confidence
  column shows the model knows that, which is the property that matters:
  low confidence switches the planner from exploitation to robust play.
* `noisy_greedy` at 92.1% is essentially optimal too: 90% of its moves are
  greedy and the remaining 10% land on the greedy move about a quarter of the
  time by chance.

## Recovering hidden parameters

`GreedyEscapeBot` flees when a rival comes within `threshold`. The number is
never exposed; it is inferred from observed flight by a posterior over
candidate values.

| true threshold | modal recovery | exact runs | mean posterior |
|---|---|---|---|
| d ≤ 1 | **1** | 8/8 | 0.56 |
| d ≤ 2 | **2** | 6/8 | 0.65 |
| d ≤ 3 | **3** | 6/8 | 0.68 |
| d ≤ 4 | **4** | 8/8 | 0.74 |
| d ≤ 6 | **6** | 8/8 | 0.86 |

34 of 40 runs recovered the threshold exactly; the rest were off by one.

## Periodicity

A periodic bot whose anomaly happens to pick its dominant action is invisible
that turn, so observed gaps are the true period times some integer. Averaging
raw gaps was wrong in a specific, reproducible way:

| true period | mean of raw gaps | minimum-gap normalisation |
|---|---|---|
| 8 | 12.9 ± 5.9 | **8.0 ± 0.0** |
| 10 | 12.9 ± 5.9 | **10.0 ± 0.0** |
| 15 | 18.0 ± 6.0 | **15.0 ± 0.0** |
| 20 | 22.9 ± 7.0 | **20.0 ± 0.0** |

Under jitter (period 15 ± 2) the estimate is 14.4 ± 1.4 at confidence 0.67; on
a non-periodic stream confidence stays at 0.26 and the detector declines to
predict.

## Things that did not work

Recorded because section 56 asks for measurable performance over complexity,
and because a benchmark that only ever confirms your ideas is not being read
honestly.

**The duel harness was biased, and it produced a wrong conclusion before
anyone noticed.** This is the most important entry on this page.

A version-vs-version duel between the `cluster`/`territory` terms switched off
and the same terms at my hand-picked values came out 28.6% against 19.6% over
56 games, and was written up as "the intuited values hurt". Then the harness
was sanity-checked by running it on two configurations with *identical*
weights, which must tie by construction. It reported **26.4% against 16.7%**.

The bug was in `head_to_head`. It rotated both entrants through every seat,
which looks sufficient — but with A always in `seat_a` and B always in
`seat_a + 1`, the other players end up arranged differently around each
entrant. Two byte-identical `GreedyFoodBot`s with non-identical fillers came
out **10.9 percentage points apart**:

| bot | win rate | placement |
|---|---|---|
| A (GreedyFoodBot) | 28.1% | 1.562 |
| B (GreedyFoodBot, byte-identical) | 17.2% | 1.688 |

That is larger than any real version improvement would produce, so every
version-vs-version measurement taken with it was measuring seat luck.

An earlier check had "passed" because it used four identical bots — which tie
trivially and prove nothing about seat balance. The regression test now
deliberately uses distinct, differently-skilled fillers.

**The fix**: play every arrangement twice with the two entrants swapped and
nothing else changed, so positional advantage is handed to each exactly once
and cancels identically rather than approximately. Byte-identical bots now tie
to the last digit on win rate, placement *and* total score (`n = 128`).

**A second fix**: `version_duel` now zeroes `explore_epsilon` on both sides.
With SUPERPAC's tie-breaking randomness live, identical weight vectors still
came out 21.9% against 26.6%. That is common random numbers applied one level
deeper than the scenario battery, and without it a duel of this size cannot
detect anything smaller than the noise.

**The honest status of `cluster` and `territory`**: unknown. The measurement
that appeared to condemn them was invalid. They ship with small defaults and
are handed to the optimiser, which searches `cluster` over [0, 5] and
`territory` over [0, 8] and is free to zero them if they do not earn their
place.

**Interception is nearly worthless under Highlander rules**, and the code now
says so explicitly rather than implementing a term that cancels itself out.
Contact kills both parties, so body-blocking is mutual destruction: the danger
term already prices those cells and adding a reward on top just fights it.
`_build_intercept_field` returns `None` unless we would *survive* the exchange
(a `higher_score` ruleset while ahead, or a non-lethal ruleset). The weight
defaults to zero.

**Three weights were dead on arrival.** `cluster`, `intercept` and `progress`
were declared in the `Weights` dataclass, referenced in the strategy layer's
multiplier tables, and never actually multiplied by anything. An audit caught
them. `cluster` and `intercept` were implemented; `progress` was deleted,
because rewarding "closing distance on the objective" is precisely what the
food-potential field already does. A dead weight is worse than no weight — it
wastes an optimiser dimension and reads as a feature that exists.

**`trap` was dead too, and that one was a real bug.** Dead-end handling was
penalising pocket *depth* only, so entering a three-deep pocket with a rival
two steps from its mouth scored identically to taking an open route. The fix
was to make the map graph label each dead-end cell with the mouth you must
return through, then price the *race*: our escape time against the rival's
arrival time at that mouth. Measured effect on a pocket cell: risk 0.34 with a
rival near the mouth versus 0.21 with it far away, moving the cell's score by
4.7 points.

## Failure analysis

`superpac/training/failure_analysis.py` replays matches with SUPERPAC
instrumented and sorts each loss into a category that points at a subsystem.
Over 14 games against the validation population:

| outcome | count | share |
|---|---|---|
| WIN | 11 | 78.6% |
| endgame_collapse | 2 | 14.3% |
| territory_loss | 1 | 7.1% |

The striking part is what is *absent*: **not one loss came from being
eliminated.** Survival is solved. Every loss is on points, and the largest
category is being ahead at the three-quarter mark and losing anyway:

```
game 6: endgame_collapse (place 1, score 70 vs 76, conf 0.72, acc 0.91,
                          survival turns 0)
```

Prediction was 91% accurate and SUPERPAC was never once in danger. It simply
got out-collected. That points at the weights rather than the models: at 100%
survival, the moves spent on mobility and danger avoidance are moves a greedy
rival spends on food.

### The fix that did not work (yet)

The first hypothesis was that `ENDGAME_LEADING` was too conservative — it
protected *any* late lead, however fragile. Lead protection is now
proportional: a lead only justifies playing safe when the food still on the
board cannot overturn it, and `endgame_lead_ratio` (0 reproduces the old
behaviour exactly) is in the optimiser's search space.

Measured on 176 games with the mirrored-pair harness and `explore_epsilon`
zeroed on both sides:

| version | win rate | placement | score |
|---|---|---|---|
| protect any lead (old) | 25.0% | 1.472 | 32.51 |
| protect only a safe lead (new) | **26.7%** | **1.455** | **32.64** |

Better on all three metrics, and by nothing like enough: 1.7 points on 176
games has a standard error around 3.3, so this is inside the noise. The
promotion gate correctly refused it. The failure profile after the change was
identical — still two endgame collapses out of fourteen.

So the change ships as a *tunable with a defensible default*, not as a proven
improvement. "Protect a lead only when the remaining food cannot overturn it"
is better specified than "protect any lead", and if it is wrong the optimiser
can set the ratio to zero and get the old behaviour back exactly.

The real remedy is almost certainly weight tuning — `death` at 260 and
`danger` at 9 are priced for a risk that, at 100% survival, is not being
taken. That is what the evolutionary search exists to settle, and it is the
right tool for it: hand-tweaking one more constant here would just be another
untested intuition.

## Weight tuning

`python scripts/evolve.py --generations 12 --population 14 --games 16` —
5,376 matches over 21 minutes on four cores. Fitness is measured on the
training population with common random numbers inside each generation and a
fresh scenario battery between them; the champion is then selected on the
disjoint *validation* population, so the search cannot win by memorising the
bots it was scored against.

| | validation win rate | placement |
|---|---|---|
| hand-set defaults | 78.1% | 0.31 |
| tuned champion | 82.8% | 0.22 |

### That 4.7-point gain was not real

The numbers above are from the optimiser's own 64-game validation pass, and
they do not survive a proper re-measurement. Re-running both weight sets over
an enlarged common battery — **180 games per cell instead of 64**, same
scenarios for both, two-proportion z-test — gives:

| weights | population | win rate | 95% CI | placement | score | survival |
|---|---|---|---|---|---|---|
| defaults | validation | 69.4% | [62.7, 76.2] | 0.428 | 53.59 | 96.7% |
| tuned | validation | 70.6% | [63.9, 77.2] | 0.417 | 54.33 | 97.8% |
| defaults | holdout | **68.9%** | [62.1, 75.7] | **0.383** | 60.48 | 97.2% |
| tuned | holdout | 67.8% | [61.0, 74.6] | 0.400 | **61.21** | **98.3%** |

```
validation   tuned - defaults = +1.1 points  z=+0.23  -> no significant difference
holdout      tuned - defaults = -1.1 points  z=-0.23  -> no significant difference
```

**5,376 matches of evolutionary search produced no measurable improvement in
win rate on either population.** That is the honest result, and it is worth
stating plainly because every intermediate signal pointed the other way: the
optimiser's own validation pass said +4.7, the promotion duel said +3.9, and
a first 80-game benchmark appeared to show a *catastrophic* 8.7-point holdout
collapse. All three were noise. Match outcomes in this game are variable
enough that 64–176 games cannot resolve differences of a few points, and
every one of those samples was small enough to say whatever it liked.

The one thing that did *not* move with the sample size: score and survival
are consistently, if slightly, better under the tuned weights on both
populations, while win rate and placement are a coin flip.

### What was shipped, and why

The tuned weights, on three tie-breaks rather than on the win rate:

1. They won the only **paired** comparison available. The duel harness holds
   scenario, seat arrangement and tie-breaking randomness fixed across both
   versions, which removes far more variance than the unpaired population
   benchmark can. It is the more sensitive instrument even though its margin
   is also not significant on its own.
2. They are better on score and survival on *both* populations.
3. Two of their largest changes have independent support from the failure
   analysis, which was derived from completely different evidence.

None of that makes the tuned weights *proven* better. It makes them not worse
and better-motivated, which is the most that 5,376 matches can honestly
support here.

### What it changed, and why that is interesting

| `information` | 0.35 | **0.751** | +114% |
| `endgame_lead_ratio` | 0.5 | **0.876** | +75% |
| `mobility` | 2.6 | **1.14** | -56% |
| `trap` | 7 | **9.69** | +38% |
| `territory` | 0.5 | **0.68** | +36% |
| `contest` | 1.1 | **0.788** | -28% |
| `forecast_horizon` | 4 | **5** | +25% |
| `cluster` | 0.3 | **0.236** | -21% |
| `risk_aversion` | 0.55 | **0.648** | +18% |
| `explore_epsilon` | 0.035 | **0.0411** | +17% |
| `beam_width` | 12 | **14** | +17% |
| `open_space` | 0.9 | **0.932** | +4% |

Two of these are the optimiser independently reaching conclusions the failure
analysis had already pointed at, from completely different evidence:

* **`mobility` more than halved.** Failure analysis had found that *no* loss
  came from elimination — survival was already at 100% — so moves spent
  keeping escape routes open were moves not spent on food. The search found
  the same thing by playing games.
* **`endgame_lead_ratio` rose to 0.88.** The A/B on protecting only a safe
  lead was inconclusive at 176 games; the optimiser pushed the parameter
  *further* in that direction than the default, which is weak independent
  support for the change.

Two more are worth noting:

* **`trap` rose 38%**, the largest increase in the table. That is the term
  that was dead on arrival and had to be rebuilt around the race for the
  pocket mouth. The search valuing it above its hand-set weight is a decent
  sign the rebuild was the right shape.
* **`intercept` stayed at exactly zero.** Free to move anywhere in [0, 5], the
  search left it alone — which matches the structural argument that under
  Highlander rules body-blocking is mutual destruction and the field is empty
  by construction.

`cluster` and `territory` were the two whose value the broken harness had
"disproved". Given a free hand in [0, 5] and [0, 8], the optimiser kept both
small but non-zero (0.24 and 0.68). So: marginal, not
worthless, and nothing like the values intuition suggested.

The following were never mutated away from their defaults and remain
hand-set: `food`, `food_potential`, `denial`, `intercept`, `death`, `danger`, `dead_end`, `stagnation`, `discount`, `potential_discount`, `territory_softness`, `max_depth`, `scenario_count`.

## Adversarial search

`python scripts/adversarial.py --rounds 28 --games 10` samples configurations
from 11 bot archetypes and keeps any that hold SUPERPAC to 55% or less when
filling three of the four seats. Four of 28 qualified:

| counter-strategy | SUPERPAC win rate | SUPERPAC placement |
|---|---|---|
| `cluster_6` (cluster bot, radius 6) | **20.0%** | 1.50 |
| `noisy_greedy_0.02` (greedy, 2% noise) | 40.0% | 0.80 |
| `intercept_3` | 50.0% | — |
| `mode_switch_(15-35)` | 60.0% | 0.40 |

Ten games each, so the individual figures are indicative rather than precise.
The *pattern* is the point, and it is unambiguous.

**Every counter-strategy that works is a pure harvester.** Not one of them
fights, traps, ambushes or outmanoeuvres SUPERPAC. `cluster_6` simply targets
dense pockets of food and collects them faster. `noisy_greedy_0.02` is
near-pure greed with the noise turned almost off. Meanwhile every *aggressive*
configuration tested — `aggressive_7`, `aggressive_16`, `aggressive_22` — lost
100% of its games, as did every scripted, periodic and fixed-priority bot.

This is the third independent line of evidence pointing at the same weakness:

| method | evidence | conclusion |
|---|---|---|
| failure analysis | 0 losses from elimination, 100% survival, all losses on points | safety spending is wasted |
| weight optimisation | `mobility` cut 56% | safety weighted too heavily |
| adversarial search | only harvesters beat it; every aggressor loses 100% | it out-survives but under-collects |

Three methods, three kinds of evidence, one answer: **SUPERPAC's remaining
weakness is harvesting throughput, not survival, prediction or planning.** Its
defensive machinery is comfortably ahead of what the opponent population can
punish, and the marginal move should be spent on food.

That is a specific, testable direction for the next iteration rather than a
vague "make it better", which is precisely what the adversarial loop exists to
produce. `results/adversarial.json` has the raw output, and the counter-bots
are now permanent league members so a future version cannot "improve" by
forgetting them.

## Performance

`python scripts/profile_agent.py`

| phase | ms/turn | share |
|---|---|---|
| search | 2.93 | 55.7% |
| turn fields | 1.09 | 20.6% |
| forecast + threat | 0.71 | 13.5% |
| model update | 0.34 | 6.4% |
| territory | 0.13 | 2.4% |
| strategy | 0.07 | 1.4% |
| **total** | **5.26** | |

Profiling found 668k calls to `positional_score` per six matches — 2.0 s of an
11 s run — almost all of them re-scoring the same `(cell, depth)` pair while
the beam sorted its frontier. Memoising per turn (960 unique keys, verified
identical to the direct computation) cut search time 36% and the whole turn
24%, from 6.96 ms to 5.26 ms.

Against an assumed 100 ms limit that leaves a wide margin, which is
deliberate: the tournament machine may be slower than this one, and a
timed-out turn scores less than a mediocre move.
