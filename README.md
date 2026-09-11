# schema-map

Editor local de schemas de banco, no espírito do drawDB. Lê DDL de PostgreSQL e
MySQL/MariaDB, desenha o diagrama, deixa evoluir tabelas e relacionamentos
visualmente e exporta o SQL resultante.

Roda inteiro na sua máquina: um servidor HTTP em `127.0.0.1`, sem conta, sem
nuvem, sem telemetria.

---

## Instalação

### Requisitos

| | versão | para quê |
|---|---|---|
| Python | 3.9 ou mais novo (testado em 3.13) | servidor e parser |
| Node.js | 18 ou mais novo (testado em 24) | só para gerar o bundle do editor |

O lado Python não tem dependência externa: usa apenas a biblioteca padrão, sem
`pip install`.

### Passos

```bash
git clone <url-do-repo> schema_map
cd schema_map

npm install              # baixa CodeMirror e esbuild
npm run build:frontend   # gera assets/sql-editor.js
```

**O build do frontend não é opcional.** Sem `assets/sql-editor.js`:

- o painel `SQL` cai para uma caixa de texto simples — funciona, mas sem
  destaque de sintaxe;
- o **inspetor não abre**: clicar numa tabela ou numa linha de coluna não faz
  nada, sem erro visível.

O `serve` avisa no terminal quando o arquivo está faltando. Se você atualizar o
repositório e o inspetor parar de responder, rode `npm run build:frontend` de
novo.

### Conferir

```bash
python schema_map.py --help
python -m unittest discover -s tests -p "test_*.py"
```

---

## Começando

```bash
# a partir de um DDL que você já tem
python schema_map.py init meu_schema.sql
python schema_map.py serve schemas/meu_schema

# do zero, escrevendo o SQL no próprio editor
python schema_map.py serve
```

O navegador abre sozinho em `http://127.0.0.1:8765/`. Use `--port` para trocar
a porta e `--no-open` para não abrir o navegador.

---

## A pasta do projeto

Cada projeto é uma pasta, por padrão dentro de `schemas/`:

```
schemas/meu_projeto/
    project.json    fonte de verdade — schema, layout, blocos e o SQL de origem
    schema.sql      DDL gerado a partir do project.json
    groups.json     agrupamento manual em blocos (opcional)
```

**`project.json`** guarda tudo: tabelas, colunas, tipos, índices,
relacionamentos, a posição de cada tabela no canvas, os retângulos dos blocos e
o SQL de origem palavra por palavra. A pasta é auto-contida — dá para mover,
versionar ou mandar para outra pessoa sem perder nada do desenho.

**`schema.sql`** é **derivado**. É reescrito a cada salvamento e existe só para
o diff do git ficar legível e para ler o DDL sem abrir JSON. Editá-lo à mão
**não muda o projeto**; para trocar o DDL, use o painel `SQL` do editor ou rode
`init` de novo.

**`groups.json`**, quando existe, é usado automaticamente como `--groups`.

### Quando a pasta é criada

| situação | cria pasta? | onde |
|---|---|---|
| `schema_map.py init arquivo.sql` | sim, na hora | `<pasta do .sql>/<nome>/` |
| projeto novo no editor, ao **salvar** | sim | `schemas/<título>/` |
| projeto novo no editor, sem salvar | não | nada em disco |
| `schema_map.py serve arquivo.sql` | não | `arquivo.layout.json` ao lado (modo legado) |

Projeto ainda sem tabela nenhuma não cria pasta. Se já existir uma pasta com o
mesmo nome, ela **nunca** é sobrescrita — a nova ganha sufixo
(`meu_projeto_2`).

