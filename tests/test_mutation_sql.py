import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from import_adapter import import_sql
from mutation_sql import mutation_statements, sync_source
from project import stable_id


SQL = """
CREATE TABLE users (id INT PRIMARY KEY, email TEXT);
CREATE TABLE posts (
  id INT PRIMARY KEY,
  user_id INT,
  CONSTRAINT fk_posts_user FOREIGN KEY (user_id) REFERENCES users(id)
);
"""


class MutationSqlTest(unittest.TestCase):
    def setUp(self):
        self.old = import_sql(SQL, dialect="postgres")
        self.users = next(table for table in self.old["tables"] if table["name"] == "users")

    def test_column_update_emits_incremental_postgres_ddl(self):
        new = copy.deepcopy(self.old)
        table = next(table for table in new["tables"] if table["id"] == self.users["id"])
        column = next(column for column in table["columns"] if column["name"] == "email")
        column["name"] = "login"
        column["type"] = "VARCHAR(200)"
        column["nullable"] = False
        column["default"] = "'pending'"

        statements = mutation_statements(self.old, new, {
            "action": "column.update", "table_id": table["id"], "column_id": column["id"]})

        text = "\n".join(statements)
        self.assertIn('RENAME COLUMN "email" TO "login"', text)
        self.assertIn('ALTER COLUMN "login" TYPE VARCHAR(200)', text)
        self.assertIn('ALTER COLUMN "login" SET NOT NULL', text)
        self.assertIn("ALTER COLUMN \"login\" SET DEFAULT 'pending'", text)

    def test_relationship_delete_drops_named_constraint(self):
        new = copy.deepcopy(self.old)
        relation = new["relationships"].pop()

        statements = mutation_statements(self.old, new, {
            "action": "relationship.delete", "relationship_id": relation["id"]})

        self.assertEqual(statements,
                         ['ALTER TABLE "posts" DROP CONSTRAINT "fk_posts_user";'])

    def test_index_create_uses_columns_and_updates_source(self):
        new = copy.deepcopy(self.old)
        table = next(table for table in new["tables"] if table["id"] == self.users["id"])
        email = next(column for column in table["columns"] if column["name"] == "email")
        index = {"id": stable_id("index", table["id"], "idx_users_email"),
                 "name": "idx_users_email", "columns": [email["id"]],
                 "unique": False, "primary_key": False}
        table["indexes"].append(index)
        operation = {"action": "index.create", "table_id": table["id"], "values": {}}

        statements = mutation_statements(self.old, new, operation)
        synced = sync_source(self.old, new, operation)

        self.assertEqual(statements,
                         ['CREATE INDEX "idx_users_email" ON "users" ("email");'])
        self.assertTrue(synced["source"]["sql"].endswith(statements[0]))


if __name__ == "__main__":
    unittest.main()
