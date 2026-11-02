"""
Flow KB (FastHTML edition), LOCAL-ONLY build - Data Strategy Limited client data-workflow knowledge base.

    python main.py     ->  http://127.0.0.1:5001

No login, no password, no rate limit, no hosting config. Listens on 127.0.0.1 only.
Data is kept in data/flowkb.db next to this file. Never deploy this folder.
"""
import asyncio
import json
import os
import sys
import traceback
from pathlib import Path

from fasthtml.common import *
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse as JSONResp, RedirectResponse, Response

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
DATA.mkdir(exist_ok=True)


import flowkb_core as core  # noqa: E402

core.init_db()   # creates data/flowkb.db and seeds the example project on first run


def json_only(req):
    # No login. State-changing API calls must still be JSON.
    if req.url.path.startswith("/api/") and req.method in ("POST", "PATCH", "PUT"):
        if "application/json" not in req.headers.get("content-type", ""):
            return JSONResp({"error": "Content-Type must be application/json"}, status_code=415)


async def bad_json(req, exc):
    # FastHTML parses JSON bodies before handlers run; turn malformed JSON into a clean 400.
    return JSONResp({"error": "Request body is not valid JSON"}, status_code=400)


app, rt = fast_app(
    exception_handlers={json.JSONDecodeError: bad_json},
    before=Beforeware(json_only),
    pico=False, surreal=False,
    static_path=str(HERE / "static"),
    secret_key=os.urandom(32).hex(),   # FastHTML requires one internally; random, in memory, never used for login
    title="Flow KB · Data Strategy Limited",
)

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect width='16' "
           "height='16' rx='3' fill='%230f172a'/%3E%3Cpath d='M3 4h4v3H3zM9 9h4v3H9z' fill='%2360a5fa'/%3E%3C/svg%3E")

# --------------------------------------------------------------------------- main page
EDGE_SVG = NotStr("""<svg id="edges" xmlns="http://www.w3.org/2000/svg"><defs>
<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#64748b"/></marker>
<marker id="arrowV" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#7c3aed"/></marker>
<marker id="arrowSel" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#0ea5e9"/></marker>
</defs><g id="edgeLayer" transform="translate(10000,10000)"></g><path id="tempEdge" d="" transform="translate(10000,10000)"/></svg>""")


def toolbar():
    add = lambda t, label, tip: Button(label, cls=f"add-node t-{t}", data_type=t, title=tip)
    return Header(
        Div(Span("◆", cls="logo"), " Flow KB ", Small("Data Strategy Limited"), cls="brand"),
        Div(Select(id="projectSelect", title="Switch project"),
            Button("＋ New project", id="btnNew", cls="primary",
                   title="New project (blank, starter skeleton, or seeded from an earlier project)"),
            Div(Button("Project ▾", id="btnProjectMenu", title="Rename, duplicate or delete this project"),
                Div(Button("Rename / change client…", id="btnRename"),
                    Button("Duplicate project…", id="btnDuplicate"),
                    Button("Start new project from this one…", id="btnSeedFrom"),
                    Hr(), Button("Delete project…", id="btnDeleteProject", cls="danger-ghost"),
                    cls="menu-items", id="projectMenu"), cls="menu"),
            cls="group"),
        Div(add("input", "Input data", "Add an input data node"), add("process", "Process", "Add a process step node"),
            add("output", "Output", "Add an output / artifact node"), add("validator", "Validator", "Add a validator / person node"),
            cls="group add"),
        Div(Button("Tidy", id="btnTidy", title="Auto-arrange nodes left to right"),
            Button("Fit", id="btnFit", title="Zoom to fit"),
            Button("−", id="btnZoomOut", title="Zoom out"), Button("＋", id="btnZoomIn", title="Zoom in"), cls="group"),
        Div(Div(Button("Export ▾", id="btnExport"),
                Div(Button("Markdown report (template sections)", data_export="markdown"),
                    Button("Mermaid flowchart", data_export="mermaid"),
                    Button("Project JSON", data_export="json"), Hr(),
                    Button("Backup of all projects (JSON)", data_export="all"),
                    cls="menu-items", id="exportMenu"), cls="menu"),
            Button("Import", id="btnImport", title="Import a Flow KB JSON export or backup"),
            Input(type="file", id="importFile", accept=".json,application/json", hidden=True),
            Button("Search KB", id="btnSearch", title="Search across all projects"),
            Button("SQL", id="btnSql", title="Run read-only SQL queries against the knowledge base"), cls="group"),
        Div(Div("✓ Saved", id="saveStatus", cls="status ok", title="Every change is saved automatically"),
            cls="tb-right"),
        id="toolbar")


