# PRAT Web UI (`prat.web`)

This subpackage contains the **web UI for PRAT reports**: a single, self-contained,
interactive HTML document produced for every analyzed feature. It is what a user opens
after running PRAT to explore which source lines a feature contributes and how that
removable code is distributed across files.

The UI is rendered by [`prat.reporting.generate_html_report()`](../reporting.py) from the
template asset in this directory.

```
src/prat/web/
├── __init__.py            # loader helpers (load_report_template / report_template_path)
├── report_template.html   # the entire UI: HTML + CSS + JS, no external dependencies
└── README.md              # this file
```

## Design goals

- **Self-contained & offline.** No CDNs, web fonts, or external scripts. A report is a
  single `.html` file you can email, archive, or open on an air-gapped machine. The test
  suite enforces this (`test_html_self_contained`).
- **Zero build step.** Plain HTML/CSS/vanilla JS. No bundler, framework, or `npm`.
- **Project-agnostic.** Nothing about a specific target project is hard-coded; all data
  arrives through placeholders at generation time.

## Features

| Area | Capability |
|------|------------|
| Summary cards | Total removable lines, files affected, average/file, largest single-file slice |
| Impact graph | SVG "ranked impact flow" of the top 8 files; click a band/bar to inspect a file |
| Results table | Sortable (file / lines / span) with sticky header, impact bars, and % of total |
| Filtering | Live name filter with a clear (`×`) button and a "showing X of Y" counter |
| Inline drawer | Per-file source preview with lightweight C/C++ syntax highlighting |
| Dark mode | Light/dark toggle, persisted in `localStorage`, defaults to `prefers-color-scheme` |
| Exports | Download the (filtered) table as **CSV**, the full report as **JSON**, or copy the file list |
| Copy actions | Copy the selected file's path or its source lines to the clipboard |
| Keyboard nav | Full keyboard operation (see shortcuts below) with visible focus rings |
| Accessibility | `aria-sort` on sortable headers, `scope="col"`, focusable rows, live regions, roles |
| Print | A dedicated `@media print` stylesheet that expands content and hides controls |

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `/` | Focus the filter input |
| `↑` / `↓` or `k` / `j` | Move selection between visible files |
| `Enter` | Open / close the focused or selected file |
| `t` | Toggle light/dark theme |
| `Esc` | Close help → clear filter → close drawer (in that order) |
| `?` | Show / hide the shortcuts popover |

## How it's generated

`generate_html_report()` loads `report_template.html`, then replaces a small set of
**`__PRAT_*__` placeholders** with escaped values and JSON blobs:

| Placeholder | Type | Meaning |
|-------------|------|---------|
| `__PRAT_FEATURE__` | HTML-escaped text | Feature name (used in `<title>`, hero, cards) |
| `__PRAT_FILE_COUNT__` | int | Number of affected files |
| `__PRAT_TOTAL_LINES__` | int | Total removable lines |
| `__PRAT_AVG_LINES__` | int | Average removable lines per file |
| `__PRAT_MAX_LINES__` | int | Largest single-file removable count |
| `__PRAT_LARGEST_FILE__` | HTML-escaped text | Name of the most-impacted file |
| `__PRAT_GENERATED_AT__` | text | UTC generation timestamp (footer) |
| `__PRAT_FEATURE_JSON__` | JSON string | Feature name for JS (`FEATURE_NAME`) |
| `__PRAT_FILE_DATA_JSON__` | JSON array | Per-file data for JS (`FILES`) |
| `__PRAT_META_JSON__` | JSON object | Summary metadata for JS (`META`) |

> **Why placeholders and not `str.format`?** The template is full of literal `{` / `}`
> from CSS and JS template literals. Using distinctive `__PRAT_*__` tokens with simple
> string replacement keeps the asset a *valid, editable HTML file* — you can open it
> directly in a browser to iterate on styling — and avoids brace-doubling noise.

All embedded JSON is escaped so a `</script>` sequence inside data can never break out of
the `<script>` block.

## JavaScript data contract

The script consumes three globals injected via the placeholders above:

```js
const FEATURE_NAME = "TLS";              // __PRAT_FEATURE_JSON__

const FILES = [                          // __PRAT_FILE_DATA_JSON__ (sorted desc by removable_lines)
  {
    file: "tls.c",                       // source file name
    removable_lines: 25,                 // count of feature-specific removable lines
    line_numbers: [10, 20],              // captured line numbers (ascending)
    snippets: [                          // captured source lines, aligned to line_numbers
      { line_number: 10, content: "tls_handshake();" },
      { line_number: 20, content: "tls_verify();" }
    ]
  }
  // ...
];

const META = {                           // __PRAT_META_JSON__
  feature: "TLS",
  total_lines: 40,
  file_count: 3,
  avg_lines: 13,
  max_lines: 25,
  largest_file: "tls.c",
  generated_at: "2026-06-25T19:30:00Z"
};
```

The `line_span` shown in the table/graph is derived in JS as
`last(line_numbers) - first(line_numbers) + 1`.

## Theming

Colors are CSS custom properties on `:root`, overridden under `[data-theme="dark"]`. To
adjust the palette, edit those variable blocks near the top of the `<style>` element — no
JS changes are needed. The active theme is stored under the `localStorage` key
`prat-theme`.

## Extending the report

- **Add a metric card:** add a `.card` in the `<section class="cards">` block; surface the
  value either via a new `__PRAT_*__` placeholder (also populate it in
  `generate_html_report`) or compute it in JS from `FILES` / `META`.
- **Add a table column:** add a `<th data-col="…" data-type="number|string">` with
  `scope="col"`, `tabindex="0"`, and `aria-sort="none"`, then extend `visibleFiles()`'s
  sort switch and the row markup in `renderTable()`.
- **Add a toolbar action:** add a `.btn` in `.toolbar-right` and wire a listener in the
  events section. Reuse `downloadFile()` / `copyText()` / `showToast()` helpers.

After editing, verify the contract still holds:

```bash
pytest src/tests/test_reporting.py -v
```

The tests assert the report is self-contained, includes the feature/file names and totals,
and still ships the `renderTable` function and the `filter` control.

## Quick manual preview

```bash
python - <<'PY'
from prat.extraction import ExtractionResult
from prat.reporting import generate_html_report

res = ExtractionResult(
    success=True,
    file_line_counts={"net.c": 10, "tls.c": 25, "ssl.c": 5},
    total_removable_lines=40,
    file_line_numbers={"net.c": [1, 2, 3], "tls.c": [10, 20], "ssl.c": [5]},
    file_line_content={
        "net.c": ["ssl_init();", "ssl_connect();", "ssl_free();"],
        "tls.c": ["tls_handshake();", "tls_verify();"],
        "ssl.c": ["SSL_CTX_new();"],
    },
)
generate_html_report(res, "TLS", "demo_report.html")
print("open demo_report.html")
PY
```
