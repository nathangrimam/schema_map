import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import model
import parse_sql


SQL = """
CREATE TABLE parents (
  id INT PRIMARY KEY
);

CREATE TABLE many_children (
  id INT PRIMARY KEY,
  parent_id INT,
  CONSTRAINT fk_many_parent FOREIGN KEY (parent_id) REFERENCES parents(id)
);

CREATE TABLE one_children (
  id INT PRIMARY KEY,
  parent_id INT UNIQUE NOT NULL,
  CONSTRAINT fk_one_parent FOREIGN KEY (parent_id) REFERENCES parents(id)
);
"""


class RelationMetadataTest(unittest.TestCase):
    def test_parser_keeps_constraint_names(self):
        parsed = parse_sql.parse(SQL, is_sql=True)
        self.assertEqual(
            [fk["name"] for fk in parsed["fks"]],
            ["fk_many_parent", "fk_one_parent"],
        )

    def test_model_infers_fk_cardinality(self):
        with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as sql_file:
            sql_file.write(SQL)
            path = sql_file.name

        try:
            edges = {edge["name"]: edge for edge in model.build(path)["edges"]}
        finally:
            os.unlink(path)

        self.assertEqual(edges["fk_many_parent"]["card"], "n:1")
        self.assertEqual(edges["fk_one_parent"]["card"], "1:1")
        self.assertFalse(edges["fk_many_parent"]["required"])
        self.assertTrue(edges["fk_one_parent"]["required"])

    def test_unknown_child_column_does_not_break_the_diagram(self):
        sql = """
        CREATE TABLE parents (id INT PRIMARY KEY);
        CREATE TABLE children (
          id INT PRIMARY KEY,
          CONSTRAINT fk_missing FOREIGN KEY (parent_id) REFERENCES parents(id)
        );
        """
        with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as sql_file:
            sql_file.write(sql)
            path = sql_file.name

        try:
            edge = model.build(path)["edges"][0]
        finally:
            os.unlink(path)

        self.assertFalse(edge["required"])

    def test_invalid_saved_layout_is_ignored_and_new_blocks_are_kept(self):
        with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as sql_file:
            sql_file.write(SQL)
            path = sql_file.name

        saved = {
            "tables": {"many_children": {"x": "invalid", "y": 10}},
            "blocks": [{"id": "broken", "name": "broken", "x": 0, "y": 0,
                        "w": -1, "h": 20, "color": "#fff"}],
        }
        try:
            parsed = parse_sql.parse(path)
            diagram = model.build_parsed(parsed, "test.sql", saved=saved)
        finally:
            os.unlink(path)

        self.assertTrue(diagram["blocks"])
        self.assertNotIn("broken", {block["id"] for block in diagram["blocks"]})


if __name__ == "__main__":
    unittest.main()
