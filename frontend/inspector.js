let inspectorSequence = 0;

const TAB_LABELS = {
  table: "Tabela",
  columns: "Colunas",
  indexes: "Índices",
  relationships: "Relações",
};

const ACTIONS = {
  tableUpdate: "table.update",
  tableDelete: "table.delete",
  columnCreate: "column.create",
  columnUpdate: "column.update",
  columnDelete: "column.delete",
  indexCreate: "index.create",
  indexUpdate: "index.update",
  indexDelete: "index.delete",
  relationshipCreate: "relationship.create",
  relationshipUpdate: "relationship.update",
  relationshipDelete: "relationship.delete",
};

const CUSTOM_TYPE = "__custom__";

// Tipos oferecidos no seletor, por dialeto. `args` descreve os parâmetros entre
// parênteses: cada entrada vira um campo, e `default` é o valor sugerido quando
// o tipo é escolhido do zero. Tipo fora da lista cai em "outro", que mantém o
// texto livre — enums, arrays e tipos de extensão continuam editáveis.
const TYPE_CATALOG = {
  postgres: [
    { name: "TEXT" },
    { name: "VARCHAR", args: [{ label: "tamanho", default: "255", required: true }] },
    { name: "CHAR", args: [{ label: "tamanho", default: "2", required: true }] },
    { name: "UUID" },
    { name: "BOOLEAN" },
    { name: "SMALLINT" },
    { name: "INTEGER" },
    { name: "BIGINT" },
    { name: "SERIAL" },
    { name: "BIGSERIAL" },
    { name: "NUMERIC", args: [{ label: "precisão", default: "18" }, { label: "escala", default: "2" }] },
    { name: "REAL" },
    { name: "DOUBLE PRECISION" },
    { name: "DATE" },
    { name: "TIME" },
    { name: "TIMESTAMP", args: [{ label: "precisão" }] },
    { name: "TIMESTAMPTZ", args: [{ label: "precisão" }] },
    { name: "JSONB" },
    { name: "JSON" },
    { name: "BYTEA" },
    { name: "INET" },
  ],
  mysql: [
    { name: "TEXT" },
    { name: "VARCHAR", args: [{ label: "tamanho", default: "255", required: true }] },
    { name: "CHAR", args: [{ label: "tamanho", default: "36", required: true }] },
    { name: "TINYINT", args: [{ label: "tamanho", default: "1" }] },
    { name: "SMALLINT", args: [{ label: "tamanho" }] },
    { name: "INT", args: [{ label: "tamanho" }] },
    { name: "BIGINT", args: [{ label: "tamanho" }] },
    { name: "DECIMAL", args: [{ label: "precisão", default: "18" }, { label: "escala", default: "2" }] },
    { name: "FLOAT" },
    { name: "DOUBLE" },
    { name: "DATE" },
    { name: "TIME" },
    { name: "DATETIME", args: [{ label: "precisão" }] },
    { name: "TIMESTAMP", args: [{ label: "precisão" }] },
    { name: "JSON" },
    { name: "BLOB" },
    { name: "LONGTEXT" },
  ],
};

function typeCatalog(dialect) {
  return TYPE_CATALOG[dialect === "mysql" ? "mysql" : "postgres"];
}

// Separa "varchar(320)" em base, parâmetros e sufixo. Sem parênteses, o texto
// inteiro é a base — "DOUBLE PRECISION" continua inteiro, e um tipo que a lista
// não conhece cai em "outro" sem perder nada.
function parseType(raw) {
  const value = String(raw === null || raw === undefined ? "" : raw).trim();
  const open = value.indexOf("(");
  if (open === -1) {
    return { base: value.toUpperCase(), baseText: value, args: [], tail: "", raw: value };
  }
  const close = value.indexOf(")", open);
  const baseText = value.slice(0, open).trim();
  const inner = close === -1 ? value.slice(open + 1) : value.slice(open + 1, close);
  return {
    base: baseText.toUpperCase(),
    baseText,
    args: inner.split(",").map((part) => part.trim()),
    tail: close === -1 ? "" : value.slice(close + 1).trim(),
    raw: value,
  };
}

function composeType(baseText, args, tail) {
  const values = args.map((value) => String(value).trim()).filter(Boolean);
  let out = values.length ? `${baseText}(${values.join(",")})` : baseText;
  if (tail) out += ` ${tail}`;
  return out;
}

