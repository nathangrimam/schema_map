#!/usr/bin/env python3
"""schema-map — editor local de diagramas a partir de DDL (PostgreSQL / MySQL).

    python3 schema_map.py init  schema.sql              # cria a pasta do projeto
    python3 schema_map.py serve schemas/meu_projeto     # edita e salva
    python3 schema_map.py build schemas/meu_projeto -o out.html
    python3 schema_map.py info  schemas/meu_projeto     # o que foi lido

Um projeto vive numa pasta com project.json (fonte de verdade: schema, layout
e blocos), schema.sql (DDL gerado, para diff) e groups.json (agrupamento
opcional).  Os comandos também aceitam um .sql solto — nesse caso o layout
continua indo para <schema>.layout.json, como antes.
"""

import argparse
import json
import os
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog='schema_map', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    for name in ('serve', 'build', 'info'):
        p = sub.add_parser(name)
        p.add_argument('sql', nargs='?' if name == 'serve' else None,
                       help='pasta do projeto ou arquivo .sql com o DDL')
        p.add_argument('--groups', help='JSON de blocos {nome: "t1 t2 ..."}')
        if name == 'serve':
            p.add_argument('--port', type=int, default=8765)
            p.add_argument('--no-open', action='store_true')
        if name == 'build':
            p.add_argument('-o', '--out', default=None)
            p.add_argument('--relayout', action='store_true',
                           help='ignora o layout salvo e recalcula')

    p = sub.add_parser('init', help='cria a pasta do projeto a partir de um .sql')
    p.add_argument('sql', help='arquivo .sql com o DDL')
    p.add_argument('-o', '--out', default=None,
                   help='pasta de destino (padrão: <pasta do .sql>/<nome>)')
    p.add_argument('--groups', help='JSON de blocos {nome: "t1 t2 ..."}')
    p.add_argument('--dialect', choices=('postgres', 'mysql'), default=None)

    a = ap.parse_args(argv)
    if a.sql and not os.path.exists(a.sql):
        sys.exit(f'arquivo não encontrado: {a.sql}')

    if a.cmd == 'init':
        import model, workspace
        if os.path.isdir(a.sql):
            sys.exit('init espera um arquivo .sql, não uma pasta')
        directory, written = workspace.create_from_sql(
            a.sql, a.out, a.dialect, a.groups, model.load_layout(a.sql))
        print(f'projeto em {directory}')
        for label in ('project', 'schema', 'groups'):
            if label in written:
                print(f'  {os.path.basename(written[label])}')
        print(f'abra com: python3 schema_map.py serve {directory}')
        return

    if a.cmd == 'info':
        import grouping, parse_sql, workspace
        kind, path = workspace.resolve(a.sql)
        if kind == 'workspace':
            import import_adapter
            r = import_adapter.project_to_parsed(workspace.load(path))
            groups = a.groups or workspace.groups_path(path)
        else:
            r = parse_sql.parse(path)
            groups = a.groups
        g, rep = grouping.resolve(r['tables'], r['fks'], groups)
        hubs, indeg = grouping.hub_tables(r['tables'], r['fks'])
        from collections import defaultdict
        by = defaultdict(list)
        for t, blk in g.items():
            by[blk].append(t)
        print(f"dialeto : {r['dialect']}")
        print(f"tabelas : {len(r['tables'])}")
        print(f"colunas : {sum(len(t['cols']) for t in r['tables'].values())}")
        print(f"FKs     : {len(r['fks'])}" +
              (f"  ({len(r['dropped'])} ignoradas: alvo fora do arquivo)" if r['dropped'] else ''))
        print(f"hubs    : {', '.join(f'{h} ({indeg[h]}x)' for h in sorted(hubs, key=lambda x: -indeg[x])) or '—'}")
        print(f"blocos  : {rep['groups']} ({rep['source']})")
        for blk, ts in sorted(by.items(), key=lambda x: -len(x[1])):
            print(f'  {len(ts):3d}  {blk}')
        if rep.get('missing'):
            print(f"  ! {len(rep['missing'])} tabelas fora do --groups -> 'ungrouped'")
        if rep.get('unknown'):
            print(f"  ! {len(rep['unknown'])} nomes no --groups que não existem no schema")
        return

    if a.cmd == 'serve':
        import server
        server.serve(a.sql, a.groups, port=a.port, open_browser=not a.no_open)
        return

    if a.cmd == 'build':
        import server
        out = a.out or (os.path.join(a.sql, 'diagrama.html') if os.path.isdir(a.sql)
                        else os.path.splitext(a.sql)[0] + '.html')
        html = server.page(a.sql, a.groups, force=a.relayout)
        open(out, 'w', encoding='utf-8').write(html)
        print(f'{out}  ({len(html)/1024:.0f} KB)')
        print('obs.: no HTML estático o botão salvar não funciona — use "serve" para editar.')
        return


if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
