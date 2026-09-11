"""Safe mutations for the canonical Schema Map project model.

The module intentionally has no SQL concerns.  It changes a deep copy of a
canonical project and validates the resulting document before returning it.
"""

import copy
import re

import project as project_model


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FK_ACTIONS = {None, "NO ACTION", "RESTRICT", "CASCADE", "SET NULL", "SET DEFAULT"}
_TABLE_ACTIONS = {"table.update", "table.delete"}
_COLUMN_ACTIONS = {"column.create", "column.update", "column.delete"}
_INDEX_ACTIONS = {"index.create", "index.update", "index.delete"}
_RELATIONSHIP_ACTIONS = {
    "relationship.create", "relationship.update", "relationship.delete"
}
_TABLE_FIELDS = {"name", "schema"}
_COLUMN_FIELDS = {
    "name", "type", "nullable", "primary_key", "unique", "default"
}
_INDEX_FIELDS = {"name", "columns", "unique"}
_RELATIONSHIP_FIELDS = {"name", "from", "to", "on_delete", "on_update"}


def _error(message):
    raise ValueError(message)


def _required_dict(value, label):
    if not isinstance(value, dict):
        _error("%s deve ser um objeto" % label)
    return value


def _text(value, label, allow_none=False):
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value.strip():
        _error("%s deve ser um texto não vazio" % label)
    return value.strip()


def _identifier(value, label, allow_none=False):
    value = _text(value, label, allow_none=allow_none)
    if value is None:
        return None
    if not _IDENTIFIER.fullmatch(value):
        _error("%s deve ser um identificador simples" % label)
    return value


def _values(operation, allowed, label):
    values = _required_dict(operation.get("values"), "%s.values" % label)
    unknown = sorted(set(values) - allowed)
    if unknown:
        _error("campo(s) não permitido(s) em %s.values: %s" %
               (label, ", ".join(unknown)))
    return values


def _find(items, item_id, label):
    for item in items:
        if item.get("id") == item_id:
            return item
    _error("%s não encontrado: %s" % (label, item_id))


def _table(project, table_id):
    return _find(project["tables"], table_id, "tabela")


def _column(table, column_id):
    return _find(table["columns"], column_id, "coluna")


def _index(table, index_id):
    return _find(table["indexes"], index_id, "índice")


def _relationship(project, relationship_id):
    return _find(project["relationships"], relationship_id, "relacionamento")


def _new_id(kind, occupied, *parts):
    """Create a stable ID and disambiguate collisions deterministically."""
    candidate = project_model.stable_id(kind, *parts)
    number = 2
    while candidate in occupied:
        candidate = project_model.stable_id(kind, *parts, number)
        number += 1
    occupied.add(candidate)
    return candidate


def _all_ids(value):
    result = {value["id"]}
    for table in value["tables"]:
        result.add(table["id"])
        result.update(column["id"] for column in table["columns"])
        result.update(index["id"] for index in table["indexes"])
    result.update(relation["id"] for relation in value["relationships"])
    result.update(block["id"] for block in value["layout"]["blocks"])
    return result


def _assert_unique_names(project):
    table_names = set()
    for table in project["tables"]:
        table_name = table["name"].casefold()
        if table_name in table_names:
            _error("tabela duplicada: %s" % table["name"])
        table_names.add(table_name)

        column_names = set()
        index_names = set()
        for column in table["columns"]:
            name = column["name"].casefold()
            if name in column_names:
                _error("coluna duplicada em %s: %s" % (table["name"], column["name"]))
            column_names.add(name)
        for index in table["indexes"]:
            if index.get("name") is None:
                continue
            name = index["name"].casefold()
            if name in index_names:
                _error("índice duplicado em %s: %s" % (table["name"], index["name"]))
            index_names.add(name)
    relationship_names = set()
    for relation in project["relationships"]:
        if relation.get("name") is None:
            continue
        name = relation["name"].casefold()
        if name in relationship_names:
            _error("relacionamento duplicado: %s" % relation["name"])
        relationship_names.add(name)


def _check_column_values(values, label, partial=False):
    result = {}
    for field in values:
        if field == "name":
            result[field] = _identifier(values[field], "%s.name" % label)
        elif field == "type":
            result[field] = _text(values[field], "%s.type" % label)
        elif field in ("nullable", "primary_key", "unique"):
            if not isinstance(values[field], bool):
                _error("%s.%s deve ser booleano" % (label, field))
            result[field] = values[field]
        elif field == "default":
            result[field] = values[field]
    return result


