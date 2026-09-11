"""Gera DDL a partir do modelo canônico, no dialeto pedido.

Este módulo fecha o fluxo `modelo canônico -> SQL gerado`. Antes, exportar
devolvia o texto de origem com os ALTER acumulados no fim, o que impedia
exportar para um dialeto diferente do importado.

Ordem de emissão, pensada para o arquivo rodar de cima a baixo sem depender da
ordem das tabelas: CREATE TABLE (com PK e UNIQUE), CREATE INDEX, e por fim as
FKs como ALTER TABLE — assim uma FK nunca referencia tabela ainda não criada.
"""

import re

DIALECTS = ('postgres', 'mysql')

# --- tipos -------------------------------------------------------------------
# Só o que muda de nome entre os bancos. Tipos iguais nos dois (VARCHAR, INT,
# DATE, TEXT...) passam direto.
_TO_MYSQL = {
    'UUID': 'CHAR(36)',
    'JSONB': 'JSON',
    'TIMESTAMPTZ': 'DATETIME',
    'TIMESTAMP WITH TIME ZONE': 'DATETIME',
    'TIMESTAMP WITHOUT TIME ZONE': 'DATETIME',
    'TIMESTAMP': 'DATETIME',
    'TIMETZ': 'TIME',
    'BOOLEAN': 'TINYINT(1)',
    'BOOL': 'TINYINT(1)',
    'BYTEA': 'BLOB',
    'INET': 'VARCHAR(45)',
    'CIDR': 'VARCHAR(45)',
    'MACADDR': 'VARCHAR(17)',
    'CITEXT': 'VARCHAR(255)',
    'DOUBLE PRECISION': 'DOUBLE',
    'REAL': 'FLOAT',
    'SERIAL': 'INT',
    'BIGSERIAL': 'BIGINT',
    'SMALLSERIAL': 'SMALLINT',
    'INTEGER': 'INT',
    'NUMERIC': 'DECIMAL',
}
_TO_POSTGRES = {
    'TINYINT(1)': 'BOOLEAN',
    'DATETIME': 'TIMESTAMP',
    'JSON': 'JSONB',
    'BLOB': 'BYTEA',
    'LONGBLOB': 'BYTEA',
    'MEDIUMBLOB': 'BYTEA',
    'TINYBLOB': 'BYTEA',
    'LONGTEXT': 'TEXT',
    'MEDIUMTEXT': 'TEXT',
    'TINYTEXT': 'TEXT',
    'DOUBLE': 'DOUBLE PRECISION',
    'FLOAT': 'REAL',
    'DATETIME(6)': 'TIMESTAMP(6)',
    'INT': 'INTEGER',
    'DECIMAL': 'NUMERIC',
}
# tipos que viram auto-incremento no destino
_SERIAL = {'SERIAL': 'INT', 'BIGSERIAL': 'BIGINT', 'SMALLSERIAL': 'SMALLINT'}

_SIZE_RE = re.compile(r'^([A-Za-z ]+?)\s*\(([^)]*)\)\s*(.*)$')


def map_type(raw, target):
    """Converte o tipo para o dialeto alvo, preservando tamanho e sufixos."""
    if not raw:
        return 'TEXT'
    text = ' '.join(str(raw).split())
    table = _TO_MYSQL if target == 'mysql' else _TO_POSTGRES

    direct = table.get(text.upper())
    if direct:
        return direct

    m = _SIZE_RE.match(text)
    if not m:
        return text
    base, size, tail = m.group(1).strip().upper(), m.group(2).strip(), m.group(3).strip()

    # TINYINT(1) é booleano no MySQL: trata o par base+tamanho antes da base só
    keyed = table.get(f'{base}({size})')
    if keyed:
        return keyed

    mapped = table.get(base, base)
    if '(' in mapped:                 # o alvo já traz tamanho próprio (UUID->CHAR(36))
        return mapped
    out = f'{mapped}({size})'
    if tail and target == 'mysql' and tail.upper() in ('UNSIGNED', 'ZEROFILL'):
        out += ' ' + tail.upper()
    return out


def _is_autoincrement(column, dialect):
    raw = (column.get('type') or '').upper()
    if raw in _SERIAL:
        return True
    if dialect == 'mysql':
        return bool(column.get('auto_increment'))
    return bool(column.get('auto_increment'))


