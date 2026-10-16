# Practice guide: DeepProbLog problems as tididi circuits

You turn small DeepProbLog programs into tididi circuits, then evaluate them as probabilities and as trainable PyTorch losses. The notebook has the exercises; this doc has the tutorial, worked examples and answers.

## How to use this guide

Work through the notebook [`notebooks/practice.ipynb`](../notebooks/practice.ipynb) from top to bottom, with this doc open beside it.

1. Read the tutorial and the recipe here, and run the matching notebook cells.
2. Run the four worked examples. Their full code is in the notebook.
3. Solve the nine problems. Each notebook cell has a `TODO`. Write down your guess before you run anything.
4. Check yourself with the notebook's `check` helper. It says whether your number matches a brute-force count, without showing the number.
5. Compare with **Answers** at the end of this doc. The notebook has no answers.

Run the notebook in this repo's environment; the [README](../README.md) says how to set it up.

Every example uses digit images that show 0, 1 or 2, with these network outputs:

| Image | P(0) | P(1) | P(2) |
| --- | --- | --- | --- |
| image 1 | 0.7 | 0.2 | 0.1 |
| image 2 | 0.1 | 0.8 | 0.1 |
| image 3 | 0.3 | 0.3 | 0.4 |

## tididi tutorial

tididi builds circuits (Tree Decision Diagrams) for true/false formulas. Every circuit it builds is decomposable and deterministic, so weighted counting takes one pass over the circuit, never a list of worlds.

### 1. Variables and the vtree

Variables are positive integers: `3` means "variable 3 is true" and `-3` means "variable 3 is false". A **vtree** is a binary tree over the variables that decides how circuits are laid out. Every circuit you combine must share one vtree.

```python
import tididi

vt = tididi.Vtree.balanced(3)                        # variables 1, 2, 3
vt = tididi.Vtree.balanced_over([1, 2, 3])           # the same, from a list
vt = tididi.Vtree.join(tididi.Vtree.balanced_over([1, 2, 3]),
                       tididi.Vtree.balanced_over([4, 5, 6]))   # group 1-3 apart from 4-6
print(vt.variables)                                   # [1, 2, 3, 4, 5, 6]
```

The vtree changes a circuit's size, never its meaning. Problem 9 measures that.

### 2. Building circuits

```python
x = tididi.literal(vt, 1)                 # variable 1 is true
not_y = tididi.literal(vt, -2)            # variable 2 is false
both = tididi.cube(vt, [1, -2])           # 1 AND NOT 2
either = tididi.clause(vt, [1, 2])        # 1 OR 2
f = (x & not_y) | tididi.literal(vt, 3)   # & is AND, | is OR, ^ is XOR, ~ is NOT
g = tididi.or_many([tididi.cube(vt, [1, 2]), tididi.cube(vt, [3])])   # OR of a list
true_circuit, false_circuit = tididi.one(vt), tididi.zero(vt)
```

Use `&`, `|`, `^` and `~`, with parentheses. Python's `and`, `or` and `not` don't build circuits; tididi raises `TypeError` if you try.

### 3. Operations use up their inputs

An operation such as `a & b` **consumes** `a` and `b`: afterwards only the result is usable. Call `.copy()` to keep an input.

```python
a = tididi.literal(vt, 1)
b = tididi.literal(vt, 2)
both = a.copy() & b        # a is still usable; b is consumed
print(a.is_consumed, b.is_consumed)   # False True
```

Queries such as `model_count` and `weighted_count` only read a circuit, so you can repeat them. Using a consumed circuit raises `ConsumedCircuitError`, and `a & a` is refused: write `a.copy() & a`.

### 4. Asking questions

```python
f.model_count()            # number of satisfying assignments over ALL vtree variables
f.is_sat()                 # is there at least one?
f.satisfying_assignment()  # one of them, as Literal objects
f.equivalent(g)            # same function?
f.implies(g)               # every model of f is a model of g?
f.support()                # the variables f actually depends on
```

`model_count` includes variables the formula leaves free: `literal(vt, 1)` over three variables has 4 models, not 1. This is Exercise 5b from the [learning guide](learning-guide.md), in tididi.

### 5. Weights and probabilities

`weighted_count` takes `{variable: (weight when false, weight when true)}` and returns an exact `Fraction`. It needs a weight for **every** variable in the vtree, or it raises `ValueError`.

