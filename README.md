# AP Library Manager

A local, portable library organiser for PDF collections, built with Python and PySide6 (Qt 6).

It is **not** a PDF reader and does not parse PDF content. It decides *where* your PDFs live
in a structure you define, and hands each file to the PDF reader you already use.

---

## Concept: a tree that is really a graph

On disk a file lives in exactly one folder. Real collections do not work that way: the same
author can belong to two shelves, and one volume can be filed under "Marxism" and "Political
Economy" at the same time without duplicating the file.

AP Library Manager stores the library as a small directed acyclic graph — `nodes` and `edges`
in SQLite — instead of a folder tree. A node may have **several parents**. The tree view
renders it once per path and shows a `×N` badge with the number of positions:

```text
Library
├── Political Economy
│   ├── Marxism
│   │   ├── Marx            ×2
│   │   └── Engels
│   └── Capital
└── Western Philosophers
    └── Marx                ×2
```

There is still only one "Marx" row in the database; only its positions are multiplied.

---

## Features

**Structure**
- Multi-parent hierarchy with cycle prevention at three layers (dialog, drag-over, write).
- Attach a node to another parent, move it between parents, or reorder siblings by drag & drop.
- "View all positions" lists every root-to-node path and jumps to the exact instance.

**Appearance**
- Per-node icon: a built-in emoji or a custom PNG/ICO/SVG copied into `icons/`.
- Per-node bold text and text colour, rendered by a custom item delegate.
- `×N` badge for shared nodes; red `!` marker for nodes with missing PDF files.

**PDF handling**
- Attach several PDFs to one node, de-duplicated case-insensitively on Windows.
- Open one PDF, the selected ones, or every PDF of a node.
- Use the system default reader or configure an executable and extra arguments.
- Missing files are only reported, never removed from the library.
- Whole-library file check, plus batch re-location that scans a folder for same-named PDFs
  (ambiguous names are skipped rather than guessed).

**Search**
- Searches node names and stored PDF paths, with space-separated **AND** terms.
- Debounced live results in a dock; each hit lists all of its positions.
- Clicking a position expands the tree and selects that exact instance.

**Import / export**
- Whole library as a portable `library.json` (flat `nodes` + `edges`, external ids `n1…nN`).
- Optional copying of PDFs into the export's `books/` and of custom icons into `icons/`.
- Import either **merges** into the current library or **replaces** it, in one transaction.

**Quality of life**
- Remembers window geometry, maximised state, expanded branches and search-dock visibility.
- Rotating log file with full tracebacks (`logging.level` configurable).

---

## Requirements

- **Python 3.10+** (developed and tested on 3.11.15)
- **PySide6 ≥ 6.5** (tested with 6.11.1)
- Windows is the primary target; the PDF launcher also has macOS (`open`) and Linux (`xdg-open`)
  fallbacks.

---

## Installation

```bash
git clone <repository-url>
cd ap_manager
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

`requirements.txt` contains the runtime dependency (`PySide6`), the test runner (`pytest`) and
the packaging tool (`pyinstaller`).

---

## Running

```bash
python main.py
```

On first start the application creates `data/library.db` (SQLite) automatically and reads
`config.json` from the project root. Nothing else needs to be set up.

---

## Configuration

`config.json` lives next to `main.py` and is written atomically; an unreadable file is backed up
to `config.json.bak` before being replaced.

| Key | Default | Meaning |
|---|---|---|
| `pdf_reader.path` | `""` | Reader executable. Empty = system default. Must exist when set. |
| `pdf_reader.args` | `""` | Extra arguments, as a shell-like string or a JSON list. The file path is always appended last. |
| `library.database_path` | `"data/library.db"` | SQLite database, relative to the application root. |
| `ui.window_width` / `window_height` | `1200` / `800` | Restored window size. |
| `ui.window_x` / `window_y` | `null` | Window position; `null` means "let the window manager decide". |
| `ui.window_maximized` | `false` | Whether the window was maximised on exit. |
| `ui.expanded_paths` | `[]` | Expanded branches, stored as `[[1], [1, 2], …]` display paths. |
| `ui.search_panel_visible` | `false` | Search dock visibility. |
| `logging.level` | `"INFO"` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`. |

---

## Data layout and portability

```text
ap_manager/
├── main.py
├── config.json
├── data/library.db      # SQLite database (created on first run)
├── books/               # optional: PDFs copied into the library
├── icons/               # custom node icons
└── logs/                # rotating log file
```

**Path policy.** PDFs inside the application root are stored as relative POSIX paths
(`books/a.pdf`), so moving the whole folder keeps them resolvable. PDFs outside the root are
stored as absolute paths — those entries stop being portable, which is the price of not copying
the user's file. "Copy to `books/`" copies first and always stores a relative path; identical
files are reused instead of duplicated (content-hash suffix).

`data/library.db`, `logs/`, `books/` and `icons/` are runtime artifacts and are ignored by git.

---

## Import / export format

Export writes `library.json`:

```json
{
    "format": "ap_manager_library",
    "version": "0.1",
    "nodes": [
        {
            "id": "n1",
            "name": "Marxism",
            "pdfs": ["./books/capital-1.pdf"],
            "icon": "icons/marx_1a2b3c4d.png",
            "style": { "bold": true, "color": "#8b1a1a" },
            "metadata": {}
        }
    ],
    "edges": [
        { "parent": "n1", "child": "n2", "sort_order": 0 }
    ]
}
```