// Seletor de tipo: uma lista de tipos conhecidos mais os campos de parâmetro
// que o tipo escolhido aceita — VARCHAR abre "tamanho", NUMERIC abre
// "precisão" e "escala". Devolve { node, read } para o formulário ler o valor
// final já montado.
function typeField({ id, value, dialect, label = "Tipo" }) {
  const catalog = typeCatalog(dialect);
  const parsed = parseType(value);
  const known = catalog.find((entry) => entry.name === parsed.base) || null;

  const field = element("div", "schema-inspector__field schema-inspector__type");
  field.appendChild(element("span", "schema-inspector__label", label));

  const options = catalog.map((entry) => ({ value: entry.name, label: entry.name }));
  options.push({ value: CUSTOM_TYPE, label: "outro (texto livre)" });
  const select = selectField(`${id}-base`, options, known ? known.name : CUSTOM_TYPE);
  select.setAttribute("aria-label", label);
  field.appendChild(select);

  const args = element("div", "schema-inspector__type-args");
  const custom = inputField("text", known ? "" : parsed.raw, `${id}-custom`, "ex.: geometry(Point,4326)");
  custom.setAttribute("aria-label", "Tipo em texto livre");
  const customField = element("label", "schema-inspector__type-arg");
  append(customField, element("span", "", "tipo completo"), custom);
  append(field, args, customField);

  function renderArgs(entry, values) {
    args.replaceChildren();
    if (!entry || !entry.args) return;
    entry.args.forEach((spec, index) => {
      const input = inputField("text", values[index] ?? "", `${id}-arg-${index}`, spec.default || "");
      input.inputMode = "numeric";
      input.setAttribute("aria-label", `${entry.name} — ${spec.label}`);
      const wrapper = element("label", "schema-inspector__type-arg");
      append(wrapper, element("span", "", spec.label + (spec.required ? "" : " (opcional)")), input);
      args.appendChild(wrapper);
    });
  }

  function sync() {
    const entry = catalog.find((item) => item.name === select.value) || null;
    customField.hidden = Boolean(entry);
    args.hidden = !entry || !entry.args;
    if (!entry) {
      args.replaceChildren();
      return;
    }
    const reuse = entry.name === parsed.base ? parsed.args : [];
    renderArgs(entry, reuse.length ? reuse : (entry.args || []).map((spec) => spec.default || ""));
  }

  select.addEventListener("change", sync);
  sync();

  return {
    node: field,
    read() {
      if (select.value === CUSTOM_TYPE) return custom.value.trim();
      const entry = catalog.find((item) => item.name === select.value);
      const values = Array.from(args.querySelectorAll("input")).map((input) => input.value);
      // mantém a grafia original quando o tipo não mudou, para não gerar um
      // ALTER só por diferença de maiúsculas (varchar -> VARCHAR)
      const baseText = entry.name === parsed.base ? parsed.baseText : entry.name;
      return composeType(baseText, values, entry.name === parsed.base ? parsed.tail : "");
    },
  };
}

const DELETE_CONFIRMATIONS = {
  table: "Excluir esta tabela e todas as relações ligadas a ela?",
  column: "Excluir esta coluna? As relações e índices que a usam também poderão ser afetados.",
  index: "Excluir este índice?",
  relationship: "Excluir esta relação?",
};

function element(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined && content !== null) node.textContent = String(content);
  return node;
}

function append(parent, ...children) {
  children.forEach((child) => {
    if (child !== null && child !== undefined) parent.appendChild(child);
  });
  return parent;
}

function text(value, fallback = "") {
  return value === null || value === undefined ? fallback : String(value);
}

function sameId(left, right) {
  return left !== null && left !== undefined && String(left) === String(right);
}

function tableName(table) {
  if (!table) return "";
  return table.schema ? `${table.schema}.${table.name}` : table.name;
}

function tableById(project, id) {
  return (project?.tables || []).find((table) => sameId(table.id, id)) || null;
}

function columnById(table, id) {
  return (table?.columns || []).find((column) => sameId(column.id, id)) || null;
}

function relationById(project, id) {
  return (project?.relationships || []).find((relation) => sameId(relation.id, id)) || null;
}

function relationTouchesTable(relation, tableId) {
  return sameId(relation?.from?.table_id, tableId) || sameId(relation?.to?.table_id, tableId);
}

function errorMessage(error) {
  if (!error) return "Operação não concluída.";
  return text(error.message || error, "Operação não concluída.");
}

function canonicalOperation(action, payload) {
  if (action === ACTIONS.tableUpdate) {
    return { action, table_id: payload.id,
      values: { name: payload.name, schema: payload.schema } };
  }
  if (action === ACTIONS.tableDelete) return { action, table_id: payload.id };
  if (action === ACTIONS.columnCreate) {
    const { table_id, ...values } = payload;
    return { action, table_id, values };
  }
  if (action === ACTIONS.columnUpdate) {
    const { table_id, id, ...values } = payload;
    return { action, table_id, column_id: id, values };
  }
  if (action === ACTIONS.columnDelete) {
    return { action, table_id: payload.table_id, column_id: payload.id };
  }
  if (action === ACTIONS.indexCreate) {
    const { table_id, ...values } = payload;
    return { action, table_id, values };
  }
  if (action === ACTIONS.indexUpdate) {
    const { table_id, id, ...values } = payload;
    return { action, table_id, index_id: id, values };
  }
  if (action === ACTIONS.indexDelete) {
    return { action, table_id: payload.table_id, index_id: payload.id };
  }
  if (action === ACTIONS.relationshipCreate) return { action, values: payload };
  if (action === ACTIONS.relationshipUpdate) {
    const { id, ...values } = payload;
    return { action, relationship_id: id, values };
  }
  if (action === ACTIONS.relationshipDelete) {
    return { action, relationship_id: payload.id };
  }
  return { action, ...payload };
}