```python
from fractions import Fraction as F

alarm = tididi.literal(vt, 1) | tididi.literal(vt, 2)      # vt has variables 1, 2, 3
weights = {1: (F("0.9"), F("0.1")), 2: (F("0.8"), F("0.2")), 3: (F("0.5"), F("0.5"))}
alarm.weighted_count(weights)                              # 7/25 = 0.28
alarm.weighted_count(weights | {3: (1, 1)})                # 14/25: free variable 3 now weighs 2
```

Two weight patterns cover everything in this guide:

- **Ordinary fact** `p::f`: weights `(1 - p, p)`. A free variable then contributes (1 − p) + p = 1, so it can't change the answer.
- **Neural choice**, one switch per option: weights `(1, p)`, and the circuit must include the exactly-one rule for that choice. A free switch would contribute 1 + p, so every switch must be constrained.

In the snippet above, variable 3 is free. With probability weights it contributes 0.5 + 0.5 = 1; with (1, 1) it doubles the answer. Give a variable you don't use `(1 - p, p)`, or leave it out of the vtree.

### 6. Evidence

For P(query | evidence), conjoin the evidence and divide:

```python
joint = (query.copy() & evidence.copy()).weighted_count(weights)
answer = joint / evidence.weighted_count(weights)
```

When the evidence is a few literals that keep changing, an `Evaluator` reuses work: `ev = query.evaluator(weights)`, then `ev.observe([5])` and `ev.value()` give the joint P(query and variable 5). Observing keeps that literal's own weight and zeroes out its opposite. `ev.clear_observations()` undoes it, and `query = ev.finish()` gives the circuit back.

### 7. Your own arithmetic: algebras

`circuit.evaluate(algebra)` walks the circuit with any object that has four methods. Products happen at AND, sums at OR:

```python
class Algebra:
    def zero(self): ...                    # value of an impossible branch
    def leaf(self, variable, sign): ...    # sign True / False: that literal's weight
                                           # sign None: a free variable; must equal
                                           # add(leaf(v, False), leaf(v, True))
    def add(self, a, b): ...
    def mul(self, a, b): ...
```

With PyTorch tensors as values, the result is differentiable: that's how DeepProbLog trains a network through a circuit (Example 4). With `max` instead of `+`, you get the most likely world instead of a probability (Problem 7).

### 8. Looking at a circuit

`node_count()` and `pair_count()` measure size. `to_dot()` returns Graphviz text you can paste into any Graphviz viewer to see the diagram.

## Useful classes and methods

These are the parts of tididi's Python API this guide uses. Everything else is in tididi's type stubs, `tididi/bindings/python/tididi/__init__.pyi` in the tididi repo.

| Name | What it does | Used in |
| --- | --- | --- |
| `Vtree.balanced(n)` | Vtree over variables 1..n | Tutorial |
| `Vtree.balanced_over(vars)` | Vtree over the listed variables | Helpers |
| `Vtree.join(left, right)` | Vtree with `left` and `right` as its two halves; keeps each group together | Helpers, Problem 9 |
| `Vtree.leaf(v)` | Vtree holding one variable, to join in an extra fact | Problem 4 |
| `Vtree.linear(vars)` | Chain-shaped vtree in the given order | Problem 9 |
| `literal(vt, v)` | Circuit for v (or ¬v when v is negative) | Everywhere |
| `cube(vt, [v, ...])` | AND of literals: one world of the chosen digits | Every query |
| `clause(vt, [v, ...])` | OR of literals | Exactly-one rule |
| `one(vt)`, `zero(vt)` | Always true, always false | Helpers |
| `or_many([c, ...])` | OR of many circuits, in one call | Every query |
| `&`, `\|`, `^`, `~` | AND, OR, XOR, NOT (consume their inputs) | Everywhere |
| `c.copy()` | Copy, so an input survives an operation | Everywhere |
| `c.model_count()` | Number of satisfying assignments, free variables included | Problems 2, 6 |
| `c.weighted_count(w)` | Exact sum of weight products; `w` maps every variable to (false, true) | Every answer |
| `c.evaluator(w)` | Reusable evaluator: `observe`, `value`, `clear_observations`, `finish` | Example 3 |
| `c.evaluate(algebra)` | One pass with your own `zero`, `leaf`, `add`, `mul` | Example 4, Problems 7, 8 |
| `c.satisfying_assignment()` | One model, as `Literal` objects | Debugging |
| `c.equivalent(d)`, `c.implies(d)` | Compare two functions | Debugging |
| `c.pair_count()`, `c.node_count()` | Circuit size | Problem 9 |
| `c.to_dot()` | Graphviz text of the diagram | Looking at a circuit |
| `ConsumedCircuitError` | Raised when you reuse a consumed circuit | Debugging |

