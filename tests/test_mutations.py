import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mutations
import project


def canonical_fixture():
    value = project.new_project("schema.sql")
    users_id = project.stable_id("table", "users")
    posts_id = project.stable_id("table", "posts")
    user_id = project.stable_id("column", users_id, "id")
    email_id = project.stable_id("column", users_id, "email")
    post_id = project.stable_id("column", posts_id, "id")
    post_user_id = project.stable_id("column", posts_id, "user_id")
    value["tables"] = [
        {"id": project.stable_id("table", "draft"), "schema": None, "name": "draft",
         "columns": [], "indexes": []},
        {"id": posts_id, "schema": None, "name": "posts", "columns": [
            {"id": post_id, "name": "id", "type": "INTEGER", "nullable": False,
             "primary_key": True, "unique": False, "default": None},
            {"id": post_user_id, "name": "user_id", "type": "INTEGER", "nullable": True,
             "primary_key": False, "unique": False, "default": None},
        ], "indexes": [{"id": project.stable_id("index", posts_id, post_id),
                         "name": None, "columns": [post_id], "unique": True,
                         "primary_key": True}]},
        {"id": users_id, "schema": None, "name": "users", "columns": [
            {"id": user_id, "name": "id", "type": "INTEGER", "nullable": False,
             "primary_key": True, "unique": False, "default": None},
            {"id": email_id, "name": "email", "type": "TEXT", "nullable": False,
             "primary_key": False, "unique": True, "default": None},
        ], "indexes": [
            {"id": project.stable_id("index", users_id, user_id), "name": None,
             "columns": [user_id], "unique": True, "primary_key": True},
            {"id": project.stable_id("index", users_id, email_id), "name": None,
             "columns": [email_id], "unique": True, "primary_key": False},
        ]},
    ]
    value["relationships"] = [{
        "id": project.stable_id("relationship", posts_id, post_user_id, users_id, user_id),
        "name": "fk_posts_users",
        "from": {"table_id": posts_id, "column_ids": [post_user_id]},
        "to": {"table_id": users_id, "column_ids": [user_id]},
        "on_delete": None, "on_update": None,
    }]
    project.validate_project(value)
    return value


