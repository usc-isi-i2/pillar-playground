import time
import tididi as T
from compile import IntProgram
for n in (10, 20, 50):
    P = IntProgram(); P.int_var('Y', 0, n); P.int_var('A', 0, n); P.le([(1,'A'),(-1,'Y')], 0)
    for name, vt in [('linear', T.Vtree.linear(P.order)), ('balanced', T.Vtree.balanced_over(P.order)),
                     ('linear rev', T.Vtree.linear(P.order[::-1]))]:
        t=time.perf_counter(); c = P._row(vt, *P.rows[0][:2])
        print(n, name, 'nodes', c.node_count(), 'pairs', c.pair_count(), 'models', c.model_count(), f'{time.perf_counter()-t:.3f}s')
print(T.Vtree.linear([1,2,3,4]).to_text())
