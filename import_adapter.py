"""Adapters between the current SQL parser and the canonical project model."""

import copy
import math

import parse_sql
from project import loads, new_project, stable_id, validate_project


def _key(schema, name):
    return ((schema or "").casefold(), (name or "").casefold())


def _as_previous(previous):
    if previous is None:
        return None
    if isinstance(previous, str):
        previous = loads(previous)
    validate_project(previous)
    return previous


def _finite(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _previous_tables(previous):
    return {_key(table.get("schema"), table["name"]): table
            for table in (previous or {}).get("tables", [])}


def _previous_columns(table):
    return {(column["name"].casefold()): column for column in (table or {}).get("columns", [])}


def _legacy_layout(legacy_layout, tables_by_key):
    """Convert old name-keyed positions and keep valid block geometry."""
    result = {"tables": {}, "blocks": []}
    if not isinstance(legacy_layout, dict):
        return result
    old_tables = legacy_layout.get("tables", {})
    if isinstance(old_tables, dict):
        for name, point in old_tables.items():
            if not isinstance(point, dict) or not _finite(point.get("x")) or not _finite(point.get("y")):
                continue
            table = tables_by_key.get(_key(None, name))
            if table:
                result["tables"][table["id"]] = {"x": point["x"], "y": point["y"]}
    blocks = legacy_layout.get("blocks", [])
    if isinstance(blocks, list):
        for number, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            required = ("name", "x", "y", "w", "h", "color")
            if not all(field in block for field in required):
                continue
            if not all(_finite(block.get(field)) for field in ("x", "y", "w", "h")):
                continue
            if block["w"] <= 0 or block["h"] <= 0:
                continue
            if not isinstance(block["name"], str) or not isinstance(block["color"], str):
                continue
            block_id = block.get("id") or stable_id("block", block["name"], number)
            raw_table_names = block.get("table_names", block.get("tables", []))
            if isinstance(raw_table_names, dict):
                raw_table_names = list(raw_table_names)
            table_ids = []
            if isinstance(raw_table_names, list):
                table_ids = [tables_by_key[_key(None, name)]["id"]
                             for name in raw_table_names
                             if isinstance(name, str) and _key(None, name) in tables_by_key]
            result["blocks"].append({
                "id": block_id,
                "name": block["name"],
                "x": block["x"],
                "y": block["y"],
                "w": block["w"],
                "h": block["h"],
                "color": block["color"],
                "table_ids": table_ids,
            })
    return result


def _copy_previous_layout(previous, table_ids):
    if not previous:
        return {"tables": {}, "blocks": []}
    old_layout = previous.get("layout", {})
    result = {"tables": {}, "blocks": []}
    for table_id, point in old_layout.get("tables", {}).items():
        if table_id in table_ids and _finite(point.get("x")) and _finite(point.get("y")):
            result["tables"][table_id] = {"x": point["x"], "y": point["y"]}
    for block in old_layout.get("blocks", []):
        if not isinstance(block, dict):
            continue
        table_block = copy.deepcopy(block)
        table_block["table_ids"] = [table_id for table_id in block.get("table_ids", [])
                                     if table_id in table_ids]
        result["blocks"].append(table_block)
    return result


def _group_foreign_keys(foreign_keys):
    """Reagrupa os pares emitidos pelo parser para constraints compostas."""
    groups, order = {}, []
    for number, foreign_key in enumerate(foreign_keys):
        name = foreign_key.get("name")
        key = ((foreign_key.get("child"), foreign_key.get("parent"), name,
                foreign_key.get("on_delete"), foreign_key.get("on_update"))
               if name else ("inline", number))
        if key not in groups:
            groups[key] = dict(foreign_key, cols=[], pcols=[])
            order.append(key)
        groups[key]["cols"].append(foreign_key.get("col"))
        groups[key]["pcols"].append(foreign_key.get("pcol"))
    return [groups[key] for key in order]


def _make_checks(table_id, parsed_checks):
    """CHECKs viram itens do modelo com id estável derivado da expressão."""
    checks = []
    for check in parsed_checks or []:
        expression = (check.get("expression") or "").strip()
        if not expression:
            continue
        checks.append({
            "id": stable_id("check", table_id, check.get("name") or expression),
            "name": check.get("name"),
            "expression": expression,
        })
    return checks


def _make_indexes(table_id, columns, unique_sets, parsed_indexes=None, previous_table=None):
    column_by_name = {column["name"].casefold(): column for column in columns}
    previous_indexes = (previous_table or {}).get("indexes", [])
    previous_by_name = {index["name"].casefold(): index for index in previous_indexes
                        if index.get("name")}
    previous_by_shape = {
        (tuple(index.get("columns", [])), bool(index.get("unique")),
         bool(index.get("primary_key"))): index for index in previous_indexes
    }
    indexes, seen = [], set()
    primary_ids = {column["id"] for column in columns if column["primary_key"]}
    definitions = list(parsed_indexes or [])
    definitions.extend({"name": None, "columns": values, "unique": True,
                        "primary_key": False} for values in unique_sets)
    for definition in definitions:
        values = definition.get("columns", [])
        column_ids = tuple(column_by_name[name.casefold()]["id"] for name in values
                           if name.casefold() in column_by_name)
        unique = bool(definition.get("unique"))
        is_primary = bool(definition.get("primary_key")) or (
            set(column_ids) == primary_ids and bool(primary_ids))
        signature = (column_ids, unique or is_primary, is_primary)
        if not column_ids or signature in seen:
            continue
        seen.add(signature)
        name = definition.get("name")
        old = (previous_by_name.get(name.casefold()) if isinstance(name, str) and name
               else previous_by_shape.get(signature))
        indexes.append({
            "id": old["id"] if old else stable_id("index", table_id, name, *column_ids,
                                                    unique, is_primary),
            "name": name if name is not None else (old.get("name") if old else None),
            "columns": list(column_ids),
            "unique": unique or is_primary,
            "primary_key": is_primary,
        })
    return indexes


def import_sql(sql, title="novo_schema.sql", dialect=None, previous=None, legacy_layout=None):
    """Parse SQL into a canonical project, reusing IDs where possible."""
    if not isinstance(sql, str):
        raise ValueError("sql deve ser texto")
    previous = _as_previous(previous)
    parsed = parse_sql.parse(sql, dialect=dialect, is_sql=True)
    actual_dialect = parsed.get("dialect") or dialect or "postgres"
    previous_tables = _previous_tables(previous)
    project = new_project(title, actual_dialect)
    if previous:
        project["id"] = previous["id"]
    project["source"] = {"sql": sql, "dialect": actual_dialect}

    tables_by_name = {}
    for name in sorted(parsed.get("tables", {})):
        parsed_table = parsed["tables"][name]
        schema = parsed_table.get("schema")
        old_table = (previous_tables.get(_key(schema, name)) or
                     previous_tables.get(_key(None, name)))
        table_id = old_table["id"] if old_table else stable_id("table", schema, name)
        columns = []
        old_columns = _previous_columns(old_table)
        for parsed_column in parsed_table.get("cols", []):
            column_name = parsed_column["name"]
            old_column = old_columns.get(column_name.casefold())
            column_id = old_column["id"] if old_column else stable_id("column", table_id, column_name)
            primary_key = bool(parsed_column.get("pk"))
            columns.append({
                "id": column_id,
                "name": column_name,
                "type": parsed_column.get("type", ""),
                "nullable": not bool(parsed_column.get("notnull")) and not primary_key,
                "primary_key": primary_key,
                "unique": False,
                "default": parsed_column.get("default"),
            })
        for unique_set in parsed_table.get("unique", []):
            if len(unique_set) == 1:
                for column in columns:
                    if column["name"].casefold() == unique_set[0].casefold():
                        column["unique"] = True
        table = {
            "id": table_id,
            "schema": schema if schema is not None else (
                old_table.get("schema") if old_table else None),
            "name": name,
            "columns": columns,
            "indexes": _make_indexes(table_id, columns, parsed_table.get("unique", []),
                                     parsed_table.get("indexes", []), old_table),
            "checks": _make_checks(table_id, parsed_table.get("checks", [])),
        }
        project["tables"].append(table)
        tables_by_name[_key(None, name)] = table
        tables_by_name[_key(table.get("schema"), name)] = table

    tables_by_id = {table["id"]: table for table in project["tables"]}
    old_relationships = (previous or {}).get("relationships", [])
    old_by_endpoint = {}
    for relation in old_relationships:
        endpoint_key = (
            relation["from"]["table_id"], tuple(relation["from"]["column_ids"]),
            relation["to"]["table_id"], tuple(relation["to"]["column_ids"]),
        )
        old_by_endpoint.setdefault(endpoint_key, []).append(relation)
    used_old_relations = set()
    for parsed_fk in _group_foreign_keys(parsed.get("fks", [])):
        child = tables_by_name.get(_key(None, parsed_fk.get("child")))
        parent = tables_by_name.get(_key(None, parsed_fk.get("parent")))
        if not child or not parent:
            continue
        child_by_name = {column["name"].casefold(): column for column in child["columns"]}
        parent_by_name = {column["name"].casefold(): column for column in parent["columns"]}
        child_columns = [child_by_name.get((name or "").casefold())
                         for name in parsed_fk["cols"]]
        parent_columns = [parent_by_name.get((name or "").casefold())
                          for name in parsed_fk["pcols"]]
        if (not child_columns or len(child_columns) != len(parent_columns)
                or any(column is None for column in child_columns + parent_columns)):
            continue
        child_ids = tuple(column["id"] for column in child_columns)
        parent_ids = tuple(column["id"] for column in parent_columns)
        endpoint_key = (child["id"], child_ids, parent["id"], parent_ids)
        old_relation = next((relation for relation in old_by_endpoint.get(endpoint_key, [])
                             if relation["id"] not in used_old_relations), None)
        if old_relation:
            used_old_relations.add(old_relation["id"])
        relation = {
            "id": old_relation["id"] if old_relation else stable_id(
                "relationship", child["id"], *child_ids, parent["id"], *parent_ids),
            "name": parsed_fk.get("name"),
            "from": {"table_id": child["id"], "column_ids": list(child_ids)},
            "to": {"table_id": parent["id"], "column_ids": list(parent_ids)},
            "on_delete": (parsed_fk.get("on_delete") if parsed_fk.get("on_delete") is not None
                          else (old_relation.get("on_delete") if old_relation else None)),
            "on_update": (parsed_fk.get("on_update") if parsed_fk.get("on_update") is not None
                          else (old_relation.get("on_update") if old_relation else None)),
        }
        project["relationships"].append(relation)

    if legacy_layout is not None:
        project["layout"] = _legacy_layout(legacy_layout, tables_by_name)
    else:
        project["layout"] = _copy_previous_layout(previous, set(tables_by_id))
    validate_project(project)
    return project


def project_to_parsed(project):
    """Adapt a canonical project to the dictionary consumed by model.py."""
    validate_project(project)
    tables, name_by_id, column_name_by_id = {}, {}, {}
    for table in project["tables"]:
        columns = []
        for column in table["columns"]:
            columns.append({"name": column["name"], "type": column["type"],
                            "notnull": not column["nullable"],
                            "pk": column["primary_key"],
                            "default": column.get("default")})
            column_name_by_id[column["id"]] = column["name"]
        unique = []
        for index in table["indexes"]:
            names = [column_name_by_id[column_id] for column_id in index["columns"]]
            if names not in unique:
                unique.append(names)
        indexes = [{"name": index.get("name"),
                    "columns": [column_name_by_id[column_id]
                                for column_id in index["columns"]],
                    "unique": index["unique"],
                    "primary_key": bool(index.get("primary_key"))}
                   for index in table["indexes"]]
        tables[table["name"]] = {"name": table["name"], "schema": table.get("schema"),
                                  "cols": columns, "unique": unique,
                                  "indexes": indexes, "fkcols": set()}
        name_by_id[table["id"]] = table["name"]
    fks = []
    for relation in project["relationships"]:
        child_name = name_by_id[relation["from"]["table_id"]]
        parent_name = name_by_id[relation["to"]["table_id"]]
        for child_column, parent_column in zip(relation["from"]["column_ids"],
                                               relation["to"]["column_ids"]):
            child_col_name = column_name_by_id[child_column]
            fks.append({"id": relation["id"], "child": child_name,
                        "col": child_col_name, "parent": parent_name,
                        "pcol": column_name_by_id[parent_column],
                        "name": relation.get("name"),
                        "on_delete": relation.get("on_delete"),
                        "on_update": relation.get("on_update")})
            tables[child_name]["fkcols"].add(child_col_name)
    return {"tables": tables, "fks": fks, "dialect": project["dialect"], "dropped": []}


def project_layout_to_legacy(project):
    """Convert ID-keyed layout to the name-keyed legacy layout format."""
    validate_project(project)
    names = {table["id"]: table["name"] for table in project["tables"]}
    layout = {"tables": {}, "blocks": []}
    for table_id, point in project["layout"]["tables"].items():
        layout["tables"][names[table_id]] = {"x": point["x"], "y": point["y"]}
    for block in project["layout"]["blocks"]:
        legacy_block = {field: block[field] for field in ("id", "name", "x", "y", "w", "h", "color")}
        if block.get("table_ids"):
            legacy_block["table_names"] = [names[table_id] for table_id in block["table_ids"]]
        layout["blocks"].append(legacy_block)
    return layout
