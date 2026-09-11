import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import model
import workspace
from server import EditorSession


def _read(path):
    with open(path, encoding='utf-8') as handle:
        return handle.read()


SQL = ("CREATE TABLE users (id INT PRIMARY KEY, email TEXT NOT NULL);\n"
       "CREATE TABLE posts (id INT PRIMARY KEY, user_id INT REFERENCES users(id));\n")


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='schema-map-test-')
        self.sql_path = os.path.join(self.root, 'blog.sql')
        with open(self.sql_path, 'w', encoding='utf-8') as sql_file:
            sql_file.write(SQL)
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_init_creates_folder_with_project_and_generated_ddl(self):
        directory, written = workspace.create_from_sql(self.sql_path)

        self.assertEqual(directory, os.path.join(self.root, 'blog'))
        self.assertTrue(workspace.is_workspace(directory))
        self.assertEqual(set(os.listdir(directory)), {'project.json', 'schema.sql'})
        self.assertIn('schema', written)
        self.assertIn('CREATE TABLE', _read(written['schema']))

    def test_original_sql_is_preserved_verbatim_in_the_project(self):
        directory, _ = workspace.create_from_sql(self.sql_path)

        self.assertEqual(workspace.load(directory)['source']['sql'], SQL)

    def test_legacy_layout_and_groups_are_carried_over(self):
        model.save(self.sql_path, {'tables': {'users': {'x': 11, 'y': 22}}, 'blocks': []})
        groups = os.path.join(self.root, 'groups.json')
        with open(groups, 'w', encoding='utf-8') as groups_file:
            json.dump({'blog': 'users posts'}, groups_file)

        directory, written = workspace.create_from_sql(
            self.sql_path, groups=groups, legacy_layout=model.load_layout(self.sql_path))

        project = workspace.load(directory)
        users = next(t for t in project['tables'] if t['name'] == 'users')
        self.assertEqual(project['layout']['tables'][users['id']], {'x': 11, 'y': 22})
        self.assertEqual(written['groups'], os.path.join(directory, 'groups.json'))
        self.assertEqual(workspace.groups_path(directory), written['groups'])

    def test_resolve_rejects_a_folder_without_a_project(self):
        with self.assertRaises(ValueError):
            workspace.resolve(self.root)
        self.assertEqual(workspace.resolve(self.sql_path), ('sql', self.sql_path))

    def test_resolve_accepts_the_project_file_itself(self):
        directory, _ = workspace.create_from_sql(self.sql_path)

        self.assertEqual(workspace.resolve(workspace.project_path(directory)),
                         ('workspace', directory))

    def test_save_writes_nothing_when_the_ddl_cannot_be_generated(self):
        directory, _ = workspace.create_from_sql(self.sql_path)
        before = _read(workspace.project_path(directory))
        broken = workspace.load(directory)
        broken['tables'][0]['columns'][0]['type'] = ''

        with self.assertRaises(ValueError):
            workspace.save(directory, broken)
        self.assertEqual(_read(workspace.project_path(directory)), before)


class WorkspaceSessionTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='schema-map-test-')
        import server
        self.addCleanup(setattr, server, 'SCHEMAS_ROOT', server.SCHEMAS_ROOT)
        server.SCHEMAS_ROOT = os.path.join(self.root, 'schemas')
        sql_path = os.path.join(self.root, 'blog.sql')
        with open(sql_path, 'w', encoding='utf-8') as sql_file:
            sql_file.write(SQL)
        self.directory, _ = workspace.create_from_sql(sql_path)
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_session_opens_the_folder_and_reports_it_as_the_source(self):
        session = EditorSession(self.directory)

        self.assertEqual(session.workspace, self.directory)
        self.assertEqual(session.source()['workspace'], 'blog')
        self.assertEqual(session.build()['meta']['nt'], 2)

    def test_groups_file_is_used_as_the_default_override(self):
        with open(os.path.join(self.directory, 'groups.json'), 'w', encoding='utf-8') as f:
            json.dump({'blog': 'users posts'}, f)

        session = EditorSession(self.directory)

        self.assertEqual(session.override, workspace.groups_path(self.directory))
        self.assertEqual(session.build()['meta']['grouping'], 'override')

    def test_saving_the_layout_persists_to_the_folder(self):
        session = EditorSession(self.directory)
        session.save_layout({'tables': {'users': {'x': 7, 'y': 9}}, 'blocks': []})

        reopened = EditorSession(self.directory).build()
        users = next(t for t in reopened['tables'] if t['name'] == 'users')
        self.assertEqual((users['x'], users['y']), (7, 9))

    def test_mutations_are_written_to_disk_right_away(self):
        session = EditorSession(self.directory)
        table = next(t for t in session.project_data()['tables'] if t['name'] == 'users')

        session.mutate({'action': 'column.create', 'table_id': table['id'],
                        'values': {'name': 'nickname', 'type': 'TEXT'}})

        names = [column['name'] for table in workspace.load(self.directory)['tables']
                 if table['name'] == 'users' for column in table['columns']]
        self.assertIn('nickname', names)
        self.assertIn('nickname', _read(workspace.schema_path(self.directory)))

    def test_detaching_stops_writing_to_the_original_folder(self):
        session = EditorSession(self.directory)
        session.apply_sql({'sql': 'CREATE TABLE other (id INT PRIMARY KEY);',
                           'title': 'other.sql', 'dialect': 'postgres',
                           'reset': True, 'detach': True})

        # o projeto vira outro; a pasta original fica intacta e só volta a
        # existir um destino quando o usuário salvar
        self.assertIsNone(session.workspace)
        self.assertEqual(len(workspace.load(self.directory)['tables']), 2)

        session.save_layout({'tables': {}, 'blocks': []})

        self.assertNotEqual(session.workspace, self.directory)
        self.assertEqual(len(workspace.load(session.workspace)['tables']), 1)


