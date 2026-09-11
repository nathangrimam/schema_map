import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import project


class ProjectModelTest(unittest.TestCase):
    def test_stable_id_is_deterministic_and_readable(self):
        first = project.stable_id("table", "public", "users")
        second = project.stable_id("table", "public", "users")

        self.assertEqual(first, second)
        self.assertTrue(first.startswith("tbl_"))
        self.assertNotEqual(first, project.stable_id("table", "public", "accounts"))

    def test_empty_project_has_versioned_canonical_shape(self):
        value = project.new_project()

        project.validate_project(value)
        self.assertEqual(value["version"], 1)
        self.assertEqual(value["tables"], [])
        self.assertEqual(value["relationships"], [])
        self.assertEqual(value["layout"], {"tables": {}, "blocks": []})
        self.assertEqual(value["source"], {"sql": "", "dialect": "postgres"})

    def test_dumps_and_loads_are_deterministic(self):
        value = project.new_project("schema.sql", "mysql")
        dumped = project.dumps(value)

        self.assertIn('"version": 1', dumped)
        self.assertEqual(dumped, project.dumps(project.loads(dumped)))
        self.assertEqual(project.loads(dumped), value)
        self.assertEqual(json.loads(dumped)["version"], 1)

    def test_validation_rejects_duplicate_ids_and_bad_references(self):
        value = project.new_project()
        table_id = project.stable_id("table", "users")
        column_id = project.stable_id("column", table_id, "id")
        value["tables"] = [{
            "id": table_id,
            "schema": None,
            "name": "users",
            "columns": [{"id": column_id, "name": "id", "type": "INT",
                         "nullable": False, "primary_key": True,
                         "unique": True, "default": None}],
            "indexes": [{"id": project.stable_id("index", table_id, column_id),
                         "name": None, "columns": [column_id], "unique": True,
                         "primary_key": True}],
        }]
        value["layout"]["tables"] = {table_id: {"x": 10, "y": 20}}
        project.validate_project(value)

        broken = copy.deepcopy(value)
        broken["layout"]["tables"]["missing"] = {"x": 0, "y": 0}
        with self.assertRaises(ValueError):
            project.validate_project(broken)

        broken = copy.deepcopy(value)
        broken["tables"][0]["indexes"][0]["id"] = table_id
        with self.assertRaises(ValueError):
            project.validate_project(broken)

    def test_diff_reports_table_column_and_relationship_changes(self):
        old = project.new_project("schema.sql")
        table_id = project.stable_id("table", "users")
        id_id = project.stable_id("column", table_id, "id")
        old["tables"] = [{"id": table_id, "schema": None, "name": "users",
                          "columns": [{"id": id_id, "name": "id", "type": "INT",
                                       "nullable": False, "primary_key": True,
                                       "unique": True, "default": None}],
                          "indexes": []}]
        project.validate_project(old)

        new = copy.deepcopy(old)
        new["tables"][0]["columns"][0]["type"] = "BIGINT"
        email_id = project.stable_id("column", table_id, "email")
        new["tables"][0]["columns"].append({
            "id": email_id, "name": "email", "type": "TEXT", "nullable": True,
            "primary_key": False, "unique": False, "default": None,
        })
        account_id = project.stable_id("table", "accounts")
        account_col_id = project.stable_id("column", account_id, "id")
        new["tables"].append({"id": account_id, "schema": None, "name": "accounts",
                               "columns": [{"id": account_col_id, "name": "id", "type": "INT",
                                            "nullable": False, "primary_key": True,
                                            "unique": True, "default": None}],
                               "indexes": []})
        new["relationships"] = [{
            "id": project.stable_id("relationship", table_id, id_id, account_id, account_col_id),
            "name": "fk_users_accounts",
            "from": {"table_id": table_id, "column_ids": [id_id]},
            "to": {"table_id": account_id, "column_ids": [account_col_id]},
            "on_delete": None,
            "on_update": None,
        }]
        result = project.diff_projects(old, new)

        self.assertTrue(result["changed"])
        self.assertEqual([table["name"] for table in result["tables"]["added"]], ["accounts"])
        self.assertEqual({column["name"] for column in result["columns"]["added"]}, {"email", "id"})
        self.assertEqual(result["summary"]["columns_changed"], 1)
        self.assertEqual(len(result["relationships"]["added"]), 1)


if __name__ == "__main__":
    unittest.main()