function labelFor(input, labelText) {
  const label = element("label", "schema-inspector__field");
  const caption = element("span", "schema-inspector__label", labelText);
  label.appendChild(caption);
  label.appendChild(input);
  return label;
}

function inputField(kind, value, id, placeholder) {
  const input = element("input", "schema-inspector__input");
  input.type = kind;
  input.id = id;
  input.value = value === null || value === undefined ? "" : String(value);
  if (placeholder) input.placeholder = placeholder;
  return input;
}

function checkbox(value, id) {
  const input = inputField("checkbox", "", id);
  input.checked = Boolean(value);
  return input;
}

function commandButton(label, action, className = "") {
  const button = element("button", `schema-inspector__button ${className}`.trim(), label);
  button.type = "button";
  button.dataset.inspectorAction = action;
  return button;
}

function submitButton(label) {
  const button = element("button", "schema-inspector__button schema-inspector__button--primary", label);
  button.type = "submit";
  return button;
}

function cancelButton(label = "Cancelar") {
  return commandButton(label, "cancel");
}

function selectField(id, options, selected, allowEmpty = false) {
  const select = element("select", "schema-inspector__select");
  select.id = id;
  if (allowEmpty) {
    const empty = element("option", "", "Selecione...");
    empty.value = "";
    select.appendChild(empty);
  }
  options.forEach((option) => {
    const node = element("option", "", option.label);
    node.value = text(option.value);
    node.selected = sameId(option.value, selected);
    select.appendChild(node);
  });
  if (!options.some((option) => sameId(option.value, selected)) && allowEmpty) {
    select.value = "";
  }
  return select;
}

function formActions(...buttons) {
  const actions = element("div", "schema-inspector__form-actions");
  return append(actions, ...buttons);
}

function emptyState(message, action) {
  const box = element("div", "schema-inspector__empty");
  append(box, element("p", "schema-inspector__empty-text", message));
  if (action) box.appendChild(action);
  return box;
}

function itemHeader(title, meta, onSelect, selected) {
  const button = element("button", `schema-inspector__item ${selected ? "is-selected" : ""}`.trim());
  button.type = "button";
  button.addEventListener("click", onSelect);
  append(button, element("strong", "schema-inspector__item-title", title));
  if (meta) button.appendChild(element("span", "schema-inspector__item-meta", meta));
  return button;
}

function moveButton(label, direction, disabled) {
  const button = commandButton(label, "move");
  button.dataset.direction = direction;
  button.title = direction === "up" ? "Mover para cima" : "Mover para baixo";
  button.disabled = disabled;
  return button;
}

function orderedColumnPicker({ id, table, selectedIds, multi = true }) {
  const wrapper = element("div", "schema-inspector__ordered-picker");
  const selected = new Set((selectedIds || []).map(String));
  const rows = new Map();

  (table?.columns || []).forEach((column) => {
    const row = element("div", "schema-inspector__column-choice");
    const input = checkbox(selected.has(String(column.id)), `${id}-${column.id}`);
    input.name = id;
    input.dataset.columnId = text(column.id);
    if (!multi) input.type = "radio";
    const caption = element("span", "schema-inspector__choice-text", `${column.name} · ${column.type}`);
    const controls = element("span", "schema-inspector__choice-controls");
    const up = moveButton("↑", "up", false);
    const down = moveButton("↓", "down", false);
    append(controls, up, down);
    append(row, input, caption, controls);
    rows.set(String(column.id), row);
    wrapper.appendChild(row);

    input.addEventListener("change", () => {
      if (!multi && input.checked) {
        wrapper.querySelectorAll(`input[name="${id}"]`).forEach((other) => {
          if (other !== input) other.checked = false;
        });
      }
      updateMoveButtons(wrapper, id);
    });
    up.addEventListener("click", () => moveChoice(wrapper, row, "up", id));
    down.addEventListener("click", () => moveChoice(wrapper, row, "down", id));
  });
  updateMoveButtons(wrapper, id);
  if (!table?.columns?.length) wrapper.appendChild(element("p", "schema-inspector__hint", "A tabela não possui colunas."));
  return wrapper;
}

function updateMoveButtons(wrapper, inputName) {
  const choices = Array.from(wrapper.querySelectorAll(`input[name="${inputName}"]`)).filter((input) => input.checked);
  const position = new Map(choices.map((input, index) => [input.closest(".schema-inspector__column-choice"), index]));
  wrapper.querySelectorAll(".schema-inspector__column-choice").forEach((row) => {
    const index = position.get(row);
    const buttons = row.querySelectorAll("button[data-inspector-action=move]");
    buttons[0].disabled = index === undefined || index === 0;
    buttons[1].disabled = index === undefined || index === choices.length - 1;
  });
}

