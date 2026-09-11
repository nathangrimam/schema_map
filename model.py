"""Monta o modelo (schema + layout) e cuida de carregar/salvar a visualização.

O layout salvo guarda só o que o usuário mexeu: posição das tabelas e os
retângulos dos blocos. A associação tabela->bloco é *geométrica* — a tabela
pertence ao bloco que contém o centro dela, igual ao drawDB. Assim, arrastar
uma tabela para dentro de um bloco já a reassocia, sem UI extra.
"""

import json
import math
import os
import tempfile

import parse_sql
import grouping
import layout as L

PALETTE = ["#2b6ca3", "#2f7d5a", "#9a6220", "#7a4a8a", "#a85a2c", "#a13d5a",
           "#3a7d8c", "#5d7a35", "#9c3d3d", "#46688f", "#6b6236", "#5b4b8a",
           "#8a4a6a", "#3f7a6d", "#7d5a3a", "#4a5d8a"]


def layout_path(sql_path):
    return os.path.splitext(sql_path)[0] + '.layout.json'


def load_layout(sql_path):
    lp = layout_path(sql_path)
    if not os.path.exists(lp):
        return None
    try:
        with open(lp, encoding='utf-8') as layout_file:
            return json.load(layout_file)
    except (OSError, ValueError):
        return None


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _saved_positions(saved, table_names):
    if not isinstance(saved, dict) or not isinstance(saved.get('tables'), dict):
        return {}
    valid = {}
    for name, point in saved['tables'].items():
        if (name in table_names and isinstance(point, dict) and
                _finite_number(point.get('x')) and _finite_number(point.get('y'))):
            valid[name] = {'x': point['x'], 'y': point['y']}
    return valid


def _saved_blocks(saved):
    if not isinstance(saved, dict) or not isinstance(saved.get('blocks'), list):
        return []
    required = ('id', 'name', 'x', 'y', 'w', 'h', 'color')
    valid = []
    for block in saved['blocks']:
        if not isinstance(block, dict) or not all(k in block for k in required):
            continue
        if not all(isinstance(block[k], str) for k in ('id', 'name', 'color')):
            continue
        if not all(_finite_number(block[k]) for k in ('x', 'y', 'w', 'h')):
            continue
        if block['w'] <= 0 or block['h'] <= 0:
            continue
        valid.append({k: block[k] for k in required})
    return valid


def build_parsed(parsed, title, override=None, saved=None, force_relayout=False):
    tables, fks = parsed['tables'], parsed['fks']

    if not tables:
        return {
            'meta': {'title': title, 'dialect': parsed['dialect'], 'nt': 0, 'nf': 0,
                     'hubs': [], 'grouping': 'vazio', 'hdr': L.HDR, 'row': L.ROW},
            'tables': [], 'edges': [], 'blocks': [], 'saved': bool(saved),
        }

    groups, report = grouping.resolve(tables, fks, override)
    hubs, indeg = grouping.hub_tables(tables, fks)

    if force_relayout:
        saved = None

    pos = _saved_positions(saved, set(tables)) if saved else {}
    saved_blocks = _saved_blocks(saved) if saved else []
    # Quando o layout salvo cobre todas as tabelas e todos os blocos, o
    # auto-layout seria inteiramente descartado abaixo. Pular L.build tira
    # segundos de cada mutação e de cada carga de página em schemas grandes.
    complete = (len(pos) == len(tables) and saved_blocks
                and {groups[name] for name in tables} <= {b['id'] for b in saved_blocks})

    if complete:
        for t in tables.values():
            point = pos[t['name']]
            t['x'], t['y'] = point['x'], point['y']
        block_list = saved_blocks
    else:
        blocks, order = L.build(tables, fks, groups)
        block_list = [{'id': g, 'name': g, 'x': b['x'], 'y': b['y'],
                       'w': b['w'], 'h': b['h'],
                       'color': PALETTE[i % len(PALETTE)]}
                      for i, (g, b) in enumerate(sorted(blocks.items()))]
        for t in tables.values():
            point = pos.get(t['name'])
            if point:                  # tabela nova fica onde o auto pôs
                t['x'], t['y'] = point['x'], point['y']
        if saved_blocks:
            ids = {b['id'] for b in saved_blocks}
            block_list = saved_blocks + [b for b in block_list if b['id'] not in ids]

    tj = []
    for name in sorted(tables):
        t = tables[name]
        fk = t.get('fkcols', set())
        tj.append({'name': name, 'x': t['x'], 'y': t['y'],
                   'w': L.TW, 'h': L.box_h(t),
                   'cols': [{'name': c['name'], 'type': c['type'],
                             'k': 'p' if c['pk'] else ('f' if c['name'] in fk else ''),
                             'pk': c['pk'], 'notnull': c['notnull'],
                             'unique': any(set(u) == {c['name']}
                                           for u in t.get('unique', []))}
                            for c in t['cols']]})

    ej = []
    for f in fks:
        child = tables[f['child']]
        child_col = next((c for c in child['cols'] if c['name'] == f['col']), None)
        unique_fk = any(set(cols) == {f['col']} for cols in child.get('unique', []))
        ej.append({'c': f['child'], 'p': f['parent'],
                   'col': f['col'], 'pcol': f['pcol'], 'name': f.get('name'),
                   'id': f.get('id'), 'on_delete': f.get('on_delete'),
                   'on_update': f.get('on_update'),
                   'card': '1:1' if unique_fk else 'n:1',
                   'required': bool(child_col and child_col['notnull']),
                   'hub': f['parent'] in hubs})

    return {
        'meta': {'title': title,
                 'dialect': parsed['dialect'],
                 'nt': len(tables), 'nf': len(fks),
                 'hubs': sorted(hubs), 'grouping': report['source'],
                 'hdr': L.HDR, 'row': L.ROW},
        'tables': tj, 'edges': ej, 'blocks': block_list,
        'saved': bool(saved),
    }


