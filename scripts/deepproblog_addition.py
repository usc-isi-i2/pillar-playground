"""DeepProbLog-style "MNIST addition" with tididi as the circuit and PyTorch as the network.

The ProbLog program this mirrors:

    nn(digit_net, [X], D, [0..9]) :: digit(X, D).
    addition(X, Y, S) :- digit(X, A), digit(Y, B), S is A + B.

The network only ever sees the *sum* of two digit images, never a digit label.
Inference is weighted model counting on a compiled circuit:

1. Each image's digit is an annotated disjunction: ten Boolean variables with
   an exactly-one constraint. Image 1 uses variables 1..10, image 2 uses 11..20.
2. For each sum s in 0..18, compile the query circuit
   OR over a+b=s of (digit1=a AND digit2=b), conjoined with both exactly-one constraints.
   This is done once, before training.
3. During training, evaluate each circuit with a probability algebra whose
   values are torch tensors. Each value is a [batch] tensor: positive literal ->
   network probability, negative literal -> 1. The result is
   P(sum = s) for the whole batch, and autograd backpropagates through the
   circuit's sums and products into the network.

Run it in this repo's environment (see the README). From the repo root:

    python scripts/deepproblog_addition.py

The images are scikit-learn's 1,797 real handwritten digits (8x8 pixels), which
ship inside the scikit-learn package, so the script needs no download.
"""

from fractions import Fraction

import torch
from torch import nn

import tididi

N = 10  # digits 0..9
FEATURES = 64  # 8x8 pixels


def var(slot: int, digit: int) -> int:
    """Boolean variable for "image `slot` shows `digit`" (slot 0 -> 1..10, slot 1 -> 11..20)."""
    return 1 + slot * N + digit


def exactly_one(vtree: tididi.Vtree, variables: list[int]) -> tididi.Circuit:
    f = tididi.clause(vtree, variables)
    for i, a in enumerate(variables):
        for b in variables[i + 1:]:
            f = f & tididi.clause(vtree, [-a, -b])
    return f


def compile_queries() -> list[tididi.Circuit]:
    """One circuit per possible sum, all over one shared vtree."""
    digit1 = [var(0, d) for d in range(N)]
    digit2 = [var(1, d) for d in range(N)]
    # Keep each image's variables together: the vtree's root splits image 1 from image 2.
    vtree = tididi.Vtree.join(tididi.Vtree.balanced_over(digit1), tididi.Vtree.balanced_over(digit2))
    domain = exactly_one(vtree, digit1) & exactly_one(vtree, digit2)

    queries = []
    for s in range(2 * N - 1):
        worlds = [tididi.cube(vtree, [var(0, a), var(1, s - a)]) for a in range(N) if 0 <= s - a < N]
        # Boolean operations consume their operands, so conjoin with a copy of the domain.
        queries.append(tididi.or_many(worlds) & domain.copy())
    return queries


class TorchProbability:
    """Probability algebra over batched tensors, satisfying tididi's Algebra protocol.

    A positive literal weighs its network probability and a negative literal weighs 1.
    Under the exactly-one constraint each world's weight is then p1[a] * p2[b],
    which gives annotated-disjunction semantics. A free variable must equal
    add(leaf(False), leaf(True)), which here is 1 + p.
    """

    def __init__(self, probs: torch.Tensor):  # probs: [batch, 2, N]
        self.probs = probs
        self.ones = torch.ones_like(probs[:, 0, 0])

    def zero(self):
        return torch.zeros_like(self.ones)

    def leaf(self, variable: int, sign: bool | None):
        slot, digit = divmod(variable - 1, N)
        p = self.probs[:, slot, digit]
        if sign is None:
            return self.ones + p
        return p if sign else self.ones

    def add(self, a, b):
        return a + b

    def mul(self, a, b):
        return a * b


def sum_probabilities(queries, probs: torch.Tensor) -> torch.Tensor:
    """[batch, 19] tensor of P(sum = s), differentiable with respect to `probs`."""
    algebra = TorchProbability(probs)
    return torch.stack([q.evaluate(algebra) for q in queries], dim=1)


