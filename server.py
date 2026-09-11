"""Servidor local do editor: serve a página e persiste o layout em disco."""

import json
import html
import os
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import model
import generate_sql
import import_adapter
import mutation_sql
import mutations
import project as project_model
import workspace

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, 'templates', 'app.html')
SQL_EDITOR_BUNDLE = os.path.join(HERE, 'assets', 'sql-editor.js')
SCHEMAS_ROOT = os.path.join(HERE, 'schemas')
MAX_BODY = 10 * 1024 * 1024
VALID_DIALECTS = {'auto', 'postgres', 'mysql'}


def render_page(m):
    with open(TEMPLATE, encoding='utf-8') as template_file:
        template = template_file.read()
    data = json.dumps(m, separators=(',', ':'))
    data = data.replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    title = html.escape(m['meta']['title'])
    return re.sub(r'__(DATA|TITLE)__', lambda match: data if match.group(1) == 'DATA' else title,
                  template)


def page(target=None, override=None, force=False):
    return render_page(EditorSession(target, override).build(force=force))


class EditorSession:
    """Estado do editor.

    Abre uma pasta de projeto (``project.json`` como fonte de verdade) ou um
    .sql solto (modo legado, layout em ``<schema>.layout.json``).
    """

    def __init__(self, target=None, override=None):
        self.lock = threading.RLock()
        self.override = override
        self.workspace = None
        self.sql_path = None
        self.dialect = None
        self.layout = None
        self.sql = ''
        self.title = 'novo_schema.sql'
        kind, path = workspace.resolve(target) if target else (None, None)
        if kind == 'workspace':
            self.workspace = path
            self.project = workspace.load(path)
            self.override = override or workspace.groups_path(path)
            self._sync_compatibility_fields()
            return
        if kind == 'sql':
            self.sql_path = path
            self.title = os.path.basename(path)
            self.layout = model.load_layout(path)
            with open(path, encoding='utf-8') as sql_file:
                self.sql = sql_file.read()
        self.project = import_adapter.import_sql(
            self.sql, self.title, self.dialect, legacy_layout=self.layout)

    @property
    def storage(self):
        """Onde o projeto vive: a pasta, o .sql legado ou só a memória."""
        return self.workspace or self.sql_path or None

    def _ensure_workspace(self):
        """Dá uma pasta ao projeto criado dentro do editor.

        Uma sessão sem destino não tinha onde gravar: o editor dizia "salvo" e
        nada ia para o disco. Na primeira gravação com conteúdo, o projeto ganha
        uma pasta em schemas/, nomeada pelo título. Um projeto ainda vazio não
        cria nada, e uma pasta já existente nunca é sobrescrita.
        """
        if self.workspace or self.sql_path or not self.project['tables']:
            return self.workspace
        # só o salvamento chama aqui: carregar SQL para olhar não cria pasta
        base = os.path.join(SCHEMAS_ROOT, workspace.slug(self.project['title']))
        directory, counter = base, 2
        while os.path.exists(directory):
            directory = '%s_%d' % (base, counter)
            counter += 1
        self.workspace = directory
        return directory

    def _persist(self):
        """Grava o projeto quando a sessão já tem uma pasta."""
        if not self.workspace:
            return None
        return workspace.save(self.workspace, self.project)['project']

    def _dialect(self, payload):
        dialect = payload.get('dialect')
        if dialect not in VALID_DIALECTS and dialect is not None:
            raise ValueError('dialeto deve ser auto, postgres ou mysql')
        return None if dialect in (None, '', 'auto') else dialect

    def _candidate(self, payload):
        sql = payload.get('sql', '')
        if not isinstance(sql, str):
            raise ValueError('sql deve ser texto')
        title = os.path.basename(payload.get('title') or 'novo_schema.sql')
        previous = None if payload.get('reset') else self.project
        candidate = import_adapter.import_sql(sql, title, self._dialect(payload), previous=previous)
        if sql.strip() and not candidate['tables']:
            raise ValueError('nenhum CREATE TABLE reconhecido no SQL')
        diagram = model.build_project(candidate, self.override)
        return candidate, diagram

    @staticmethod
    def _result(diagram, changes=None, include_diagram=False):
        result = {'ok': True, 'tables': diagram['meta']['nt'],
                  'relations': diagram['meta']['nf'],
                  'dialect': diagram['meta']['dialect']}
        if changes is not None:
            result['changes'] = changes
        if include_diagram:
            # o editor redesenha com isto em vez de recarregar a página
            result['diagram'] = diagram
        return result

    def _sync_compatibility_fields(self):
        self.sql = self.project['source']['sql']
        self.title = self.project['title']
        dialect = self.project['dialect']
        self.dialect = dialect if dialect in ('postgres', 'mysql') else None
        self.layout = import_adapter.project_layout_to_legacy(self.project)

    def build(self, force=False):
        with self.lock:
            return model.build_project(self.project, self.override, force_relayout=force)

    def source(self):
        with self.lock:
            storage = self.storage
            return {'sql': self.sql, 'title': self.title,
                    'dialect': self.dialect or 'auto',
                    'source': os.path.basename(storage) if storage else None,
                    'workspace': os.path.basename(self.workspace) if self.workspace else None,
                    'project_id': self.project['id'], 'version': self.project['version']}

    def project_data(self):
        with self.lock:
            return project_model.loads(project_model.dumps(self.project))

    def validate(self, payload):
        with self.lock:
            candidate, diagram = self._candidate(payload)
            changes = project_model.diff_projects(self.project, candidate)
            return self._result(diagram, changes)

    def apply_sql(self, payload):
        with self.lock:
            candidate, diagram = self._candidate(payload)
            changes = project_model.diff_projects(self.project, candidate)
            if payload.get('detach'):
                self.sql_path = None
                self.workspace = None
            self.project = candidate
            self._sync_compatibility_fields()
            self._persist()
            return self._result(diagram, changes, include_diagram=True)

    def apply_project(self, payload):
        with self.lock:
            project_model.validate_project(payload)
            self.project = project_model.loads(project_model.dumps(payload))
            self.sql_path = None
            self._sync_compatibility_fields()
            self._persist()
            diagram = model.build_project(self.project, self.override)
            return self._result(diagram, include_diagram=True)

    def mutate(self, operation):
        with self.lock:
            previous = self.project
            candidate = mutations.apply_mutation(previous, operation)
            mutation_sql.sync_source(previous, candidate, operation)
            project_model.validate_project(candidate)
            changes = project_model.diff_projects(previous, candidate)
            self.project = candidate
            self._sync_compatibility_fields()
            self._persist()
            diagram = model.build_project(self.project, self.override)
            result = self._result(diagram, changes, include_diagram=True)
            result['message'] = 'schema atualizado'
            return result

    def save_layout(self, payload):
        with self.lock:
            legacy = {'tables': payload.get('tables', {}),
                      'blocks': payload.get('blocks', [])}
            names = {table['name']: table['id'] for table in self.project['tables']}
            positions = {}
            for name, point in model._saved_positions(legacy, set(names)).items():
                positions[names[name]] = point
            old_blocks = {block['id']: block.get('table_ids', [])
                          for block in self.project['layout']['blocks']}
            blocks = []
            for block in model._saved_blocks(legacy):
                block['table_ids'] = [table_id for table_id in old_blocks.get(block['id'], [])
                                      if table_id in names.values()]
                blocks.append(block)
            self.project['layout'] = {'tables': positions, 'blocks': blocks}
            project_model.validate_project(self.project)
            self.layout = import_adapter.project_layout_to_legacy(self.project)
            self._ensure_workspace()
            saved = self._persist()
            if saved:
                return saved
            if self.sql_path:
                return model.save(self.sql_path, self.layout)
            return 'em memória (nenhuma tabela ainda)'


