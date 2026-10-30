import time, sys
import compile as C
P, _ = C.copilot_program(C.MODELS[sys.argv[1]])
import tididi as T
vt = T.Vtree.linear(P.order)
print('bool vars', len(P.order), {n: (lo, hi) for n, (lo, hi, _) in P.ints.items()})
for terms, K, unless in P.rows:
    t = time.perf_counter(); c = P._row(vt, terms, K)
    print(f'row {[f"{a}{x}" for a,x in terms]} <= {K}: nodes {c.node_count()} in {time.perf_counter()-t:.2f}s', flush=True)
