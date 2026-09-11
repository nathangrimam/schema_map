"""Canonical, versioned project model for schema-map.

This module deliberately contains no SQL knowledge.  SQL import and the
legacy diagram adapter live in :mod:`import_adapter`, which keeps the
canonical model usable by future editors and exporters as well.
"""

import hashlib
import json
import math
import re


PROJECT_VERSION = 1

_ID_PREFIXES = {
    "project": "prj",
    "table": "tbl",
    "column": "col",
    "index": "idx",
    "relationship": "rel",
    "relation": "rel",
    "block": "blk",
}


def _text(value):
    if value is None:
        return ""
    return str(value)


def stable_id(kind, *parts):
    """Return a deterministic, readable identifier for a model entity."""
    raw_kind = re.sub(r"[^a-z0-9]+", "_", _text(kind).strip().lower()).strip("_")
    prefix = _ID_PREFIXES.get(raw_kind, raw_kind or "id")
    payload = "\x1f".join(_text(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return "%s_%s" % (prefix, digest)


def new_project(title="novo_schema.sql", dialect="postgres"):
    """Create an empty canonical project with a deterministic project ID."""
    dialect = dialect or "postgres"
    return {
        "version": PROJECT_VERSION,
        "id": stable_id("project", title, dialect),
        "title": title,
        "dialect": dialect,
        "tables": [],
        "relationships": [],
        "layout": {"tables": {}, "blocks": []},
        "source": {"sql": "", "dialect": dialect},
    }


def _is_string(value, allow_none=False):
    return (allow_none and value is None) or (isinstance(value, str) and bool(value.strip()))


def _is_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _require_dict(value, label):
    if not isinstance(value, dict):
        raise ValueError("%s deve ser um objeto" % label)


def _require_list(value, label):
    if not isinstance(value, list):
        raise ValueError("%s deve ser uma lista" % label)


def validate_project(project):
    """Validate the canonical shape and all internal references.

    The function returns ``None`` on success and raises ``ValueError`` with a
    short path-like message on invalid data.  IDs are checked globally so a
    malformed document cannot make an entity ambiguous to an editor.
    """
    _require_dict(project, "project")
    if project.get("version") != PROJECT_VERSION:
        raise ValueError("project.version incompatível")
    for field in ("id", "title", "dialect"):
        if not _is_string(project.get(field)):
            raise ValueError("project.%s inválido" % field)
    _require_list(project.get("tables"), "project.tables")
    _require_list(project.get("relationships"), "project.relationships")
    _require_dict(project.get("layout"), "project.layout")
    _require_dict(project["layout"].get("tables"), "project.layout.tables")
    _require_list(project["layout"].get("blocks"), "project.layout.blocks")
    _require_dict(project.get("source"), "project.source")
    if not isinstance(project["source"].get("sql"), str):
        raise ValueError("project.source.sql inválido")
    if not _is_string(project["source"].get("dialect")):
        raise ValueError("project.source.dialect inválido")

    ids = set()

    def add_id(value, label):
        if not _is_string(value):
            raise ValueError("%s.id inválido" % label)
        if value in ids:
            raise ValueError("ID duplicado: %s" % value)
        ids.add(value)

    add_id(project["id"], "project")
    tables_by_id = {}
    columns_by_id = {}
    table_names = set()
    for table in project["tables"]:
        _require_dict(table, "table")
        add_id(table.get("id"), "table")
        table_id = table["id"]
        tables_by_id[table_id] = table
        if not _is_string(table.get("name")):
            raise ValueError("table.name inválido")
        if table["name"] in table_names:
            raise ValueError("tabela duplicada: %s" % table["name"])
        table_names.add(table["name"])
        if table.get("schema") is not None and not _is_string(table.get("schema")):
            raise ValueError("table.schema inválido")
        _require_list(table.get("columns"), "table.columns")
        _require_list(table.get("indexes"), "table.indexes")
        names = set()
        columns_by_id[table_id] = {}
        for column in table["columns"]:
            _require_dict(column, "column")
            add_id(column.get("id"), "column")
            if not _is_string(column.get("name")) or column["name"] in names:
                raise ValueError("coluna inválida ou duplicada em %s" % table["name"])
            names.add(column["name"])
            if not _is_string(column.get("type")):
                raise ValueError("column.type inválido")
            for flag in ("nullable", "primary_key", "unique"):
                if not isinstance(column.get(flag), bool):
                    raise ValueError("column.%s inválido" % flag)
            columns_by_id[table_id][column["id"]] = column
        for index in table["indexes"]:
            _require_dict(index, "index")
            add_id(index.get("id"), "index")
            if not _is_string(index.get("name"), allow_none=True):
                raise ValueError("index.name inválido")
            _require_list(index.get("columns"), "index.columns")
            if not index["columns"]:
                raise ValueError("index.columns vazio")
            if any(column_id not in columns_by_id[table_id] for column_id in index["columns"]):
                raise ValueError("index referencia coluna inexistente")
            if not isinstance(index.get("unique"), bool):
                raise ValueError("index.unique inválido")
            if "primary_key" in index and not isinstance(index["primary_key"], bool):
                raise ValueError("index.primary_key inválido")

    relation_ids = set()
    for relation in project["relationships"]:
        _require_dict(relation, "relationship")
        add_id(relation.get("id"), "relationship")
        relation_ids.add(relation["id"])
        if not _is_string(relation.get("name"), allow_none=True):
            raise ValueError("relationship.name inválido")
        for endpoint_name in ("from", "to"):
            endpoint = relation.get(endpoint_name)
            _require_dict(endpoint, "relationship.%s" % endpoint_name)
            table_id = endpoint.get("table_id")
            if table_id not in tables_by_id:
                raise ValueError("relationship.%s.table_id inexistente" % endpoint_name)
            _require_list(endpoint.get("column_ids"), "relationship.%s.column_ids" % endpoint_name)
            if not endpoint["column_ids"]:
                raise ValueError("relationship.%s.column_ids vazio" % endpoint_name)
            if any(column_id not in columns_by_id[table_id]
                   for column_id in endpoint["column_ids"]):
                raise ValueError("relationship.%s referencia coluna inexistente" % endpoint_name)
        for action in ("on_delete", "on_update"):
            if not _is_string(relation.get(action), allow_none=True):
                raise ValueError("relationship.%s inválido" % action)

    for table_id, point in project["layout"]["tables"].items():
        if table_id not in tables_by_id:
            raise ValueError("layout referencia tabela inexistente")
        _require_dict(point, "layout.tables.%s" % table_id)
        if not _is_number(point.get("x")) or not _is_number(point.get("y")):
            raise ValueError("posição inválida para %s" % table_id)

    for block in project["layout"]["blocks"]:
        _require_dict(block, "layout.block")
        add_id(block.get("id"), "block")
        for field in ("name", "color"):
            if not _is_string(block.get(field)):
                raise ValueError("block.%s inválido" % field)
        for field in ("x", "y", "w", "h"):
            if not _is_number(block.get(field)):
                raise ValueError("block.%s inválido" % field)
        if block["w"] <= 0 or block["h"] <= 0:
            raise ValueError("dimensão de bloco inválida")
        table_ids = block.get("table_ids", [])
        if not isinstance(table_ids, list) or any(table_id not in tables_by_id for table_id in table_ids):
            raise ValueError("block.table_ids inválido")
    return None


def dumps(project):
    """Serialize a valid project deterministically as versioned JSON."""
    validate_project(project)
    return json.dumps(project, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def loads(text):
    """Load and validate a canonical project from JSON text."""
    if not isinstance(text, str):
        raise ValueError("project JSON deve ser texto")
    try:
        project = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("JSON de projeto inválido") from exc
    validate_project(project)
    return project


def _by_id(items):
    return {item["id"]: item for item in items}


def _changed_fields(old, new, excluded=()):
    keys = sorted(set(old) | set(new))
    return {key: {"from": old.get(key), "to": new.get(key)}
            for key in keys if key not in excluded and old.get(key) != new.get(key)}


def _diff_entities(old_items, new_items, label, excluded=()):
    old_by_id, new_by_id = _by_id(old_items), _by_id(new_items)
    added = [new_by_id[key] for key in sorted(set(new_by_id) - set(old_by_id))]
    removed = [old_by_id[key] for key in sorted(set(old_by_id) - set(new_by_id))]
    changed = []
    for key in sorted(set(old_by_id) & set(new_by_id)):
        fields = _changed_fields(old_by_id[key], new_by_id[key], excluded)
        if fields:
            item = {"id": key, "changes": fields}
            if "name" in new_by_id[key]:
                item["name"] = new_by_id[key]["name"]
            changed.append(item)
    return {"added": added, "removed": removed, "changed": changed}


def _column_diff(old, new):
    result = _diff_entities(old, new, "columns")
    return result


def diff_projects(old, new):
    """Return a structural summary suitable for an editor preview."""
    validate_project(old)
    validate_project(new)
    old_tables, new_tables = _by_id(old["tables"]), _by_id(new["tables"])
    table_result = {"added": [], "removed": [], "changed": []}
    columns = {"added": [], "removed": [], "changed": []}
    for table_id in sorted(set(new_tables) - set(old_tables)):
        table_result["added"].append(new_tables[table_id])
        columns["added"].extend(new_tables[table_id]["columns"])
    for table_id in sorted(set(old_tables) - set(new_tables)):
        table_result["removed"].append(old_tables[table_id])
        columns["removed"].extend(old_tables[table_id]["columns"])
    for table_id in sorted(set(old_tables) & set(new_tables)):
        old_table, new_table = old_tables[table_id], new_tables[table_id]
        table_changes = _changed_fields(old_table, new_table, ("columns", "indexes"))
        table_columns = _column_diff(old_table["columns"], new_table["columns"])
        for key in columns:
            columns[key].extend(table_columns[key])
        if table_changes or any(table_columns.values()) or old_table["indexes"] != new_table["indexes"]:
            item = {"id": table_id, "name": new_table["name"], "changes": table_changes}
            if any(table_columns.values()):
                item["columns"] = table_columns
            if old_table["indexes"] != new_table["indexes"]:
                item["indexes"] = {"from": old_table["indexes"], "to": new_table["indexes"]}
            table_result["changed"].append(item)

    relationship_result = _diff_entities(old["relationships"], new["relationships"], "relationships")
    result = {
        "changed": bool(table_result["added"] or table_result["removed"] or table_result["changed"]
                         or any(columns.values()) or any(relationship_result.values())),
        "tables": table_result,
        "columns": columns,
        "relationships": relationship_result,
    }
    result["summary"] = {
        "tables_added": len(table_result["added"]),
        "tables_removed": len(table_result["removed"]),
        "tables_changed": len(table_result["changed"]),
        "columns_added": len(columns["added"]),
        "columns_removed": len(columns["removed"]),
        "columns_changed": len(columns["changed"]),
        "relationships_added": len(relationship_result["added"]),
        "relationships_removed": len(relationship_result["removed"]),
        "relationships_changed": len(relationship_result["changed"]),
    }
    return result