@rt("/")
def get():
    return (Title("Flow KB · Data Strategy Limited"), Link(rel="icon", href=FAVICON),
            Link(rel="stylesheet", href="/style.css"),
            toolbar(),
            Main(Div(Div(EDGE_SVG, Div(id="nodeLayer"), id="world"),
                     Div(H2("Start mapping the workflow"),
                         P("Add an ", B("Output"), " for the month-end artifact, then work backwards: the ", B("Process"),
                           " steps, the ", B("Input data"), " they use, and the ", B("Validators"), " who check and sign off."),
                         P("Type directly on a node to name it, drag the ", B("●"),
                           " handle onto another node to connect them, and use the panel on the right for details."),
                         id="emptyHint", hidden=True),
                     Div(Span("Input data", cls="lg t-input"), Span("Process", cls="lg t-process"),
                         Span("Output", cls="lg t-output"), Span("Validator", cls="lg t-validator"),
                         Span("100%", cls="zoom", id="zoomLabel"), id="legend"),
                     id="canvas", tabindex="0"),
                 Aside(id="panel")),
            Div(Div(id="modal", role="dialog", aria_modal="true"), id="modalBackdrop", hidden=True),
            Div(id="toast", hidden=True),
            Script(src="/app.js"))


# --------------------------------------------------------------------------- JSON API
def _dispatch(fn, groups, query, body):
    with core.LOCK:
        conn = core.connect()
        try:
            result = fn(conn, groups, query, body)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def api(path, method, fn):
    "Register core handler `fn` as a FastHTML route; path params are passed through as strings."
    async def handler(req: Request):
        try:
            body = None
            if method in ("post", "patch", "put"):
                raw = await req.body()
                if raw:
                    try:
                        body = json.loads(raw.decode("utf-8"))
                    except ValueError:
                        return JSONResp({"error": "Request body is not valid JSON"}, status_code=400)
            groups = tuple(str(v) for v in req.path_params.values())
            query = {k: req.query_params.getlist(k) for k in req.query_params.keys()}
            result = await run_in_threadpool(_dispatch, fn, groups, query, body)
        except core.ApiError as e:
            return JSONResp({"error": e.message}, status_code=e.status)
        except (ValueError, TypeError, KeyError) as e:
            return JSONResp({"error": "Bad request: %s" % e}, status_code=400)
        except core.sqlite3.IntegrityError as e:
            return JSONResp({"error": "Constraint failed: %s" % e}, status_code=400)
        except Exception as e:  # pragma: no cover
            traceback.print_exc()
            return JSONResp({"error": "Server error: %s" % e}, status_code=500)
        status = 200
        if isinstance(result, tuple):
            status, result = result
        if isinstance(result, core.Raw):
            headers = {"Cache-Control": "no-store"}
            if req.query_params.get("download") == "1" and result.filename:
                from urllib.parse import quote
                headers["Content-Disposition"] = "attachment; filename*=UTF-8''%s" % quote(result.filename)
            return Response(result.body, status_code=status, media_type=result.content_type, headers=headers)
        return JSONResp(result, status_code=status, headers={"Cache-Control": "no-store"})
    handler.__name__ = "api_%s_%s" % (method, fn.__name__)
    app.route(path, methods=[method])(handler)


for _path, _method, _fn in [
    ("/api/health", "get", core.h_health),
    ("/api/schema", "get", core.h_schema),
    ("/api/clients", "get", core.h_clients),
    ("/api/projects", "get", core.h_list_projects),
    ("/api/projects", "post", core.h_create_project),
    ("/api/projects/{pid:int}", "get", core.h_get_project),
    ("/api/projects/{pid:int}", "patch", core.h_update_project),
    ("/api/projects/{pid:int}", "delete", core.h_delete_project),
    ("/api/projects/{pid:int}/duplicate", "post", core.h_duplicate_project),
    ("/api/projects/{pid:int}/nodes", "post", core.h_create_node),
    ("/api/projects/{pid:int}/edges", "post", core.h_create_edge),
    ("/api/projects/{pid:int}/layout", "put", core.h_layout),
    ("/api/projects/{pid:int}/export", "get", core.h_export),
    ("/api/export-all", "get", core.h_export_all),
    ("/api/import", "post", core.h_import),
    ("/api/nodes/{nid}", "get", core.h_get_node),
    ("/api/nodes/{nid}", "patch", core.h_update_node),
    ("/api/nodes/{nid}", "delete", core.h_delete_node),
    ("/api/edges/{eid}", "patch", core.h_update_edge),
    ("/api/edges/{eid}", "delete", core.h_delete_edge),
    ("/api/search", "get", core.h_search),
    ("/api/sql", "post", core.h_sql),
]:
    api(_path, _method, _fn)


# Local only: bind to this machine. Override the port with FLOWKB_PORT.
serve(host="127.0.0.1", port=int(os.getenv("FLOWKB_PORT", "5001")), reload=False)