def _check_table_values(values, label):
    result = {}
    if "name" in values:
        result["name"] = _identifier(values["name"], "%s.name" % label)
    if "schema" in values:
        result["schema"] = _identifier(values["schema"], "%s.schema" % label,
                                        allow_none=True)
    return result


def _check_index_values(values, label, partial=False):
    result = {}
    if "name" in values:
        result["name"] = _identifier(values["name"], "%s.name" % label,
                                      allow_none=True)
    if "columns" in values:
        if not isinstance(values["columns"], list) or not values["columns"]:
            _error("%s.columns deve ser uma lista não vazia" % label)
        if any(not isinstance(column_id, str) or not column_id.strip()
               for column_id in values["columns"]):
            _error("%s.columns contém ID inválido" % label)
        if len(set(values["columns"])) != len(values["columns"]):
            _error("%s.columns não pode conter colunas repetidas" % label)
        result["columns"] = list(values["columns"])
    if "unique" in values:
        if not isinstance(values["unique"], bool):
            _error("%s.unique deve ser booleano" % label)
        result["unique"] = values["unique"]
    return result


def _check_action(value, label):
    if value not in _FK_ACTIONS:
        _error("%s deve ser NO ACTION, RESTRICT, CASCADE, SET NULL, SET DEFAULT ou None" % label)
    return value


def _check_endpoint(endpoint, value, label):
    endpoint = _required_dict(endpoint, "%s.%s" % (label, value))
    if not isinstance(endpoint.get("table_id"), str) or not endpoint["table_id"]:
        _error("%s.%s.table_id inválido" % (label, value))
    columns = endpoint.get("column_ids")
    if not isinstance(columns, list) or not columns:
        _error("%s.%s.column_ids deve ser uma lista não vazia" % (label, value))
    if any(not isinstance(column_id, str) or not column_id for column_id in columns):
        _error("%s.%s.column_ids contém ID inválido" % (label, value))
    if len(set(columns)) != len(columns):
        _error("%s.%s.column_ids não pode conter colunas repetidas" % (label, value))
    return {"table_id": endpoint["table_id"], "column_ids": list(columns)}


def _check_relationship_values(values, label):
    result = {}
    if "name" in values:
        result["name"] = _identifier(values["name"], "%s.name" % label, allow_none=True)
    for endpoint in ("from", "to"):
        if endpoint in values:
            result[endpoint] = _check_endpoint(values[endpoint], endpoint, label)
    for action in ("on_delete", "on_update"):
        if action in values:
            result[action] = _check_action(values[action], "%s.%s" % (label, action))
    return result


def _endpoint_key(relation):
    return (
        relation["from"]["table_id"], tuple(relation["from"]["column_ids"]),
        relation["to"]["table_id"], tuple(relation["to"]["column_ids"]),
    )


def _validate_relationships(project):
    seen = set()
    for relation in project["relationships"]:
        key = _endpoint_key(relation)
        if key in seen:
            _error("relacionamento duplicado para os mesmos endpoints")
        seen.add(key)
        if len(relation["from"]["column_ids"]) != len(relation["to"]["column_ids"]):
            _error("relacionamento exige o mesmo número de colunas nos endpoints")
        _check_action(relation.get("on_delete"), "relationship.on_delete")
        _check_action(relation.get("on_update"), "relationship.on_update")


def _column_names(table, column_ids):
    by_id = {column["id"]: column["name"] for column in table["columns"]}
    return [by_id[column_id] for column_id in column_ids]


def _derived_index_name(table, kind, column_ids):
    prefix = "pk" if kind == "primary" else "uq"
    base = "%s_%s_%s" % (prefix, table["name"], "_".join(
        _column_names(table, column_ids)))
    existing = {index.get("name", "").casefold() for index in table["indexes"]
                if index.get("name")}
    candidate = base
    number = 2
    while candidate.casefold() in existing:
        candidate = "%s_%d" % (base, number)
        number += 1
    return candidate


