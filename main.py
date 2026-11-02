"""
Flow KB (FastHTML edition) - Data Strategy Limited client data-workflow knowledge base.

    FLOWKB_PASSWORD='choose-a-long-password' python main.py     ->  http://localhost:5001

Plash conventions followed: entry point main.py, dependencies in requirements.txt, port 5001
(FastHTML's serve() default), persistent SQLite in data/, secrets via plash.env.
"""
import asyncio
import hashlib
import hmac
import json
import os
import sys
import time
import traceback
from pathlib import Path

from fasthtml.common import *
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse as JSONResp, RedirectResponse, Response

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
DATA.mkdir(exist_ok=True)


def _load_env_file(fn):
    "Load `export KEY=VALUE` lines from plash.env for local runs (never overrides real env vars)."
    p = HERE / fn
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


_load_env_file("plash.env")
IN_PRODUCTION = os.getenv("PLASH_PRODUCTION") == "1"   # set automatically by Plash
PASSWORD = os.getenv("FLOWKB_PASSWORD", "")
if len(PASSWORD) < 8:
    sys.exit("\n  Flow KB refuses to start: set FLOWKB_PASSWORD (8+ characters).\n"
             "  Local:  FLOWKB_PASSWORD='your-long-password' python main.py\n"
             "          (or put  export FLOWKB_PASSWORD='...'  in plash.env)\n"
             "  Plash:  add it to plash.env, then run plash-deploy.\n")
# Sessions are tagged with a fingerprint of the password, so changing it logs everyone out.
PW_TAG = hashlib.sha256(("flowkb:" + PASSWORD).encode()).hexdigest()[:24]

import flowkb_core as core  # noqa: E402

core.init_db()   # creates data/flowkb.db and seeds the example project on first run


# --------------------------------------------------------------------------- auth
_failures = {}   # ip -> [timestamps]; simple brute-force throttle
MAX_FAILS, WINDOW = 10, 15 * 60


def client_ip(req):
    # Use the right-most X-Forwarded-For entry (added by the nearest proxy, i.e. Plash's), which a
    # client cannot forge; left-most entries are client-supplied.
    fwd = req.headers.get("x-forwarded-for", "")
    return fwd.split(",")[-1].strip() if fwd else (req.client.host if req.client else "?")


def auth_before(req, sess):
    if sess.get("auth") != PW_TAG:
        if req.url.path.startswith("/api/"):
            return JSONResp({"error": "Login required"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    # CSRF hardening: state-changing API calls must be JSON (forces a CORS preflight cross-site;
    # the session cookie is also SameSite=Lax).
    if req.url.path.startswith("/api/") and req.method in ("POST", "PATCH", "PUT"):
        if "application/json" not in req.headers.get("content-type", ""):
            return JSONResp({"error": "Content-Type must be application/json"}, status_code=415)


async def bad_json(req, exc):
    # FastHTML parses JSON bodies before handlers run; turn malformed JSON into a clean 400.
    return JSONResp({"error": "Request body is not valid JSON"}, status_code=400)


app, rt = fast_app(
    exception_handlers={json.JSONDecodeError: bad_json},
    before=Beforeware(auth_before, skip=[r"/login", r"/favicon\.ico"]),
    pico=False, surreal=False,
    static_path=str(HERE / "static"),
    key_fname=str(DATA / ".sesskey"),          # persisted in data/ so sessions survive redeploys
    secret_key=os.getenv("FLOWKB_SESSION_SECRET") or None,
    session_cookie="flowkb_session",
    max_age=30 * 24 * 3600,
    sess_https_only=IN_PRODUCTION,
    same_site="lax",
    title="Flow KB · Data Strategy Limited",
)

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect width='16' "
           "height='16' rx='3' fill='%230f172a'/%3E%3Cpath d='M3 4h4v3H3zM9 9h4v3H9z' fill='%2360a5fa'/%3E%3C/svg%3E")

LOGIN_CSS = """
body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;background:#f1f5f9;margin:0;display:grid;place-items:center;min-height:100vh;color:#0f172a}
.card{background:#fff;border:1px solid #cbd5e1;border-radius:14px;padding:28px 30px;width:min(380px,92vw);box-shadow:0 10px 30px rgba(15,23,42,.08)}
h1{font-size:20px;margin:0 0 2px}.sub{color:#64748b;font-size:13px;margin-bottom:18px}
label{font-size:13px;font-weight:600;display:block;margin-bottom:4px}
input{width:100%;box-sizing:border-box;border:1px solid #cbd5e1;border-radius:8px;padding:9px 10px;font:inherit}
button{margin-top:14px;width:100%;background:#0f172a;color:#fff;border:0;border-radius:8px;padding:10px;font:inherit;font-weight:600;cursor:pointer}
#login-msg{min-height:20px;margin-top:10px;font-size:13px;color:#dc2626}
"""


def login_page(msg=""):
    return (Title("Log in · Flow KB"), Link(rel="icon", href=FAVICON), Style(LOGIN_CSS),
            Div(H1("◆ Flow KB"), Div("Data Strategy Limited · client data-workflow knowledge base", cls="sub"),
                Form(Label("Password", fr="password"),
                     Input(type="password", name="password", id="password", autofocus=True, required=True,
                           autocomplete="current-password"),
                     Button("Log in", type="submit"),
                     Div(msg, id="login-msg"),
                     method="post", action="/login", hx_post="/login", hx_target="#login-msg", hx_swap="innerHTML"),
                cls="card"))


@rt("/login")
def get(sess):
    if sess.get("auth") == PW_TAG:
        return RedirectResponse("/", status_code=303)
    return login_page()


@rt("/login")
async def post(req, sess, password: str = ""):
    ip, now = client_ip(req), time.time()
    recent = [t for t in _failures.get(ip, []) if now - t < WINDOW]
    is_htmx = req.headers.get("hx-request") == "true"
    if len(recent) >= MAX_FAILS:
        msg = "Too many failed attempts. Try again in a few minutes."
        return (msg if is_htmx else Response(to_xml(login_page(msg)), status_code=429, media_type="text/html"))
    if hmac.compare_digest(password.encode("utf-8"), PASSWORD.encode("utf-8")):
        _failures.pop(ip, None)
        sess["auth"] = PW_TAG
        if is_htmx:
            return HttpHeader("HX-Redirect", "/")
        return RedirectResponse("/", status_code=303)
    recent.append(now)
    _failures[ip] = recent
    await asyncio.sleep(1)   # slow down guessing
    msg = "Incorrect password."
    if is_htmx:
        return msg
    return Response(to_xml(login_page(msg)), status_code=401, media_type="text/html")


@rt("/logout")
def post(sess):
    sess.clear()
    return RedirectResponse("/login", status_code=303)


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
            Form(Button("⏻", type="submit", title="Log out", aria_label="Log out"), id="logoutForm", method="post", action="/logout"),
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


# Plash exposes port 5001 only, so production always binds 5001 (FastHTML's default).
# Locally you may override with FLOWKB_PORT. Auto-reload is for local development only.
serve(port=5001 if IN_PRODUCTION else int(os.getenv("FLOWKB_PORT", "5001")), reload=not IN_PRODUCTION)