The notebook adds a few helpers of its own, built only from the calls above:

| Helper | What it does |
| --- | --- |
| `var(image, digit)` | Switch variable for "image shows digit": image 0 uses 1–3, image 1 uses 4–6, image 2 uses 7–9 |
| `exactly_one(vt, vars)` | Exactly one of `vars` is true: one clause plus a "not both" clause per pair |
| `digit_vtree(images, extra=())` | Joins one vtree group per image, then any extra fact variables |
| `domain(vt, images)` | AND of the exactly-one rules for every image |
| `where(vt, images, condition)` | OR of the cubes for every digit combination where `condition(digits)` holds; no domain |
| `digit_weights(probs)` | Switch weights `(1, p)` for the digit variables |
| `fact_weights({v: p})` | Ordinary-fact weights `(1 - p, p)` |
| `check(value, condition, ...)` | Compares your value with a brute-force count and says match or no match, without the number |

## Recipe: from a DeepProbLog program to a tididi circuit

Every problem below follows the same seven steps. The rule that catches people out is step 5: **add the exactly-one domain last, after any negation.**

| DeepProbLog | tididi |
| --- | --- |
| `nn(net, [X], D, [0, 1, 2]) :: digit(X, D).` | Three switch variables per image, weights `(1, p)`, plus `exactly_one` for that image |
| `nn(net, [X]) :: cat(X).` (one probability) | One variable, weights `(1 - p, p)`, no exactly-one |
| `0.2::typo.` | One variable, weights `(1 - p, p)` |
| A rule body: `digit(X, A), digit(Y, B), A + B =:= 2` | `or_many` of one `cube` per digit combination that satisfies it |
| Two rules for the same head | `\|` of their circuits |
| `\+ goal` (negation) | `~` of the goal's circuit, before the domain is added |
| Evidence, P(q \| e) | `weighted_count(q & e) / weighted_count(e)` |

1. **Number the variables.** One switch per (image, digit) with `var(image, digit)`, then one variable per ordinary fact after them.
2. **Build the vtree.** Keep each image's switches together with `Vtree.join`; `digit_vtree` does this. Join each extra fact on with `Vtree.leaf`.
3. **Ground the rule.** List every digit combination that makes the body true, and OR their cubes: `where(vt, images, condition)`.
4. **Combine with the other facts** using `&`, `|` and `~`.
5. **Add the domain last:** `circuit & domain(vt, images)`. Negating a circuit that already contains the domain lets in impossible worlds where an image shows two digits, or none. Problem 4 shows the damage.
6. **Weigh every variable:** `(1, p)` for switches, `(1 - p, p)` for ordinary facts.
7. **Evaluate.** `weighted_count` gives the exact probability. `evaluate` with a PyTorch algebra gives a differentiable one for training. A conditional is a ratio of two counts.

Why step 6 has two patterns: under the exactly-one rule, each image has exactly one switch on. An off switch must weigh 1, so that a world's weight is exactly p₁(a) · p₂(b). An ordinary fact is a real coin, so both sides count: (1 − p, p).

## Worked examples

Each example is a DeepProbLog program, its tididi circuit and the result. The notebook runs the same code.

### Example 1: addition

```prolog
nn(digit_net, [X], D, [0, 1, 2]) :: digit(X, D).
addition(X, Y, S) :- digit(X, A), digit(Y, B), S is A + B.
query(addition(img1, img2, 2)).
```

```python
vt = digit_vtree(2)
sum_is_2 = where(vt, 2, lambda d: d[0] + d[1] == 2) & domain(vt, 2)
weights = digit_weights([IMAGE1, IMAGE2])
show(sum_is_2.weighted_count(weights))
print("worlds:", sum_is_2.model_count(), " size:", sum_is_2.pair_count(), "pairs")
```

**Result: 6/25 = 0.24**, over 3 worlds: (0, 2), (1, 1) and (2, 0). By hand: 0.7 × 0.1 + 0.2 × 0.8 + 0.1 × 0.1 = 0.07 + 0.16 + 0.01.

### Example 2: a comparison

```prolog
less_than(X, Y) :- digit(X, A), digit(Y, B), A < B.
query(less_than(img1, img2)).
```

```python
less_than = where(vt, 2, lambda d: d[0] < d[1]) & domain(vt, 2)
show(less_than.weighted_count(weights))
```

