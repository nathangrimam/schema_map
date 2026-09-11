import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import model
import server
from server import EditorSession, render_page


SQL = "CREATE TABLE users (id INT PRIMARY KEY);"

_ROOT = None


def setUpModule():
    # salvar um projeto sem destino cria pasta em schemas/; aqui vai para o temp
    global _ROOT
    _ROOT = tempfile.mkdtemp(prefix="schema-map-root-")
    setUpModule.original = server.SCHEMAS_ROOT
    server.SCHEMAS_ROOT = _ROOT


def tearDownModule():
    server.SCHEMAS_ROOT = setUpModule.original
    shutil.rmtree(_ROOT, ignore_errors=True)


class EditorSessionTest(unittest.TestCase):
    def test_saved_layout_is_loaded_from_disk(self):
        with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as sql_file:
            sql_file.write(SQL)
            path = sql_file.name

        layout_path = model.layout_path(path)
        expected = {"tables": {"users": {"x": 10, "y": 20}}, "blocks": []}
        try:
            model.save(path, expected)
            self.assertEqual(model.load_layout(path), expected)
        finally:
            os.unlink(path)
            if os.path.exists(layout_path):
                os.unlink(layout_path)

    def test_blank_session_builds_empty_project(self):
        session = EditorSession()
        page = session.build()

        self.assertEqual(page["meta"]["nt"], 0)
        self.assertFalse(page["saved"])
        self.assertEqual(session.source()["sql"], "")

    def test_validate_does_not_replace_current_sql(self):
        session = EditorSession()
        result = session.validate({"sql": SQL, "title": "users.sql", "dialect": "auto"})

        self.assertEqual(result["tables"], 1)
        self.assertEqual(result["changes"]["summary"]["tables_added"], 1)
        self.assertEqual(session.source()["sql"], "")

    def test_reapply_preserves_ids_and_reports_column_change(self):
        session = EditorSession()
        session.apply_sql({"sql": SQL, "title": "users.sql", "dialect": "postgres"})
        before = session.project_data()
        changed = "CREATE TABLE users (id BIGINT PRIMARY KEY, email TEXT);"

        preview = session.validate({"sql": changed, "title": "users.sql",
                                    "dialect": "postgres"})
        session.apply_sql({"sql": changed, "title": "users.sql", "dialect": "postgres"})
        after = session.project_data()

        self.assertEqual(before["tables"][0]["id"], after["tables"][0]["id"])
        self.assertEqual(before["tables"][0]["columns"][0]["id"],
                         after["tables"][0]["columns"][0]["id"])
        self.assertEqual(preview["changes"]["summary"]["columns_added"], 1)
        self.assertEqual(preview["changes"]["summary"]["columns_changed"], 1)

    def test_layout_is_stored_by_stable_table_id(self):
        session = EditorSession()
        session.apply_sql({"sql": SQL, "title": "users.sql", "dialect": "postgres"})
        table_id = session.project_data()["tables"][0]["id"]

        session.save_layout({"tables": {"users": {"x": 31, "y": 47}}, "blocks": []})

        self.assertEqual(session.project_data()["layout"]["tables"][table_id],
                         {"x": 31, "y": 47})

    def test_inspector_column_mutation_updates_project_sql_and_diagram(self):
        session = EditorSession()
        session.apply_sql({"sql": SQL, "title": "users.sql", "dialect": "postgres"})
        before = session.project_data()
        table = before["tables"][0]
        column = table["columns"][0]

        result = session.mutate({
            "action": "column.update", "table_id": table["id"],
            "column_id": column["id"],
            "values": {"name": "user_id", "type": "BIGINT", "nullable": False,
                       "primary_key": True, "unique": True, "default": None},
        })
        after = session.project_data()

        self.assertEqual(result["tables"], 1)
        self.assertEqual(after["tables"][0]["columns"][0]["name"], "user_id")
        self.assertEqual(after["tables"][0]["columns"][0]["id"], column["id"])
        self.assertIn('RENAME COLUMN "id" TO "user_id"', session.source()["sql"])
        self.assertEqual(session.build()["tables"][0]["id"], table["id"])

        preview = session.validate({"sql": session.source()["sql"],
                                    "title": "users.sql", "dialect": "postgres"})
        self.assertFalse(preview["changes"]["changed"])

    def test_inspector_index_and_fk_updates_round_trip_through_sql(self):
        sql = """
        CREATE TABLE users (id INT PRIMARY KEY, email TEXT);
        CREATE TABLE posts (
          id INT PRIMARY KEY,
          user_id INT,
          CONSTRAINT fk_posts_user FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """
        session = EditorSession()
        session.apply_sql({"sql": sql, "title": "blog.sql", "dialect": "postgres"})
        current = session.project_data()
        users = next(table for table in current["tables"] if table["name"] == "users")
        email = next(column for column in users["columns"] if column["name"] == "email")

        session.mutate({"action": "index.create", "table_id": users["id"],
                        "values": {"name": "idx_users_email", "columns": [email["id"]],
                                   "unique": False}})
        relation = session.project_data()["relationships"][0]
        session.mutate({"action": "relationship.update",
                        "relationship_id": relation["id"],
                        "values": {"on_delete": "CASCADE", "on_update": "RESTRICT"}})

        source = session.source()["sql"]
        self.assertIn('CREATE INDEX "idx_users_email"', source)
        self.assertIn('ON DELETE CASCADE ON UPDATE RESTRICT', source)
        preview = session.validate({"sql": source, "title": "blog.sql",
                                    "dialect": "postgres"})
        self.assertFalse(preview["changes"]["changed"])

    def test_inspector_table_rename_and_schema_round_trip_through_sql(self):
        session = EditorSession()
        session.apply_sql({"sql": SQL, "title": "users.sql", "dialect": "postgres"})
        table = session.project_data()["tables"][0]

        session.mutate({"action": "table.update", "table_id": table["id"],
                        "values": {"name": "accounts", "schema": "identity"}})

        source = session.source()["sql"]
        self.assertIn('RENAME TO "accounts"', source)
        self.assertIn('SET SCHEMA "identity"', source)
        preview = session.validate({"sql": source, "title": "users.sql",
                                    "dialect": "postgres"})
        self.assertFalse(preview["changes"]["changed"])

    def test_invalid_inspector_mutation_is_transactional(self):
        session = EditorSession()
        session.apply_sql({"sql": SQL, "title": "users.sql", "dialect": "postgres"})
        before_project = session.project_data()
        before_source = session.source()["sql"]

        with self.assertRaises(ValueError):
            session.mutate({"action": "column.create",
                            "table_id": before_project["tables"][0]["id"],
                            "values": {"name": "bad-name", "type": "INT"}})

        self.assertEqual(session.project_data(), before_project)
        self.assertEqual(session.source()["sql"], before_source)

    def test_apply_replaces_session_but_not_source_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as sql_file:
            sql_file.write(SQL)
            path = sql_file.name

        changed = "CREATE TABLE accounts (id INT PRIMARY KEY);"
        try:
            session = EditorSession(path)
            self.assertEqual(session.source()["source"], os.path.basename(path))
            session.apply_sql({"sql": changed, "title": "accounts.sql", "dialect": "postgres"})

            self.assertEqual(session.source()["sql"], changed)
            with open(path, encoding="utf-8") as original_file:
                self.assertEqual(original_file.read(), SQL)
        finally:
            os.unlink(path)

    def test_imported_sql_detaches_from_previous_file_and_layout(self):
        with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as sql_file:
            sql_file.write(SQL)
            path = sql_file.name

        try:
            session = EditorSession(path)
            session.layout = {"tables": {"users": {"x": 10, "y": 20}}, "blocks": []}
            session.apply_sql({"sql": SQL, "title": "imported.sql",
                               "dialect": "postgres", "detach": True})

            self.assertIsNone(session.source()["source"])
            self.assertEqual(session.layout, {"tables": {}, "blocks": []})
        finally:
            os.unlink(path)

    def test_title_is_escaped_in_page(self):
        session = EditorSession()
        model = session.build()
        model["meta"]["title"] = "<script>alert(1)</script>"

        page = render_page(model)

        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)

    def test_only_supported_dialects_are_accepted(self):
        session = EditorSession()

        with self.assertRaisesRegex(ValueError, "dialeto"):
            session.validate({"sql": SQL, "title": "users.sql", "dialect": "oracle"})

    def test_mutation_answers_with_the_redrawn_diagram(self):
        # o editor redesenha com esta resposta em vez de recarregar a página
        session = EditorSession()
        session.apply_sql({"sql": SQL, "title": "users.sql", "dialect": "postgres"})
        table = session.project_data()["tables"][0]

        result = session.mutate({"action": "column.create", "table_id": table["id"],
                                 "values": {"name": "email", "type": "TEXT"}})

        diagram = result["diagram"]
        self.assertEqual(diagram["meta"]["nt"], 1)
        names = [column["name"] for column in diagram["tables"][0]["cols"]]
        self.assertEqual(names, ["id", "email"])

    def test_applying_sql_answers_with_the_redrawn_diagram(self):
        session = EditorSession()

        result = session.apply_sql({"sql": SQL, "title": "users.sql", "dialect": "postgres"})

        self.assertEqual(result["diagram"]["meta"]["nt"], 1)
        self.assertEqual(result["diagram"]["tables"][0]["name"], "users")

    def test_validation_does_not_carry_a_diagram(self):
        # validar é só prévia: não redesenha nada, logo não precisa do payload
        session = EditorSession()

        result = session.validate({"sql": SQL, "title": "users.sql", "dialect": "postgres"})

        self.assertNotIn("diagram", result)

    def test_placeholder_like_names_are_not_replaced_inside_data(self):
        session = EditorSession()
        model = session.build()
        model["tables"] = [{"name": "__TITLE__"}]

        page = render_page(model)

        self.assertIn('"name":"__TITLE__"', page)


if __name__ == "__main__":
    unittest.main()
