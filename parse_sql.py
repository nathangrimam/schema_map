"""Small, order-aware SQL DDL parser used by the diagram and inspectors.

It intentionally is not a general SQL parser.  It covers the DDL emitted by
the editor and common PostgreSQL/MySQL dumps while retaining the legacy
``tables``/``fks`` output consumed by the renderer.
"""

import re


IDENT = r'[`"\[]?([A-Za-z_]\w*)[`"\]]?'
CREATE_RE = re.compile(
    r'^\s*CREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?'
    rf'(?:{IDENT}\s*\.\s*)?{IDENT}\s*\(', re.I | re.S)
TABLE_NAME_RE = re.compile(
    r'^\s*ALTER\s+TABLE\s+(?:ONLY\s+)?(?:' + IDENT + r'\s*\.\s*)?' + IDENT,
    re.I | re.S)
COLNAME_RE = re.compile(rf'^\s*{IDENT}\s+(.*)$', re.S)
CONSTRAINT_START = re.compile(
    r'^(?:PRIMARY\s+KEY|UNIQUE|CHECK|CONSTRAINT|FOREIGN\s+KEY|EXCLUDE|'
    r'KEY|INDEX|FULLTEXT|SPATIAL|PERIOD)\b', re.I)
TOKEN_RE = re.compile(r'[A-Za-z_]+(?:\s*\([^)]*\))?|\S+')
TYPE_CONT = {'PRECISION', 'VARYING', 'WITH', 'WITHOUT', 'TIME', 'ZONE',
             'UNSIGNED', 'ZEROFILL', 'SIGNED', 'LOCAL'}


def _ident(value):
    value = value.strip().rstrip(';').strip()
    if len(value) >= 2 and value[0] in '`"[' and value[-1] in '`"]':
        return value[1:-1]
    return value


def _cols(raw):
    return [_ident(value.strip().split()[0]) for value in raw.split(',') if value.strip()]


def column_type(rest: str) -> str:
    """Extract a column type, stopping at its first column constraint."""
    tokens = TOKEN_RE.findall(rest)
    if not tokens:
        return ''
    result = [tokens[0].replace(' ', '')]
    for token in tokens[1:]:
        base = re.split(r'[\s(]', token, maxsplit=1)[0].upper()
        if base in TYPE_CONT:
            result.append(token.replace(' ', ''))
        else:
            break
    return ' '.join(result)


def detect_dialect(sql: str) -> str:
    sample = sql[:200000]
    score_my = len(re.findall(r'`|ENGINE\s*=|AUTO_INCREMENT|TINYINT|DATETIME\b', sample, re.I))
    score_pg = len(re.findall(r'\bUUID\b|JSONB|TIMESTAMPTZ|SERIAL\b|::|TEXT\[\]', sample, re.I))
    return 'mysql' if score_my > score_pg else 'postgres'


def strip_comments(sql: str) -> str:
    sql = re.sub(r'/\*.*?\*/', ' ', sql, flags=re.S)
    result = []
    for line in sql.splitlines():
        stripped = line.lstrip()
        if stripped.startswith('--') or stripped.startswith('#'):
            continue
        result.append(line)
    return '\n'.join(result)