**Result: 13/20 = 0.65.** Only the rule's condition changed; the domain and the weights are the same. By hand: P(image 1 = 0) × P(image 2 ≥ 1) + P(image 1 = 1) × P(image 2 = 2) = 0.7 × 0.9 + 0.2 × 0.1.

### Example 3: evidence

The label says the sum is 2. How likely is it that image 1 shows a 0?

```python
first_is_0 = tididi.literal(vt, var(0, 0))
joint = (sum_is_2.copy() & first_is_0).weighted_count(weights)
show(joint / sum_is_2.weighted_count(weights))          # P(digit1 = 0 | sum = 2)

ev = sum_is_2.copy().evaluator(weights)
ev.observe([var(0, 0)])
show(ev.value())                                          # the joint, P(sum = 2 and digit1 = 0)
```

**Result: 7/24 ≈ 0.2917**; the evaluator prints the joint, **7/100 = 0.07**. The network alone said 0.7 for a 0. The label rules out most of that, since (0, 2) needs image 2 to be a 2, and the network gives that only 0.1.

### Example 4: training through the circuit

The circuit stays fixed while the network's probabilities change, so compile once and evaluate with tensors:

```python
class TorchProbability:
    """tididi algebra over tensors: switch on -> p, off -> 1, free -> 1 + p."""

    def __init__(self, probs: torch.Tensor):   # probs[image, digit]
        self.probs = probs

    def zero(self) -> torch.Tensor:
        return torch.tensor(0.0)

    def leaf(self, variable: int, sign: bool | None) -> torch.Tensor:
        image, digit = divmod(variable - 1, N)
        p = self.probs[image, digit]
        if sign is None:
            return 1 + p
        return p if sign else torch.tensor(1.0)

    def add(self, a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
        return a + b

    def mul(self, a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
        return a * b


logits = torch.tensor([[2.0, 0.7, 0.0], [0.0, 2.1, 0.0]], requires_grad=True)
p = less_than.evaluate(TorchProbability(logits.softmax(dim=1)))
loss = -p.log()
loss.backward()
with torch.no_grad():
    logits -= 0.5 * logits.grad
```

**Result:** P(digit1 < digit2) = 0.6595 before the step and 0.6974 after it. These logits are the learning guide's, so the softmax only approximates 0.7 / 0.2 / 0.1. The gradients are:

|  | digit 0 | digit 1 | digit 2 |
| --- | --- | --- | --- |
| image 1 | −0.2608 | +0.1647 | +0.0961 |
| image 2 | +0.0984 | −0.0619 | −0.0365 |

A step moves *against* the gradient. So image 1 is pushed towards 0 and image 2 towards 1 or 2: exactly what makes "image 1 < image 2" more likely.

## Problems

Guess first, then build the circuit in the notebook and run `check`. Problems 1–5 practise the recipe; 6–9 go past it.

### Problem 1: product

```prolog
product(X, Y, P) :- digit(X, A), digit(Y, B), P is A * B.
query(product(img1, img2, 0)).
```

Find P(product = 0) for images 1 and 2.

### Problem 2: three images

```prolog
sum3(X, Y, Z, S) :- digit(X, A), digit(Y, B), digit(Z, C), S is A + B + C.
query(sum3(img1, img2, img3, 3)).
```

Find P(sum = 3) for images 1, 2 and 3. Before you run it, say how many worlds the circuit should have.

### Problem 3: which digit, given the sum?

The label says image 1 + image 2 = 3. Find P(image 1 shows a 2 | sum = 3).

### Problem 4: a noisy label

The person labelling the data writes "even" or "odd" for the sum, but makes a typo 20% of the time:

```prolog
0.2::typo.
even_sum(X, Y) :- digit(X, A), digit(Y, B), (A + B) mod 2 =:= 0.
reported_even(X, Y) :- even_sum(X, Y), \+ typo.
reported_even(X, Y) :- \+ even_sum(X, Y), typo.
```

Find P(reported_even(img1, img2)). Give `typo` variable 7. Follow the recipe's step 5 and step 6 exactly: this is where they matter.

### Problem 5: a yes/no network

A network outputs one probability per image instead of a choice between digits:

```prolog
nn(cat_net, [X]) :: cat(X).
one_cat(X, Y) :- cat(X), \+ cat(Y).
one_cat(X, Y) :- \+ cat(X), cat(Y).
```

The network gives 0.9 for image 1 and 0.3 for image 2. Find P(one_cat(img1, img2)). Then say what goes wrong with switch weights `(1, p)` here, and why.

