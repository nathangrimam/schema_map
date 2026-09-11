"""Agrupamento de tabelas em blocos (bounded contexts).

Sem arquivo de override, os blocos são inferidos do grafo de FKs por
modularidade (Louvain), com dois ajustes que importam num schema real:

1. Tabelas-hub (ex.: `tenants`, referenciada por 97 das 139) ligam tudo a tudo.
   Se contarem como aresta normal, o grafo vira um bloco só. O peso da aresta
   cai com o grau de entrada do pai, então elas se diluem.
2. Prefixo de nome carrega intenção de projeto (`service_order_*`, `tenant_*`),
   então soma um peso de afinidade.
"""

import re
from collections import defaultdict

import community


def _prefix(name, depth=2):
    parts = name.split('_')
    return '_'.join(parts[:depth]) if len(parts) > depth else name


def hub_tables(tables, fks, ratio=0.18, floor=6):
    indeg = defaultdict(int)
    for f in fks:
        indeg[f['parent']] += 1
    cut = max(floor, ratio * len(tables))
    return {t for t, d in indeg.items() if d >= cut}, dict(indeg)


def build_weights(tables, fks, prefix_weight=0.6, damp=0.75):
    """Peso da aresta = 1/indeg(pai)^damp — pais muito referenciados (hubs)
    carregam pouca informação de agrupamento e se diluem sozinhos."""
    names = sorted(tables)
    _, indeg = hub_tables(tables, fks)

    w = defaultdict(float)
    for f in fks:
        a, b = f['child'], f['parent']
        if a == b:
            continue
        k = (a, b) if a < b else (b, a)
        w[k] += 1.0 / (max(1, indeg.get(b, 1)) ** damp)

    by_prefix = defaultdict(list)
    for n in names:
        by_prefix[_prefix(n)].append(n)
    for group in by_prefix.values():
        if len(group) < 2:
            continue
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                k = (a, b) if a < b else (b, a)
                w[k] += prefix_weight

    return names, dict(w), indeg


def auto_groups(tables, fks, target=(8, 16)):
    names, w, indeg = build_weights(tables, fks)
    label, _, _ = community.tune(names, w, target=target)
    label = {n: label.get(n, n) for n in names}

    adj = defaultdict(list)
    for (a, b), v in w.items():
        adj[a].append((b, v))
        adj[b].append((a, v))

    clusters = defaultdict(list)
    for n, l in label.items():
        clusters[l].append(n)

    # absorve clusters minúsculos no vizinho mais conectado
    for _ in range(3):
        small = [l for l, ns in clusters.items() if len(ns) < 3]
        if not small:
            break
        for l in small:
            members = clusters.pop(l, [])
            if not members:
                continue
            pull = defaultdict(float)
            for n in members:
                for m, v in adj[n]:
                    if label[m] != l:
                        pull[label[m]] += v
            if not pull:
                clusters[l] = members
                continue
            dest = max(sorted(pull), key=lambda x: pull[x])
            clusters[dest].extend(members)
            for n in members:
                label[n] = dest

    # nomeia cada bloco pela tabela mais central dele
    out, used = {}, set()
    for l, members in clusters.items():
        anchor = max(sorted(members), key=lambda n: (indeg.get(n, 0), -len(n)))
        gname = anchor
        i = 2
        while gname in used:
            gname = f'{anchor}_{i}'
            i += 1
        used.add(gname)
        for n in members:
            out[n] = gname
    return out


def load_override(path):
    """Aceita JSON {bloco: "t1 t2 ..."} ou {bloco: ["t1","t2"]}."""
    import json
    data = json.load(open(path, encoding='utf-8'))
    out = {}
    for g, v in data.items():
        for t in (v.split() if isinstance(v, str) else v):
            out[t] = g
    return out


def resolve(tables, fks, override_path=None):
    """Devolve (mapa tabela->bloco, relatorio)."""
    report = {}
    if override_path:
        g = load_override(override_path)
        missing = sorted(set(tables) - set(g))
        extra = sorted(set(g) - set(tables))
        for t in missing:                    # nada fica de fora do desenho
            g[t] = 'ungrouped'
        report = {'source': 'override', 'missing': missing, 'unknown': extra}
    else:
        g = auto_groups(tables, fks)
        report = {'source': 'auto', 'missing': [], 'unknown': []}
    report['groups'] = len(set(g[t] for t in tables))
    return g, report
