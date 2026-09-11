"""Workspace em pasta: um projeto de diagramação por diretório.

    schemas/<projeto>/
        project.json   modelo canônico completo — fonte de verdade
        schema.sql     DDL gerado a partir de project.json, para leitura e diff
        groups.json    override opcional de agrupamento {bloco: "t1 t2 ..."}

``project.json`` guarda tudo (tabelas, colunas, índices, relacionamentos,
layout, SQL de origem), então a pasta é auto-contida: dá para mover, versionar
ou compartilhar sem perder posição de tabela nem bloco.  ``schema.sql`` é
derivado — reescrito a cada salvamento — e existe só para o diff do git ficar
legível; editá-lo à mão não muda o projeto.
"""

import json
import os
import re
import tempfile

import generate_sql
import import_adapter
import project as project_model

PROJECT_FILE = 'project.json'
SCHEMA_FILE = 'schema.sql'
GROUPS_FILE = 'groups.json'


def slug(title):
    """Nome de pasta estável a partir do título do projeto."""
    base = os.path.splitext(os.path.basename(title or ''))[0]
    base = re.sub(r'[^a-zA-Z0-9]+', '_', base).strip('_').lower()
    return base or 'projeto'


def project_path(directory):
    return os.path.join(directory, PROJECT_FILE)


def schema_path(directory):
    return os.path.join(directory, SCHEMA_FILE)


def groups_path(directory):
    """Caminho do override de agrupamento, ou None se a pasta não tiver um."""
    path = os.path.join(directory, GROUPS_FILE)
    return path if os.path.isfile(path) else None


def is_workspace(path):
    return bool(path) and os.path.isfile(project_path(path))


def resolve(path):
    """Classifica um alvo de linha de comando.

    Devolve ``('workspace', dir)`` para uma pasta de projeto, ``('sql', file)``
    para um .sql solto (modo legado) e levanta ``ValueError`` no resto.
    """
    if not path:
        return None, None
    target = os.path.abspath(path)
    if os.path.isdir(target):
        if not is_workspace(target):
            raise ValueError('pasta sem %s: %s' % (PROJECT_FILE, path))
        return 'workspace', target
    if not os.path.isfile(target):
        raise ValueError('arquivo não encontrado: %s' % path)
    if os.path.basename(target) == PROJECT_FILE:
        return 'workspace', os.path.dirname(target)
    return 'sql', target


def _atomic_write(path, text):
    directory = os.path.dirname(path) or '.'
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=directory,
                                     prefix='.schema-map-', suffix='.tmp',
                                     delete=False, newline='\n') as temp_file:
        temp_file.write(text)
        tmp = temp_file.name
    try:
        os.replace(tmp, path)          # troca atômica: nunca deixa arquivo parcial
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


def load(directory):
    """Lê e valida o projeto canônico da pasta."""
    with open(project_path(directory), encoding='utf-8') as project_file:
        return project_model.loads(project_file.read())


def save(directory, project):
    """Grava project.json e reescreve o schema.sql derivado.

    O DDL é gerado antes de qualquer escrita: se o projeto não puder virar SQL,
    nada é tocado no disco.
    """
    payload = project_model.dumps(project)          # valida antes de gravar
    try:
        ddl = generate_sql.generate(project)
    except Exception as exc:                        # noqa: BLE001 - vira erro de IO
        raise ValueError('não foi possível gerar o DDL: %s' % exc) from exc
    os.makedirs(directory, exist_ok=True)
    _atomic_write(project_path(directory), payload)
    _atomic_write(schema_path(directory), ddl)
    return {'project': project_path(directory), 'schema': schema_path(directory)}


def create_from_sql(sql_path, directory=None, dialect=None, groups=None,
                    legacy_layout=None):
    """Cria a pasta do projeto a partir de um .sql solto.

    ``directory`` cai para ``<pasta do .sql>/<slug do nome>``.  Um layout legado
    (``<schema>.layout.json``) e um ``--groups`` existentes são aproveitados.
    """
    with open(sql_path, encoding='utf-8') as sql_file:
        sql = sql_file.read()
    title = os.path.basename(sql_path)
    directory = os.path.abspath(directory or os.path.join(os.path.dirname(
        os.path.abspath(sql_path)), slug(title)))
    project = import_adapter.import_sql(sql, title, dialect,
                                        legacy_layout=legacy_layout)
    written = save(directory, project)
    if groups and os.path.isfile(groups):
        with open(groups, encoding='utf-8') as groups_file:
            data = json.load(groups_file)
        _atomic_write(os.path.join(directory, GROUPS_FILE),
                      json.dumps(data, ensure_ascii=False, indent=1) + '\n')
        written['groups'] = os.path.join(directory, GROUPS_FILE)
    return directory, written
