"""Layout: posiciona tabelas dentro de cada bloco e os blocos no canvas.

Dentro do bloco — layout em camadas (estilo Sugiyama):
  1. camada = profundidade de dependência (pai à esquerda, filho à direita);
  2. ordem dentro da camada por baricentro, para reduzir cruzamentos;
  3. y de cada tabela puxado para a média das tabelas que ela referencia —
     é isso que faz a tabela de ligação parar entre as duas pontas.

Entre blocos — os mais acoplados ficam vizinhos (recozimento simulado sobre
uma grade), depois empacotamento por fileira.
"""

import math
import random
from collections import defaultdict

TW = 250            # largura da caixa
HDR = 34            # altura do cabeçalho
ROW = 18            # altura de cada coluna listada
PADB = 10           # respiro no rodapé da caixa

GX = 110            # vão horizontal entre colunas de tabelas
GY = 40             # vão vertical mínimo
GAPCAP = 110        # vão vertical máximo (impede buracos acumulados)
PADX = 46           # margem interna do bloco
PADT = 74           # espaço para o título do bloco
PADBOT = 46
CGAP = 280          # vão entre blocos na fileira
RGAP = 260          # vão entre fileiras
MAXCOL = 4          # máximo de tabelas empilhadas por coluna


def box_h(table, max_cols=None):
    n = len(table['cols']) if max_cols is None else min(len(table['cols']), max_cols)
    return HDR + ROW * n + PADB


def layout_block(names, edges, heights):
    """edges: lista (filho, pai) restrita ao bloco. Devolve (X, Y, w, h)."""
    par, ch = {n: [] for n in names}, {n: [] for n in names}
    for c, p in edges:
        if c != p and c in par and p in ch:
            par[c].append(p)
            ch[p].append(c)

    memo, vis = {}, set()

    def depth(n):
        if n in memo:
            return memo[n]
        if n in vis:                       # ciclo (ex.: parent_id auto-referente)
            return 0
        vis.add(n)
        d = 1 + max((depth(p) for p in par[n]), default=-1) if par[n] else 0
        vis.discard(n)
        memo[n] = d
        return d

    for n in names:
        depth(n)
    maxl = max(memo.values())
    layers = [[n for n in names if memo[n] == l] for l in range(maxl + 1)]

    idx = {}
    for L in layers:
        for i, n in enumerate(L):
            idx[n] = i

    def bary(n, rel):
        a = rel[n]
        return sum(idx[x] for x in a) / len(a) if a else idx[n]

    for _ in range(14):                    # reduz cruzamentos
        for l in range(1, maxl + 1):
            layers[l].sort(key=lambda n: bary(n, par))
            for i, n in enumerate(layers[l]):
                idx[n] = i
        for l in range(maxl - 1, -1, -1):
            layers[l].sort(key=lambda n: bary(n, ch))
            for i, n in enumerate(layers[l]):
                idx[n] = i

    cols = []                              # camada larga demais vira sub-colunas
    for L in layers:
        k = max(1, math.ceil(len(L) / MAXCOL))
        per = math.ceil(len(L) / k)
        for i in range(0, len(L), per):
            cols.append(L[i:i + per])

    X, Y = {}, {}
    for ci, C in enumerate(cols):
        for n in C:
            X[n] = ci * (TW + GX)

    def place(C, want):
        prev = None
        for n in sorted(C, key=lambda n: want[n]):
            y = want[n]
            if prev is not None:
                y = max(prev + GY, min(y, prev + GAPCAP))
            Y[n] = y
            prev = y + heights[n]

    for C in cols:
        run, want = 0.0, {}
        for n in C:
            want[n] = run
            run += heights[n] + GY
        place(C, want)

    for p in range(4):                     # alterna puxando por pais e por filhos
        for C in cols:
            want = {}
            for n in C:
                rel = [x for x in (ch[n] if p % 2 else par[n]) if x in Y]
                want[n] = (sum(Y[x] + heights[x] / 2 for x in rel) / len(rel)
                           - heights[n] / 2) if rel else Y[n]
            place(C, want)

    ymin = min(Y.values())
    for n in names:
        Y[n] = round(Y[n] - ymin)
    w = len(cols) * TW + (len(cols) - 1) * GX + 2 * PADX
    h = round(max(Y[n] + heights[n] for n in names)) + PADT + PADBOT
    return X, Y, w, h


