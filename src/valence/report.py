"""Generate an interactive HTML report from pipeline results (JSONL/JSON)."""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

PAGE_SIZE = 100

# CDN libs: 2D from SMILES (SmilesDrawer), 3D from XYZ (3Dmol.js)
SMILES_DRAWER_JS = "https://unpkg.com/smiles-drawer@2.1.7/dist/smiles-drawer.min.js"
MOL3D_JS = "https://cdnjs.cloudflare.com/ajax/libs/3Dmol/2.4.2/3Dmol-min.js"


def load_results(path: Path) -> list[dict]:
    """Load results from .jsonl (one object per line) or a JSON array/object file."""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []

    if path.suffix.lower() == ".jsonl" or "\n" in text and not text.lstrip().startswith("["):
        rows: list[dict] = []
        for i, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{i}: invalid JSON: {e}") from e
        return rows

    data = json.loads(text)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "results" in data:
        return list(data["results"])
    if isinstance(data, dict):
        return [data]
    raise ValueError(f"Unsupported JSON structure in {path}")


def build_html(rows: list[dict], *, page_size: int = PAGE_SIZE, title: str = "QM9 results") -> str:
    """Render a self-contained HTML report with 2D/3D viewers and pagination."""
    payload = json.dumps(rows, ensure_ascii=False)
    # Prevent </script> breakouts inside embedded JSON
    payload = payload.replace("<", "\\u003c")

    n = len(rows)
    n_pages = max(1, (n + page_size - 1) // page_size) if n else 1

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(title)}</title>
<script src="{SMILES_DRAWER_JS}"></script>
<script src="{MOL3D_JS}"></script>
<style>
  :root {{
    --bg: #0f1419;
    --panel: #1a2332;
    --border: #2d3a4d;
    --text: #e7ecf3;
    --muted: #8b9bb4;
    --accent: #5b9fd4;
    --danger: #e06c75;
    --ok: #98c379;
    --cell: 220px;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.4;
  }}
  header {{
    padding: 1.25rem 1.5rem;
    border-bottom: 1px solid var(--border);
    background: linear-gradient(180deg, #1a2332 0%, #0f1419 100%);
    position: sticky;
    top: 0;
    z-index: 20;
  }}
  header h1 {{
    margin: 0 0 0.35rem;
    font-size: 1.25rem;
    font-weight: 600;
  }}
  header .meta {{ color: var(--muted); font-size: 0.9rem; }}
  .pager {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
    margin-top: 0.75rem;
  }}
  .pager button {{
    background: var(--panel);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.35rem 0.75rem;
    cursor: pointer;
    font: inherit;
  }}
  .pager button:hover:not(:disabled) {{ border-color: var(--accent); color: var(--accent); }}
  .pager button:disabled {{ opacity: 0.4; cursor: not-allowed; }}
  .pager button.active {{ background: var(--accent); color: #0a0e14; border-color: var(--accent); }}
  .pager .info {{ color: var(--muted); font-size: 0.85rem; margin-left: 0.5rem; }}
  main {{ padding: 1rem 1.25rem 3rem; overflow-x: auto; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    min-width: 960px;
  }}
  th, td {{
    border: 1px solid var(--border);
    padding: 0.6rem;
    vertical-align: top;
    text-align: left;
  }}
  th {{
    background: var(--panel);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted);
    position: sticky;
    top: 0;
  }}
  tr.row-hidden {{ display: none; }}
  .id {{
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.85rem;
    white-space: nowrap;
  }}
  .smiles {{
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.8rem;
    word-break: break-all;
    max-width: 14rem;
  }}
  .badge {{
    display: inline-block;
    margin-top: 0.35rem;
    font-size: 0.7rem;
    padding: 0.15rem 0.4rem;
    border-radius: 4px;
    background: #243044;
    color: var(--muted);
  }}
  .badge.ok {{ color: var(--ok); border: 1px solid #3d5a3a; }}
  .badge.err {{ color: var(--danger); border: 1px solid #5a3038; }}
  .viewer-wrap {{
    position: relative;
    width: var(--cell);
    height: var(--cell);
    background: #0a0e14;
    border-radius: 8px;
    border: 1px solid var(--border);
    overflow: hidden;
  }}
  .viewer-wrap canvas, .viewer-wrap svg {{
    display: block;
  }}
  .view-2d, .view-3d {{
    width: 100%;
    height: 100%;
  }}
  .view-3d {{ position: relative; }}
  .placeholder {{
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    color: var(--muted);
    font-size: 0.8rem;
    text-align: center;
    padding: 0.75rem;
  }}
  /* InChI overlay on hover */
  .inchi-overlay {{
    pointer-events: none;
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    max-height: 0;
    overflow: hidden;
    opacity: 0;
    transition: max-height 0.15s ease, opacity 0.15s ease, padding 0.15s ease;
    background: rgba(10, 14, 20, 0.92);
    color: #d7e3f4;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.65rem;
    line-height: 1.35;
    padding: 0 0.5rem;
    word-break: break-all;
    z-index: 5;
  }}
  .viewer-wrap:hover .inchi-overlay.has-inchi {{
    max-height: 55%;
    opacity: 1;
    padding: 0.45rem 0.5rem;
    overflow-y: auto;
    pointer-events: auto;
  }}
  .energy {{
    margin-top: 0.35rem;
    font-size: 0.75rem;
    color: var(--muted);
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }}
</style>
</head>
<body>
<header>
  <h1>{html.escape(title)}</h1>
  <div class="meta">{n} entries · page size {page_size} · 2D from SMILES · 3D from XYZ (obabel / xtb)</div>
  <div class="pager" id="pager">
    <button type="button" id="prev-btn" aria-label="Previous page">← Prev</button>
    <div id="page-buttons"></div>
    <button type="button" id="next-btn" aria-label="Next page">Next →</button>
    <span class="info" id="page-info"></span>
  </div>
</header>
<main>
  <table>
    <thead>
      <tr>
        <th>ID</th>
        <th>SMILES</th>
        <th>2D (source SMILES)</th>
        <th>3D openbabel</th>
        <th>3D optimized (xtb)</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</main>
<script id="results-data" type="application/json">{payload}</script>
<script>
(function () {{
  const PAGE_SIZE = {page_size};
  const rows = JSON.parse(document.getElementById("results-data").textContent);
  const tbody = document.getElementById("tbody");
  const pageButtons = document.getElementById("page-buttons");
  const pageInfo = document.getElementById("page-info");
  const prevBtn = document.getElementById("prev-btn");
  const nextBtn = document.getElementById("next-btn");

  let page = 0;
  const nPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE) || 1);
  const drawer = (typeof SmilesDrawer !== "undefined")
    ? new SmilesDrawer.Drawer({{ width: 210, height: 210, bondThickness: 1.2 }})
    : null;

  const viewers3d = new Map(); // element id -> $3Dmol viewer

  function esc(s) {{
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }}

  function inchiOverlay(inchi) {{
    if (!inchi) {{
      return '<div class="inchi-overlay">No InChI</div>';
    }}
    return '<div class="inchi-overlay has-inchi" title="' + esc(inchi) + '">' + esc(inchi) + "</div>";
  }}

  function buildRows() {{
    const frag = document.createDocumentFragment();
    rows.forEach((r, idx) => {{
      const tr = document.createElement("tr");
      tr.dataset.index = String(idx);
      tr.className = "data-row";

      const id = r.identifier != null ? r.identifier : idx;
      const smiles = r.smiles || "";
      const err = r.error;
      const badge = err
        ? '<span class="badge err" title="' + esc(err) + '">error</span>'
        : '<span class="badge ok">ok</span>';
      const energy = (r.energy != null && r.energy !== "")
        ? '<div class="energy">E = ' + esc(Number(r.energy).toFixed(6)) + " Eh</div>"
        : "";

      const id2d = "smi-" + idx;
      const idOb = "ob3d-" + idx;
      const idXt = "xt3d-" + idx;

      tr.innerHTML =
        '<td class="id">' + esc(id) + "<br/>" + badge + "</td>" +
        '<td class="smiles" title="' + esc(smiles) + '">' + esc(smiles) + "</td>" +
        '<td><div class="viewer-wrap" data-kind="2d" data-smiles="' + esc(smiles) + '" data-inchi="' + esc(r.inchi_start || "") + '">' +
          '<canvas class="view-2d" id="' + id2d + '" width="210" height="210"></canvas>' +
          inchiOverlay(r.inchi_start) +
        "</div></td>" +
        '<td><div class="viewer-wrap" data-kind="3d" data-xyz-key="obabel_geometry" id="wrap-' + idOb + '">' +
          '<div class="view-3d" id="' + idOb + '"></div>' +
          inchiOverlay(r.inchi_obabel) +
        "</div></td>" +
        '<td><div class="viewer-wrap" data-kind="3d" data-xyz-key="optimized_geometry" id="wrap-' + idXt + '">' +
          '<div class="view-3d" id="' + idXt + '"></div>' +
          inchiOverlay(r.inchi_xtb) +
        "</div>" + energy + "</td>";

      // stash xyz on elements after insert
      frag.appendChild(tr);
    }});
    tbody.appendChild(frag);

    // Attach XYZ payloads (avoid huge attribute strings with HTML-escaping issues)
    rows.forEach((r, idx) => {{
      const ob = document.getElementById("ob3d-" + idx);
      const xt = document.getElementById("xt3d-" + idx);
      if (ob) ob.dataset.xyz = r.obabel_geometry || "";
      if (xt) xt.dataset.xyz = r.optimized_geometry || "";
    }});
  }}

  function render2dVisible() {{
    if (!drawer) return;
    tbody.querySelectorAll("tr.data-row:not(.row-hidden) .viewer-wrap[data-kind='2d']").forEach((wrap) => {{
      if (wrap.dataset.drawn === "1") return;
      const smiles = wrap.dataset.smiles || "";
      const canvas = wrap.querySelector("canvas");
      if (!smiles || !canvas) {{
        wrap.innerHTML = '<div class="placeholder">No SMILES</div>' + wrap.querySelector(".inchi-overlay")?.outerHTML;
        wrap.dataset.drawn = "1";
        return;
      }}
      SmilesDrawer.parse(
        smiles,
        (tree) => {{
          drawer.draw(tree, canvas, "dark", false);
          wrap.dataset.drawn = "1";
        }},
        () => {{
          const ov = wrap.querySelector(".inchi-overlay");
          wrap.innerHTML = '<div class="placeholder">2D draw failed</div>';
          if (ov) wrap.appendChild(ov);
          wrap.dataset.drawn = "1";
        }}
      );
    }});
  }}

  function render3dVisible() {{
    if (typeof $3Dmol === "undefined") return;
    tbody.querySelectorAll("tr.data-row:not(.row-hidden) .view-3d").forEach((el) => {{
      if (el.dataset.drawn === "1") return;
      const xyz = el.dataset.xyz || "";
      if (!xyz.trim()) {{
        el.innerHTML = '<div class="placeholder">No geometry</div>';
        el.dataset.drawn = "1";
        return;
      }}
      el.innerHTML = "";
      const viewer = $3Dmol.createViewer(el, {{ backgroundColor: "0a0e14" }});
      try {{
        viewer.addModel(xyz, "xyz");
        viewer.setStyle({{}}, {{ stick: {{ radius: 0.12 }}, sphere: {{ scale: 0.22 }} }});
        viewer.zoomTo();
        viewer.render();
        viewers3d.set(el.id, viewer);
      }} catch (e) {{
        el.innerHTML = '<div class="placeholder">3D load failed</div>';
      }}
      el.dataset.drawn = "1";
    }});
  }}

  function showPage(p) {{
    page = Math.max(0, Math.min(nPages - 1, p));
    const start = page * PAGE_SIZE;
    const end = start + PAGE_SIZE;
    tbody.querySelectorAll("tr.data-row").forEach((tr) => {{
      const i = Number(tr.dataset.index);
      tr.classList.toggle("row-hidden", i < start || i >= end);
    }});
    pageInfo.textContent = rows.length
      ? ("Page " + (page + 1) + " / " + nPages + " · showing " +
         (start + 1) + "–" + Math.min(end, rows.length) + " of " + rows.length)
      : "No entries";
    prevBtn.disabled = page <= 0;
    nextBtn.disabled = page >= nPages - 1;
    pageButtons.querySelectorAll("button[data-page]").forEach((b) => {{
      b.classList.toggle("active", Number(b.dataset.page) === page);
    }});
    // Defer viewers so layout has sizes
    requestAnimationFrame(() => {{
      render2dVisible();
      render3dVisible();
    }});
  }}

  function buildPager() {{
    pageButtons.innerHTML = "";
    for (let i = 0; i < nPages; i++) {{
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = String(i + 1);
      b.dataset.page = String(i);
      b.addEventListener("click", () => showPage(i));
      pageButtons.appendChild(b);
    }}
    prevBtn.addEventListener("click", () => showPage(page - 1));
    nextBtn.addEventListener("click", () => showPage(page + 1));
  }}

  buildRows();
  buildPager();
  showPage(0);
}})();
</script>
</body>
</html>
"""


def generate_report(
    input_path: str | Path,
    output_path: str | Path,
    *,
    page_size: int = PAGE_SIZE,
    title: str = "QM9 difficult cases — results",
) -> Path:
    rows = load_results(Path(input_path))
    html_text = build_html(rows, page_size=page_size, title=title)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_text, encoding="utf-8")
    return out.resolve()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Render pipeline results (JSONL/JSON) to an interactive HTML table"
    )
    parser.add_argument(
        "-i",
        "--input",
        default="output/results.jsonl",
        help="Results file (.jsonl or .json). Default: output/results.jsonl",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="output/results.html",
        help="Output HTML path (default: output/results.html)",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=PAGE_SIZE,
        help=f"Rows per page (default: {PAGE_SIZE})",
    )
    parser.add_argument(
        "--title",
        default="QM9 difficult cases — results",
        help="HTML document title",
    )
    args = parser.parse_args(argv)
    out = generate_report(
        args.input,
        args.output,
        page_size=args.page_size,
        title=args.title,
    )
    print(out, file=sys.stdout)


if __name__ == "__main__":
    main()