def build_sql(sql, title='novo_schema.sql', override=None, saved=None,
              dialect=None, force_relayout=False):
    parsed = parse_sql.parse(sql, dialect=dialect, is_sql=True)
    if sql.strip() and not parsed['tables']:
        raise ValueError('nenhum CREATE TABLE reconhecido no SQL')
    return build_parsed(parsed, title, override, saved, force_relayout)


def build_project(project, override=None, force_relayout=False):
    """Adapta o projeto canônico para o renderizador legado."""
    from import_adapter import project_layout_to_legacy, project_to_parsed

    saved = None if force_relayout else project_layout_to_legacy(project)
    if saved and not saved['tables'] and not saved['blocks']:
        saved = None
    diagram = build_parsed(project_to_parsed(project),
                           project.get('title') or 'novo_schema.sql',
                           override, saved, force_relayout)
    canonical_tables = {table['name']: table for table in project['tables']}
    for table in diagram['tables']:
        canonical = canonical_tables[table['name']]
        table['id'] = canonical['id']
        table['schema'] = canonical.get('schema')
        table['indexes'] = canonical['indexes']
        columns = {column['name']: column for column in canonical['columns']}
        for column in table['cols']:
            source = columns[column['name']]
            column['id'] = source['id']
            column['nullable'] = source['nullable']
            column['default'] = source.get('default')
    relationships = {relationship['id']: relationship
                     for relationship in project['relationships']}
    for edge in diagram['edges']:
        relationship = relationships.get(edge.get('id'))
        if relationship:
            edge['on_delete'] = relationship.get('on_delete')
            edge['on_update'] = relationship.get('on_update')
    diagram['meta']['project_id'] = project['id']
    diagram['meta']['project_version'] = project['version']
    return diagram


def build(sql_path, override=None, force_relayout=False):
    with open(sql_path, encoding='utf-8') as sql_file:
        sql = sql_file.read()
    saved = None if force_relayout else load_layout(sql_path)
    return build_sql(sql, os.path.basename(sql_path), override, saved,
                     force_relayout=force_relayout)


def save(sql_path, payload):
    lp = layout_path(sql_path)
    data = {'tables': payload.get('tables', {}), 'blocks': payload.get('blocks', [])}
    directory = os.path.dirname(lp) or '.'
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=directory,
                                     prefix='.schema-map-', suffix='.tmp',
                                     delete=False) as temp_file:
        json.dump(data, temp_file, ensure_ascii=False, indent=1)
        tmp = temp_file.name
    try:
        os.replace(tmp, lp)            # troca atômica: nunca deixa arquivo parcial
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return lp