def check_against_exact(queries) -> None:
    """Compare the torch algebra with tididi's exact rational weighted count."""
    p1 = [Fraction(d + 1, 55) for d in range(N)]
    p2 = [Fraction(N - d, 55) for d in range(N)]
    weights = {var(0, d): (Fraction(1), p1[d]) for d in range(N)}
    weights |= {var(1, d): (Fraction(1), p2[d]) for d in range(N)}
    probs = torch.tensor([[[float(p) for p in p1], [float(p) for p in p2]]], dtype=torch.float64)

    approx = sum_probabilities(queries, probs)[0]
    for s, q in enumerate(queries):
        exact = q.weighted_count(weights)
        expected = sum(p1[a] * p2[s - a] for a in range(N) if 0 <= s - a < N)
        assert exact == expected, (s, exact, expected)
        assert abs(float(exact) - approx[s].item()) < 1e-12, (s, exact, approx[s].item())
    assert abs(approx.sum().item() - 1) < 1e-12
    print("check: torch evaluation matches tididi's exact weighted count; sums total 1")


def load_digit_images() -> tuple[torch.Tensor, torch.Tensor]:
    """scikit-learn's handwritten digits: [1797, 64] pixels scaled to 0..1, and their true digits."""
    from sklearn.datasets import load_digits

    digits = load_digits()
    return torch.tensor(digits.data, dtype=torch.float32) / 16, torch.tensor(digits.target)


def make_pairs(n: int, images: torch.Tensor, labels: torch.Tensor, gen: torch.Generator):
    """n random pairs of images from the pool, with their true digits."""
    picks = torch.randint(0, len(images), (n, 2), generator=gen)
    return images[picks], labels[picks]


def main() -> None:
    torch.manual_seed(0)
    gen = torch.Generator().manual_seed(0)

    queries = compile_queries()
    sizes = [q.pair_count() for q in queries]
    print(f"compiled {len(queries)} query circuits, {min(sizes)}..{max(sizes)} pairs each")
    check_against_exact(queries)

    # Split the images first, so no test pair reuses an image seen in training.
    images, labels = load_digit_images()
    order = torch.randperm(len(images), generator=gen)
    train_pool, test_pool = order[:1300], order[1300:]
    train_x, train_digits = make_pairs(3000, images[train_pool], labels[train_pool], gen)
    test_x, test_digits = make_pairs(1000, images[test_pool], labels[test_pool], gen)
    train_sums = train_digits.sum(dim=1)  # the only supervision
    test_sums = test_digits.sum(dim=1)

    net = nn.Sequential(nn.Linear(FEATURES, 64), nn.ReLU(), nn.Linear(64, N))
    optimizer = torch.optim.Adam(net.parameters(), lr=1e-3)

    def digit_probs(x: torch.Tensor) -> torch.Tensor:  # [batch, 2, FEATURES] -> [batch, 2, N]
        return net(x.reshape(-1, FEATURES)).softmax(dim=-1).reshape(-1, 2, N)

    batch = 32
    for epoch in range(1, 6):
        net.train()
        total = 0.0
        for i in torch.randperm(len(train_x)).split(batch):
            p_sum = sum_probabilities(queries, digit_probs(train_x[i]))
            p_label = p_sum.gather(1, train_sums[i, None]).squeeze(1)
            loss = -p_label.clamp_min(1e-12).log().mean()
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total += loss.item() * len(i)

        net.eval()
        with torch.no_grad():
            probs = digit_probs(test_x)
            sum_acc = (sum_probabilities(queries, probs).argmax(dim=1) == test_sums).float().mean()
            digit_acc = (probs.argmax(dim=-1) == test_digits).float().mean()
        print(f"epoch {epoch}: loss {total / len(train_x):.4f}  "
              f"test sum acc {sum_acc:.3f}  test digit acc {digit_acc:.3f} (never trained on digits)")


if __name__ == "__main__":
    main()