### Problem 6: find the bug

This is meant to be Example 1's circuit, but the answer is wrong:

```python
vt = digit_vtree(2)
worlds = [tididi.cube(vt, [var(0, a), var(1, 2 - a)]) for a in range(3)]
buggy = tididi.or_many(worlds) & exactly_one(vt, [var(0, d) for d in range(N)])
```

Before you run it: is its weighted count too big or too small, and how many worlds does it have instead of 3? Then run it, and fix it.

### Problem 7: the most likely explanation

The label says the sum is 2. Which pair of digits is the single most likely explanation, and how likely is that world? Write an algebra whose values are `(weight, assignment)` pairs. `mul` multiplies the weights and joins the assignments; `add` keeps the larger. Evaluate Example 1's circuit with it.

### Problem 8: two labels for the same pair

Start both images at uniform probabilities (`logits = torch.zeros(2, 3, requires_grad=True)`). Train with plain SGD, learning rate 1, for 200 steps, on the loss −log P(sum = 2) − log P(image 1 < image 2).

1. Which digit does each image end up on, and why?
2. Now train from zeros on −log P(sum = 2) alone. What happens, and why?

### Problem 9: does the vtree matter?

Use 10 digits per image (variables 1–10 for image 1, 11–20 for image 2), as in the [digit-addition example](digit-addition-explained.md). Build all 19 sum circuits, each with the domain, under two vtrees:

- **grouped:** `Vtree.join` of one group per image;
- **interleaved:** `Vtree.linear` over image 1 digit 0, image 2 digit 0, image 1 digit 1, image 2 digit 1, and so on.

Add up `pair_count()` over the 19 circuits for each vtree. Which is smaller, by roughly how much, and do the probabilities change?

## Answers

Every number below comes from running the solution code against tididi and matching it to a brute-force count.

| Problem | Answer |
| --- | --- |
| 1. Product = 0 | 73/100 = 0.73 |
| 2. Three images, sum = 3 | 167/500 = 0.334, over 7 worlds |
| 3. P(digit1 = 2 \| sum = 3) | 4/5 = 0.8 |
| 4. Reported even | 49/125 = 0.392 |
| 5. Exactly one cat | 33/50 = 0.66 |
| 6. Buggy circuit | 44/125 = 0.352 (too big), 12 worlds |
| 7. Most likely explanation of sum = 2 | (1, 1), weight 4/25 = 0.16 |
| 8. Two labels | Image 1 → 0, image 2 → 2; sum alone: no movement |
| 9. Vtree size | Grouped 1,432 pairs, interleaved 6,874 (4.8×); same probabilities |

### 1. Product

```python
product_0 = where(vt, 2, lambda d: d[0] * d[1] == 0) & domain(vt, 2)
show(product_0.weighted_count(weights))
```

The product is 0 unless both digits are non-zero: 1 − (0.2 + 0.1) × (0.8 + 0.1) = 1 − 0.27 = 0.73.

### 2. Three images

```python
vt3 = digit_vtree(3)
sum3 = where(vt3, 3, lambda d: sum(d) == 3) & domain(vt3, 3)
show(sum3.weighted_count(digit_weights([IMAGE1, IMAGE2, IMAGE3])))
print(sum3.model_count())
```

Seven worlds: the six orderings of (0, 1, 2), plus (1, 1, 1). The exactly-one rule leaves no free switches, so `model_count` really is the number of worlds.

### 3. Which digit, given the sum?

```python
sum_is_3 = where(vt, 2, lambda d: sum(d) == 3) & domain(vt, 2)
joint = (sum_is_3.copy() & tididi.literal(vt, var(0, 2))).weighted_count(weights)
show(joint / sum_is_3.weighted_count(weights))
```

Two worlds make 3: (1, 2) with 0.2 × 0.1 = 0.02, and (2, 1) with 0.1 × 0.8 = 0.08. So 0.08 / 0.10 = 0.8. On its own the network thought image 1 was a 2 with only 0.1, but image 2 looks so much like a 1 that (2, 1) explains the label best.

### 4. A noisy label

```python
TYPO = 7
vt4 = digit_vtree(2, extra=(TYPO,))
even = where(vt4, 2, lambda d: (d[0] + d[1]) % 2 == 0)        # no domain yet
typo = tididi.literal(vt4, TYPO)
reported_even = ((even.copy() & ~typo.copy()) | (~even & typo)) & domain(vt4, 2)
weights4 = digit_weights([IMAGE1, IMAGE2]) | fact_weights({TYPO: F("0.2")})
show(reported_even.weighted_count(weights4))
```