def serve(target=None, override=None, port=8765, open_browser=True):
    session = EditorSession(target, override)

    class H(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype='application/json; charset=utf-8'):
            b = body if isinstance(body, bytes) else body.encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(b)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            path = self.path.split('?', 1)[0]      # ignora query (cache-bust)
            if path in ('/', '/index.html'):
                try:
                    self._send(200, render_page(session.build()), 'text/html; charset=utf-8')
                except Exception as e:
                    self._send(500, f'<pre>{html.escape(str(e))}</pre>',
                               'text/html; charset=utf-8')
            elif path == '/api/sql':
                self._send(200, json.dumps(session.source()))
            elif path == '/api/sql/generated':
                # DDL gerado a partir do modelo canônico, no dialeto pedido.
                # Diferente de /api/sql, que devolve o texto de origem.
                try:
                    import urllib.parse
                    query = urllib.parse.parse_qs(self.path.partition('?')[2])
                    dialect = (query.get('dialect') or [None])[0]
                    project = session.project_data()
                    sql = generate_sql.generate(project, dialect)
                    self._send(200, json.dumps({
                        'sql': sql,
                        'dialect': dialect or project.get('dialect'),
                        'title': project.get('title') or 'schema.sql',
                    }))
                except Exception as e:
                    self._send(400, json.dumps({'error': str(e)}))
            elif path == '/api/project':
                self._send(200, project_model.dumps(session.project_data()))
            elif path == '/assets/sql-editor.js' and os.path.exists(SQL_EDITOR_BUNDLE):
                with open(SQL_EDITOR_BUNDLE, 'rb') as asset_file:
                    self._send(200, asset_file.read(), 'text/javascript; charset=utf-8')
            else:
                self._send(404, '{"error":"not found"}')

        def do_POST(self):
            try:
                n = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                self._send(400, '{"error":"Content-Length inválido"}')
                return
            if n < 0 or n > MAX_BODY:
                self._send(413, '{"error":"requisição excede o limite de 10 MB"}')
                return
            raw = self.rfile.read(n) if n else b'{}'
            path = self.path.split('?', 1)[0]
            if path == '/api/layout':
                try:
                    f = session.save_layout(json.loads(raw))
                    self._send(200, json.dumps({
                        'ok': True, 'file': f,
                        'workspace': (os.path.basename(session.workspace)
                                      if session.workspace else None)}))
                except Exception as e:
                    self._send(500, json.dumps({'error': str(e)}))
            elif path == '/api/relayout':
                try:
                    m = session.build(force=True)
                    self._send(200, json.dumps({'tables': [{'name': t['name'], 'x': t['x'],
                                                            'y': t['y']} for t in m['tables']],
                                                'blocks': m['blocks']}))
                except Exception as e:
                    self._send(500, json.dumps({'error': str(e)}))
            elif path in ('/api/sql', '/api/sql/validate'):
                try:
                    payload = json.loads(raw)
                    result = (session.validate(payload) if path.endswith('/validate')
                              else session.apply_sql(payload))
                    self._send(200, json.dumps(result))
                except Exception as e:
                    self._send(400, json.dumps({'error': str(e)}))
            elif path == '/api/project':
                try:
                    result = session.apply_project(json.loads(raw))
                    self._send(200, json.dumps(result))
                except Exception as e:
                    self._send(400, json.dumps({'error': str(e)}))
            elif path == '/api/mutate':
                try:
                    result = session.mutate(json.loads(raw))
                    self._send(200, json.dumps(result))
                except Exception as e:
                    self._send(400, json.dumps({'error': str(e)}))
            else:
                self._send(404, '{"error":"not found"}')

        def log_message(self, *a):
            pass                                   # silencia o log por requisição

    httpd = ThreadingHTTPServer(('127.0.0.1', port), H)
    url = f'http://127.0.0.1:{port}/'
    print(f'schema-map  ->  {url}')
    if session.workspace:
        print(f'  projeto: {workspace.project_path(session.workspace)}')
        print(f'  ddl    : {workspace.schema_path(session.workspace)}  (gerado)')
        groups = workspace.groups_path(session.workspace)
        if groups:
            print(f'  blocos : {groups}')
    else:
        print(f'  schema : {session.sql_path or "novo projeto"}')
        print(f'  layout : {model.layout_path(session.sql_path) if session.sql_path else "em memoria"}')
    if not os.path.exists(SQL_EDITOR_BUNDLE):
        # sem o bundle o inspetor não monta e clicar numa coluna não faz nada
        print('  ! assets/sql-editor.js nao encontrado: o inspetor de tabelas,')
        print('    colunas, indices e FKs fica indisponivel.')
        print('    gere com: npm install && npm run build:frontend')
    print('  Ctrl+C para parar')
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nencerrado')