def _sync_derived_indexes(table, remove_unset=False):
    """Keep one primary index and one unique index per column flag."""
    primary_columns = [column["id"] for column in table["columns"]
                       if column.get("primary_key")]
    indexes = table["indexes"]
    primary = [index for index in indexes if index.get("primary_key")]
    if primary_columns:
        if primary:
            primary_index = primary[0]
            primary_index["columns"] = list(primary_columns)
            primary_index["unique"] = True
            for duplicate in primary[1:]:
                indexes.remove(duplicate)
        else:
            occupied = {index["id"] for index in indexes}
            indexes.append({
                "id": _new_id("index", occupied, table["id"], "primary", *primary_columns),
                "name": _derived_index_name(table, "primary", primary_columns),
                "columns": list(primary_columns),
                "unique": True,
                "primary_key": True,
            })
    else:
        for index in list(primary):
            indexes.remove(index)

    if remove_unset:
        for column in table["columns"]:
            if column.get("unique") or column.get("primary_key"):
                continue
            wanted = [column["id"]]
            for index in list(indexes):
                if (not index.get("primary_key") and index.get("unique")
                        and index.get("columns") == wanted):
                    indexes.remove(index)

    for column in table["columns"]:
        if not column.get("unique") or column.get("primary_key"):
            continue
        wanted = [column["id"]]
        matching = next((index for index in indexes
                         if not index.get("primary_key") and index.get("unique")
                         and index.get("columns") == wanted), None)
        if matching is None:
            occupied = {index["id"] for index in indexes}
            indexes.append({
                "id": _new_id("index", occupied, table["id"], "unique", column["id"]),
                "name": _derived_index_name(table, "unique", wanted),
                "columns": wanted,
                "unique": True,
                "primary_key": False,
            })


def _ensure_column_refs(table, column_ids, label):
    for column_id in column_ids:
        _column(table, column_id)


def _ensure_no_primary_index(index, action):
    if index.get("primary_key"):
        _error("não é permitido %s índice primary_key diretamente" % action)


def _apply_table(value, operation, action):
    table_id = operation.get("table_id")
    table = _table(value, table_id)
    if action == "table.delete":
        value["tables"].remove(table)
        value["layout"]["tables"].pop(table_id, None)
        for block in value["layout"]["blocks"]:
            block["table_ids"] = [item for item in block.get("table_ids", [])
                                   if item != table_id]
        value["relationships"] = [
            relation for relation in value["relationships"]
            if relation["from"]["table_id"] != table_id
            and relation["to"]["table_id"] != table_id
        ]
        return
    values = _values(operation, _TABLE_FIELDS, action)
    checked = _check_table_values(values, action)
    for key, item in checked.items():
        table[key] = item


def _apply_column(value, operation, action):
    table = _table(value, operation.get("table_id"))
    table_id = table["id"]
    if action == "column.create":
        values = _values(operation, _COLUMN_FIELDS, action)
        checked = _check_column_values(values, action)
        if "name" not in checked or "type" not in checked:
            _error("column.create exige name e type")
        if any(column["name"].casefold() == checked["name"].casefold()
               for column in table["columns"]):
            _error("coluna duplicada em %s: %s" % (table["name"], checked["name"]))
        column = {
            "id": _new_id("column", _all_ids(value), table_id, checked["name"]),
            "name": checked["name"], "type": checked["type"],
            "nullable": checked.get("nullable", True),
            "primary_key": checked.get("primary_key", False),
            "unique": checked.get("unique", False),
            "default": checked.get("default"),
        }
        if column["primary_key"]:
            column["nullable"] = False
            column["unique"] = True
        table["columns"].append(column)
        _sync_derived_indexes(table)
        return

    column = _column(table, operation.get("column_id"))
    if action == "column.delete":
        column_id = column["id"]
        table["columns"].remove(column)
        table["indexes"] = [index for index in table["indexes"]
                            if column_id not in index.get("columns", [])]
        value["relationships"] = [
            relation for relation in value["relationships"]
            if column_id not in relation["from"]["column_ids"]
            and column_id not in relation["to"]["column_ids"]
        ]
        return
    values = _values(operation, _COLUMN_FIELDS, action)
    checked = _check_column_values(values, action, partial=True)
    if "name" in checked and any(other["id"] != column["id"]
                                 and other["name"].casefold() == checked["name"].casefold()
                                 for other in table["columns"]):
        _error("coluna duplicada em %s: %s" % (table["name"], checked["name"]))
    column.update(checked)
    if column.get("primary_key"):
        column["nullable"] = False
        column["unique"] = True
    _sync_derived_indexes(table, remove_unset=bool(
        {"unique", "primary_key"} & set(checked)))


