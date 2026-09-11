"""Detecção de comunidades (Louvain) com resolução ajustável.

Grafo não direcionado e ponderado. `resolution` > 1 produz mais blocos e
menores; < 1 produz menos e maiores.
"""

from collections import defaultdict


def louvain(nodes, weights, resolution=1.0, max_levels=10):
    """nodes: lista. weights: dict {(a,b): w} com a<b. Devolve {no: comunidade}."""
    node_map = {n: n for n in nodes}          # nó original -> nó atual (agregado)
    cur_nodes = list(nodes)
    cur_w = dict(weights)

    for _ in range(max_levels):
        comm, moved = _one_level(cur_nodes, cur_w, resolution)
        if not moved:
            break
        node_map = {n: comm[node_map[n]] for n in nodes}
        # agrega o grafo: cada comunidade vira um nó
        agg = defaultdict(float)
        for (a, b), w in cur_w.items():
            ca, cb = comm[a], comm[b]
            if ca == cb:
                continue                       # laços não afetam as próximas fusões
            k = (ca, cb) if ca < cb else (cb, ca)
            agg[k] += w
        new_nodes = sorted(set(comm.values()))
        if len(new_nodes) == len(cur_nodes):
            break
        cur_nodes, cur_w = new_nodes, dict(agg)

    return node_map


def _one_level(nodes, weights, resolution):
    adj = defaultdict(list)
    deg = defaultdict(float)
    m2 = 0.0
    for (a, b), w in weights.items():
        adj[a].append((b, w))
        adj[b].append((a, w))
        deg[a] += w
        deg[b] += w
        m2 += 2 * w
    if m2 == 0:
        return {n: n for n in nodes}, False

    comm = {n: n for n in nodes}
    tot = defaultdict(float)
    for n in nodes:
        tot[n] = deg[n]

    moved_any = False
    for _ in range(20):
        moved = False
        for n in nodes:                        # ordem determinística
            c_old = comm[n]
            tot[c_old] -= deg[n]

            links = defaultdict(float)
            for m, w in adj[n]:
                if m != n:
                    links[comm[m]] += w

            best_c, best_gain = c_old, links.get(c_old, 0.0) - resolution * tot[c_old] * deg[n] / m2
            for c in sorted(links):
                gain = links[c] - resolution * tot[c] * deg[n] / m2
                if gain > best_gain + 1e-12:
                    best_gain, best_c = gain, c

            tot[best_c] += deg[n]
            comm[n] = best_c
            if best_c != c_old:
                moved = moved_any = True
        if not moved:
            break
    return comm, moved_any


def tune(nodes, weights, target=(8, 16), lo=0.3, hi=8.0, steps=18):
    """Busca a resolução que cai na faixa alvo de nº de blocos."""
    best = None
    for _ in range(steps):
        mid = (lo + hi) / 2
        cm = louvain(nodes, weights, resolution=mid)
        k = len(set(cm.values()))
        if best is None or abs(k - sum(target) / 2) < abs(best[1] - sum(target) / 2):
            best = (cm, k, mid)
        if target[0] <= k <= target[1]:
            return cm, k, mid
        if k < target[0]:
            lo = mid                            # poucos blocos -> sobe resolução
        else:
            hi = mid
    return best