def map_default(value, column_type, target):
    """Traduz o default para o dialeto alvo quando a função muda de nome."""
    if value is None or value == '':
        return None
    text = str(value).strip()
    upper = text.upper().rstrip('()').strip()

    now = {'NOW', 'CURRENT_TIMESTAMP', 'TRANSACTION_TIMESTAMP', 'STATEMENT_TIMESTAMP'}
    if upper in now:
        return 'CURRENT_TIMESTAMP' if target == 'mysql' else 'NOW()'
    if upper in ('GEN_RANDOM_UUID', 'UUID_GENERATE_V4'):
        return '(UUID())' if target == 'mysql' else 'gen_random_uuid()'
    if upper == 'UUID':
        return '(UUID())' if target == 'mysql' else 'gen_random_uuid()'

    # booleano: MySQL guarda em TINYINT(1)
    if upper in ('TRUE', 'FALSE'):
        if target == 'mysql':
            return '1' if upper == 'TRUE' else '0'
        return upper.lower()
    if target == 'postgres' and (column_type or '').upper().startswith('BOOL'):
        if text == '1':
            return 'true'
        if text == '0':
            return 'false'
    return text


# --- identificadores ---------------------------------------------------------
def quote(name, dialect):
    if dialect == 'mysql':
        return '`' + str(name).replace('`', '``') + '`'
    return '"' + str(name).replace('"', '""') + '"'


def _qualified(table, dialect):
    schema = table.get('schema')
    if schema and dialect == 'postgres':
        return f'{quote(schema, dialect)}.{quote(table["name"], dialect)}'
    return quote(table['name'], dialect)


def _col_names(table, column_ids):
    by_id = {c['id']: c['name'] for c in table['columns']}
    return [by_id[cid] for cid in column_ids if cid in by_id]


def _index_name(table, index, cols):
    if index.get('name'):
        return index['name']
    prefix = 'pk' if index.get('primary_key') else ('uq' if index.get('unique') else 'idx')
    return '_'.join([prefix, table['name'], *cols])[:63]


def _fk_name(relationship, child, cols):
    if relationship.get('name'):
        return relationship['name']
    return '_'.join(['fk', child['name'], *cols])[:63]


# --- emissão -----------------------------------------------------------------
def _column_sql(column, dialect, in_primary, convert=True):
    parts = [quote(column['name'], dialect)]
    raw = (column.get('type') or '').upper()
    auto = _is_autoincrement(column, dialect)

    if auto and dialect == 'postgres':
        parts.append({'SERIAL': 'SERIAL', 'BIGSERIAL': 'BIGSERIAL',
                      'SMALLSERIAL': 'SMALLSERIAL'}.get(raw, 'SERIAL'))
    else:
        source = _SERIAL.get(raw, column.get('type'))
        parts.append(map_type(source, dialect) if convert else source)

    if not column.get('nullable', True) or in_primary:
        parts.append('NOT NULL')

    default = (map_default(column.get('default'), column.get('type'), dialect)
               if convert else column.get('default'))
    if default is not None and not (auto and dialect == 'postgres'):
        parts.append('DEFAULT ' + default)

    if auto and dialect == 'mysql':
        parts.append('AUTO_INCREMENT')
    return ' '.join(parts)


def _table_sql(table, dialect, convert=True):
    primary = next((i for i in table['indexes'] if i.get('primary_key')), None)
    pk_cols = _col_names(table, primary['columns']) if primary else []
    pk_set = set(pk_cols)

    lines = [_column_sql(c, dialect, c['name'] in pk_set, convert)
             for c in table['columns']]

    if pk_cols:
        cols = ', '.join(quote(c, dialect) for c in pk_cols)
        lines.append(f'PRIMARY KEY ({cols})')

    for index in table['indexes']:
        if index.get('primary_key') or not index.get('unique'):
            continue
        cols = _col_names(table, index['columns'])
        if not cols:
            continue
        name = _index_name(table, index, cols)
        joined = ', '.join(quote(c, dialect) for c in cols)
        lines.append(f'CONSTRAINT {quote(name, dialect)} UNIQUE ({joined})')

    for check in table.get('checks', []) or []:
        expression = (check.get('expression') or '').strip()
        if not expression:
            continue
        if check.get('name'):
            lines.append(f'CONSTRAINT {quote(check["name"], dialect)} CHECK ({expression})')
        else:
            lines.append(f'CHECK ({expression})')

    body = ',\n    '.join(lines)
    suffix = ' ENGINE=InnoDB DEFAULT CHARSET=utf8mb4' if dialect == 'mysql' else ''
    return f'CREATE TABLE {_qualified(table, dialect)} (\n    {body}\n){suffix};'