A pasta `schemas/` não é versionada: é onde ficam os seus projetos, que são
seus. Veja [Versionamento](#versionamento).

---

## Linha de comando

### `init` — cria a pasta do projeto

```
python schema_map.py init ARQUIVO.sql [-o PASTA] [--groups G.json] [--dialect postgres|mysql]
```

Aproveita um layout legado (`<schema>.layout.json`) e um `--groups` que já
existam. O dialeto é detectado sozinho; `--dialect` só é preciso em DDL ambíguo.

### `serve` — abre o editor

```
python schema_map.py serve [ALVO] [--port 8765] [--no-open] [--groups G.json]
```

`ALVO` pode ser a pasta do projeto, o `project.json` dentro dela, ou um `.sql`
solto. Sem alvo, começa um projeto vazio.

### `build` — HTML estático

```
python schema_map.py build ALVO [-o SAIDA.html] [--relayout]
```

Gera um HTML autocontido, para mandar por e-mail ou versionar. No HTML estático
o botão salvar não funciona — é só leitura. `--relayout` ignora o layout salvo
e recalcula tudo.

### `info` — o que foi lido

Imprime dialeto, contagem de tabelas, colunas e FKs, as tabelas-hub (as mais
referenciadas) e a divisão em blocos, sem abrir nada.

---

## Usando o editor

### Navegar

| tecla | ação |
|---|---|
| `⌘K` / `Ctrl+K` | paleta de comandos |
| `F` | ajustar à tela |
| `Ctrl/Cmd + S` | salvar |
| `Ctrl/Cmd + Z` | desfazer |
| `Esc` | limpar seleção |
| roda | zoom no cursor |
| arrastar fundo | mover a tela |

### Selecionar

- **Clique no cabeçalho da tabela** — seleciona a tabela, destaca as FKs ligadas
  a ela e abre o inspetor na aba *Tabela*.
- **Clique numa linha de coluna** — abre o inspetor na aba *Colunas*, já com o
  formulário daquela coluna. A linha fica marcada no diagrama enquanto você
  edita.
- **Clique numa linha de relação** — mostra nome, cardinalidade e as duas
  pontas, e abre o inspetor na aba *Relações*.

### Editar pelo inspetor

O painel da direita tem quatro abas:

- **Tabela** — nome, schema, excluir.
- **Colunas** — criar, editar e excluir. O campo *tipo* é uma lista por
  dialeto: escolher `VARCHAR` abre o campo *tamanho*, `DECIMAL` abre *precisão*
  e *escala*. Tipos fora da lista ficam em *outro (texto livre)*, preservando o
  texto original — enums, arrays e tipos de extensão continuam editáveis.
- **Índices** — criar, editar e excluir, inclusive compostos, com a ordem das
  colunas. O índice da chave primária é somente leitura.
- **Relações** — criar, editar e excluir FKs, inclusive compostas, com
  `ON DELETE` e `ON UPDATE`.

### Editar direto no diagrama

Dois cliques:

- no **cabeçalho** da tabela, renomeia a tabela;
- na **metade esquerda** de uma linha de coluna, edita o nome;
- na **metade direita** da mesma linha, edita o tipo.

`Tab` alterna entre nome e tipo sem precisar de um segundo duplo clique.

Toda alteração é validada no servidor antes de entrar. O diagrama é redesenhado
na hora, sem recarregar a página: câmera, zoom e seleção continuam onde estavam.

### Blocos

Os blocos são os retângulos coloridos que agrupam tabelas por domínio.

A associação é **geométrica**, como no drawDB: a tabela pertence ao bloco cujo
retângulo contém o centro dela. Arrastar para dentro já reassocia — o cabeçalho
muda de cor na hora. Não há lista de membros para manter em sincronia.

- *novo bloco* na paleta de comandos cria um retângulo;
- arrastar a borda redimensiona;
- dois cliques no título renomeia;
- *auto-organizar* recalcula posições e blocos do zero (pede confirmação).

### Arquivo de blocos (`--groups`)

```json
{
  "contas": "usuarios perfis papeis permissoes",
  "vendas": ["pedidos", "itens_pedido", "pagamentos"]
}
```

Aceita string com espaços ou lista. Tabela que não aparecer no arquivo cai em
`ungrouped` (e o `info` avisa quantas foram). Dentro da pasta do projeto, o
arquivo se chama `groups.json` e é usado sem precisar da opção.

Sem `groups.json`, os blocos são deduzidos automaticamente (Louvain sobre o
grafo de FKs, com peso extra para prefixos de nome em comum).

### Salvar

| | |
|---|---|
| `Ctrl+S` ou botão *salvar* | grava na hora |
| auto-salvar (ligado por padrão) | grava sozinho depois de cada mudança |

O que é gravado: posições, blocos e o schema inteiro, em `project.json`, mais o
`schema.sql` derivado. O `.sql` de origem que você importou **nunca** é
sobrescrito.

### Editar SQL

Os comandos `novo`, `abrir` e `SQL` ficam na barra do diagrama. O editor usa
CodeMirror 6, com destaque por dialeto, busca, histórico, autocomplete e
correspondência de parênteses.

Antes de aplicar, o servidor valida o DDL e mostra a **prévia estrutural**:
tabelas, colunas e relações adicionadas, removidas ou alteradas. Nada entra na
sessão sem passar por isso.

### Exportar

- **exportar SQL (texto de origem)** — o DDL original com os `ALTER` das suas
  edições acumulados no fim; preserva comentários e formatação do arquivo
  importado.
- **exportar DDL gerado — PostgreSQL** / **— MySQL** — DDL limpo, reconstruído
  do modelo, no dialeto escolhido. É por aqui que se converte um schema de um
  banco para o outro: `UUID` ⇄ `CHAR(36)`, `JSONB` ⇄ `JSON`, `BOOLEAN` ⇄
  `TINYINT(1)`, `NOW()` ⇄ `CURRENT_TIMESTAMP` e assim por diante.
- **exportar projeto (.json)** — o `project.json`, para levar tudo para outra
  máquina.

---

## Versionamento

A pasta `schemas/` é onde seus projetos vivem. Duas escolhas:

**Versionar** — `project.json` entra no git e o layout viaja com o schema. O
`schema.sql` ao lado deixa o diff legível: dá para ver no PR que uma coluna
mudou de tipo.

**Não versionar** — acrescente ao `.gitignore`:

```
schemas/
```

Atenção: `.gitignore` não descarta o que já está rastreado. Se alguma pasta de
`schemas/` já foi commitada antes, é preciso tirá-la do índice:

```bash
git rm -r --cached schemas/
git commit -m "chore: para de versionar os schemas locais"
```

Os arquivos continuam no disco; só saem do controle de versão.

---

## Problemas comuns

**Clicar na tabela ou na coluna não abre nada.**
O bundle do frontend não foi gerado. Rode `npm run build:frontend`. O terminal
do `serve` avisa quando o arquivo está faltando.

**"nenhum CREATE TABLE reconhecido no SQL".**
O parser só entende `CREATE TABLE`. Views, functions, triggers e procedures são
preservados no texto de origem, mas não entram no diagrama nem no DDL gerado.

**O diagrama voltou para o layout automático.**
Aconteceu um `--relayout`, ou o `project.json` não foi encontrado. Confirme que
você abriu a pasta do projeto, e não o `.sql` solto.

**O editor demora para responder em schemas grandes.**
Uma edição num schema de 139 tabelas leva cerca de 0,4 s. Se estiver muito pior,
provavelmente o layout salvo está incompleto — uma tabela nova ainda sem
posição força o recálculo automático a cada operação. Salve uma vez para fixar
as posições.

**A porta 8765 já está em uso.**
`python schema_map.py serve ALVO --port 9000`.

**O texto de origem cresce a cada edição.**
Cada mutação acrescenta um `ALTER` ao SQL de origem, inclusive quando você
desfaz renomeando de volta. Isso não afeta o modelo nem o DDL gerado — use
*exportar DDL gerado* para obter um SQL limpo.

---

## Limites conhecidos

- Índices avançados, enums, views, triggers, procedures e partições são
  preservados no texto de origem, mas não entram no DDL gerado nem têm edição
  visual própria.
- O DDL gerado é normalizado: comentários e formatação do arquivo original não
  sobrevivem a ele (use *exportar SQL (texto de origem)* para isso).
- `build` gera HTML estático para navegação; os comandos de projeto e salvar
  dependem da API iniciada por `serve`.
- O agrupamento automático acerta cerca de 40% dos pares quando comparado a uma
  divisão feita à mão por domínio de negócio — serve de ponto de partida, não de
  resposta final. Para o resultado bom, use `--groups`.
- Desfazer (`Ctrl+Z`) cobre movimentação no canvas, mas é zerado a cada mudança
  estrutural do schema.

---

## Estrutura do repositório

| arquivo | papel |
|---|---|
| `schema_map.py` | linha de comando |
| `server.py` | servidor local e sessão do editor |
| `workspace.py` | a pasta do projeto: criar, ler, gravar |
| `project.py` | modelo canônico, validação, serialização e diff |
| `parse_sql.py` | DDL → tabelas, colunas, FKs |
| `generate_sql.py` | modelo canônico → DDL, com tradução de tipos |
| `mutations.py` | valida e aplica operações estruturais no projeto |
| `mutation_sql.py` | converte operações visuais em DDL incremental |
| `import_adapter.py` | adapta SQL e layouts antigos para o projeto canônico |
| `model.py` | monta o diagrama e persiste o layout |
| `layout.py` | posiciona tabelas e blocos |
| `grouping.py` | blocos (automático ou override) |
| `community.py` | Louvain com resolução ajustável |
| `templates/app.html` | a interface |
| `frontend/sql-editor.js` | integração CodeMirror 6 |
| `frontend/inspector.js` | inspetores de tabela, coluna, índice e FK |
| `tests/` | suíte em `unittest` mais um teste de ponta a ponta em Playwright |

### Como o layout é calculado

Dentro de cada bloco, layout em camadas no estilo Sugiyama: camada por
profundidade de dependência (pai à esquerda, filho à direita), ordem dentro da
camada por baricentro para reduzir cruzamentos, e o `y` de cada tabela puxado
para a média das que ela referencia — é isso que faz a tabela de ligação parar
entre as duas pontas.

Entre blocos, os mais acoplados ficam vizinhos (recozimento simulado sobre uma
grade), depois empacotamento por fileira.

O cálculo automático só roda quando precisa: se o layout salvo já cobre toda
tabela e todo bloco, ele é pulado inteiro.