class MutationTest(unittest.TestCase):
    def setUp(self):
        self.base = canonical_fixture()
        self.users = next(table for table in self.base["tables"] if table["name"] == "users")
        self.posts = next(table for table in self.base["tables"] if table["name"] == "posts")
        self.user_id = self.users["columns"][0]["id"]
        self.email_id = self.users["columns"][1]["id"]
        self.post_user_id = self.posts["columns"][1]["id"]
        self.relation_id = self.base["relationships"][0]["id"]

    def apply(self, operation):
        return mutations.apply_mutation(self.base, operation)

    def test_apply_is_immutable_and_creates_column(self):
        original = copy.deepcopy(self.base)
        changed = self.apply({
            "action": "column.create", "table_id": self.posts["id"],
            "values": {"name": "published_at", "type": "TIMESTAMP"},
        })
        posts = next(table for table in changed["tables"] if table["id"] == self.posts["id"])
        self.assertEqual(self.base, original)
        self.assertIn("published_at", [column["name"] for column in posts["columns"]])

    def test_column_create_primary_and_unique_indexes_have_deterministic_names(self):
        draft_id = next(table["id"] for table in self.base["tables"] if table["name"] == "draft")
        changed = self.apply({"action": "column.create", "table_id": draft_id,
                              "values": {"name": "id", "type": "INTEGER", "primary_key": True}})
        changed = mutations.apply_mutation(changed, {"action": "column.create", "table_id": draft_id,
                              "values": {"name": "slug", "type": "TEXT", "unique": True}})
        draft = next(table for table in changed["tables"] if table["id"] == draft_id)
        slug = next(column for column in draft["columns"] if column["name"] == "slug")
        unique = next(index for index in draft["indexes"] if index["columns"] == [slug["id"]])
        self.assertEqual(unique["name"], "uq_draft_slug")
        self.assertEqual(next(index for index in draft["indexes"] if index["primary_key"])["name"],
                         "pk_draft_id")
        imported_primary = next(index for index in self.users["indexes"] if index["primary_key"])
        self.assertIsNone(imported_primary["name"])

    def test_table_update_delete_cascades_layout_and_relationships(self):
        changed = copy.deepcopy(self.base)
        changed["layout"]["tables"][self.posts["id"]] = {"x": 10, "y": 20}
        changed["layout"]["blocks"] = [{"id": "blk_custom", "name": "A", "x": 0,
                                           "y": 0, "w": 100, "h": 100,
                                           "color": "#fff", "table_ids": [self.posts["id"]]}]
        changed = mutations.apply_mutation(changed, {
            "action": "table.update", "table_id": self.posts["id"],
            "values": {"name": "articles", "schema": "public"},
        })
        self.assertEqual(next(t for t in changed["tables"] if t["id"] == self.posts["id"])["name"], "articles")
        changed = mutations.apply_mutation(changed, {"action": "table.delete", "table_id": self.posts["id"]})
        self.assertNotIn(self.posts["id"], [t["id"] for t in changed["tables"]])
        self.assertNotIn(self.posts["id"], changed["layout"]["tables"])
        self.assertEqual(changed["layout"]["blocks"][0]["table_ids"], [])
        self.assertEqual(changed["relationships"], [])

    def test_column_update_syncs_primary_and_unique_indexes(self):
        changed = self.apply({"action": "column.update", "table_id": self.users["id"],
                              "column_id": self.email_id,
                              "values": {"primary_key": True, "type": "VARCHAR"}})
        users = next(table for table in changed["tables"] if table["id"] == self.users["id"])
        email = next(c for c in users["columns"] if c["id"] == self.email_id)
        self.assertTrue(email["primary_key"])
        self.assertFalse(email["nullable"])
        self.assertTrue(email["unique"])
        primary = next(i for i in users["indexes"] if i["primary_key"])
        self.assertEqual(primary["columns"], [self.user_id, self.email_id])
        changed = mutations.apply_mutation(changed, {"action": "column.update",
                              "table_id": self.users["id"], "column_id": self.email_id,
                              "values": {"primary_key": False, "unique": False}})
        users = next(table for table in changed["tables"] if table["id"] == self.users["id"])
        self.assertTrue(any(i["primary_key"] and i["columns"] == [self.user_id]
                            for i in users["indexes"]))
        self.assertFalse(any(i["columns"] == [self.email_id] and i["unique"]
                             for i in users["indexes"]))

    def test_column_delete_cascades_indexes_and_relationships(self):
        changed = self.apply({"action": "column.delete", "table_id": self.posts["id"],
                              "column_id": self.post_user_id})
        post = next(t for t in changed["tables"] if t["id"] == self.posts["id"])
        self.assertNotIn(self.post_user_id, [c["id"] for c in post["columns"]])
        self.assertFalse(any(self.post_user_id in i["columns"] for i in post["indexes"]))
        self.assertEqual(changed["relationships"], [])

    def test_index_crud_and_primary_index_protection(self):
        changed = self.apply({"action": "index.create", "table_id": self.posts["id"],
                              "values": {"name": "idx_posts_user", "columns": [self.post_user_id],
                                          "unique": False}})
        posts = next(t for t in changed["tables"] if t["id"] == self.posts["id"])
        index = next(i for i in posts["indexes"] if i["name"] == "idx_posts_user")
        changed = mutations.apply_mutation(changed, {"action": "index.update", "table_id": posts["id"],
                              "index_id": index["id"], "values": {"unique": True}})
        posts = next(table for table in changed["tables"] if table["id"] == self.posts["id"])
        index = next(i for i in posts["indexes"] if i["id"] == index["id"])
        self.assertTrue(index["unique"])
        changed = mutations.apply_mutation(changed, {"action": "index.delete", "table_id": posts["id"],
                                                      "index_id": index["id"]})
        posts = next(table for table in changed["tables"] if table["id"] == self.posts["id"])
        self.assertFalse(any(i["id"] == index["id"] for i in posts["indexes"]))
        primary = next(i for i in self.users["indexes"] if i.get("primary_key"))
        for action in ("index.delete", "index.update"):
            with self.assertRaisesRegex(ValueError, "primary_key"):
                self.apply({"action": action, "table_id": self.users["id"],
                            "index_id": primary["id"], "values": {"unique": False}})

    def test_new_ids_are_deterministic_and_disambiguated_on_collision(self):
        operation = {"action": "index.create", "table_id": self.posts["id"],
                     "values": {"columns": [self.post_user_id], "unique": False}}
        first = self.apply(operation)
        second = mutations.apply_mutation(first, operation)
        indexes = [index for index in second["tables"]
                   if index["id"] == self.posts["id"]][0]["indexes"]
        created = [index for index in indexes if index["columns"] == [self.post_user_id]
                   and not index["unique"]]
        self.assertEqual(len(created), 2)
        self.assertNotEqual(created[0]["id"], created[1]["id"])
        self.assertIsNone(created[0]["name"])
        self.assertIsNone(created[1]["name"])

    def test_relationship_crud_requires_valid_endpoints_and_actions(self):
        changed = self.apply({"action": "relationship.create", "values": {
            "name": "fk_users_posts_2", "from": {"table_id": self.users["id"],
            "column_ids": [self.email_id]}, "to": {"table_id": self.posts["id"],
            "column_ids": [self.post_user_id]}, "on_delete": "CASCADE", "on_update": None}})
        self.assertEqual(len(changed["relationships"]), 2)
        relation = changed["relationships"][-1]
        changed = mutations.apply_mutation(changed, {"action": "relationship.update",
            "relationship_id": relation["id"], "values": {"on_delete": "SET NULL"}})
        self.assertEqual(changed["relationships"][-1]["on_delete"], "SET NULL")
        changed = mutations.apply_mutation(changed, {"action": "relationship.delete",
                                                      "relationship_id": relation["id"]})
        self.assertEqual(len(changed["relationships"]), 1)

    def test_invalid_mutations_raise_clear_portuguese_errors(self):
        cases = [
            ({"action": "column.create", "table_id": self.users["id"],
              "values": {"name": "bad-name", "type": "INT"}}, "identificador simples"),
            ({"action": "column.create", "table_id": self.users["id"],
              "values": {"name": "ID", "type": "INT"}}, "duplicada"),
            ({"action": "relationship.create", "values": {
                "from": {"table_id": self.posts["id"], "column_ids": [self.post_user_id]},
                "to": {"table_id": self.users["id"], "column_ids": [self.user_id]},
                "on_delete": "DROP TABLE"}}, "NO ACTION"),
            ({"action": "index.create", "table_id": self.posts["id"],
              "values": {"columns": ["missing"]}}, "não encontrado"),
            ({"action": "relationship.create", "values": {
                "from": {"table_id": self.posts["id"], "column_ids": [self.post_user_id]},
                "to": {"table_id": self.users["id"], "column_ids": [self.user_id, self.email_id]}}},
             "mesmo número"),
            ({"action": "relationship.create", "values": {
                "name": "FK_POSTS_USERS", "from": {"table_id": self.posts["id"],
                "column_ids": [self.post_user_id]}, "to": {"table_id": self.users["id"],
                "column_ids": [self.user_id]} }}, "relacionamento duplicado"),
        ]
        for operation, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    self.apply(operation)

        duplicate = {"action": "relationship.create", "values": {
            "from": {"table_id": self.posts["id"], "column_ids": [self.post_user_id]},
            "to": {"table_id": self.users["id"], "column_ids": [self.user_id]}}}
        with self.assertRaisesRegex(ValueError, "duplicado"):
            self.apply(duplicate)


if __name__ == "__main__":
    unittest.main()
