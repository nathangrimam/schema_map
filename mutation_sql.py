"""Gera DDL incremental para manter edições visuais sincronizadas com a fonte."""


def _find(items, entity_id, label):
    item = next((value for value in items if value['id'] == entity_id), None)
    if item is None:
        raise ValueError('%s não encontrado' % label)
    return item


def _table(project, table_id):
    return _find(project['tables'], table_id, 'tabela')


def _column(table, column_id):
    return _find(table['columns'], column_id, 'coluna')


def _quote(value, dialect):
    mark = '`' if dialect == 'mysql' else '"'
    return mark + str(value).replace(mark, mark + mark) + mark


def _table_name(table, dialect):
    name = _quote(table['name'], dialect)
    return (_quote(table['schema'], dialect) + '.' + name) if table.get('schema') else name


def _column_definition(column, dialect):
    result = '%s %s' % (_quote(column['name'], dialect), column['type'])
    if not column['nullable']:
        result += ' NOT NULL'
    if column.get('default') not in (None, ''):
        result += ' DEFAULT ' + str(column['default'])
    return result


def _index_name(table, index):
    if index.get('name'):
        return index['name']
    columns = [next(column['name'] for column in table['columns'] if column['id'] == column_id)
               for column_id in index['columns']]
    prefix = 'pk' if index.get('primary_key') else ('uq' if index['unique'] else 'idx')
    return '%s_%s_%s' % (prefix, table['name'], '_'.join(columns))


def _create_index(table, index, dialect):
    columns = ', '.join(_quote(_column(table, column_id)['name'], dialect)
                        for column_id in index['columns'])
    table_name = _table_name(table, dialect)
    if index.get('primary_key'):
        return 'ALTER TABLE %s ADD PRIMARY KEY (%s);' % (table_name, columns)
    unique = 'UNIQUE ' if index['unique'] else ''
    return 'CREATE %sINDEX %s ON %s (%s);' % (
        unique, _quote(_index_name(table, index), dialect), table_name, columns)


def _drop_index(table, index, dialect):
    table_name = _table_name(table, dialect)
    if index.get('primary_key'):
        if dialect == 'mysql':
            return 'ALTER TABLE %s DROP PRIMARY KEY;' % table_name
        constraint = index.get('name') or table['name'] + '_pkey'
        return 'ALTER TABLE %s DROP CONSTRAINT %s;' % (
            table_name, _quote(constraint, dialect))
    name = _quote(_index_name(table, index), dialect)
    if dialect == 'mysql':
        return 'DROP INDEX %s ON %s;' % (name, table_name)
    return 'DROP INDEX %s;' % name


def _index_changes(old_table, new_table, dialect):
    old = {index['id']: index for index in old_table['indexes']}
    new = {index['id']: index for index in new_table['indexes']}
    statements = []
    for index_id in sorted(set(old) - set(new)):
        statements.append(_drop_index(old_table, old[index_id], dialect))
    for index_id in sorted(set(old) & set(new)):
        before, after = old[index_id], new[index_id]
        comparable = ('name', 'columns', 'unique', 'primary_key')
        if any(before.get(field) != after.get(field) for field in comparable):
            statements.append(_drop_index(old_table, before, dialect))
            statements.append(_create_index(new_table, after, dialect))
    for index_id in sorted(set(new) - set(old)):
        statements.append(_create_index(new_table, new[index_id], dialect))
    return statements


def _relationship(project, relationship_id):
    return _find(project['relationships'], relationship_id, 'relacionamento')


def _relationship_name(project, relationship):
    if relationship.get('name'):
        return relationship['name']
    child = _table(project, relationship['from']['table_id'])
    column = _column(child, relationship['from']['column_ids'][0])
    parent = _table(project, relationship['to']['table_id'])
    return 'fk_%s_%s_%s' % (child['name'], column['name'], parent['name'])


def _add_relationship(project, relationship, dialect):
    child = _table(project, relationship['from']['table_id'])
    parent = _table(project, relationship['to']['table_id'])
    child_columns = ', '.join(_quote(_column(child, value)['name'], dialect)
                              for value in relationship['from']['column_ids'])
    parent_columns = ', '.join(_quote(_column(parent, value)['name'], dialect)
                               for value in relationship['to']['column_ids'])
    statement = 'ALTER TABLE %s ADD CONSTRAINT %s FOREIGN KEY (%s) REFERENCES %s (%s)' % (
        _table_name(child, dialect), _quote(_relationship_name(project, relationship), dialect),
        child_columns, _table_name(parent, dialect), parent_columns)
    if relationship.get('on_delete'):
        statement += ' ON DELETE ' + relationship['on_delete']
    if relationship.get('on_update'):
        statement += ' ON UPDATE ' + relationship['on_update']
    return statement + ';'


def _drop_relationship(project, relationship, dialect):
    child = _table(project, relationship['from']['table_id'])
    name = _quote(_relationship_name(project, relationship), dialect)
    command = 'DROP FOREIGN KEY' if dialect == 'mysql' else 'DROP CONSTRAINT'
    return 'ALTER TABLE %s %s %s;' % (_table_name(child, dialect), command, name)