def _apply_index(value, operation, action):
    table = _table(value, operation.get("table_id"))
    if action == "index.create":
        values = _values(operation, _INDEX_FIELDS, action)
        checked = _check_index_values(values, action)
        if "columns" not in checked:
            _error("index.create exige columns")
        _ensure_column_refs(table, checked["columns"], "index.columns")
        if checked.get("name") is not None and any(
                index.get("name") and index["name"].casefold() == checked["name"].casefold()
                for index in table["indexes"]):
            _error("índice duplicado em %s: %s" % (table["name"], checked["name"]))
        occupied = _all_ids(value)
        table["indexes"].append({
            "id": _new_id("index", occupied, table["id"], checked.get("name"),
                            *checked["columns"]),
            "name": checked.get("name"), "columns": checked["columns"],
            "unique": checked.get("unique", False), "primary_key": False,
        })
        return

    index = _index(table, operation.get("index_id"))
    _ensure_no_primary_index(index, "alterar" if action == "index.update" else "excluir")
    if action == "index.delete":
        table["indexes"].remove(index)
        return
    values = _values(operation, _INDEX_FIELDS | {"primary_key"}, action)
    if "primary_key" in values:
        _error("não é permitido alterar índice primary_key diretamente")
    checked = _check_index_values(values, action, partial=True)
    if "columns" in checked:
        _ensure_column_refs(table, checked["columns"], "index.columns")
    if "name" in checked and checked["name"] is not None and any(
            other["id"] != index["id"] and other.get("name")
            and other["name"].casefold() == checked["name"].casefold()
            for other in table["indexes"]):
        _error("índice duplicado em %s: %s" % (table["name"], checked["name"]))
    index.update(checked)


def _apply_relationship(value, operation, action):
    if action == "relationship.create":
        values = _values(operation, _RELATIONSHIP_FIELDS, action)
        checked = _check_relationship_values(values, action)
        if "from" not in checked or "to" not in checked:
            _error("relationship.create exige from e to")
        relation = {
            "id": _new_id("relationship", _all_ids(value),
                           checked["from"]["table_id"],
                           *checked["from"]["column_ids"],
                           checked["to"]["table_id"],
                           *checked["to"]["column_ids"]),
            "name": checked.get("name"), "from": checked["from"], "to": checked["to"],
            "on_delete": checked.get("on_delete"), "on_update": checked.get("on_update"),
        }
        for endpoint_name in ("from", "to"):
            table = _table(value, relation[endpoint_name]["table_id"])
            _ensure_column_refs(table, relation[endpoint_name]["column_ids"],
                                "relationship.%s" % endpoint_name)
        if len(relation["from"]["column_ids"]) != len(relation["to"]["column_ids"]):
            _error("relacionamento exige o mesmo número de colunas nos endpoints")
        if any(_endpoint_key(item) == _endpoint_key(relation)
               for item in value["relationships"]):
            _error("relacionamento duplicado para os mesmos endpoints")
        value["relationships"].append(relation)
        return

    relation = _relationship(value, operation.get("relationship_id"))
    if action == "relationship.delete":
        value["relationships"].remove(relation)
        return
    values = _values(operation, _RELATIONSHIP_FIELDS, action)
    checked = _check_relationship_values(values, action)
    candidate = copy.deepcopy(relation)
    candidate.update(checked)
    if "from" in checked:
        table = _table(value, candidate["from"]["table_id"])
        _ensure_column_refs(table, candidate["from"]["column_ids"], "relationship.from")
    if "to" in checked:
        table = _table(value, candidate["to"]["table_id"])
        _ensure_column_refs(table, candidate["to"]["column_ids"], "relationship.to")
    if len(candidate["from"]["column_ids"]) != len(candidate["to"]["column_ids"]):
        _error("relacionamento exige o mesmo número de colunas nos endpoints")
    if any(item["id"] != relation["id"] and _endpoint_key(item) == _endpoint_key(candidate)
           for item in value["relationships"]):
        _error("relacionamento duplicado para os mesmos endpoints")
    relation.update(checked)


def apply_mutation(value, operation):
    """Apply one canonical mutation and return a validated deep copy."""
    project_model.validate_project(value)
    result = copy.deepcopy(value)
    operation = _required_dict(operation, "operation")
    action = operation.get("action")
    if action not in (_TABLE_ACTIONS | _COLUMN_ACTIONS | _INDEX_ACTIONS |
                      _RELATIONSHIP_ACTIONS):
        _error("ação de mutação inválida: %s" % action)

    if action in _TABLE_ACTIONS:
        _apply_table(result, operation, action)
    elif action in _COLUMN_ACTIONS:
        _apply_column(result, operation, action)
    elif action in _INDEX_ACTIONS:
        _apply_index(result, operation, action)
    else:
        _apply_relationship(result, operation, action)

    _assert_unique_names(result)
    _validate_relationships(result)
    project_model.validate_project(result)
    return result
