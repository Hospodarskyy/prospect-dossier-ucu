"""The agent graph as an HTML page for st.iframe: Graphviz in the browser
(viz.js from the jsDelivr CDN) and a card with the node's state values when the
mouse is over a node.

The card values include model output (judge summary, facts). They reach the
page only as JSON inside the script and are shown with textContent, never as
HTML, so they cannot run code in the page."""
import html
import json

from .graph import NODES, TOOLS, GraphState, graph_dot, node_title, state_of

VIZ_JS = "https://cdn.jsdelivr.net/npm/@viz-js/viz@3.31.0/dist/viz-global.js"
HEIGHT = 350            # px of the iframe; the graph scales to its width (and fits this height)

STATE_LABEL = {"active": "running", "done": "done", "todo": "not reached"}
THEMES = {
    "dark": {"card": "#1f2329", "text": "#e6e8eb", "muted": "#9aa3ad", "border": "#3a4048",
             "good": "#5cc98b", "bad": "#ff7b6b", "warn": "#f2b84b"},
    "light": {"card": "#ffffff", "text": "#1d2b3a", "muted": "#5b626c", "border": "#d5d9de",
              "good": "#1f7a48", "bad": "#b3261e", "warn": "#9a5b00"},
}


def node_cards(gs: GraphState) -> dict:
    """node id -> {title, kind, state, rows}; every node gets a card."""
    cards = {}
    for node_id in (*NODES, *TOOLS):
        title, kind = node_title(node_id)
        state = state_of(node_id, gs)
        rows = [[k, v] for k, v in gs.info.get(node_id, {}).items()]
        cards[node_id] = {"title": title, "kind": kind, "state": STATE_LABEL[state], "rows": rows}
    return cards


def _script_json(value) -> str:
    """JSON that is safe inside a <script> element."""
    return json.dumps(value).replace("</", "<\\/")


def graph_html(gs: GraphState, theme: str | None = None) -> str:
    colors = THEMES["light" if theme == "light" else "dark"]
    css_vars = ";".join(f"--{k}:{v}" for k, v in colors.items())
    return TEMPLATE % {
        "vars": css_vars,
        "viz": html.escape(VIZ_JS, quote=True),
        "dot": _script_json(graph_dot(gs)),
        "cards": _script_json(node_cards(gs)),
        "height": HEIGHT - 10,
    }


TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8">
<style>
  :root { %(vars)s }
  html, body { margin: 0; background: transparent; color: var(--text);
               font: 13px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; }
  #graph svg { width: 100%%; height: auto; max-height: %(height)spx; display: block; }
  #graph g.node { cursor: pointer; }
  #graph g.node:hover { filter: brightness(1.08) drop-shadow(0 0 3px rgba(120,160,220,.7)); }
  #msg { color: var(--muted); padding: 8px 0; }
  #card { position: fixed; display: none; z-index: 10; max-width: 380px; min-width: 220px;
          background: var(--card); color: var(--text); border: 1px solid var(--border);
          border-radius: 8px; padding: 10px 12px; box-shadow: 0 6px 20px rgba(0,0,0,.35);
          pointer-events: none; }
  #card .head { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; }
  #card .title { font-weight: 600; font-size: 14px; }
  #card .kind, #card .state, #card .empty { color: var(--muted); font-size: 12px; }
  #card .state.running { color: var(--warn); }
  #card table { border-collapse: collapse; margin-top: 6px; width: 100%%; }
  #card td { padding: 2px 0; vertical-align: top; }
  #card td.k { color: var(--muted); padding-right: 10px; white-space: nowrap; }
  #card td.v { word-break: break-word; }
  #card .good { color: var(--good); font-weight: 600; }
  #card .bad { color: var(--bad); font-weight: 600; }
  #card .warn { color: var(--warn); font-weight: 600; }
</style></head>
<body>
<div id="graph"><div id="msg">Drawing the graph…</div></div>
<div id="card"></div>
<script src="%(viz)s"></script>
<script>
const DOT = %(dot)s;
const CARDS = %(cards)s;
const TONE = {pass: "good", ok: "good", fail: "bad", failed: "bad", partial: "warn"};
const card = document.getElementById("card");

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function fill(id) {
  const c = CARDS[id];
  card.replaceChildren();
  const head = el("div", "head");
  const left = el("div");
  left.append(el("div", "title", c.title), el("div", "kind", c.kind));
  head.append(left, el("div", "state " + c.state.replace(" ", "-"), c.state));
  card.append(head);
  if (!c.rows.length) {
    card.append(el("div", "empty", c.state === "not reached"
      ? "This step did not run (yet)." : "No state values saved for this step."));
    return;
  }
  const table = el("table");
  for (const [k, v] of c.rows) {
    const tr = el("tr");
    const td = el("td", "v");
    const tone = TONE[String(v).toLowerCase()];
    td.append(tone ? el("span", tone, v) : document.createTextNode(v));
    tr.append(el("td", "k", k), td);
    table.append(tr);
  }
  card.append(table);
}

function place(ev) {
  const pad = 14, w = card.offsetWidth, h = card.offsetHeight;
  let x = ev.clientX + pad, y = ev.clientY + pad;
  if (x + w > window.innerWidth - 4) x = Math.max(4, ev.clientX - w - pad);
  if (y + h > window.innerHeight - 4) y = Math.max(4, ev.clientY - h - pad);
  card.style.left = x + "px";
  card.style.top = y + "px";
}

if (typeof Viz === "undefined") {
  document.getElementById("msg").textContent =
    "Could not load viz.js from cdn.jsdelivr.net (no internet?), so the graph is not drawn.";
} else Viz.instance().then(viz => {
  const svg = viz.renderSVGElement(DOT);
  svg.removeAttribute("width");
  svg.removeAttribute("height");
  for (const g of svg.querySelectorAll("g.node")) {
    const title = g.querySelector("title");
    const id = title ? title.textContent : "";
    if (title) title.remove();            // no native tooltip on top of the card
    if (!CARDS[id]) continue;
    g.addEventListener("mouseenter", ev => { fill(id); card.style.display = "block"; place(ev); });
    g.addEventListener("mousemove", place);
    g.addEventListener("mouseleave", () => { card.style.display = "none"; });
  }
  for (const t of svg.querySelectorAll("title")) t.remove();
  document.getElementById("graph").replaceChildren(svg);
}).catch(err => {
  document.getElementById("msg").textContent =
    "Could not draw the graph (viz.js is loaded from cdn.jsdelivr.net): " + err;
});
</script>
</body></html>
"""