def _removed_relationships(old, new, dialect):
    remaining = {relationship['id'] for relationship in new['relationships']}
    return [_drop_relationship(old, relationship, dialect)
            for relationship in old['relationships'] if relationship['id'] not in remaining]


def mutation_statements(old, new, operation):
    """Retorna as instruções SQL incrementais correspondentes a uma mutação."""
    action = operation.get('action')
    dialect = new.get('dialect') or old.get('dialect') or 'postgres'
    statements = []

    if action == 'table.update':
        before = _table(old, operation['table_id'])
        after = _table(new, operation['table_id'])
        current_name = _table_name(before, dialect)
        if before['name'] != after['name']:
            statements.append('ALTER TABLE %s RENAME TO %s;' %
                              (current_name, _quote(after['name'], dialect)))
        if before.get('schema') != after.get('schema'):
            if dialect != 'postgres':
                raise ValueError('alterar schema visualmente requer PostgreSQL')
            if not after.get('schema'):
                raise ValueError('informe o schema de destino')
            statements.append('ALTER TABLE %s SET SCHEMA %s;' %
                              (_quote(after['name'], dialect),
                               _quote(after['schema'], dialect)))
    elif action == 'table.delete':
        statements.extend(_removed_relationships(old, new, dialect))
        statements.append('DROP TABLE %s;' % _table_name(_table(old, operation['table_id']), dialect))
    elif action == 'column.create':
        table = _table(new, operation['table_id'])
        created = next(column for column in table['columns']
                       if all(column['id'] != old_column['id']
                              for old_column in _table(old, table['id'])['columns']))
        statements.append('ALTER TABLE %s ADD COLUMN %s;' %
                          (_table_name(table, dialect), _column_definition(created, dialect)))
        statements.extend(_index_changes(_table(old, table['id']), table, dialect))
    elif action == 'column.update':
        old_table = _table(old, operation['table_id'])
        new_table = _table(new, operation['table_id'])
        before = _column(old_table, operation['column_id'])
        after = _column(new_table, operation['column_id'])
        table_name = _table_name(new_table, dialect)
        current = before['name']
        if before['name'] != after['name']:
            statements.append('ALTER TABLE %s RENAME COLUMN %s TO %s;' %
                              (table_name, _quote(before['name'], dialect),
                               _quote(after['name'], dialect)))
            current = after['name']
        if dialect == 'mysql':
            if any(before.get(field) != after.get(field)
                   for field in ('name', 'type', 'nullable', 'default')):
                statements.append('ALTER TABLE %s MODIFY COLUMN %s;' %
                                  (table_name, _column_definition(after, dialect)))
        else:
            if before['type'] != after['type']:
                statements.append('ALTER TABLE %s ALTER COLUMN %s TYPE %s;' %
                                  (table_name, _quote(current, dialect), after['type']))
            if before['nullable'] != after['nullable']:
                mode = 'DROP NOT NULL' if after['nullable'] else 'SET NOT NULL'
                statements.append('ALTER TABLE %s ALTER COLUMN %s %s;' %
                                  (table_name, _quote(current, dialect), mode))
            if before.get('default') != after.get('default'):
                mode = ('DROP DEFAULT' if after.get('default') in (None, '')
                        else 'SET DEFAULT ' + str(after['default']))
                statements.append('ALTER TABLE %s ALTER COLUMN %s %s;' %
                                  (table_name, _quote(current, dialect), mode))
        statements.extend(_index_changes(old_table, new_table, dialect))
    elif action == 'column.delete':
        old_table = _table(old, operation['table_id'])
        new_table = _table(new, operation['table_id'])
        statements.extend(_removed_relationships(old, new, dialect))
        statements.extend(_index_changes(old_table, new_table, dialect))
        column = _column(old_table, operation['column_id'])
        statements.append('ALTER TABLE %s DROP COLUMN %s;' %
                          (_table_name(old_table, dialect), _quote(column['name'], dialect)))
    elif action.startswith('index.'):
        old_table = _table(old, operation['table_id'])
        new_table = _table(new, operation['table_id'])
        statements.extend(_index_changes(old_table, new_table, dialect))
    elif action == 'relationship.create':
        relationship = next(value for value in new['relationships']
                            if all(value['id'] != old_value['id']
                                   for old_value in old['relationships']))
        statements.append(_add_relationship(new, relationship, dialect))
    elif action == 'relationship.update':
        before = _relationship(old, operation['relationship_id'])
        after = _relationship(new, operation['relationship_id'])
        statements.extend([_drop_relationship(old, before, dialect),
                           _add_relationship(new, after, dialect)])
    elif action == 'relationship.delete':
        statements.append(_drop_relationship(
            old, _relationship(old, operation['relationship_id']), dialect))
    else:
        raise ValueError('ação de mutação não suportada')
    return statements


def sync_source(old, new, operation):
    """Anexa o DDL da mutação ao SQL original e atualiza o projeto resultante."""
    statements = mutation_statements(old, new, operation)
    source = old['source']['sql'].rstrip()
    addition = '\n'.join(statements)
    sql = (source + '\n\n' + addition).lstrip() if source else addition
    new['source'] = {'sql': sql, 'dialect': new['dialect']}
    return new