def order_blocks(block_names, coupling, cols, rows, seed=7, restarts=40):
    """Recozimento simulado: blocos acoplados ficam perto na grade.

    Acoplamento e distância entre células são pré-calculados em matrizes, e uma
    troca é avaliada pelo delta que ela causa — só os pares que envolvem as duas
    posições mudam. Isso deixa cada passo O(n) em vez de O(n²) e dispensa copiar
    a permutação a cada tentativa.
    """
    rnd = random.Random(seed)
    cells = [(c * 1.0, r * 1.8) for r in range(rows) for c in range(cols)]
    n = len(block_names)

    weight = [[0.0] * n for _ in range(n)]
    position = {name: i for i, name in enumerate(block_names)}
    for (a, b), w in coupling.items():
        i, j = position.get(a), position.get(b)
        if i is not None and j is not None and i != j:
            weight[i][j] = weight[j][i] = weight[i][j] + w
    distance = [[math.hypot(cells[i][0] - cells[j][0], cells[i][1] - cells[j][1])
                 for j in range(n)] for i in range(n)]

    def cost(perm):
        s = 0.0
        for i in range(n):
            wi, di = weight[perm[i]], distance[i]
            for j in range(i + 1, n):
                w = wi[perm[j]]
                if w:
                    s += w * di[j]
        return s

    def delta(perm, i, j):
        """Quanto o custo muda ao trocar o conteúdo das posições i e j."""
        a, b = perm[i], perm[j]
        wa, wb = weight[a], weight[b]
        di, dj = distance[i], distance[j]
        s = 0.0
        for k in range(n):
            if k == i or k == j:
                continue
            c = perm[k]
            diff = wb[c] - wa[c]
            if diff:
                s += diff * (di[k] - dj[k])
        return s

    best, bestc = list(range(n)), float('inf')
    for _ in range(restarts):
        perm = list(range(n))
        rnd.shuffle(perm)
        cur = cost(perm)
        T = 2.5
        while T > 0.01:
            i, j = rnd.randrange(n), rnd.randrange(n)
            if i != j:
                change = delta(perm, i, j)
                if change < 0 or rnd.random() < math.exp(-change / T):
                    perm[i], perm[j] = perm[j], perm[i]
                    cur += change
            T *= 0.9995
        cur = cost(perm)            # recalcula: os deltas acumulam erro de ponto flutuante
        if cur < bestc:
            best, bestc = perm[:], cur
    return [block_names[i] for i in best], bestc


def build(tables, fks, groups, grid_cols=None):
    names_by_group = defaultdict(list)
    for t in sorted(tables):
        names_by_group[groups[t]].append(t)

    heights = {t: box_h(tables[t]) for t in tables}

    coupling = defaultdict(float)
    for f in fks:
        ga, gb = groups[f['child']], groups[f['parent']]
        if ga != gb:
            coupling[(ga, gb) if ga < gb else (gb, ga)] += 1

    blocks = {}
    for g, members in names_by_group.items():
        inside = [(f['child'], f['parent']) for f in fks
                  if groups[f['child']] == g and groups[f['parent']] == g]
        X, Y, w, h = layout_block(members, inside, heights)
        blocks[g] = {'name': g, 'members': members, 'X': X, 'Y': Y, 'w': w, 'h': h}

    gnames = sorted(blocks)
    k = len(gnames)
    cols = grid_cols or max(1, round(math.sqrt(k * 1.9)))
    rows = math.ceil(k / cols)
    order, _ = order_blocks(gnames, dict(coupling), cols, rows)

    placed, y = {}, 0
    for r in range(rows):
        row = order[r * cols:(r + 1) * cols]
        if not row:
            continue
        rh = max(blocks[g]['h'] for g in row)
        x = 0
        for g in row:
            b = blocks[g]
            bx, by = x, round(y + (rh - b['h']) / 2)
            placed[g] = {'x': bx, 'y': by, 'w': b['w'], 'h': b['h'],
                         'members': b['members']}
            for t in b['members']:
                tables[t]['x'] = round(bx + PADX + b['X'][t])
                tables[t]['y'] = round(by + PADT + b['Y'][t])
            x += b['w'] + CGAP
        y += rh + RGAP

    return placed, order