P(even sum) = P(0) + P(2) + P(4) = 0.07 + 0.24 + 0.01 = 0.32. Then 0.32 × 0.8 + 0.68 × 0.2 = 0.392.

The two traps, both measured:

- **Domain before the negation** (`even` built with `& domain(...)` and then `~even`): **1.1695**, more than 1. `~even` then also holds in every impossible world where an image shows two digits or none, and those worlds carry weight.
- **`typo` weighted `(1, 0.2)`**: **0.456**. A typo-free world should weigh 0.8, not 1.

### 5. A yes/no network

```python
vt5 = tididi.Vtree.balanced(2)                      # 1 = cat(img1), 2 = cat(img2)
one_cat = tididi.literal(vt5, 1) ^ tididi.literal(vt5, 2)
show(one_cat.weighted_count(fact_weights({1: F("0.9"), 2: F("0.3")})))
```

0.9 × 0.7 + 0.1 × 0.3 = 0.63 + 0.03 = 0.66. A single-probability network is an ordinary fact, so it needs `(1 - p, p)`. With `(1, p)` the answer is 0.9 + 0.3 = **1.2**: "not a cat" weighs 1 instead of 0.1 or 0.7. `(1, p)` is only right for switches held in check by an exactly-one rule.

### 6. Find the bug

The circuit has no exactly-one rule for image 2. In each of the 3 intended worlds, image 2's other two switches are free, so each world becomes 4: 3 × 4 = **12 worlds**. A free switch weighs 1 + p, so the total is **too big: 0.352**. For example, world (1, 1) becomes 0.2 × 0.8 × (1 + 0.1) × (1 + 0.1). Fix: `& domain(vt, 2)` instead of image 1's rule alone. The fixed circuit gives 0.24 again.

### 7. The most likely explanation

```python
class MaxProduct:
    """Values are (weight, assignment); add keeps the heavier, mul joins."""

    def __init__(self, weights: dict[int, tuple[F, F]]):
        self.weights = weights

    def zero(self) -> tuple[F, tuple]:
        return (F(0), ())

    def leaf(self, variable: int, sign: bool | None) -> tuple[F, tuple]:
        if sign is None:                              # free: take its heavier side
            off, on = self.weights[variable]
            return (off, ((variable, False),)) if off >= on else (on, ((variable, True),))
        return (self.weights[variable][sign], ((variable, sign),))

    def add(self, a: tuple, b: tuple) -> tuple:
        return a if a[0] >= b[0] else b

    def mul(self, a: tuple, b: tuple) -> tuple:
        return (a[0] * b[0], a[1] + b[1])


best, assignment = sum_is_2.evaluate(MaxProduct(weights))
print(best, [v for v, on in assignment if on])        # 4/25 [2, 5]
```

Variables 2 and 5 are image 1 = 1 and image 2 = 1, with weight 0.16. That's 2/3 of the evidence's 0.24, so (1, 1) is also the explanation that gets most of the gradient when training on "sum = 2".

### 8. Two labels for the same pair

```python
logits = torch.zeros(2, 3, requires_grad=True)
optimizer = torch.optim.SGD([logits], lr=1.0)
for step in range(200):
    probs = logits.softmax(dim=1)
    loss = (-sum_is_2.evaluate(TorchProbability(probs)).log()
            - less_than.evaluate(TorchProbability(probs)).log())
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
print(logits.softmax(dim=1))
```

1. Image 1 ends at 0.997 on digit 0, and image 2 at 0.997 on digit 2. Sum 2 allows (0, 2), (1, 1) and (2, 0); "image 1 < image 2" rules out the last two. Together the labels are proof of (0, 2), as with "sum = 4" in the learning guide.
2. With sum = 2 alone, nothing moves: every probability stays 1/3. At uniform probabilities, (0, 2), (1, 1) and (2, 0) all pull with equal force, so the gradient is exactly 0. An ambiguous label gives no signal until something breaks the tie: another label, a random start, or other training pairs.

### 9. Does the vtree matter?

Grouped: **1,432 pairs** in total; interleaved: **6,874 pairs**, about 4.8 times more. All 19 probabilities are identical under both. The vtree changes a circuit's size, never its meaning. Each exactly-one rule only talks about one image's switches, so keeping those switches together in the vtree keeps the rule compact. Interleaving makes the circuit track both images' choices at once.