def _indexes_sql(table, dialect):
    out = []
    for index in table['indexes']:
        if index.get('primary_key') or index.get('unique'):
            continue
        cols = _col_names(table, index['columns'])
        if not cols:
            continue
        name = _index_name(table, index, cols)
        joined = ', '.join(quote(c, dialect) for c in cols)
        out.append(f'CREATE INDEX {quote(name, dialect)} '
                   f'ON {_qualified(table, dialect)} ({joined});')
    return out


def _relationship_sql(relationship, tables_by_id, dialect):
    child = tables_by_id.get(relationship['from']['table_id'])
    parent = tables_by_id.get(relationship['to']['table_id'])
    if not child or not parent:
        return None
    child_cols = _col_names(child, relationship['from']['column_ids'])
    parent_cols = _col_names(parent, relationship['to']['column_ids'])
    if not child_cols or not parent_cols:
        return None

    name = _fk_name(relationship, child, child_cols)
    stmt = (f'ALTER TABLE {_qualified(child, dialect)} '
            f'ADD CONSTRAINT {quote(name, dialect)} FOREIGN KEY '
            f'({", ".join(quote(c, dialect) for c in child_cols)}) '
            f'REFERENCES {_qualified(parent, dialect)} '
            f'({", ".join(quote(c, dialect) for c in parent_cols)})')
    if relationship.get('on_delete'):
        stmt += f' ON DELETE {relationship["on_delete"]}'
    if relationship.get('on_update'):
        stmt += f' ON UPDATE {relationship["on_update"]}'
    return stmt + ';'


def generate(project, dialect=None, header=True):
    """Devolve o DDL completo do projeto no dialeto pedido."""
    target = dialect or project.get('dialect') or 'postgres'
    if target not in DIALECTS:
        raise ValueError(f'dialeto inválido: {target} (use {" ou ".join(DIALECTS)})')

    # converter tipos só quando o dialeto muda: assim exportar postgres->postgres
    # devolve a grafia que o usuário escreveu (INT continua INT, não vira INTEGER)
    convert = (project.get('dialect') or target) != target
    tables = sorted(project.get('tables', []), key=lambda t: t['name'])
    by_id = {t['id']: t for t in tables}
    out = []

    if header:
        name = project.get('title') or 'schema'
        out.append(f'-- {name}\n-- Gerado por schema-map a partir do modelo do projeto.\n'
                   f'-- Dialeto: {"PostgreSQL" if target == "postgres" else "MySQL / MariaDB"}\n')

    if target == 'postgres':
        schemas = sorted({t['schema'] for t in tables if t.get('schema')})
        for schema in schemas:
            out.append(f'CREATE SCHEMA IF NOT EXISTS {quote(schema, target)};')
        if schemas:
            out.append('')

    for enum in project.get('enums', []) or []:
        if target != 'postgres':
            continue
        values = ', '.join("'" + str(v).replace("'", "''") + "'" for v in enum.get('values', []))
        out.append(f'CREATE TYPE {quote(enum["name"], target)} AS ENUM ({values});')
    if project.get('enums') and target == 'postgres':
        out.append('')

    for table in tables:
        out.append(_table_sql(table, target, convert))
        out.append('')

    index_lines = [line for table in tables for line in _indexes_sql(table, target)]
    if index_lines:
        out.extend(index_lines)
        out.append('')

    fk_lines = []
    for relationship in project.get('relationships', []):
        stmt = _relationship_sql(relationship, by_id, target)
        if stmt:
            fk_lines.append(stmt)
    if fk_lines:
        out.extend(sorted(fk_lines))
        out.append('')

    return '\n'.join(out).rstrip() + '\n'