function moveChoice(wrapper, row, direction, inputName) {
  const input = row.querySelector(`input[name="${inputName}"]`);
  if (!input || !input.checked) return;
  const siblings = Array.from(wrapper.querySelectorAll(".schema-inspector__column-choice"));
  const selectedRows = siblings.filter((item) => item.querySelector(`input[name="${inputName}"]`)?.checked);
  const index = selectedRows.indexOf(row);
  const targetIndex = direction === "up" ? index - 1 : index + 1;
  if (index < 0 || targetIndex < 0 || targetIndex >= selectedRows.length) return;
  const target = selectedRows[targetIndex];
  if (direction === "up") target.before(row);
  else target.after(row);
  updateMoveButtons(wrapper, inputName);
}

function selectedColumnIds(wrapper, inputName) {
  return Array.from(wrapper.querySelectorAll(`input[name="${inputName}"]`))
    .filter((input) => input.checked)
    .map((input) => input.dataset.columnId)
    .filter(Boolean);
}

function relationEndpointPicker({ id, project, selectedTableId, selectedColumnIds }) {
  const wrapper = element("div", "schema-inspector__endpoint-picker");
  const tables = (project?.tables || []).map((table) => ({ value: table.id, label: tableName(table) }));
  const tableSelect = selectField(`${id}-table`, tables, selectedTableId, true);
  const columnsHost = element("div", "schema-inspector__endpoint-columns");
  wrapper.appendChild(labelFor(tableSelect, "Tabela"));
  wrapper.appendChild(columnsHost);

  const renderColumns = () => {
    const table = tableById(project, tableSelect.value);
    columnsHost.replaceChildren();
    columnsHost.appendChild(element("span", "schema-inspector__label", "Colunas"));
    columnsHost.appendChild(orderedColumnPicker({
      id: `${id}-columns`,
      table,
      selectedIds: table && sameId(table.id, selectedTableId) ? selectedColumnIds : [],
    }));
  };
  tableSelect.addEventListener("change", renderColumns);
  renderColumns();
  wrapper.getValue = () => ({
    table_id: tableSelect.value,
    column_ids: selectedColumnIdsFromEndpoint(columnsHost, `${id}-columns`),
  });
  return wrapper;
}

function selectedColumnIdsFromEndpoint(host, inputName) {
  return selectedColumnIds(host.querySelector(".schema-inspector__ordered-picker"), inputName);
}