- `nodes`/`edges` are **flat**: nesting cannot represent multi-parent positions, `sort_order`
  or cycles.
- `id` values are file-local (`n1…nN`). On import they are mapped to freshly generated database
  ids, so a file can be imported into any library.
- `format` and `version` are validated before anything is written; unknown versions are
  rejected instead of being imported with silently missing fields.
- The whole import (including the `replace` clear-out) runs in a single transaction, so a
  failure leaves the previous library untouched.
- Unknown keys are ignored, so future versions can add fields without breaking this importer.

---

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+N` | New root node |
| `Ctrl+Shift+N` | New child node |
| `F2` | Edit node properties |
| `Ctrl+Shift+A` / `Ctrl+Shift+M` | Attach to another position / move to another position |
| `Ctrl+Shift+L` | View all positions |
| `Ctrl+Shift+D` | Remove the current position (the node stays visible elsewhere) |
| `Ctrl+Delete` | Delete the node completely — all positions; PDFs stay on disk |
| `Ctrl+Shift+P` / `Ctrl+O` | Manage PDFs / open PDF |
| `Ctrl+F` / `Ctrl+Shift+F` | Focus the search box / open the search dialog |
| `Ctrl+I` / `Ctrl+E` | Import / export library |
| `F5` | Refresh the tree |
| `Esc` | Clear the search box |
| `Ctrl+Q` / `Alt+F4` | Quit |

---

## Project structure

```text
main.py                  # entry point: logging, QApplication, main window
models/
├── database.py          # SQLite connection, schema, CRUD, transactions, graph algorithms
├── node.py              # Node dataclass + icon/colour normalisation
├── edge.py              # Edge dataclass
└── library.py           # LibraryService: business rules (cycle checks, attach/move/reorder, PDFs)
controllers/
└── app_controller.py    # View -> Controller -> Library -> Database boundary
services/
├── path_manager.py      # portable path storage/resolution, books/ copying
├── pdf_launcher.py      # configured reader or platform default, batch launch
├── exporter.py          # whole-library export
├── importer.py          # whole-library import with id mapping
├── relocator.py         # batch re-location planning for missing PDFs
└── search.py            # search model and match classification
views/
├── main_window.py       # menus, actions, docks, persistence
├── tree_model.py        # QAbstractItemModel projecting the graph
├── library_tree_view.py # drag & drop, drop indicator, MIME handling
├── search_panel.py      # result list with positions
├── delegates/           # custom painting (badges, icons, colours)
└── dialogs/             # node, PDF, search, settings, import/export dialogs
utils/
├── constants.py         # every path, key, colour and limit in one place
├── config_manager.py    # atomic config.json reads/writes
├── settings_manager.py  # window geometry and expanded-branch persistence
├── json_utils.py        # exchange-format validation
├── icon_utils.py        # emoji rendering, custom icon import (content-addressed)
├── error_messages.py    # exceptions -> user-facing messages
└── logger.py            # rotating file + console logging
tests/                   # pytest suite, GUI tests run headless (offscreen)
```

---

## Tests

```bash
python -m pytest
```

The suite covers the data layer, graph rules, path handling, import/export round trips,
search, re-location planning, logging and the Qt views. GUI tests run with
`QT_QPA_PLATFORM=offscreen`, so they work in a plain terminal.

Current status: **437 tests passing**.

---

## Documentation

Design and per-phase records live in `_mds/`:

| File | Contents |
|---|---|
| `_mds/plan.md` | Full design document (data model, UI, import/export, error handling). |
| `_mds/stage.md` | Phase-by-phase breakdown with files, functions and acceptance criteria. |
| `_mds/g1.md` | Code review of the Phase 1 data layer and the resulting fixes. |
| `_mds/phase*_completion.md` | Delivery record, design decisions and known limits per phase. |
| `_mds/phase3_feasibility.md` | Feasibility study that fed into Phase 3. |

---

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | SQLite schema, CRUD, cycle detection | ✅ |
| 2 | `QTreeView` projection of the graph | ✅ |
| 3 | Node editing, icons, colours, delegates | ✅ |
| 4 | PDF management, reader configuration, missing files | ✅ |
| 5 | Multi-parent interactions, drag & drop, reordering | ✅ |
| 6 | JSON import / export | ✅ |
| 7 | Search, state persistence, batch re-location, logging | ✅ |
| 8 | FDF / annotation extension (optional) | ⬜ not started |

---

## Known limitations

- **UI language:** all user-facing strings are Simplified Chinese; there is no i18n layer yet.
- **Top-level ordering:** roots are ordered by database id; only children of a node can be
  reordered by dragging (`sort_order` lives on `edges`, and a root has no incoming edge).
- **Merge import:** importing the same file twice appends a second copy of the nodes rather
  than merging by name. Use "replace" for a clean result.
- **Search** is a case-insensitive SQLite `LIKE` substring match over names and PDF paths —
  no fuzzy matching, no tags, no PDF full-text search. Results are capped (100 by default,
  500 maximum).
- **Batch re-location** matches by file name only and does not compare content hashes;
  ambiguous names are skipped and must be fixed individually.
- **Export** does not include `created_time` / `updated_time`; re-imported nodes get the import
  timestamp. Re-exporting into the same folder does not clean up previously copied files that
  are no longer referenced.
- **Drag & drop** does not auto-scroll near view edges, and multi-selection supports
  "attach" only (one instance at a time for "move").
- **Packaging:** PyInstaller is installed and declared, but no build configuration or spec file
  is committed yet.
