import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from import_adapter import import_sql, project_layout_to_legacy, project_to_parsed


SQL = """
CREATE TABLE accounts (
  id INT PRIMARY KEY,
  email VARCHAR(100) UNIQUE NOT NULL
);
CREATE TABLE invoices (
  id INT PRIMARY KEY,
  account_id INT NOT NULL,
  CONSTRAINT fk_invoice_account FOREIGN KEY (account_id) REFERENCES accounts(id)
);
"""


class ImportAdapterTest(unittest.TestCase):
    def test_import_creates_canonical_tables_columns_indexes_and_relationship(self):
        value = import_sql(SQL, title="billing.sql")

        self.assertEqual(value["version"], 1)
        self.assertEqual([table["name"] for table in value["tables"]], ["accounts", "invoices"])
        accounts = value["tables"][0]
        email = next(column for column in accounts["columns"] if column["name"] == "email")
        self.assertTrue(email["unique"])
        self.assertTrue(email["nullable"] is False)
        self.assertEqual(len(accounts["indexes"]), 2)
        relation = value["relationships"][0]
        self.assertEqual(relation["name"], "fk_invoice_account")
        self.assertEqual(set(relation), {"id", "name", "from", "to", "on_delete", "on_update"})

    def test_reimport_reuses_table_column_and_relationship_ids(self):
        first = import_sql(SQL, title="billing.sql")
        changed_sql = SQL.replace("account_id INT NOT NULL", "account_id BIGINT NOT NULL")
        second = import_sql(changed_sql, title="billing.sql", previous=first)

        first_tables = {table["name"]: table for table in first["tables"]}
        second_tables = {table["name"]: table for table in second["tables"]}
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first_tables["invoices"]["id"], second_tables["invoices"]["id"])
        first_columns = {column["name"]: column for column in first_tables["invoices"]["columns"]}
        second_columns = {column["name"]: column for column in second_tables["invoices"]["columns"]}
        self.assertEqual(first_columns["account_id"]["id"], second_columns["account_id"]["id"])
        self.assertEqual(first["relationships"][0]["id"], second["relationships"][0]["id"])
        self.assertEqual(second_columns["account_id"]["type"], "BIGINT")

    def test_legacy_layout_is_migrated_to_ids_and_can_round_trip(self):
        legacy = {
            "tables": {"accounts": {"x": 120, "y": 80}, "invoices": {"x": 420, "y": 80}},
            "blocks": [{"id": "billing", "name": "billing", "x": 20, "y": 20,
                        "w": 900, "h": 500, "color": "#2b6ca3"}],
        }
        value = import_sql(SQL, legacy_layout=legacy)
        ids_by_name = {table["name"]: table["id"] for table in value["tables"]}

        self.assertEqual(value["layout"]["tables"][ids_by_name["accounts"]], {"x": 120, "y": 80})
        self.assertEqual(value["layout"]["blocks"][0]["table_ids"], [])
        round_trip = project_layout_to_legacy(value)
        self.assertEqual(round_trip["tables"], legacy["tables"])
        self.assertEqual(round_trip["blocks"][0]["id"], "billing")

    def test_previous_layout_is_kept_when_no_legacy_layout_is_given(self):
        first = import_sql(SQL)
        account_id = next(table["id"] for table in first["tables"] if table["name"] == "accounts")
        first["layout"]["tables"][account_id] = {"x": 77, "y": 88}
        second = import_sql(SQL, previous=first)

        self.assertEqual(second["layout"]["tables"][account_id], {"x": 77, "y": 88})

    def test_legacy_block_table_names_are_migrated(self):
        legacy = {
            "tables": {},
            "blocks": [{"id": "billing", "name": "billing", "x": 20, "y": 20,
                        "w": 900, "h": 500, "color": "#2b6ca3",
                        "table_names": ["accounts", "missing"]}],
        }
        value = import_sql(SQL, legacy_layout=legacy)
        account_id = next(table["id"] for table in value["tables"] if table["name"] == "accounts")

        self.assertEqual(value["layout"]["blocks"][0]["table_ids"], [account_id])
        self.assertEqual(project_layout_to_legacy(value)["blocks"][0]["table_names"], ["accounts"])

    def test_project_to_parsed_preserves_legacy_contract(self):
        value = import_sql(SQL)
        parsed = project_to_parsed(value)

        self.assertEqual(set(parsed["tables"]), {"accounts", "invoices"})
        self.assertEqual(parsed["fks"][0]["name"], "fk_invoice_account")
        self.assertIn("account_id", parsed["tables"]["invoices"]["fkcols"])
        self.assertEqual(parsed["tables"]["accounts"]["cols"][0]["pk"], True)

    def test_named_composite_fk_remains_one_canonical_relationship(self):
        value = import_sql("""
        CREATE TABLE parents (tenant_id INT, id INT, PRIMARY KEY (tenant_id, id));
        CREATE TABLE children (
          tenant_id INT,
          parent_id INT,
          CONSTRAINT fk_children_parent FOREIGN KEY (tenant_id, parent_id)
            REFERENCES parents (tenant_id, id)
        );
        """)

        self.assertEqual(len(value["relationships"]), 1)
        relation = value["relationships"][0]
        self.assertEqual(len(relation["from"]["column_ids"]), 2)
        self.assertEqual(len(relation["to"]["column_ids"]), 2)
        self.assertEqual(len(project_to_parsed(value)["fks"]), 2)

    def test_invalid_or_missing_fk_columns_are_not_emitted_as_invalid_canonical_refs(self):
        sql = """
        CREATE TABLE accounts (id INT PRIMARY KEY);
        CREATE TABLE invoices (id INT PRIMARY KEY);
        ALTER TABLE invoices ADD CONSTRAINT fk_missing FOREIGN KEY (account_id) REFERENCES accounts(id);
        """
        value = import_sql(sql)
        self.assertEqual(value["relationships"], [])


if __name__ == "__main__":
    unittest.main()
