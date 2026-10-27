# The linear programs in the PILLAR demos

This document writes out, as mathematics, the linear programs (LPs) that the two original demo
pages build and solve. Start with the plain-English summary below; section 2 includes one small LP
written out with real numbers next to its solver file, which shows how to read the `.lp` files.

## In plain words

All three problems decide **how many units to send where, before demand is known**, and minimise
**shipping cost plus a penalty for each unit of expected shortage**, under hard limits on what can
be shipped. They differ in how the service rule ("priority stores get at least 90% of what
customers actually want, with high probability") is enforced.

| | Decides | Minimises | Must hold | Uncertainty |
|---|---|---|---|---|
| **Circuit Copilot** | Shipments from depots A and B to four sites, plus local backup at S4 | Transport + backup + expected shortage penalty | Depot limits; every site gets 60% of its forecast; the priority rule holds with probability ≥ τ | Three demand "worlds" (Normal, Surge, Storm); in the storm scenario one lane arrives late in the Storm world |
| **PILLAR Replan** | Shipments of each category on each DC-to-store lane | Transport + expected shortage penalty (+ large penalties if the rules have to be relaxed) | DC capacities; floors; the priority rule as a minimum number of units per priority store | A mixture of storm scenarios, updated by the evidence the operator enters |
| **Forecast comparison** | Stock level at each of three stores | Units stocked + 8 × expected shortage | Total capacity; base floors; all three stores meet 90% of demand in ≥ 95% of the samples | The training observations (or only their mean) |

The probability rule is what makes these more than ordinary LPs. Copilot handles it by solving one
LP per combination of worlds and keeping the cheapest that qualifies. Replan turns it into a fixed
minimum number of units per store. The forecast comparison searches over a grid of stock levels.

 It is extracted from `demos/original/*.html`; line numbers refer to those
files. The Python port in `demos/backend/src/pillar_demos/` builds the same LPs (`copilot.py`,
`replan.py`) and solves them with the same simplex (`lp.py`).

Both demos use one solver, `solveLP` (Copilot line 55, Replan line 258): a dense two-phase simplex
that minimises $`c^\top x`$ subject to rows of the form $`a^\top x \;\{\le, \ge, =\}\; b`$ and
$`x \ge 0`$. Phase 1 minimises the sum of artificial variables; phase 2 the real objective. It
pivots on the most negative reduced cost, switches to Bland's rule after 50 degenerate pivots,
and breaks ratio-test ties by the lower basis index. When an LP has several optimal vertices,
these rules decide which plan the page shows.

The forecast comparison section at the bottom of both pages does **not** call the LP solver. It
enumerates candidate stock levels exhaustively; the same problem written as an integer program
is in the last section.

Solver-ready `.lp`/`.mps` instances of these models exist in a separate package
(`PILLAR_Solver_Models`). Its Replan and Copilot subset LPs were checked row by row against the
models the original pages build, and its MILPs against the original's search; see
[Cross-check](#cross-check-with-the-solver-ready-instances).

---

## 1. Circuit Copilot

Source: `solve` (line 194), `score` (line 186), `worldWeights` (line 178), `minimumBackup`
(line 219) in `pillar-circuit-copilot.html`.

**In plain words.** Two depots ship to four sites before anyone knows which of three worlds will
happen: normal demand, a surge, or a storm (S4 wants 60, 70 or 80 units). In the storm scenario,
depot A's shipment to S4 arrives too late in the Storm world, though it still costs money. A plan
must keep every site at 60% of its forecast, and S1 and S4 must get 90% of their actual demand in
enough worlds that the chance of meeting that rule is at least τ. The page tries all 8
combinations of "worlds where the rule is enforced", solves an LP for each, and keeps the
cheapest plan that reaches τ.

### Data

| Symbol | Meaning | Value |
|---|---|---|
| Sites $`j`$ | S1, S2, S3, S4 (S1 and S4 are priority sites) | $`j = 1..4`$ |
| Worlds $`w`$ | Normal, Surge, Storm | $`w = 1..3`$ |
| $`c^A_j`$, $`c^B_j`$ | Transport cost per unit from depot A, B | $`c^A = (1,2,5,6)`$, $`c^B = (6,5,2,1)`$ |
| $`c^L`$ | Local backup cost per unit (S4 only) | `backupCost`, default 12 |
| $`K_A`$, $`K_B`$ | Depot dispatch limits | `capacityA` 130, `capacityB` 50 |
| $`\bar L`$ | Backup limit | `backupLimit` (30) if backup enabled, else 0 |
| $`F_j`$ | Original forecast | $`(50, 40, 45, 55)`$ |
| $`d_{wj}`$ | Realised demand | $`50, 40, 45`$ for S1–S3 in every world; S4: $`60, 70, 80`$ |
| $`\phi`$ | Forecast floor fraction | `floor`, 0.6 |
| $`\alpha`$ | Priority service level | `exceptionService` (0.8) if `exceptionAuthorized`, else `service` (0.9) |
| $`\tau`$ | Required probability that the priority rule holds | `tau`, 0.95 |
| $`\rho_j`$ | Shortage penalty | `penaltyPriority` (20) for S1, S4; `penaltyOther` (10) for S2, S3 |
| $`\delta_w`$ | 1 if A→S4 arrives in time in world $`w`$ | 0 only for Storm in the `storm` scenario |
| $`\pi_w`$ | Posterior world probability | below |

**World probabilities.** With storm probability $`q`$ (`stormProbability`, 0.3), the priors are
$`\big((1-q)\tfrac{0.15}{0.7},\ (1-q)\tfrac{0.55}{0.7},\ q\big)`$. Observed evidence (`evidence` =
Normal, Surge or Storm) zeroes the other worlds; the result is renormalised to $`\pi_w`$.

### Variables (21)

- $`x^A_j, x^B_j \ge 0`$: units sent from depot A and B to site $`j`$ (8 variables);
- $`x^L \ge 0`$: local backup units to S4;
- $`s_{wj} \ge 0`$: shortage at site $`j`$ in world $`w`$ (12 variables).

Units that reach site $`j`$ in world $`w`$:

```math
y_{wj} = x^A_j + x^B_j \quad (j = 1,2,3), \qquad
y_{w4} = \delta_w\, x^A_4 + x^B_4 + x^L .
```

A late A→S4 shipment still costs transport but delivers nothing in that world.

### The LP for a subset $`S \subseteq \{\text{Normal}, \text{Surge}, \text{Storm}\}`$

```math
\begin{aligned}
\min\quad & \sum_j \big(c^A_j x^A_j + c^B_j x^B_j\big) + c^L x^L
  + \sum_w \pi_w \sum_j \rho_j\, s_{wj} \\
\text{s.t.}\quad
& \textstyle\sum_j x^A_j \le K_A, \qquad \sum_j x^B_j \le K_B, \qquad x^L \le \bar L
  && \text{(capacity)} \\
& y_{wj} \ge \phi\, F_j && \forall w \text{ with } \pi_w \gt  0,\ \forall j \quad \text{(floors)} \\
& y_{wj} + s_{wj} \ge d_{wj} && \forall w, j \quad \text{(shortage)} \\
& y_{w1} \ge \alpha \cdot 50, \qquad y_{w4} \ge \alpha\, d_{w4} && \forall w \in S \text{ with } \pi_w \gt  0
  \quad \text{(priority rule)} \\
& x, s \ge 0 .
\end{aligned}
```

The objective is transport plus backup cost plus expected shortage penalty. At an optimum
$`s_{wj} = \max(0, d_{wj} - y_{wj})`$.

### The chance constraint, solved by enumeration

The policy asks for $`P(\text{priority rule holds}) \ge \tau`$, where the rule holds in world $`w`$
when $`y_{w1} \ge 50\alpha`$ and $`y_{w4} \ge \alpha d_{w4}`$. The page does not use binaries. It
solves the LP once for each of the $`2^3 = 8`$ subsets $`S`$ (bit $`w`$ of `mask`), then for each
optimal plan:

1. scores it (`score`): it must respect capacities and floors, and its probability is
   $`\sum_w \pi_w \cdot \mathbb 1[\text{rule holds in } w]`$, evaluated by the compiled arithmetic
   circuit, with a $`10^{-7}`$ tolerance;
2. keeps it if that probability is at least $`\tau - 10^{-7}`$;
3. picks the cheapest kept plan, replacing the incumbent only when cheaper by more than $`10^{-6}`$
   (so the first subset wins ties).

Enumerating every subset makes this an exact solution of the chance-constrained problem. If no
subset qualifies the page reports the problem infeasible, together with the highest probability
any hard-feasible plan reached.

**Equivalent MILP.** The same problem as one mixed-integer program: drop the subset, add a binary
$`v_w`$ per world that switches off that world's priority rows, and bound the probability of the
switched-off worlds:

```math
\begin{aligned}
& y_{w1} + 50\alpha\, v_w \ge 50\alpha, \qquad y_{w4} + \alpha d_{w4}\, v_w \ge \alpha d_{w4}
  && \forall w \\
& \textstyle\sum_w \pi_w v_w \le 1 - \tau, \qquad v_w \in \{0, 1\} .
\end{aligned}
```

The big-M is the threshold itself, which is valid because $`y \ge 0`$. $`v_w = 1`$ permits a
violation in $`w`$; it does not assert one. The optimum equals the best subset LP's. The plan can
differ when several plans tie, because the page keeps the first subset that reaches the minimum.
The page also applies floors and priority rows only in worlds with $`\pi_w \gt  0`$, which matters
once evidence has ruled a world out.

### Derived queries

- **Most-likely-world plan**: the same procedure with the evidence set to the most probable
  world, so $`\pi`$ is a point mass, then scored under the real $`\pi`$.
- **Minimum backup** (`minimumBackup`): enable backup and bisect $`\bar L`$ on $`[0, 100]`$ for 32
  steps, solving the full enumeration at each step. The answer is the smallest limit with a
  feasible plan, rounded to $`10^{-5}`$. In the storm scenario at $`\tau = 0.95`$ it is 21.99999,
  shown as 22 units.
- **Independence test**: no LP. A fixed plan is scored twice, once with the storm linking high
  demand and late delivery, and once treating them as independent (70% vs 91%).

---

## 2. PILLAR Replan

Source: `buildModel` (line 399), `chanceThreshold` (line 488), `solvePlan` (line 496),
`evaluatePlan` (line 575), `recompute` (line 683) in `pillar-replan-chatgpt.html`.

**In plain words.** Distribution centres ship to stores, by category, before the week's demand is
known. Demand is a probability distribution that changes as the operator reports evidence (a storm
warning, rising sales, a closed lane). One LP picks the shipments. Expected shortage is costed
exactly, using a few straight-line pieces per store. The service rule becomes a minimum number of
units per priority store: the smallest amount that meets the rule with the required probability.
If the network cannot meet the floors or the rule, very expensive slack variables absorb the gap,
and the page reports them as "relaxed".

### Data

| Symbol | Meaning |
|---|---|
| DCs $`d`$ | Toy: A, B. Storm: one DC per state (CA, TX, WI) |
| Keys $`k = (s, c)`$ | Store $`s`$ and category $`c`$. Toy: S1–S4 with one category `units`. Storm: 10 stores × FOODS, HOUSEHOLD, HOBBIES = 30 keys |
| Lanes $`\ell = (d, s)`$ | Toy: every DC to every store. Storm: every DC to every store, minus CA→TX when that lane is closed |
| $`\kappa_\ell`$ | Lane cost per unit. Toy: A $`(1,2,5,6)`$, B $`(6,5,2,1)`$. Storm: in-state 1; cross-state CA–TX 4, CA–WI 6, TX–WI 4.5, each scaled by $`m/4`$ where $`m`$ = `crossStateMultiplier` (default 4) |
| $`K_d`$ | DC capacity. Toy: 130, 50. Storm: $`\mathrm{round}(1.35 \cdot \sum_{\text{state}} \text{base mean})`$, times `txCap` (1, 0.7 or 0.4) for TX |
| $`F_k`$ | Normal-week forecast. Toy: 50, 40, 45, 55. Storm: $`\mathrm{round}(\text{weekly}_s \cdot \text{share}_c)`$, FOODS × 1.06 in a SNAP week. A loaded CSV of M5 aggregates replaces $`\text{weekly}_s \cdot \text{share}_c`$ (and the cv) for the keys it lists |
| $`\phi`$ | Floor fraction (`floor.fraction`, 0.6), or 0 if no floor |
| $`P`$, $`f_k`$ | Priority keys and their service fractions. Toy: S1, S4 at 0.9. Storm: TX_1–TX_3 FOODS at 0.9 |
| $`\rho_k`$ | Shortage penalty: `penalties.priority` for $`k \in P`$, `penalties.other` otherwise |
| $`\tau`$ | Required probability that the priority rule holds; `joint` = all priority keys together |

### Demand model

Demand comes from a mixture over latent configurations $`\kappa`$ with posterior weights $`w_\kappa`$.
Within a configuration, keys are independent.

- **Toy**: one configuration. S1–S3 demand is fixed at 50, 40, 45; S4 is 60, 70 or 80 with
  probability 0.15, 0.55, 0.30.
- **Storm**: 18 configurations: storm outcome $`z \in`$ {miss, graze, landfall}, Texas surge
  $`u \in`$ {low, medium, high}, emergency $`e \in`$ {no, yes}. The weight is
  $`p(z)\,p(u \mid z)\,p(e \mid z)`$ times the likelihood of the observed evidence: advisory given
  $`z`$, sales signal given $`u`$, TX capacity given $`z`$, lane status given $`z`$. An emergency reported
  as declared or not declared removes the configurations that disagree. Weights are normalised.
  Given $`\kappa`$, each key has a five-point distribution with mean $`\mu_k`$:
  the base mean, raised in Texas by the surge (FOODS $`\times (1+g_u)`$, HOUSEHOLD
  $`\times (1+0.8 g_u)`$, HOBBIES $`\times (1-0.5 g_u)`$, with $`g = 0.04, 0.18, 0.38`$). Its atoms are
  $`\mathrm{round}\big(\mu_k (1 + \text{cv}_c\, \zeta_i / \sigma)\big)`$ with probabilities
  $`(0.1, 0.2, 0.4, 0.2, 0.1)`$, where $`\zeta = (-1.6, -0.7, 0, 0.7, 1.6)`$ and
  $`\sigma = \sqrt{2(0.1 \cdot 2.56 + 0.2 \cdot 0.49)}`$. The exception rule lowers $`f_k`$ to
  $`\min(f_k, \text{exception fraction})`$ in configurations with an emergency.

The LP uses each key's **marginal** distribution: atoms $`v_{k1} \lt  \dots \lt  v_{kn}`$ with
probabilities $`p_{ki}`$, pooled across configurations (values equal to within 0.001 are merged).

### Variables

- $`x_{\ell c} \ge 0`$: units of category $`c`$ shipped on lane $`\ell`$;
- $`t_k \ge 0`$: expected shortfall at key $`k`$;
- $`h_k \ge 0`$: slack on the floor at key $`k`$;
- $`g_k \ge 0`$ for $`k \in P`$: slack on the priority rule.

Units delivered to key $`k = (s, c)`$: $`\;q_k = \sum_{\ell \text{ into } s} x_{\ell c}`$.

### The LP (`solvePlan`, mode `mmap`)

```math
\begin{aligned}
\min\quad & \sum_{\ell, c} \kappa_\ell\, x_{\ell c} + \sum_k \rho_k\, t_k
  + 10^4 \sum_k h_k + 10^5 \sum_{k \in P} g_k \\
\text{s.t.}\quad
& \textstyle\sum_{\ell \text{ from } d,\ c} x_{\ell c} \le K_d && \forall d \quad \text{(DC capacity)} \\
& q_k + h_k \ge \phi\, F_k && \forall k \quad \text{(floor)} \\
& t_k + \Big(\sum_{i \ge m} p_{ki}\Big) q_k \ \ge\ \sum_{i \ge m} p_{ki}\, v_{ki}
  && \forall k,\ m = 1..n \quad \text{(expected shortfall)} \\
& q_k + g_k \ge \theta_k && \forall k \in P \quad \text{(priority chance constraint)} \\
& x, t, h, g \ge 0 .
\end{aligned}
```

**Expected shortfall.** For a discrete demand $`D`$,
$`\mathbb E[(D - q)^+] = \max_m \big(\sum_{i \ge m} p_i v_i - q \sum_{i \ge m} p_i\big)^+`$, a convex
piecewise-linear function of $`q`$. The $`n`$ rows plus $`t_k \ge 0`$ are its epigraph, so at the optimum
$`t_k`$ equals the expected shortfall exactly.

**Chance constraint as a threshold.** The rule at $`k`$ holds when $`q_k \ge f_k D_k`$. Its probability
is $`P_k(q) = \sum_\kappa w_\kappa \Pr_\kappa(D_k \le q / f_{k\kappa})`$, a nondecreasing step
function of $`q`$. So "$`P_k(q_k) \ge \tau_{\text{each}}`$" is exactly $`q_k \ge \theta_k`$, where
$`\theta_k`$ (`chanceThreshold`) is the smallest candidate $`q \in \{v \cdot f_{k\kappa}\}`$ with
$`P_k(q) \ge \tau_{\text{each}} - 10^{-12}`$. The chance constraint becomes a linear lower bound.

**Several priority keys.** With `joint` and $`|P| \gt  1`$, each key uses
$`\tau_{\text{each}} = 1 - (1 - \tau)/|P|`$. By the union bound, all keys then hold together with
probability at least $`\tau`$; this is conservative, not an exact joint chance constraint. Otherwise
$`\tau_{\text{each}} = \tau`$.

**Slacks.** $`h`$ and $`g`$ keep the LP feasible when the network cannot meet the policy. Their
penalties ($`10^4`$, $`10^5`$) are far above any lane or shortage cost, so in practice they are
positive only when the policy cannot be met. The LP does not guarantee the smallest possible
relaxation; it trades slack against those penalties. The page reports any slack above $`10^{-4}`$ as "relaxed".

### Worked example: the toy LP at τ = 70%

This is `replan_toy_tau070.lp` from the solver package, line for line. Two DCs (A: 130 units,
B: 50) supply four stores. S1, S2, S3 demand is known (50, 40, 45). S4 demand is 60, 70 or 80
with probability 15%, 55%, 30%. S1 and S4 are priority stores (90% service, 70% probability),
every store gets 60% of its forecast (50, 40, 45, 55), and a unit short costs 20 at priority
stores and 10 elsewhere.

Variables, with the names the `.lp` file uses:

```
x_A_S1 … x_B_S4                 shipments (8)                       x on lane ℓ
expected_shortage_S1 … _S4      expected units short at each store  t_k
floor_relax_S1 … _S4            slack on the 60% floor              h_k
priority_relax_S1, _S4          slack on the priority rule          g_k
```

Write `q_S1 = x_A_S1 + x_B_S1` for the units S1 receives (likewise S2, S3, S4).

```
minimise   1 x_A_S1 + 2 x_A_S2 + 5 x_A_S3 + 6 x_A_S4          transport from A
         + 6 x_B_S1 + 5 x_B_S2 + 2 x_B_S3 + 1 x_B_S4          transport from B
         + 20 t_S1 + 10 t_S2 + 10 t_S3 + 20 t_S4               shortage penalty
         + 10000 (h_S1 + h_S2 + h_S3 + h_S4)                   floor relaxation
         + 100000 (g_S1 + g_S4)                                priority relaxation

subject to
  cap_A        x_A_S1 + x_A_S2 + x_A_S3 + x_A_S4  <= 130       DC limits
  cap_B        x_B_S1 + x_B_S2 + x_B_S3 + x_B_S4  <= 50

  floor_S1     q_S1 + h_S1  >= 30                              60% of forecast 50
  floor_S2     q_S2 + h_S2  >= 24                              60% of 40
  floor_S3     q_S3 + h_S3  >= 27                              60% of 45
  floor_S4     q_S4 + h_S4  >= 33                              60% of 55

  epi          q_S1 + t_S1  >= 50                              t ≥ shortfall, demand 50
  epi          q_S2 + t_S2  >= 40
  epi          q_S3 + t_S3  >= 45
  epi          q_S4 + t_S4  >= 71.5                            three pieces of
  epi     0.85 q_S4 + t_S4  >= 62.5                            E[(D − q)⁺] for S4
  epi     0.30 q_S4 + t_S4  >= 24

  chance_S1    q_S1 + g_S1  >= 45                              90% of 50
  chance_S4    q_S4 + g_S4  >= 63                              90% of 70: see below

  all variables >= 0
```

Where the S4 numbers come from:

- **Expected shortage.** One row per demand value, from the lowest up:
  `t ≥ (sum of p·v over demands ≥ that value) − (sum of p over them) · q`.
  From 60: 0.15·60 + 0.55·70 + 0.30·80 = 71.5, with slope 1.
  From 70: 38.5 + 24 = 62.5, slope 0.85. From 80: 24, slope 0.30.
  The largest of the three is the expected shortfall at that q.
- **Priority rule.** S4 meets 90% of demand D when q ≥ 0.9·D. The candidates are 0.9 × (60, 70, 80)
  = 54, 63, 72, which succeed with probability 15%, 70%, 100%. The smallest that reaches 70% is 63.
  At τ = 95% it would be 72, the only change in `replan_toy_tau095.lp`.

The solution (HiGHS and the page agree):

| | S1 | S2 | S3 | S4 | |
|---|---|---|---|---|---|
| From A | 50 | 33 | 27 | 20 | uses all 130 |
| From B | 0 | 0 | 0 | 50 | uses all 50 |
| Received $`q`$ | 50 | 33 | 27 | 70 | |
| Expected shortage $`t`$ | 0 | 7 | 18 | 3 | S4: 30% chance of being 10 short |

Transport is 50 + 66 + 135 + 120 + 50 = **421** (slide 20's figure). The shortage penalty is
10·7 + 10·18 + 20·3 = 310, so the objective is **731**. No slack is used.

Why this plan: B's 50 units all go to S4, its cheapest lane. A's 130 units are the bottleneck and
go where each unit saves the most penalty for its cost:

| Use of one unit from A | Penalty saved | Cost | Net |
|---|---|---|---|
| S1, up to 50 | 20 | 1 | 19 |
| S4, from 50 to 70 (demand ≥ 70 with probability 85%) | 20 × 0.85 = 17 | 6 | 11 |
| S2, up to 40 | 10 | 2 | 8 |
| S3, up to 45 | 10 | 5 | 5 |
| S4, above 70 (demand is 80 with probability 30%) | 20 × 0.30 = 6 | 6 | 0 |

So A sends 50 to S1 and 20 to S4. S3 gets only its floor of 27, because the floor is required.
The remaining 33 go to S2. At τ = 95% the rule forces S4 up to 72, so S2 drops to 31 and the
objective rises to 747.

### Variants solved by the page

- **Most-likely-world plan** (mode `mpe`): find the configuration and per-key demand values with
  the highest probability (`mpeQuery`). Replace every key's distribution by a point mass at that
  demand, and set $`\theta_k = f_{k\kappa^*} D^*_k`$. Same LP otherwise.
- **Value of capacity**: re-solve the `mmap` LP with $`K_d`$ raised by one step (1 unit in the toy,
  1,000 in the storm network) for each DC in turn. Report the change in expected cost.
- **Lane closure check** ("Can we still meet the Texas rule if the CA lane closes?"): condition the
  model on the closure (which also shifts the storm posterior) and drop the CA→TX lanes. Then score
  the current plan without its CA→TX shipments (no LP), and re-solve the `mmap` LP for a new plan.

### How plans are scored (no LP)

`evaluatePlan` computes, for any plan (the solver's, the most-likely-world plan, or one written by
the LLM): transport $`\sum \kappa_\ell x_{\ell c}`$, expected shortfall penalty
$`\sum_k \rho_k \mathbb E[(D_k - q_k)^+]`$, per-key rule probability $`P_k(q_k)`$, and the joint probability
$`\sum_\kappa w_\kappa \prod_{k \in P} \Pr_\kappa(D_k \le q_k / f_{k\kappa})`$, which is exact under the
mixture model. The backtest then draws 2,000 weeks from the mixture (seeded mulberry32) and counts
how often each plan meets the rule.

### Check: the toy preset

The toy is the network from the tag-up slides. Solving the LP at $`\tau = 0.7`$ and $`\tau = 0.9`$ gives
transport costs 421 and 429, matching slide 20; the page checks this on its Model tab.

---

## 3. Forecast comparison: an integer program, solved by enumeration

**In plain words.** Three stores share one stock budget. The page learns demand from the first 70%
of the observed dates, then picks stock levels two ways: from the average demand (a point
forecast), and from all training observations (a distribution). Each must cover 90% of demand at
all three stores in at least 95% of the observations. The plans are then scored on the remaining
30% of dates. It searches a grid of stock levels instead of calling a solver.

The shared "Forecasting, translation, and decisions" section stocks three stores under one total
capacity. It picks stock levels $`x = (x_1, x_2, x_3)`$ by exhaustive search:

- Candidate levels per store: $`\lceil \beta \bar d_j \rceil`$ (base floor of the training mean), and
  for every sample $`\lceil \gamma d_j \rceil`$, $`\lfloor d_j \rfloor`$, $`\lceil d_j \rceil`$, each raised
  to at least the base floor.
- Feasible: $`x_1 + x_2 + x_3 \le`$ capacity, and the share of samples with
  $`x_j \ge \gamma d_j`$ for all $`j`$ is at least 0.95. Under "independent marginals" it is the product
  of the per-store shares.
- Cost: $`\sum_j x_j + 8 \cdot \text{mean}_{\text{samples}} \sum_j (d_j - x_j)^+`$; the cheapest
  feasible candidate wins.

Here $`\gamma`$ is the priority floor (0.8 when an emergency is declared), $`\beta`$ the base floor,
and the samples are the training rows (or only the training mean for the point forecast).

**As an integer program.** With samples $`d^{(n)}`$, $`n = 1..N`$ (each of mass $`1/N`$), shortage
variables $`s_{nj} \ge 0`$, and binaries $`v_n`$ for the joint rule:

```math
\begin{aligned}
\min\quad & \textstyle\sum_j x_j + \frac{8}{N} \sum_{n,j} s_{nj} \\
\text{s.t.}\quad
& \textstyle\sum_j x_j \le \text{capacity}, \qquad x_j \ge \beta \bar d_j \\
& x_j + s_{nj} \ge d^{(n)}_j && \forall n, j \\
& x_j + \gamma d^{(n)}_j\, v_n \ge \gamma d^{(n)}_j && \forall n, j \\
& \textstyle\frac{1}{N} \sum_n v_n \le 0.05, \qquad x_j \in \mathbb Z_{\ge 0},\ v_n \in \{0, 1\} .
\end{aligned}
```

For the point forecast, $`N = 1`$ with the training mean as the only sample, and the rule is a hard
constraint ($`v`$ fixed to 0). The "independent marginals" option (a product of per-store shares)
has no linear form like this.

**The page's search is not always optimal for this program.** It only tries the candidate levels
above, the points where one store's cost or rule changes. When the capacity binds, the best
integer plan can sit between candidate levels, and the page returns a costlier plan. A
brute-force check over all integer plans on the bundled data (3 datasets × 2 rule sets ×
capacities 150, 175, 200, 220, 240, 300 × point and distribution) found 8 such cases. All were at
capacity 150 or 200, and in every one the true optimum used the full capacity. For example, correlated data, reference rules, capacity 150, point
forecast: the page picks 36 / 55 / 59 at cost 227.00; the integer optimum is 36 / 50 / 64 at
224.57. At the default capacity, 240, the page and the integer program agree.

---

## Cross-check with the solver-ready instances

The `PILLAR_Solver_Models` package (October 2026) contains `.lp`/`.mps` files with HiGHS results.
Checked against the models the original pages build (via the exact Python port):

| Instance | Result |
|---|---|
| `replan_toy_tau070`, `replan_toy_tau095`, `replan_storm_tau090`, `replan_storm_tau095` | Constraint matrix, bounds and objective identical to `solvePlan`'s, row for row; objectives 731, 747, 281,839.58, 281,839.58 agree |
| `copilot_*` subset LPs (4 files) | Rows and objective identical to the page's LP for that subset; the backup limit is a variable bound instead of a row, which is equivalent. Same status and optimum (747, 731, infeasible, 742) |
| `copilot_*_exact_milp` (3 files) | Same optimum as the page's 8-subset search: 731, infeasible, 742 |
| `stocking_point_integer` | Same optimum as the page's search: 160.43, plan 40 / 55 / 65. At capacity 240 the capacity does not bind; at tighter capacities the page's search can return a costlier plan than this program (see section 3) |
| `stocking_joint_integer_milp` | Same optimum, 242.14, but a different optimal plan: 57 / 81 / 97 where the page picks 57 / 81 / 95. The page's held-out violation rate and test cost are for its own plan |

The package's instances fix the default parameters (no evidence observed, default penalties,
service 0.9, no exception). Other settings need regenerated files.
