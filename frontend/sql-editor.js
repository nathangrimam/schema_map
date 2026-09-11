import { autocompletion } from "@codemirror/autocomplete";
import { basicSetup } from "codemirror";
import { PostgreSQL, MySQL, sql } from "@codemirror/lang-sql";
import { Compartment, EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";

export { mountSchemaInspector } from "./inspector.js";

const DEFAULT_VALUE = "";
const DEFAULT_DIALECT = "postgres";

const editorTheme = EditorView.theme({
  "&": {
    height: "100%",
    color: "#d8dee9",
    backgroundColor: "#0e1116",
    fontSize: "13px",
  },
  ".cm-scroller": {
    overflow: "auto",
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    lineHeight: "1.55",
  },
  ".cm-content": {
    minHeight: "100%",
    padding: "14px 0",
    caretColor: "#5aa9e6",
  },
  ".cm-line": {
    padding: "0 16px",
  },
  ".cm-gutters": {
    border: "0",
    borderRight: "1px solid #29313c",
    color: "#7d8794",
    backgroundColor: "#161a21",
  },
  ".cm-activeLine": {
    backgroundColor: "#161a21",
  },
  ".cm-activeLineGutter": {
    color: "#d8dee9",
    backgroundColor: "#1b212a",
  },
  ".cm-selectionBackground, ::selection": {
    backgroundColor: "#28465e !important",
  },
  ".cm-tooltip": {
    color: "#d8dee9",
    backgroundColor: "#1b212a",
    border: "1px solid #39424f",
    boxShadow: "0 8px 20px rgba(0, 0, 0, 0.35)",
  },
}, { dark: true });

function normalizeDialect(dialect) {
  return String(dialect || DEFAULT_DIALECT).toLowerCase() === "mysql"
    ? "mysql"
    : "postgres";
}

function dialectExtension(dialect) {
  return sql({ dialect: normalizeDialect(dialect) === "mysql" ? MySQL : PostgreSQL });
}

/**
 * Mount a framework-free CodeMirror SQL editor into a DOM element.
 * @param {{parent: HTMLElement, value?: string, dialect?: string, onChange?: (value: string) => void}} options
 * @returns {{getValue: () => string, setValue: (value: string) => void, setDialect: (dialect: string) => void, focus: () => void, destroy: () => void}}
 */
export function mountSqlEditor(options) {
  if (!options || !(options.parent instanceof HTMLElement)) {
    throw new TypeError("mountSqlEditor requires a parent HTMLElement");
  }

  const parent = options.parent;
  const onChange = typeof options.onChange === "function" ? options.onChange : () => {};
  const dialect = new Compartment();
  let currentDialect = normalizeDialect(options.dialect);
  let suppressChanges = false;

  const state = EditorState.create({
    doc: String(options.value ?? DEFAULT_VALUE),
    extensions: [
      basicSetup,
      dialect.of(dialectExtension(currentDialect)),
      autocompletion(),
      editorTheme,
      EditorView.updateListener.of((update) => {
        if (update.docChanged && !suppressChanges) {
          onChange(update.state.doc.toString());
        }
      }),
    ],
  });

  const view = new EditorView({ state, parent });
  view.contentDOM.setAttribute("aria-label", parent.getAttribute("aria-label") || "Editor SQL");

  return {
    getValue() {
      return view.state.doc.toString();
    },

    setValue(value) {
      const nextValue = String(value ?? DEFAULT_VALUE);
      if (nextValue === view.state.doc.toString()) return;
      suppressChanges = true;
      try {
        view.dispatch({
          changes: { from: 0, to: view.state.doc.length, insert: nextValue },
        });
      } finally {
        suppressChanges = false;
      }
    },

    setDialect(nextDialect) {
      const normalized = normalizeDialect(nextDialect);
      if (normalized === currentDialect) return;
      currentDialect = normalized;
      view.dispatch({
        effects: dialect.reconfigure(dialectExtension(currentDialect)),
      });
    },

    focus() {
      view.focus();
    },

    destroy() {
      view.destroy();
    },
  };
}