function mountSchemaInspector(options) {
  if (!options || !(options.parent instanceof HTMLElement)) {
    throw new TypeError("mountSchemaInspector requires a parent HTMLElement");
  }
  if (typeof options.getProject !== "function") {
    throw new TypeError("mountSchemaInspector requires getProject()");
  }
  if (typeof options.onMutate !== "function") {
    throw new TypeError("mountSchemaInspector requires onMutate()");
  }

  const parent = options.parent;
  const instance = `schema-inspector-${++inspectorSequence}`;
  const state = {
    project: null,
    phase: "loading",
    error: "",
    notice: "",
    processing: false,
    tab: "table",
    tableId: null,
    relationshipId: null,
    itemId: { columns: null, indexes: null },
    editing: { table: false, column: null, index: null, relationship: null },
  };

  const root = element("section", "schema-inspector");
  root.dataset.instance = instance;
  parent.replaceChildren(root);

  // Avisa quem hospeda o inspetor qual coluna esta em foco, para o diagrama
  // marcar a linha correspondente. So dispara quando a selecao muda de fato.
  let lastSelection = "";
  function announceSelection() {
    if (typeof options.onSelectColumn !== "function") return;
    const columnId = state.tab === "columns" && state.editing.column !== "new"
      ? state.editing.column || state.itemId.columns
      : null;
    const key = [state.tableId || "", columnId || ""].join("/");
    if (key === lastSelection) return;
    lastSelection = key;
    options.onSelectColumn(columnId ? { tableId: state.tableId, columnId } : null);
  }

  function currentTable() {
    return tableById(state.project, state.tableId);
  }

  function setNotice(message, isError = false) {
    state.notice = message;
    state.error = isError ? message : "";
    const status = root.querySelector("[data-inspector-status]");
    if (status) {
      status.textContent = message;
      status.classList.toggle("is-error", isError);
      status.classList.toggle("is-success", !isError && Boolean(message));
    }
  }

  function renderStatus() {
    const status = element("p", "schema-inspector__status");
    status.dataset.inspectorStatus = "true";
    status.setAttribute("aria-live", "polite");
    status.textContent = state.error || state.notice || (state.processing ? "Processando..." : "");
    if (state.error) status.classList.add("is-error");
    return status;
  }

  function renderHeader() {
    const header = element("header", "schema-inspector__header");
    const heading = element("div", "schema-inspector__heading");
    append(heading, element("h2", "schema-inspector__title", "Inspetor"), renderStatus());
    const tableOptions = (state.project?.tables || []).map((table) => ({ value: table.id, label: tableName(table) }));
    const tableSelect = selectField(`${instance}-table`, tableOptions, state.tableId, true);
    tableSelect.setAttribute("aria-label", "Tabela selecionada");
    tableSelect.addEventListener("change", () => selectTable(tableSelect.value));
    const picker = element("div", "schema-inspector__selection");
    append(picker, element("span", "schema-inspector__selection-label", "Seleção"), tableSelect);
    append(header, heading, picker);
    return header;
  }

  function renderTabs() {
    const nav = element("nav", "schema-inspector__tabs");
    nav.setAttribute("aria-label", "Seções do inspetor");
    Object.entries(TAB_LABELS).forEach(([key, label]) => {
      const button = commandButton(label, "tab", state.tab === key ? "is-active" : "");
      button.dataset.tab = key;
      button.setAttribute("aria-pressed", state.tab === key ? "true" : "false");
      button.addEventListener("click", () => {
        state.tab = key;
        state.notice = "";
        render();
      });
      nav.appendChild(button);
    });
    return nav;
  }

  function renderTableTab(table) {
    if (!table) return emptyState("Selecione uma tabela para inspecionar.");
    const form = element("form", "schema-inspector__form");
    const name = inputField("text", table.name, `${instance}-table-name`);
    const schema = inputField("text", table.schema, `${instance}-table-schema`, "opcional");
    append(form,
      labelFor(name, "Nome"),
      labelFor(schema, "Schema"),
      formActions(
        submitButton("Salvar tabela"),
        commandButton("Excluir tabela", "delete-table", "schema-inspector__button--danger"),
      ));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      mutate(ACTIONS.tableUpdate, { id: table.id, name: name.value.trim(), schema: schema.value.trim() || null }, "Tabela atualizada.");
    });
    form.querySelector("[data-inspector-action=delete-table]").addEventListener("click", () => {
      if (window.confirm(DELETE_CONFIRMATIONS.table)) mutate(ACTIONS.tableDelete, { id: table.id }, "Tabela excluída.");
    });
    return append(element("div", "schema-inspector__panel"), element("h3", "schema-inspector__panel-title", "Dados da tabela"), form);
  }

  function renderColumnForm(table, column) {
    const creating = !column;
    const form = element("form", "schema-inspector__form schema-inspector__form--card");
    const name = inputField("text", column?.name, `${instance}-column-name`);
    const type = typeField({ id: `${instance}-column-type`, value: column?.type,
      dialect: state.project?.dialect });
    const nullable = checkbox(column?.nullable ?? true, `${instance}-column-nullable`);
    const primary = checkbox(column?.primary_key, `${instance}-column-primary`);
    const unique = checkbox(column?.unique, `${instance}-column-unique`);
    const defaultValue = inputField("text", column?.default, `${instance}-column-default`, "NULL");
    append(form,
      labelFor(name, "Nome"), type.node,
      labelFor(nullable, "Aceita nulo"), labelFor(primary, "Chave primária"),
      labelFor(unique, "Única"), labelFor(defaultValue, "Valor padrão"),
      formActions(submitButton(creating ? "Criar coluna" : "Salvar coluna"), cancelButton()),
    );
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const payload = {
        table_id: table.id,
        ...(creating ? {} : { id: column.id }),
        name: name.value.trim(),
        type: type.read(),
        nullable: nullable.checked,
        primary_key: primary.checked,
        unique: unique.checked,
        default: defaultValue.value.trim() || null,
      };
      mutate(creating ? ACTIONS.columnCreate : ACTIONS.columnUpdate, payload, creating ? "Coluna criada." : "Coluna atualizada.");
    });
    form.querySelector("[data-inspector-action=cancel]").addEventListener("click", () => {
      state.editing.column = null;
      render();
    });
    return form;
  }

  function renderColumnsTab(table) {
    if (!table) return emptyState("Selecione uma tabela para ver as colunas.");
    const panel = element("div", "schema-inspector__panel");
    const toolbar = element("div", "schema-inspector__panel-toolbar");
    append(toolbar, element("h3", "schema-inspector__panel-title", `${table.columns.length} coluna${table.columns.length === 1 ? "" : "s"}`),
      commandButton("Nova coluna", "new-column", "schema-inspector__button--primary"));
    panel.appendChild(toolbar);
    const list = element("div", "schema-inspector__list");
    table.columns.forEach((column) => {
      const row = element("article", "schema-inspector__list-row");
      const header = itemHeader(column.name, `${column.type}${column.primary_key ? " · PK" : ""}${column.nullable ? "" : " · NOT NULL"}`, () => {
        state.itemId.columns = column.id;
        state.editing.column = column.id;
        render();
      }, sameId(state.itemId.columns, column.id));
      const controls = element("div", "schema-inspector__row-actions");
      const edit = commandButton("Editar", "edit-column");
      const remove = commandButton("Excluir", "delete-column", "schema-inspector__button--danger");
      append(controls, edit, remove);
      append(row, header, controls);
      edit.addEventListener("click", () => {
        state.itemId.columns = column.id;
        state.editing.column = column.id;
        render();
      });
      remove.addEventListener("click", () => {
        if (window.confirm(DELETE_CONFIRMATIONS.column)) mutate(ACTIONS.columnDelete, { table_id: table.id, id: column.id }, "Coluna excluída.");
      });
      list.appendChild(row);
      if (sameId(state.editing.column, column.id)) list.appendChild(renderColumnForm(table, column));
    });
    if (!table.columns.length) list.appendChild(emptyState("Esta tabela ainda não possui colunas."));
    panel.appendChild(list);
    if (state.editing.column === "new") panel.appendChild(renderColumnForm(table, null));
    return panel;
  }

  function renderIndexForm(table, index) {
    const creating = !index;
    const form = element("form", "schema-inspector__form schema-inspector__form--card");
    const name = inputField("text", index?.name, `${instance}-index-name`, "opcional");
    const unique = checkbox(index?.unique, `${instance}-index-unique`);
    const picker = orderedColumnPicker({ id: `${instance}-index-columns`, table, selectedIds: index?.columns || [] });
    append(form, labelFor(name, "Nome"), labelFor(unique, "Único"),
      element("span", "schema-inspector__label", "Colunas na ordem do índice"), picker);
    if (index?.primary_key) {
      form.appendChild(element("p", "schema-inspector__hint", "Índice da chave primária. A chave é somente leitura e não pode ser excluída."));
      name.disabled = true;
      unique.disabled = true;
      picker.querySelectorAll("input, button").forEach((control) => { control.disabled = true; });
    }
    const actions = index?.primary_key
      ? [cancelButton("Fechar")]
      : [submitButton(creating ? "Criar índice" : "Salvar índice"), cancelButton()];
    append(form, formActions(...actions));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (index?.primary_key) return;
      const payload = { table_id: table.id, ...(creating ? {} : { id: index.id }), name: name.value.trim() || null, unique: unique.checked, columns: selectedColumnIds(picker, `${instance}-index-columns`) };
      mutate(creating ? ACTIONS.indexCreate : ACTIONS.indexUpdate, payload, creating ? "Índice criado." : "Índice atualizado.");
    });
    form.querySelector("[data-inspector-action=cancel]").addEventListener("click", () => {
      state.editing.index = null;
      render();
    });
    return form;
  }

  function renderIndexesTab(table) {
    if (!table) return emptyState("Selecione uma tabela para ver os índices.");
    const panel = element("div", "schema-inspector__panel");
    const toolbar = element("div", "schema-inspector__panel-toolbar");
    append(toolbar, element("h3", "schema-inspector__panel-title", `${table.indexes.length} índice${table.indexes.length === 1 ? "" : "s"}`),
      commandButton("Novo índice", "new-index", "schema-inspector__button--primary"));
    panel.appendChild(toolbar);
    const list = element("div", "schema-inspector__list");
    table.indexes.forEach((index) => {
      const row = element("article", "schema-inspector__list-row");
      const names = index.columns.map((id) => columnById(table, id)?.name || id).join(", ");
      const title = index.name || (index.primary_key ? "Chave primária" : "Índice sem nome");
      const meta = `${index.unique ? "UNIQUE · " : ""}${names}`;
      const header = itemHeader(title, meta, () => {
        state.itemId.indexes = index.id;
        state.editing.index = index.id;
        render();
      }, sameId(state.itemId.indexes, index.id));
      const controls = element("div", "schema-inspector__row-actions");
      const edit = commandButton("Editar", "edit-index");
      append(controls, edit);
      if (!index.primary_key) controls.appendChild(commandButton("Excluir", "delete-index", "schema-inspector__button--danger"));
      append(row, header, controls);
      edit.addEventListener("click", () => {
        state.itemId.indexes = index.id;
        state.editing.index = index.id;
        render();
      });
      const remove = controls.querySelector("[data-inspector-action=delete-index]");
      if (remove) remove.addEventListener("click", () => {
        if (window.confirm(DELETE_CONFIRMATIONS.index)) mutate(ACTIONS.indexDelete, { table_id: table.id, id: index.id }, "Índice excluído.");
      });
      list.appendChild(row);
      if (sameId(state.editing.index, index.id)) list.appendChild(renderIndexForm(table, index));
    });
    if (!table.indexes.length) list.appendChild(emptyState("Esta tabela ainda não possui índices."));
    panel.appendChild(list);
    if (state.editing.index === "new") panel.appendChild(renderIndexForm(table, null));
    return panel;
  }

  function renderRelationshipForm(relation) {
    const creating = !relation;
    const project = state.project;
    const from = relation?.from || { table_id: state.tableId, column_ids: [] };
    const to = relation?.to || { table_id: null, column_ids: [] };
    const form = element("form", "schema-inspector__form schema-inspector__form--card");
    const name = inputField("text", relation?.name, `${instance}-relationship-name`, "opcional");
    const fromPicker = relationEndpointPicker({ id: `${instance}-from`, project, selectedTableId: from.table_id, selectedColumnIds: from.column_ids });
    const toPicker = relationEndpointPicker({ id: `${instance}-to`, project, selectedTableId: to.table_id, selectedColumnIds: to.column_ids });
    const actions = ["NO ACTION", "CASCADE", "RESTRICT", "SET NULL", "SET DEFAULT"].map((value) => ({ value, label: value }));
    const onDelete = selectField(`${instance}-on-delete`, actions, relation?.on_delete || "NO ACTION");
    const onUpdate = selectField(`${instance}-on-update`, actions, relation?.on_update || "NO ACTION");
    append(form, labelFor(name, "Nome"), element("h4", "schema-inspector__subheading", "Origem"), fromPicker,
      element("h4", "schema-inspector__subheading", "Destino"), toPicker,
      labelFor(onDelete, "Ao excluir"), labelFor(onUpdate, "Ao atualizar"),
      formActions(submitButton(creating ? "Criar relação" : "Salvar relação"), cancelButton()));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const fromValue = fromPicker.getValue();
      const toValue = toPicker.getValue();
      const payload = {
        ...(creating ? {} : { id: relation.id }),
        name: name.value.trim() || null,
        from: fromValue,
        to: toValue,
        on_delete: onDelete.value,
        on_update: onUpdate.value,
      };
      mutate(creating ? ACTIONS.relationshipCreate : ACTIONS.relationshipUpdate, payload, creating ? "Relação criada." : "Relação atualizada.");
    });
    form.querySelector("[data-inspector-action=cancel]").addEventListener("click", () => {
      state.editing.relationship = null;
      render();
    });
    return form;
  }

  function renderRelationshipsTab(table) {
    if (!table) return emptyState("Selecione uma tabela para ver as relações.");
    const relations = (state.project?.relationships || []).filter((relation) => relationTouchesTable(relation, table.id));
    const panel = element("div", "schema-inspector__panel");
    const toolbar = element("div", "schema-inspector__panel-toolbar");
    append(toolbar, element("h3", "schema-inspector__panel-title", `${relations.length} ${relations.length === 1 ? "relação" : "relações"}`),
      commandButton("Nova relação", "new-relationship", "schema-inspector__button--primary"));
    panel.appendChild(toolbar);
    const list = element("div", "schema-inspector__list");
    relations.forEach((relation) => {
      const fromTable = tableById(state.project, relation.from.table_id);
      const toTable = tableById(state.project, relation.to.table_id);
      const fromColumns = relation.from.column_ids.map((id) => columnById(fromTable, id)?.name || id).join(", ");
      const toColumns = relation.to.column_ids.map((id) => columnById(toTable, id)?.name || id).join(", ");
      const row = element("article", "schema-inspector__list-row");
      const header = itemHeader(relation.name || "Relação sem nome", `${tableName(fromTable)}.${fromColumns} → ${tableName(toTable)}.${toColumns}`, () => selectRelationship(relation.id), sameId(state.relationshipId, relation.id));
      const controls = element("div", "schema-inspector__row-actions");
      const edit = commandButton("Editar", "edit-relationship");
      const remove = commandButton("Excluir", "delete-relationship", "schema-inspector__button--danger");
      append(controls, edit, remove);
      row.appendChild(header);
      row.appendChild(controls);
      edit.addEventListener("click", () => {
        state.relationshipId = relation.id;
        state.editing.relationship = relation.id;
        render();
      });
      remove.addEventListener("click", () => {
        if (window.confirm(DELETE_CONFIRMATIONS.relationship)) mutate(ACTIONS.relationshipDelete, { id: relation.id }, "Relação excluída.");
      });
      list.appendChild(row);
      if (sameId(state.editing.relationship, relation.id)) list.appendChild(renderRelationshipForm(relation));
    });
    if (!relations.length) list.appendChild(emptyState("Esta tabela ainda não possui relações."));
    panel.appendChild(list);
    if (state.editing.relationship === "new") panel.appendChild(renderRelationshipForm(null));
    return panel;
  }

  function renderContent() {
    if (state.phase === "loading") return emptyState("Carregando projeto...");
    if (state.phase === "error") return emptyState(state.error || "Não foi possível carregar o projeto.", commandButton("Tentar novamente", "refresh"));
    if (!state.project) return emptyState("Nenhum projeto carregado.");
    const table = currentTable();
    if (state.tab === "table") return renderTableTab(table);
    if (state.tab === "columns") return renderColumnsTab(table);
    if (state.tab === "indexes") return renderIndexesTab(table);
    return renderRelationshipsTab(table);
  }

  function render() {
    root.replaceChildren(renderHeader(), renderTabs(), renderContent());
    root.classList.toggle("is-processing", state.processing);
    root.setAttribute("aria-busy", state.processing ? "true" : "false");
    root.querySelectorAll("button, input, select").forEach((control) => {
      if (state.processing) control.disabled = true;
    });
    const refresh = root.querySelector("[data-inspector-action=refresh]");
    if (refresh) refresh.addEventListener("click", refreshProject);
    const newColumn = root.querySelector("[data-inspector-action=new-column]");
    if (newColumn) newColumn.addEventListener("click", () => { state.editing.column = "new"; render(); });
    const newIndex = root.querySelector("[data-inspector-action=new-index]");
    if (newIndex) newIndex.addEventListener("click", () => { state.editing.index = "new"; render(); });
    const newRelationship = root.querySelector("[data-inspector-action=new-relationship]");
    if (newRelationship) newRelationship.addEventListener("click", () => { state.editing.relationship = "new"; render(); });
    announceSelection();
  }

  async function mutate(action, payload, successMessage) {
    state.processing = true;
    state.error = "";
    state.notice = "Processando...";
    render();
    try {
      const response = await options.onMutate(canonicalOperation(action, payload));
      state.processing = false;
      state.notice = response?.message || successMessage;
      state.error = "";
      render();
      return response;
    } catch (error) {
      state.processing = false;
      state.error = errorMessage(error);
      state.notice = "";
      render();
      return null;
    }
  }

  async function refreshProject() {
    state.phase = "loading";
    state.error = "";
    // o diagrama pode ter sido redesenhado por fora: força reemitir a seleção
    // para a linha da coluna voltar a ficar marcada nos nós novos
    lastSelection = "";
    render();
    try {
      const project = await options.getProject();
      state.project = project || null;
      state.phase = "ready";
      if (!tableById(state.project, state.tableId)) {
        state.tableId = state.project?.tables?.[0]?.id || null;
      }
      if (!relationById(state.project, state.relationshipId)) state.relationshipId = null;
      if (state.relationshipId) {
        const relation = relationById(state.project, state.relationshipId);
        if (relation) state.tableId = relation.from.table_id;
      }
      const refreshedTable = currentTable();
      if (!columnById(refreshedTable, state.itemId.columns)) state.itemId.columns = null;
      if (!(refreshedTable?.indexes || []).some((index) => sameId(index.id, state.itemId.indexes))) {
        state.itemId.indexes = null;
      }
      if (state.editing.column !== "new" && !columnById(refreshedTable, state.editing.column)) {
        state.editing.column = null;
      }
      if (state.editing.index !== "new" && !(refreshedTable?.indexes || []).some((index) => sameId(index.id, state.editing.index))) {
        state.editing.index = null;
      }
      if (state.editing.relationship !== "new" && !relationById(state.project, state.editing.relationship)) {
        state.editing.relationship = null;
      }
      if (!state.project) state.phase = "empty";
      render();
      return state.project;
    } catch (error) {
      state.project = null;
      state.phase = "error";
      state.error = errorMessage(error);
      render();
      return null;
    }
  }

  function selectTable(id) {
    if (!state.project || !tableById(state.project, id)) return false;
    state.tableId = id;
    state.relationshipId = null;
    state.tab = "table";
    state.notice = "";
    state.error = "";
    Object.assign(state.editing, { table: false, column: null, index: null, relationship: null });
    render();
    return true;
  }

  function selectRelationship(id) {
    const relation = relationById(state.project, id);
    if (!relation) return false;
    state.relationshipId = id;
    state.tableId = relation.from.table_id;
    state.tab = "relationships";
    state.notice = "";
    state.error = "";
    state.editing.relationship = id;
    render();
    return true;
  }

  function selectColumn(tableId, columnId) {
    const table = tableById(state.project, tableId);
    if (!table || !columnById(table, columnId)) return false;
    state.tableId = tableId;
    state.relationshipId = null;
    state.tab = "columns";
    state.itemId.columns = columnId;
    state.editing.column = columnId;
    state.notice = "";
    state.error = "";
    render();
    return true;
  }

  function clear() {
    lastSelection = "";
    if (typeof options.onSelectColumn === "function") options.onSelectColumn(null);
    state.project = null;
    state.phase = "empty";
    state.tableId = null;
    state.relationshipId = null;
    state.notice = "";
    state.error = "";
    state.editing = { table: false, column: null, index: null, relationship: null };
    render();
  }

  render();
  refreshProject();
  return { selectTable, selectColumn, selectRelationship, clear, refresh: refreshProject };
}

export { mountSchemaInspector };