def split_statements(sql: str):
    """Split at top-level semicolons, respecting quoted strings."""
    statements, current = [], []
    depth, quote = 0, None
    index = 0
    while index < len(sql):
        char = sql[index]
        if quote:
            current.append(char)
            # mysqldump escapa com barra invertida (\'); sem tratar isso o
            # estado de aspas inverte e os CREATE TABLE seguintes somem
            if char == '\\' and quote in "'\"" and index + 1 < len(sql):
                current.append(sql[index + 1])
                index += 2
                continue
            if char == quote:
                if quote == "'" and index + 1 < len(sql) and sql[index + 1] == "'":
                    current.append(sql[index + 1])
                    index += 1
                else:
                    quote = None
            index += 1
            continue
        if char in "'\"`":
            quote = char
        elif char == '[':
            quote = ']'
        elif char == '(':
            depth += 1
        elif char == ')':
            depth = max(0, depth - 1)
        if char == ';' and depth == 0:
            if ''.join(current).strip():
                statements.append(''.join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    if ''.join(current).strip():
        statements.append(''.join(current).strip())
    return statements


def split_top_level(body: str):
    """Divide a CREATE TABLE body while respecting nested expressions."""
    items, current = [], []
    depth, quote = 0, None
    index = 0
    while index < len(body):
        char = body[index]
        if quote:
            current.append(char)
            if char == quote:
                if quote == "'" and index + 1 < len(body) and body[index + 1] == "'":
                    current.append(body[index + 1])
                    index += 1
                else:
                    quote = None
            index += 1
            continue
        if char in "'\"`":
            quote = char
        elif char == '[':
            quote = ']'
        elif char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        if char == ',' and depth == 0:
            if ''.join(current).strip():
                items.append(''.join(current))
            current = []
        else:
            current.append(char)
        index += 1
    if ''.join(current).strip():
        items.append(''.join(current))
    return [' '.join(item.split()) for item in items if item.strip()]


def _find_matching(text, opening):
    depth, quote = 0, None
    index = opening - 1
    while index + 1 < len(text):
        index += 1
        char = text[index]
        if quote:
            if char == '\\' and quote in "'\"":
                index += 1                      # pula o caractere escapado
                continue
            if char == quote:
                quote = None
            continue
        if char in "'\"`":
            quote = char
        elif char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0:
                return index
    return len(text)


def _default(rest):
    match = re.search(r'\bDEFAULT\s+', rest, re.I)
    if not match:
        return None
    value = rest[match.end():].strip()
    depth, quote, end = 0, None, len(value)
    index = 0
    while index < len(value):
        char = value[index]
        if quote:
            if char == quote:
                if quote == "'" and index + 1 < len(value) and value[index + 1] == "'":
                    index += 1
                else:
                    quote = None
        elif char in "'\"`":
            quote = char
        elif char == '(':
            depth += 1
        elif char == ')':
            depth = max(0, depth - 1)
        elif char.isspace() and depth == 0:
            tail = value[index:].lstrip()
            if re.match(r'^(?:NOT\s+NULL|NULL|PRIMARY\s+KEY|UNIQUE|CHECK|REFERENCES|ON\s+UPDATE|ON\s+DELETE|COLLATE|COMMENT|AUTO_INCREMENT|GENERATED|STORAGE)\b', tail, re.I):
                end = index
                break
        index += 1
    return value[:end].strip() or None


def _actions(rest):
    result = {}
    for kind, value in re.findall(
        r'\bON\s+(DELETE|UPDATE)\s+(NO\s+ACTION|RESTRICT|CASCADE|SET\s+NULL|SET\s+DEFAULT)\b',
        rest, re.I):
        result['on_' + kind.lower()] = re.sub(r'\s+', ' ', value.upper())
    return result


def _reference(rest):
    match = re.search(
        r'\bREFERENCES\s+((?:[`"\[]?[\w]+[`"\]]?\s*\.\s*)?[`"\[]?[\w]+[`"\]]?)\s*\(([^)]*)\)',
        rest, re.I)
    if not match:
        return None
    return _ident(match.group(1).split('.')[-1]), _cols(match.group(2)), _actions(rest)


def _column_definition(name, definition):
    upper = definition.upper()
    value = {'name': _ident(name), 'type': column_type(definition),
             'notnull': bool(re.search(r'\bNOT\s+NULL\b', upper)),
             'pk': bool(re.search(r'\bPRIMARY\s+KEY\b', upper))}
    default = _default(definition)
    if default is not None:
        value['default'] = default
    return value


def _new_table(name, schema=None):
    return {'name': name, 'schema': schema, 'cols': [], 'unique': [], 'indexes': [],
            'checks': []}


def _check_expression(item):
    """Extrai a expressão de um CHECK, respeitando parênteses aninhados.

    `CHECK (status IN ('A','B'))` tem parênteses dentro da expressão, então um
    `[^)]*` corta no lugar errado.
    """
    match = re.match(r'^(?:CONSTRAINT\s+' + IDENT + r'\s+)?CHECK\s*(?=\()', item, re.I)
    if not match:
        return None
    opening = item.index('(', match.end() - 1)
    closing = _find_matching(item, opening)
    if closing <= opening:
        return None
    return match.group(1), item[opening + 1:closing].strip()


def _add_check(table, name, expression):
    if not expression:
        return
    for existing in table['checks']:
        if existing['expression'] == expression:
            return
    table['checks'].append({'name': name, 'expression': expression})


def _add_unique(table, columns):
    columns = list(columns)
    if columns and columns not in table['unique']:
        table['unique'].append(columns)


def _add_index(table, name, columns, unique=False, primary_key=False):
    columns = list(columns)
    if not columns:
        return
    for index in table['indexes']:
        if (index.get('name') == name and index['columns'] == columns and
                bool(index['unique']) == bool(unique) and
                bool(index['primary_key']) == bool(primary_key)):
            return
    table['indexes'].append({'name': name, 'columns': columns,
                             'unique': bool(unique), 'primary_key': bool(primary_key)})


def _constraint(item):
    primary = re.match(r'^(?:CONSTRAINT\s+' + IDENT + r'\s+)?PRIMARY\s+KEY\s*\(([^)]*)\)', item, re.I)
    if primary:
        return 'primary', primary.group(1), _cols(primary.group(2)), item[primary.end():]
    unique = re.match(r'^(?:CONSTRAINT\s+' + IDENT + r'\s+)?UNIQUE(?:\s+(?:KEY|INDEX))?(?:\s+' + IDENT + r')?\s*\(([^)]*)\)', item, re.I)
    if unique:
        named = re.match(r'^CONSTRAINT\s+' + IDENT + r'\s+UNIQUE', item, re.I)
        name = named.group(1) if named else None
        if not name:
            unnamed = re.match(r'^UNIQUE\s+(?:KEY|INDEX)?\s*' + IDENT + r'\s*\(', item, re.I)
            name = unnamed.group(1) if unnamed else None
        return 'unique', name, _cols(unique.group(3)), item[unique.end():]
    foreign = re.match(r'^(?:CONSTRAINT\s+' + IDENT + r'\s+)?FOREIGN\s+KEY\s*\(([^)]*)\)\s*(.+)$', item, re.I)
    if foreign:
        named = re.match(r'^CONSTRAINT\s+' + IDENT, item, re.I)
        return 'foreign', named.group(1) if named else None, _cols(foreign.group(2)), foreign.group(3)
    index = re.match(r'^(?:(UNIQUE)\s+)?(?:KEY|INDEX)\s*(?:' + IDENT + r')?\s*\(([^)]*)\)', item, re.I)
    if index:
        return 'index', index.group(2), _cols(index.group(3)), item[index.end():]
    check = _check_expression(item)
    if check:
        return 'check', check[0], [], check[1]
    return None


def _create_table(statement, tables, fks):
    match = CREATE_RE.match(statement)
    if not match:
        return False
    schema, name = match.group(1), match.group(2)
    opening = statement.find('(', match.start())
    closing = _find_matching(statement, opening)
    table = tables.setdefault(name, _new_table(name, schema))
    for item in split_top_level(statement[opening + 1:closing]):
        constraint = _constraint(item)
        if constraint:
            kind, constraint_name, columns, remainder = constraint
            if kind == 'primary':
                for column in table['cols']:
                    if column['name'] in columns:
                        column['pk'] = True
                _add_unique(table, columns)
                _add_index(table, constraint_name, columns, True, True)
            elif kind == 'unique':
                _add_unique(table, columns)
                _add_index(table, constraint_name, columns, True, False)
            elif kind == 'index':
                is_unique = bool(re.match(r'^UNIQUE\b', item, re.I))
                _add_index(table, constraint_name, columns, is_unique, False)
            elif kind == 'check':
                _add_check(table, constraint_name, remainder)
            elif kind == 'foreign':
                reference = _reference(remainder)
                if reference:
                    parent, parent_columns, actions = reference
                    for child_column, parent_column in zip(columns, parent_columns):
                        fk = {'child': name, 'col': child_column, 'parent': parent,
                              'pcol': parent_column, 'name': constraint_name}
                        fk.update(actions)
                        fks.append(fk)
            continue
        column_match = COLNAME_RE.match(item)
        if not column_match or CONSTRAINT_START.match(item):
            continue
        value = _column_definition(column_match.group(1), column_match.group(2))
        if not value['type']:
            continue
        table['cols'].append(value)
        inline_check = re.search(r'\bCHECK\s*(?=\()', column_match.group(2), re.I)
        if inline_check:
            _add_check(table, None,
                       _check_expression(column_match.group(2)[inline_check.start():])[1])
        if value['pk'] or re.search(r'\bUNIQUE\b', item, re.I):
            _add_unique(table, [value['name']])
        if value['pk']:
            named = re.search(r'\bCONSTRAINT\s+' + IDENT + r'\s+PRIMARY\s+KEY\b', column_match.group(2), re.I)
            _add_index(table, named.group(1) if named else None,
                       [value['name']], True, True)
        elif re.search(r'\bUNIQUE\b', item, re.I):
            named = re.search(r'\bCONSTRAINT\s+' + IDENT + r'\s+UNIQUE\b', column_match.group(2), re.I)
            _add_index(table, named.group(1) if named else None,
                       [value['name']], True, False)
        reference = _reference(column_match.group(2))
        if reference:
            parent, parent_columns, actions = reference
            if parent_columns:
                fk = {'child': name, 'col': value['name'], 'parent': parent,
                      'pcol': parent_columns[0], 'name': None}
                fk.update(actions)
                fks.append(fk)
    return True


def _table_name(statement):
    match = TABLE_NAME_RE.match(statement)
    return (_ident(match.group(2)), match.group(1)) if match else (None, None)


def _rename_table(old, new, tables, fks):
    table = tables.pop(old, None)
    if not table:
        return
    table['name'] = new
    tables[new] = table
    for fk in fks:
        if fk['child'] == old:
            fk['child'] = new
        if fk['parent'] == old:
            fk['parent'] = new


def _rename_column(table, old, new, fks):
    if not table:
        return
    for column in table['cols']:
        if column['name'] == old:
            column['name'] = new
    table['unique'] = [[new if value == old else value for value in values]
                      for values in table['unique']]
    for index in table['indexes']:
        index['columns'] = [new if value == old else value for value in index['columns']]
    for fk in fks:
        if fk['child'] == table['name'] and fk['col'] == old:
            fk['col'] = new
        if fk['parent'] == table['name'] and fk['pcol'] == old:
            fk['pcol'] = new


def _drop_column(table, name, fks):
    if not table:
        return
    table['cols'] = [column for column in table['cols'] if column['name'] != name]
    table['unique'] = [values for values in table['unique'] if name not in values]
    table['indexes'] = [index for index in table['indexes'] if name not in index['columns']]
    fks[:] = [fk for fk in fks if not ((fk['child'] == table['name'] and fk['col'] == name) or
                                       (fk['parent'] == table['name'] and fk['pcol'] == name))]


def _alter_column(table, name, definition, operation):
    if not table:
        return
    column = next((value for value in table['cols'] if value['name'] == name), None)
    if not column:
        return
    if operation == 'type':
        column['type'] = column_type(definition)
    elif operation == 'set_notnull':
        column['notnull'] = True
    elif operation == 'drop_notnull':
        column['notnull'] = False
    elif operation == 'set_default':
        default = _default(definition if re.match(r'^DEFAULT\b', definition, re.I)
                            else 'DEFAULT ' + definition)
        if default is not None:
            column['default'] = default
    elif operation == 'drop_default':
        column.pop('default', None)


def _set_primary_key(table, columns, name=None):
    if not table:
        return
    for column in table['cols']:
        if column['name'] in columns:
            column['pk'] = True
    _add_unique(table, columns)
    _add_index(table, name, columns, True, True)


def _drop_primary_key(table):
    if not table:
        return
    primary_indexes = [index for index in table['indexes'] if index.get('primary_key')]
    for column in table['cols']:
        column['pk'] = False
    table['indexes'] = [index for index in table['indexes'] if not index.get('primary_key')]
    for index in primary_indexes:
        if index['columns'] in table['unique']:
            table['unique'].remove(index['columns'])


def _apply_alter(statement, tables, fks):
    table_name, _schema = _table_name(statement)
    if not table_name:
        return
    table = tables.get(table_name)
    table_match = TABLE_NAME_RE.match(statement)
    body = statement[table_match.end():].strip()

    rename_table = re.match(r'^RENAME\s+TO\s+' + IDENT + r'$', body, re.I)
    if rename_table:
        _rename_table(table_name, rename_table.group(1), tables, fks)
        return
    rename_column = re.match(r'^RENAME\s+COLUMN\s+' + IDENT + r'\s+TO\s+' + IDENT + r'$', body, re.I)
    if rename_column:
        _rename_column(table, rename_column.group(1), rename_column.group(2), fks)
        return
    set_schema = re.match(r'^SET\s+SCHEMA\s+' + IDENT + r'$', body, re.I)
    if set_schema:
        if table:
            table['schema'] = set_schema.group(1)
        return
    drop_column = re.match(r'^DROP\s+(?:COLUMN\s+)?' + IDENT + r'(?:\s+CASCADE)?$', body, re.I)
    if drop_column:
        _drop_column(table, drop_column.group(1), fks)
        return
    add_primary = re.match(r'^ADD\s+(?:CONSTRAINT\s+' + IDENT + r'\s+)?PRIMARY\s+KEY\s*\(([^)]*)\)', body, re.I)
    if add_primary:
        named = re.match(r'^ADD\s+CONSTRAINT\s+' + IDENT, body, re.I)
        _set_primary_key(table, _cols(add_primary.group(2)), named.group(1) if named else None)
        return
    if re.match(r'^DROP\s+PRIMARY\s+KEY$', body, re.I):
        _drop_primary_key(table)
        return
    add_fk = re.match(r'^ADD\s+(?:CONSTRAINT\s+' + IDENT + r'\s+)?FOREIGN\s+KEY\s*\(([^)]*)\)\s*(.+)$', body, re.I | re.S)
    if add_fk:
        named = re.match(r'^ADD\s+CONSTRAINT\s+' + IDENT, body, re.I)
        reference = _reference(add_fk.group(3))
        if table and reference:
            parent, parent_columns, actions = reference
            for child_column, parent_column in zip(_cols(add_fk.group(2)), parent_columns):
                fk = {'child': table_name, 'col': child_column, 'parent': parent,
                      'pcol': parent_column, 'name': named.group(1) if named else None}
                fk.update(actions)
                fks.append(fk)
        return
    add_index = re.match(r'^ADD\s+(?:(UNIQUE)\s+)?(?:INDEX|KEY)\s*' + IDENT + r'\s*\(([^)]*)\)', body, re.I)
    if add_index:
        columns = _cols(add_index.group(3))
        _add_index(table, add_index.group(2), columns, bool(add_index.group(1)), False)
        if add_index.group(1):
            _add_unique(table, columns)
        return
    drop_index = re.match(r'^DROP\s+(?:INDEX|KEY)\s+' + IDENT + '$', body, re.I)
    if drop_index:
        name = drop_index.group(1)
        removed = [index for index in (table or {}).get('indexes', [])
                   if index.get('name') == name]
        if table:
            table['indexes'] = [index for index in table['indexes']
                                if index.get('name') != name]
            for index in removed:
                if index.get('unique') and index['columns'] in table['unique']:
                    if not any(other.get('unique') and other['columns'] == index['columns']
                               for other in table['indexes']):
                        table['unique'].remove(index['columns'])
        return
    add_column = re.match(r'^ADD\s+(?:COLUMN\s+)?' + IDENT + r'\s+(.+)$', body, re.I | re.S)
    if add_column and not re.match(r'^ADD\s+(?:CONSTRAINT|FOREIGN|PRIMARY|UNIQUE|CHECK|INDEX|KEY)\b', body, re.I):
        value = _column_definition(add_column.group(1), add_column.group(2))
        if table and value['type']:
            table['cols'].append(value)
            if value['pk'] or re.search(r'\bUNIQUE\b', add_column.group(2), re.I):
                _add_unique(table, [value['name']])
            reference = _reference(add_column.group(2))
            if reference and reference[1]:
                fk = {'child': table_name, 'col': value['name'], 'parent': reference[0],
                      'pcol': reference[1][0], 'name': None}
                fk.update(reference[2])
                fks.append(fk)
        return
    modify = re.match(r'^MODIFY\s+(?:COLUMN\s+)?' + IDENT + r'\s+(.+)$', body, re.I | re.S)
    if modify:
        value = _column_definition(modify.group(1), modify.group(2))
        column = next((item for item in (table or {}).get('cols', [])
                       if item['name'] == modify.group(1)), None)
        if column:
            column.update({'type': value['type'], 'notnull': value['notnull'], 'pk': value['pk']})
            if 'default' in value:
                column['default'] = value['default']
            else:
                column.pop('default', None)
        return
    alter = re.match(r'^ALTER\s+COLUMN\s+' + IDENT + r'\s+(.+)$', body, re.I | re.S)
    if alter:
        operation = alter.group(2).strip()
        if re.match(r'^TYPE\s+', operation, re.I):
            _alter_column(table, alter.group(1), re.sub(r'^TYPE\s+', '', operation, flags=re.I), 'type')
        elif re.match(r'^SET\s+NOT\s+NULL$', operation, re.I):
            _alter_column(table, alter.group(1), '', 'set_notnull')
        elif re.match(r'^DROP\s+NOT\s+NULL$', operation, re.I):
            _alter_column(table, alter.group(1), '', 'drop_notnull')
        elif re.match(r'^SET\s+DEFAULT\s+', operation, re.I):
            _alter_column(table, alter.group(1), re.sub(r'^SET\s+', '', operation, flags=re.I), 'set_default')
        elif re.match(r'^DROP\s+DEFAULT$', operation, re.I):
            _alter_column(table, alter.group(1), '', 'drop_default')
        return
    drop_constraint = re.match(r'^DROP\s+CONSTRAINT\s+' + IDENT + r'(?:\s+CASCADE)?$', body, re.I)
    if drop_constraint:
        name = drop_constraint.group(1)
        if table:
            removed = [index for index in table['indexes'] if index.get('name') == name]
            # A source CREATE TABLE often has an unnamed primary constraint,
            # while the visual synchronizer emits its deterministic name.
            normalized_name = name.casefold()
            if (not removed and
                    (normalized_name.startswith('pk_') or normalized_name.endswith('_pkey'))):
                removed = [index for index in table['indexes']
                           if index.get('primary_key')]
            table['indexes'] = [index for index in table['indexes'] if index.get('name') != name]
            if removed:
                removed_ids = {id(index) for index in removed}
                table['indexes'] = [index for index in table['indexes']
                                    if id(index) not in removed_ids]
            for index in removed:
                if index.get('primary_key'):
                    for column in table['cols']:
                        if column['name'] in index['columns']:
                            column['pk'] = False
                if index.get('unique') and index['columns'] in table['unique']:
                    if not any(other.get('unique') and other['columns'] == index['columns']
                               for other in table['indexes']):
                        table['unique'].remove(index['columns'])
        fks[:] = [fk for fk in fks if not (fk['child'] == table_name and fk.get('name') == name)]
        return
    drop_fk = re.match(r'^DROP\s+FOREIGN\s+KEY\s+' + IDENT, body, re.I)
    if drop_fk:
        fks[:] = [fk for fk in fks if not (fk['child'] == table_name and fk.get('name') == drop_fk.group(1))]


def _drop_table(statement, tables, fks):
    match = re.match(r'^DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:' + IDENT + r'\s*\.\s*)?' + IDENT, statement, re.I)
    if not match:
        return False
    name = match.group(2)
    tables.pop(name, None)
    fks[:] = [fk for fk in fks if fk['child'] != name and fk['parent'] != name]
    return True


def _apply_index_statement(statement, tables):
    match = re.match(r'^CREATE\s+(UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?' + IDENT + r'\s+ON\s+(?:' + IDENT + r'\s*\.\s*)?' + IDENT + r'\s*\(([^)]*)\)', statement, re.I | re.S)
    if not match:
        return False
    table = tables.get(match.group(4))
    if table:
        columns = _cols(match.group(5))
        _add_index(table, match.group(2), columns, bool(match.group(1)), False)
        if match.group(1):
            _add_unique(table, columns)
    return True


def _drop_index_statement(statement, tables):
    match = re.match(r'^DROP\s+INDEX\s+(?:IF\s+EXISTS\s+)?' + IDENT + r'(?:\s+ON\s+' + IDENT + r')?$', statement, re.I)
    if not match:
        return False
    index_name, table_name = match.group(1), match.group(2)
    targets = [tables[table_name]] if table_name and table_name in tables else list(tables.values())
    for table in targets:
        removed = [index for index in table['indexes'] if index.get('name') == index_name]
        table['indexes'] = [index for index in table['indexes'] if index.get('name') != index_name]
        for index in removed:
            if index['unique'] and index['columns'] in table['unique']:
                table['unique'].remove(index['columns'])
    return True


def _dedup_fks(fks):
    result, positions = [], {}
    for fk in fks:
        key = (fk['child'], fk['col'], fk['parent'], fk['pcol'])
        if key not in positions:
            positions[key] = len(result)
            result.append(fk)
        else:
            current = result[positions[key]]
            for field in ('name', 'on_delete', 'on_update'):
                if not current.get(field) and fk.get(field):
                    current[field] = fk[field]
    return result


def parse(path_or_sql: str, dialect: str = None, is_sql: bool = False):
    if is_sql:
        sql = path_or_sql
    else:
        with open(path_or_sql, encoding='utf-8') as sql_file:
            sql = sql_file.read()
    dialect = dialect or detect_dialect(sql)
    tables, fks = {}, []
    for statement in split_statements(strip_comments(sql)):
        upper = statement.lstrip().upper()
        if upper.startswith('CREATE') and re.match(r'^CREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\b', statement, re.I):
            _create_table(statement, tables, fks)
        elif upper.startswith('CREATE'):
            _apply_index_statement(statement, tables)
        elif upper.startswith('ALTER TABLE'):
            _apply_alter(statement, tables, fks)
        elif upper.startswith('DROP TABLE'):
            _drop_table(statement, tables, fks)
        elif upper.startswith('DROP INDEX'):
            _drop_index_statement(statement, tables)

    known = set(tables)
    dropped = [fk for fk in fks if fk['parent'] not in known or fk['child'] not in known]
    fks = _dedup_fks([fk for fk in fks if fk['parent'] in known and fk['child'] in known])
    for table in tables.values():
        table['fkcols'] = {fk['col'] for fk in fks if fk['child'] == table['name']}
    return {'tables': tables, 'fks': fks, 'dialect': dialect, 'dropped': dropped}


if __name__ == '__main__':
    import json
    import sys
    result = parse(sys.argv[1])
    print(json.dumps({'dialect': result['dialect'], 'tables': len(result['tables']),
                      'fks': len(result['fks']), 'dropped': len(result['dropped']),
                      'cols': sum(len(table['cols']) for table in result['tables'].values())}, indent=1))
