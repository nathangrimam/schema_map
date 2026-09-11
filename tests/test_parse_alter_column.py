import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import parse_sql


class AlterAddColumnTest(unittest.TestCase):
    def test_postgres_add_column_with_inline_reference(self):
        sql = """
        CREATE TABLE teams (id integer PRIMARY KEY);
        CREATE TABLE members (id integer PRIMARY KEY);
        ALTER TABLE members ADD COLUMN team_id integer NOT NULL
            REFERENCES teams(id);
        ALTER TABLE members ADD display_name varchar(80) UNIQUE;
        """

        parsed = parse_sql.parse(sql, dialect="postgres", is_sql=True)
        members = parsed["tables"]["members"]
        columns = {column["name"]: column for column in members["cols"]}

        self.assertEqual(columns["team_id"], {
            "name": "team_id", "type": "integer", "notnull": True,
            "pk": False,
        })
        self.assertEqual(columns["display_name"], {
            "name": "display_name", "type": "varchar(80)",
            "notnull": False, "pk": False,
        })
        self.assertIn(["display_name"], members["unique"])
        self.assertEqual(parsed["fks"], [{
            "child": "members", "col": "team_id", "parent": "teams",
            "pcol": "id", "name": None,
        }])

    def test_mysql_add_column_primary_key_and_inline_reference(self):
        sql = """
        CREATE TABLE accounts (`id` INT PRIMARY KEY);
        CREATE TABLE invoices (`id` INT);
        ALTER TABLE `invoices` ADD `account_id` INT NOT NULL
            REFERENCES `accounts` (`id`);
        ALTER TABLE `invoices` ADD COLUMN `external_id` VARCHAR(40)
            UNIQUE NOT NULL;
        ALTER TABLE `invoices` ADD COLUMN `sequence_no` BIGINT PRIMARY KEY;
        """

        parsed = parse_sql.parse(sql, dialect="mysql", is_sql=True)
        invoices = parsed["tables"]["invoices"]
        columns = {column["name"]: column for column in invoices["cols"]}

        self.assertEqual(columns["account_id"]["type"], "INT")
        self.assertTrue(columns["account_id"]["notnull"])
        self.assertEqual(columns["external_id"]["type"], "VARCHAR(40)")
        self.assertTrue(columns["external_id"]["notnull"])
        self.assertTrue(columns["sequence_no"]["pk"])
        self.assertIn(["external_id"], invoices["unique"])
        self.assertIn(["sequence_no"], invoices["unique"])
        self.assertEqual(len(parsed["fks"]), 1)
        self.assertEqual(parsed["fks"][0]["parent"], "accounts")


if __name__ == "__main__":
    unittest.main()
