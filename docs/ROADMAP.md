# Implementation roadmap

The brief's section 52 lays out fourteen phases. This is what was actually
built in each, what the benchmark said about it, and what remains.

## Executed

### Phase 1 — game adapter
No teacher files existed, so this phase became *"make the unknown API a
run-time discovery problem instead of a design-time guess"*. `RuleSet` holds
every rule that could differ; `StateExtractor` sniffs the host object and
calibrates the axis order from evidence. Verified against five synthetic host
dialects, and end-to-end against three of them through the built submission.

### Phase 2 — baseline
`MapGraph` (BFS, all-pairs distances under 1400 cells, dead-end peeling,
junctions, articulation points, connected regions), `GameState`, a
rule-parameterised reference `Engine`, a braided symmetric map generator, and
a tournament driver. First run: 120 games, 13 bots, zero crashes.

**What it taught us**: under an elimination ruleset, `defensive` (94.7%
survival, 47.2 avg score) beat `cluster` (43.9% survival, 68.6 avg score).
Survival dominates scoring. That single table set `death` two orders of
magnitude above `food` and motivated the survival override.

### Phase 3 — strategic map intelligence
Territory as a soft-logistic race per pellet, contest scores, food clusters,
mobility, dead-end pockets. 0.15 ms per analysis.

### Phases 4–8 — opponent modelling
One independent model per rival: eleven competing hypotheses mixed by
fixed-share weighting, a backed-off n-gram, a context-conditioned policy
model, two periodicity detectors, a latent-mode HMM, and calibrated
prediction scoring.

**Measured**: 100% top-1 on greedy, 98.1% on greedy-escape, 94.8% on scripted
patterns, 31.6% on uniform-random — the last of which is the theoretical
ceiling, with confidence correctly at 0.19. Hidden escape thresholds recovered
exactly in 34 of 40 runs.

### Phases 9–10 — scenarios and the robust planner
Multi-turn probabilistic forecasts, time-aware threat maps, top-K enumerated
joint scenarios, one beam per opening move, expected value blended with
conditional value at risk.

### Phase 11 — active learning
Information gain from standing at a distance that *splits* a rival's escape
threshold posterior — binary entropy peaks exactly where the observation is
most informative. Annealed to zero as the game becomes decisive.

### Phase 12 — automatic optimisation
Evolutionary search with common random numbers within each generation and a
fresh battery between them; champion selected on a disjoint validation
population.

### Phase 13 — adversarial league
Counter-strategy search over 11 archetypes and their parameter spaces, with a
league that grows and never shrinks so old threats stay as regression tests.

### Phase 14 — tournament build
`scripts/build_submission.py` flattens the runtime into one file, guards
against nested intra-package imports, embeds tuned weights, and ships a
self-test. Verified standalone.

## Course corrections

Three things were built, measured, and then changed because the measurement
disagreed with the design.

1. **Dead-end handling was wrong.** Penalising pocket *depth* meant a
   three-deep pocket with a rival two steps from its mouth scored the same as
   an open route. Rebuilt around the race for the pocket mouth.
2. **The duel harness was biased by 10.9 points** and had already produced a
   wrong conclusion. Rebuilt around mirrored pairs; byte-identical bots now
   tie exactly. See `docs/RESULTS.md`.
3. **Four weights were dead on arrival** — declared, referenced in the
   strategy tables, never multiplied by anything. Three were implemented, one
   was deleted as redundant, and an import-time guard now prevents the
   optimiser's bounds from drifting from the weight set.

## Not built, and why

**Full expectimax / minimax.** Rejected on the brief's own reasoning (section
34): multiple opponents, non-adversarial behaviour, stochastic actions, and a
branching factor that makes the tree useless at any affordable depth. The beam
plus scenario approach reaches depth 6 in ~3 ms.

**A neural policy.** No dependency budget for it, no training infrastructure
that would fit a school tournament, and nothing in the benchmarks suggesting
the evaluation function is the bottleneck rather than the opponent models.

**Learned opponent embeddings.** The eleven hand-specified hypotheses already
reach the prediction ceiling on every deterministic archetype. There is no
headroom left for a learned representation to recover.

## What to do next

Three independent methods now agree on where the remaining weakness is, which
makes the next step unusually well specified.

| method | evidence | conclusion |
|---|---|---|
| failure analysis | 0 losses from elimination, 100% survival, all losses on points | safety spending is wasted |
| weight optimisation | `mobility` cut 56% by the search | safety weighted too heavily |
| adversarial search | only pure harvesters beat it; every aggressor loses 100% | it out-survives but under-collects |

**SUPERPAC's defensive machinery is comfortably ahead of what the opponent
population can punish. The marginal move should be spent on food.**

In priority order:

1. **Re-target to the real API.** Everything else is speculative until the
   teacher's files exist. `docs/GAME_API.md` has the procedure; it should take
   under an hour, and it changes no AI code.
2. **Attack harvesting throughput**, guided by the finding above. The specific
   target is `cluster_6`, which holds SUPERPAC to 20%: a bot that does nothing
   but collect dense pockets efficiently. Candidate directions: replace the
   max-form food-potential field with something that does not double-count
   revisits, plan multi-pellet routes rather than greedy potential ascent, or
   simply push `danger` and `death` down and see where the survival rate
   starts to cost more than the food gains.
3. **Scale the benchmark before trusting any of it.** This is the lesson of
   the whole results file: at 64–176 games, three separate measurements said
   the weight tuning helped by 4.7 points, helped by 3.9 points, and hurt by
   8.7 points. At 720 games the answer was "no significant difference". The
   brief asks for 10,000+ games; a few hours on four cores would let genuinely
   small improvements be detected instead of imagined.
4. **Close the adversarial loop.** The search finds counter-strategies; wiring
   its output back into the optimiser's training population and iterating is
   what the brief calls critical, and only the first half of it is built.
5. **Deeper search, if it pays.** SUPERPAC uses ~4 ms of a ~62 ms budget.
   Raising `max_depth` and `beam_width` is free in wall-clock terms; whether
   it is free in *quality* terms is genuinely open, since deeper search
   against a mispredicted opponent compounds the error rather than reducing
   it. Given point 3, answering this needs thousands of games, not hundreds.
