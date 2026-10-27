# pillar-playground

Learning material and experiments for using [tididi](https://github.com/Tractables/tididi) circuits as
the engine behind ProbLog and DeepProbLog. Everything here is built around one problem: two
handwritten digit images, labelled only with their sum.

## What's here

Read and run them in this order.

| Step | Doc | Notebook | What you get |
| --- | --- | --- | --- |
| 1 | [Learning guide](docs/learning-guide.md) | [`learning_guide.ipynb`](notebooks/learning_guide.ipynb) | The ideas from school probability up to tididi, in seven steps with exercises and answers |
| 2 | [How the digit-addition example works](docs/digit-addition-explained.md) | [`digit_addition.ipynb`](notebooks/digit_addition.ipynb) | One problem solved four ways: by hand with probability, ProbLog, DeepProbLog and tididi |
| 3 | [Practice guide](docs/practice-guide.md) | [`practice.ipynb`](notebooks/practice.ipynb) | A tididi tutorial, worked examples and nine problems to solve yourself |

The digit-addition notebook is organised as:

1. **Problem description**: the digit images and the two questions (inference and learning).
2. **Probability solution**: possible worlds, multiply and add.
3. **ProbLog solution**: the rule as a logic program, and the ground formula ProbLog builds.
4. **DeepProbLog solution**: the digit chances come from a network, which learns from sums alone.
5. **tididi solution**: the same circuits built by hand with tididi, and trained through.

Scripts:

- [`scripts/deepproblog_addition.py`](scripts/deepproblog_addition.py): the tididi solution as one script.
- [`scripts/make_doc_images.py`](scripts/make_doc_images.py): redraws the data-based pictures in `docs/images`.

Demos: [`demos/`](demos/README.md) holds two supply-planning demos, PILLAR Replan and Circuit Copilot,
with a Python (FastAPI) backend and a TypeScript (Vite) front end. They do not use tididi. See its
README to run them.

## Setup

This repo has its own Python environment, separate from tididi's. It expects the
[tididi](https://github.com/Tractables/tididi) repo checked out next to it, because tididi's Python
binding is not on PyPI and is built from source (this needs a Rust toolchain).

```sh
cd pillar-playground
python3 -m venv .venv                      # Python 3.10 or newer
source .venv/bin/activate
python -m pip install -r requirements.txt
(cd ../tididi/bindings/python && maturin develop --release)   # builds tididi into .venv
jupyter lab
```

Rerun the `maturin develop --release` line whenever tididi's Rust code changes.

Optional: the practice notebook's `draw` helper needs [Graphviz](https://graphviz.org)
(`brew install graphviz` on macOS).

Tested with Python 3.10, torch 2.14, problog 2.3.0 and deepproblog 2.1.0. DeepProbLog's
`ApproximateEngine` needs SWI-Prolog; nothing here uses it, so its warning at import is harmless.
