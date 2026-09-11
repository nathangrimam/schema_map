import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import parse_sql


class InspectorDdlParserTest(unittest.TestCase):
    def test_postgres_metadata_and_ordered_alter_dependencies(self):
        sql = """
        CREATE TABLE public.accounts (
          id integer,
          status text NOT NULL DEFAULT 'new',
          created_at timestamptz DEFAULT (now()),
          CONSTRAINT accounts_pk PRIMARY KEY (id),
          CONSTRAINT uq_accounts_status UNIQUE (status)
        );
        CREATE TABLE public.orders (
          id integer PRIMARY KEY,
          account_id integer,
          CONSTRAINT fk_orders_accounts FOREIGN KEY (account_id)
            REFERENCES accounts(id) ON DELETE CASCADE ON UPDATE SET NULL
        );
        CREATE UNIQUE INDEX idx_orders_account ON public.orders (account_id);
        CREATE INDEX idx_orders_id ON orders (id);

        ALTER TABLE orders RENAME TO purchases;
        ALTER TABLE purchases RENAME COLUMN account_id TO owner_id;
        ALTER TABLE purchases ALTER COLUMN owner_id TYPE bigint;
        ALTER TABLE purchases ALTER COLUMN owner_id SET NOT NULL;
        ALTER TABLE purchases ALTER COLUMN owner_id SET DEFAULT 0;
        ALTER TABLE purchases ALTER COLUMN owner_id DROP DEFAULT;
        ALTER TABLE purchases ALTER COLUMN owner_id DROP NOT NULL;
        ALTER TABLE accounts DROP CONSTRAINT uq_accounts_status;
        ALTER TABLE accounts DROP COLUMN status;
        DROP INDEX idx_orders_account;
        """

        parsed = parse_sql.parse(sql, dialect="postgres", is_sql=True)
        accounts = parsed["tables"]["accounts"]
        purchases = parsed["tables"]["purchases"]

        self.assertEqual(accounts["schema"], "public")
        self.assertEqual(
            next(column for column in accounts["cols"] if column["name"] == "created_at")["default"],
            "(now())",
        )
        self.assertNotIn("status", {column["name"] for column in accounts["cols"]})
        self.assertEqual(
            {index["name"] for index in accounts["indexes"]}, {"accounts_pk"}
        )
        self.assertEqual(purchases["indexes"], [
            {"name": None, "columns": ["id"], "unique": True, "primary_key": True},
            {"name": "idx_orders_id", "columns": ["id"], "unique": False, "primary_key": False},
        ])
        owner = next(column for column in purchases["cols"] if column["name"] == "owner_id")
        self.assertEqual(owner["type"], "bigint")
        self.assertFalse(owner["notnull"])
        self.assertNotIn("default", owner)
        self.assertEqual(parsed["fks"][0]["child"], "purchases")
        self.assertEqual(parsed["fks"][0]["col"], "owner_id")

    def test_postgres_add_and_drop_primary_key(self):
        sql = """
        CREATE TABLE things (id integer, code integer);
        ALTER TABLE things ADD CONSTRAINT things_pk PRIMARY KEY (id);
        ALTER TABLE things DROP CONSTRAINT things_pk;
        ALTER TABLE things ADD PRIMARY KEY (code);
        ALTER TABLE things DROP PRIMARY KEY;
        """

        parsed = parse_sql.parse(sql, dialect="postgres", is_sql=True)
        table = parsed["tables"]["things"]
        self.assertFalse(any(column["pk"] for column in table["cols"]))
        self.assertFalse(table["indexes"])
        self.assertEqual(table["unique"], [])

        unnamed = parse_sql.parse("""
            CREATE TABLE users (id integer PRIMARY KEY);
            ALTER TABLE users DROP CONSTRAINT pk_users_id;
        """, dialect="postgres", is_sql=True)
        self.assertFalse(any(column["pk"] for column in unnamed["tables"]["users"]["cols"]))

    def test_postgres_set_default_keeps_parenthesized_function(self):
        parsed = parse_sql.parse("""
            CREATE TABLE events (payload text);
            ALTER TABLE events ALTER COLUMN payload SET DEFAULT lower('NEW');
        """, dialect="postgres", is_sql=True)
        payload = parsed["tables"]["events"]["cols"][0]
        self.assertEqual(payload["default"], "lower('NEW')")

    def test_postgres_set_schema_updates_table_metadata(self):
        parsed = parse_sql.parse("""
            CREATE TABLE users (id integer PRIMARY KEY);
            ALTER TABLE users SET SCHEMA identity;
        """, dialect="postgres", is_sql=True)

        self.assertEqual(parsed["tables"]["users"]["schema"], "identity")

    def test_postgres_fk_actions_and_drop_table_dependencies(self):
        sql = """
        CREATE TABLE parent (id integer PRIMARY KEY);
        CREATE TABLE child (
          id integer PRIMARY KEY,
          parent_id integer,
          CONSTRAINT child_parent_fk FOREIGN KEY (parent_id)
            REFERENCES parent(id) ON DELETE SET NULL ON UPDATE CASCADE
        );
        ALTER TABLE parent RENAME COLUMN id TO parent_id;
        ALTER TABLE child RENAME COLUMN parent_id TO owner_id;
        """

        parsed = parse_sql.parse(sql, dialect="postgres", is_sql=True)
        self.assertEqual(parsed["fks"], [{
            "child": "child", "col": "owner_id", "parent": "parent",
            "pcol": "parent_id", "name": "child_parent_fk",
            "on_delete": "SET NULL", "on_update": "CASCADE",
        }])

        parsed = parse_sql.parse(sql + "DROP TABLE parent;", dialect="postgres", is_sql=True)
        self.assertEqual(parsed["fks"], [])
        self.assertNotIn("parent", parsed["tables"])

    def test_mysql_keys_modify_and_index_crud(self):
        sql = """
        CREATE TABLE users (
          id INT,
          code VARCHAR(20) NOT NULL DEFAULT ('guest'),
          KEY idx_code (code),
          UNIQUE KEY uq_code (code)
        ) ENGINE=InnoDB;
        CREATE TABLE sessions (
          id INT PRIMARY KEY,
          user_id INT,
          CONSTRAINT fk_sessions_user FOREIGN KEY (user_id)
            REFERENCES users(id) ON DELETE RESTRICT ON UPDATE CASCADE
        );
        CREATE UNIQUE INDEX idx_sessions_user ON sessions (user_id);
        ALTER TABLE users ADD CONSTRAINT users_pk PRIMARY KEY (id);
        ALTER TABLE users MODIFY COLUMN code BIGINT NOT NULL DEFAULT 7;
        ALTER TABLE users DROP INDEX idx_code;
        ALTER TABLE users DROP PRIMARY KEY;
        ALTER TABLE sessions DROP FOREIGN KEY fk_sessions_user;
        DROP INDEX idx_sessions_user ON sessions;
        """

        parsed = parse_sql.parse(sql, dialect="mysql", is_sql=True)
        users = parsed["tables"]["users"]
        code = next(column for column in users["cols"] if column["name"] == "code")
        self.assertEqual(code["type"], "BIGINT")
        self.assertTrue(code["notnull"])
        self.assertEqual(code["default"], "7")
        self.assertEqual(users["indexes"], [{
            "name": "uq_code", "columns": ["code"],
            "unique": True, "primary_key": False,
        }])
        self.assertEqual(parsed["tables"]["sessions"]["indexes"], [
            {"name": None, "columns": ["id"], "unique": True, "primary_key": True}
        ])
        self.assertEqual(parsed["fks"], [])


if __name__ == "__main__":
    unittest.main()