class NewProjectTest(unittest.TestCase):
    """Projeto criado dentro do editor: sessão sem .sql e sem pasta."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='schema-map-root-')
        import server
        self.original_root = server.SCHEMAS_ROOT
        server.SCHEMAS_ROOT = self.root
        self.addCleanup(setattr, server, 'SCHEMAS_ROOT', self.original_root)
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_empty_project_does_not_create_a_folder(self):
        session = EditorSession()

        result = session.save_layout({'tables': {}, 'blocks': []})

        self.assertIsNone(session.workspace)
        self.assertEqual(os.listdir(self.root), [])
        self.assertNotIn('.json', result)

    def test_loading_sql_alone_creates_nothing(self):
        # abrir um SQL só para olhar não pode sujar a pasta de schemas
        session = EditorSession()

        session.apply_sql({'sql': SQL, 'title': 'blog.sql', 'dialect': 'postgres',
                           'reset': True})

        self.assertIsNone(session.workspace)
        self.assertEqual(os.listdir(self.root), [])

    def test_first_save_creates_a_folder_named_after_the_title(self):
        session = EditorSession()
        session.apply_sql({'sql': SQL, 'title': 'blog.sql', 'dialect': 'postgres',
                           'reset': True})

        session.save_layout({'tables': {}, 'blocks': []})

        self.assertEqual(session.workspace, os.path.join(self.root, 'blog'))
        self.assertTrue(workspace.is_workspace(session.workspace))
        self.assertEqual(len(workspace.load(session.workspace)['tables']), 2)

    def test_layout_of_a_new_project_lands_in_the_folder(self):
        session = EditorSession()
        session.apply_sql({'sql': SQL, 'title': 'blog.sql', 'dialect': 'postgres',
                           'reset': True})

        session.save_layout({'tables': {'users': {'x': 4, 'y': 8}}, 'blocks': []})
        self.assertIsNotNone(session.workspace)

        reopened = EditorSession(session.workspace).build()
        users = next(t for t in reopened['tables'] if t['name'] == 'users')
        self.assertEqual((users['x'], users['y']), (4, 8))

    def test_an_existing_folder_is_never_overwritten(self):
        first = EditorSession()
        first.apply_sql({'sql': SQL, 'title': 'blog.sql', 'dialect': 'postgres',
                         'reset': True})
        first.save_layout({'tables': {}, 'blocks': []})

        second = EditorSession()
        second.apply_sql({'sql': 'CREATE TABLE outra (id INT PRIMARY KEY);',
                          'title': 'blog.sql', 'dialect': 'postgres', 'reset': True})
        second.save_layout({'tables': {}, 'blocks': []})

        self.assertEqual(second.workspace, os.path.join(self.root, 'blog_2'))
        self.assertEqual(len(workspace.load(first.workspace)['tables']), 2)
        self.assertEqual(len(workspace.load(second.workspace)['tables']), 1)

    def test_opening_a_loose_sql_keeps_the_legacy_layout_file(self):
        sql_path = os.path.join(self.root, 'solto.sql')
        with open(sql_path, 'w', encoding='utf-8') as sql_file:
            sql_file.write(SQL)
        session = EditorSession(sql_path)

        saved = session.save_layout({'tables': {'users': {'x': 1, 'y': 2}}, 'blocks': []})

        self.assertIsNone(session.workspace)
        self.assertTrue(saved.endswith('solto.layout.json'))


if __name__ == '__main__':
    unittest.main()
