#!/usr/bin/env python3
"""
Flow KB core - domain model, SQLite schema, seed data, exports and API handlers.

Framework-agnostic (stdlib sqlite3 only). The FastHTML web layer lives in main.py.
Each handler has the signature  fn(conn, path_groups, query_dict_of_lists, json_body).
"""
import datetime
import json
import os
import pathlib
import re
import sqlite3
import threading
import uuid

APP_NAME = "Flow KB"
APP_VERSION = "1.0.0"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")          # Plash keeps data/ between deployments
DB_PATH = os.environ.get("FLOWKB_DB") or os.path.join(DATA_DIR, "flowkb.db")
LOCK = threading.RLock()

# --------------------------------------------------------------------------
# Domain schema (single source of truth - also served to the browser)
# --------------------------------------------------------------------------
RESPONSIBILITIES = ["Process walkthrough", "Validator", "Sign-off owner",
                    "Data source SME", "Controls reviewer", "Other"]

NODE_TYPES = {
    "input": {
        "label": "Input data", "short": "Input data", "color": "#2563eb", "shape": "parallelogram",
        "title_label": "Input name",
        "title_placeholder": "e.g. Claims extract.xlsx",
        "summary": ["source_system", "format", "refresh"],
        "fields": [
            {"key": "source_system", "label": "Original source system", "placeholder": "e.g. Claims admin system (table/view), SAP GL, manual"},
            {"key": "how_obtained", "label": "How it's obtained today", "placeholder": "Emailed by Claims team / manual export / copy-paste"},
            {"key": "owner", "label": "Owner", "placeholder": "Who owns / provides this data?"},
            {"key": "format", "label": "Format", "placeholder": "xlsx / csv / SQL view / PDF"},
            {"key": "refresh", "label": "Refresh / timing", "placeholder": "e.g. Monthly, available BD+2"},
            {"key": "access", "label": "Access granted?", "kind": "select", "options": ["", "Y", "N", "Requested"]},
            {"key": "notes", "label": "Notes", "kind": "textarea", "placeholder": "Where did the number come from before it reached the spreadsheet? Hard-coded values? Unknown origins?"},
        ],
    },
    "process": {
        "label": "Process step", "short": "Process", "color": "#059669", "shape": "rect",
        "title_label": "Step name",
        "title_placeholder": "e.g. Paste extract into 'Raw' tab",
        "summary": ["performed_by", "tool", "time_taken"],
        "fields": [
            {"key": "description", "label": "Step description", "kind": "textarea", "placeholder": "Walk me through this step as if I were covering for you."},
            {"key": "performed_by", "label": "Performed by", "placeholder": "Name / role"},
            {"key": "tool", "label": "Tool / system", "placeholder": "Excel, SQL, SAP, Power Query..."},
            {"key": "time_taken", "label": "Time taken", "placeholder": "e.g. 3 hours per cycle"},
            {"key": "manual", "label": "Manual?", "kind": "select", "options": ["", "Y", "N", "Partly"]},
            {"key": "business_rules", "label": "Business rules / calculations", "kind": "textarea", "placeholder": "BR-01 Exclude cancelled policies (Status <> 'CANC')..."},
            {"key": "risk", "label": "Risk / pain point", "placeholder": "What has gone wrong here before?"},
            {"key": "notes", "label": "Notes", "kind": "textarea", "placeholder": "Judgement calls, workarounds, key-person risk"},
        ],
    },
    "output": {
        "label": "Output / artifact", "short": "Output", "color": "#d97706", "shape": "document",
        "title_label": "Artifact name",
        "title_placeholder": "e.g. Monthly Claims Reconciliation.xlsx",
        "summary": ["frequency", "effort", "consumers"],
        "fields": [
            {"key": "location", "label": "Location", "placeholder": "SharePoint / network drive path / system"},
            {"key": "format", "label": "Format", "placeholder": "Excel workbook / CSV / Power BI report"},
            {"key": "frequency", "label": "Frequency", "placeholder": "Monthly - produced by business day X"},
            {"key": "consumers", "label": "Consumers / audience", "placeholder": "CFO, Board pack, Regulator (RBNZ), Reinsurer"},
            {"key": "effort", "label": "Manual effort per cycle", "placeholder": "X hours / Y people"},
            {"key": "pain_points", "label": "Pain points", "kind": "textarea", "placeholder": "Errors, delays, key-person risk, version control"},
            {"key": "downstream", "label": "Downstream uses", "placeholder": "What decision or report is blocked if this is late or wrong?"},
            {"key": "notes", "label": "Notes / key tabs & KPIs", "kind": "textarea", "placeholder": "Tabs, tables or KPIs on the artifact; what does 'done' look like?"},
        ],
    },
    "validator": {
        "label": "Validator / person", "short": "Validator", "color": "#7c3aed", "shape": "stadium",
        "title_label": "Person's name",
        "title_placeholder": "e.g. Jane Smith",
        "summary": ["role", "organisation", "email", "phone"],
        "fields": [
            {"key": "role", "label": "Role / team", "placeholder": "e.g. Finance Manager"},
            {"key": "organisation", "label": "Organisation", "placeholder": "e.g. Example Client A"},
            {"key": "responsibility", "label": "Responsibility", "kind": "select", "options": [""] + RESPONSIBILITIES},
            {"key": "email", "label": "Email", "kind": "email", "placeholder": "name@client.co.nz"},
            {"key": "phone", "label": "Phone", "kind": "tel", "placeholder": "+64 ..."},
            {"key": "availability", "label": "Availability", "placeholder": "e.g. Tue/Thu mornings"},
            {"key": "validation_tests", "label": "Validation tests", "kind": "textarea", "placeholder": "T-01 Completeness: row counts match source\nT-02 Reconciliation: totals tie to GL"},
            {"key": "tolerance", "label": "Tolerance / sign-off criteria", "placeholder": "e.g. within $1,000 or 0.01%; N parallel-run months"},
            {"key": "notes", "label": "Notes", "kind": "textarea", "placeholder": "Who would notice first if a number were wrong? What evidence do they need?"},
        ],
    },
}

PROJECT_META_FIELDS = [
    {"key": "business_unit", "label": "Business unit / team", "placeholder": "e.g. Finance - Actuarial Reporting"},
    {"key": "engagement_lead", "label": "Engagement lead (DSL)", "placeholder": "Name"},
    {"key": "client_sponsor", "label": "Client sponsor", "placeholder": "Name, role"},
    {"key": "start_date", "label": "Start date", "kind": "date"},
    {"key": "target_date", "label": "Target delivery date", "kind": "date"},
    {"key": "objective", "label": "One-line objective", "kind": "textarea", "placeholder": "Automate production of [artifact], reducing effort from X hours to Y hours..."},
    {"key": "in_scope", "label": "In scope", "kind": "textarea"},
    {"key": "out_of_scope", "label": "Out of scope", "kind": "textarea"},
    {"key": "risks", "label": "Risks / assumptions / issues", "kind": "textarea", "placeholder": "One per line"},
    {"key": "next_steps", "label": "Next steps", "kind": "textarea", "placeholder": "One per line, e.g. Schedule process walkthrough with producer"},
]

KNOWN_CLIENTS = ["Example Client A", "Example Client B"]

# Denormalised, indexed columns on `nodes` (copied from the JSON data on every save)
KEY_COLUMNS = ["source_system", "owner", "format", "refresh", "performed_by", "tool", "manual",
               "frequency", "location", "role", "organisation", "email", "phone", "responsibility"]

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS schema_info (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS projects (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    client            TEXT NOT NULL DEFAULT '',
    name              TEXT NOT NULL DEFAULT '',
    description       TEXT NOT NULL DEFAULT '',
    meta              TEXT NOT NULL DEFAULT '{}',   -- JSON: snapshot, scope, risks, next steps
    source_project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,  -- seeded from
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nodes (
    id             TEXT PRIMARY KEY,
    project_id     INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    type           TEXT NOT NULL CHECK (type IN ('input','process','output','validator')),
    title          TEXT NOT NULL DEFAULT '',
    x              REAL NOT NULL DEFAULT 0,
    y              REAL NOT NULL DEFAULT 0,
    data           TEXT NOT NULL DEFAULT '{}',      -- JSON: all fields for the node type
    source_system  TEXT, owner TEXT, format TEXT, refresh TEXT,
    performed_by   TEXT, tool TEXT, manual TEXT,
    frequency      TEXT, location TEXT,
    role           TEXT, organisation TEXT, email TEXT, phone TEXT, responsibility TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_project ON nodes(project_id);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_source_system ON nodes(source_system);
CREATE INDEX IF NOT EXISTS idx_nodes_email ON nodes(email);
CREATE TABLE IF NOT EXISTS edges (
    id          TEXT PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_id   TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    target_id   TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    label       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_edges_project ON edges(project_id);

-- Convenience views for querying across all projects
CREATE VIEW IF NOT EXISTS v_nodes AS
    SELECT p.client, p.name AS project, n.* FROM nodes n JOIN projects p ON p.id = n.project_id;
CREATE VIEW IF NOT EXISTS v_inputs AS
    SELECT p.client, p.name AS project, n.project_id, n.id, n.title AS input, n.source_system, n.owner,
           n.format, n.refresh, n.data FROM nodes n JOIN projects p ON p.id = n.project_id WHERE n.type = 'input';
CREATE VIEW IF NOT EXISTS v_processes AS
    SELECT p.client, p.name AS project, n.project_id, n.id, n.title AS step, n.performed_by, n.tool, n.manual,
           n.data FROM nodes n JOIN projects p ON p.id = n.project_id WHERE n.type = 'process';
CREATE VIEW IF NOT EXISTS v_outputs AS
    SELECT p.client, p.name AS project, n.project_id, n.id, n.title AS artifact, n.location, n.format,
           n.frequency, n.data FROM nodes n JOIN projects p ON p.id = n.project_id WHERE n.type = 'output';
CREATE VIEW IF NOT EXISTS v_validators AS
    SELECT p.client, p.name AS project, n.project_id, n.id, n.title AS name, n.role, n.organisation,
           n.responsibility, n.email, n.phone, n.data FROM nodes n JOIN projects p ON p.id = n.project_id
    WHERE n.type = 'validator';
CREATE VIEW IF NOT EXISTS v_edges AS
    SELECT p.client, p.name AS project, e.project_id, e.id, s.type AS source_type, s.title AS source,
           e.label, t.type AS target_type, t.title AS target
    FROM edges e JOIN projects p ON p.id = e.project_id
    JOIN nodes s ON s.id = e.source_id JOIN nodes t ON t.id = e.target_id;
"""


def now():
    return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()


def new_id():
    return uuid.uuid4().hex[:12]


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class Raw(object):
    def __init__(self, body, content_type, filename=None):
        self.body = body
        self.content_type = content_type
        self.filename = filename


def connect(path=None):
    conn = sqlite3.connect(path or DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(seed=True):
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    with LOCK:
        conn = connect()
        try:
            conn.executescript(SCHEMA_SQL)
            conn.execute("INSERT OR IGNORE INTO schema_info(key, value) VALUES ('schema_version', '1')")
            conn.commit()
            seeded = conn.execute("SELECT value FROM schema_info WHERE key='seeded'").fetchone()
            if seed and not seeded:
                seed_example(conn)
                conn.execute("INSERT OR REPLACE INTO schema_info(key, value) VALUES ('seeded', ?)", (now(),))
                conn.commit()
        finally:
            conn.close()


# --------------------------------------------------------------------------
# Row helpers
# --------------------------------------------------------------------------
def loads(s, default=None):
    try:
        v = json.loads(s) if s else default
        return v if v is not None else default
    except (ValueError, TypeError):
        return default


def project_dict(row, counts=None):
    d = {k: row[k] for k in row.keys()}
    d["meta"] = loads(d.get("meta"), {})
    if counts is not None:
        d["counts"] = counts
    return d


def node_dict(row):
    return {"id": row["id"], "project_id": row["project_id"], "type": row["type"], "title": row["title"],
            "x": row["x"], "y": row["y"], "data": loads(row["data"], {}),
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


def edge_dict(row):
    return {"id": row["id"], "project_id": row["project_id"], "source_id": row["source_id"],
            "target_id": row["target_id"], "label": row["label"],
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


def clean_data(data):
    if not isinstance(data, dict):
        return {}
    out = {}
    for k, v in data.items():
        if not isinstance(k, str) or k.startswith("_"):
            continue
        if v is None:
            continue
        out[k] = v if isinstance(v, (str, int, float, bool)) else json.dumps(v)
    return out


def key_values(data):
    vals = []
    for k in KEY_COLUMNS:
        v = data.get(k)
        vals.append(str(v).strip() if v not in (None, "") else None)
    return vals


def get_project_row(conn, pid):
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
    if not row:
        raise ApiError(404, "Project %s not found" % pid)
    return row


def touch_project(conn, pid):
    conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now(), pid))


def insert_project(conn, client, name, description="", meta=None, source_project_id=None):
    ts = now()
    cur = conn.execute(
        "INSERT INTO projects(client, name, description, meta, source_project_id, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (client or "", name or "Untitled project", description or "", json.dumps(meta or {}),
         source_project_id, ts, ts))
    return cur.lastrowid


def insert_node(conn, pid, ntype, title="", x=0, y=0, data=None, nid=None):
    if ntype not in NODE_TYPES:
        raise ApiError(400, "Unknown node type %r" % ntype)
    data = clean_data(data or {})
    nid = nid or new_id()
    ts = now()
    cols = ", ".join(KEY_COLUMNS)
    qs = ", ".join("?" for _ in KEY_COLUMNS)
    conn.execute(
        "INSERT INTO nodes(id, project_id, type, title, x, y, data, %s, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?, %s, ?, ?)" % (cols, qs),
        [nid, pid, ntype, title or "", float(x or 0), float(y or 0), json.dumps(data)] + key_values(data) + [ts, ts])
    return nid


def insert_edge(conn, pid, source_id, target_id, label="", eid=None):
    if source_id == target_id:
        raise ApiError(400, "An edge cannot connect a node to itself")
    for nid in (source_id, target_id):
        r = conn.execute("SELECT project_id FROM nodes WHERE id = ?", (nid,)).fetchone()
        if not r or r["project_id"] != pid:
            raise ApiError(400, "Node %s is not in project %s" % (nid, pid))
    dup = conn.execute("SELECT id FROM edges WHERE project_id=? AND source_id=? AND target_id=?",
                       (pid, source_id, target_id)).fetchone()
    if dup:
        raise ApiError(409, "Those nodes are already connected")
    eid = eid or new_id()
    ts = now()
    conn.execute("INSERT INTO edges(id, project_id, source_id, target_id, label, created_at, updated_at) "
                 "VALUES (?,?,?,?,?,?,?)", (eid, pid, source_id, target_id, label or "", ts, ts))
    return eid


def load_graph(conn, pid):
    nodes = [node_dict(r) for r in conn.execute(
        "SELECT * FROM nodes WHERE project_id = ? ORDER BY created_at, rowid", (pid,))]
    edges = [edge_dict(r) for r in conn.execute(
        "SELECT * FROM edges WHERE project_id = ? ORDER BY created_at, rowid", (pid,))]
    return nodes, edges


STRUCTURE_KEEP = {"validator": ["role", "responsibility"], "input": ["source_system", "format"],
                  "process": ["tool", "manual"], "output": ["format", "frequency"]}


def copy_graph(conn, nodes, edges, dst_pid, mode="full", dx=0, dy=0):
    """Copy nodes/edges (dicts) into dst project with fresh ids. mode: full | structure."""
    idmap = {}
    for n in nodes:
        data = dict(n.get("data") or {})
        title = n.get("title") or ""
        if mode == "structure":
            keep = STRUCTURE_KEEP.get(n.get("type"), [])
            data = {k: v for k, v in data.items() if k in keep}
            if n.get("type") == "validator":
                title = ""  # people differ per client; keep the role, blank the name
        idmap[n["id"]] = insert_node(conn, dst_pid, n.get("type"), title,
                                     float(n.get("x") or 0) + dx, float(n.get("y") or 0) + dy, data)
    count = 0
    for e in edges:
        s, t = idmap.get(e.get("source_id")), idmap.get(e.get("target_id"))
        if s and t and s != t:
            try:
                insert_edge(conn, dst_pid, s, t, e.get("label") or "")
                count += 1
            except ApiError:
                pass
    return idmap


# --------------------------------------------------------------------------
# Seed data
# --------------------------------------------------------------------------
def seed_example(conn):
    pid = insert_project(
        conn, "Example Insurer (sample data)", "Example \u2013 Month-end claims reconciliation",
        "Sample project showing a typical manual month-end claims reconciliation. "
        "Use it as a template: New project \u2192 start from this project.",
        {
            "business_unit": "Finance \u2013 Claims Reporting",
            "engagement_lead": "Jonathan Ng (DSL)",
            "client_sponsor": "Chief Financial Officer",
            "objective": "Automate production of the Monthly Claims Reconciliation workbook, currently "
                         "produced manually each month-end, reducing effort from ~16 hours to ~2 hours while "
                         "improving accuracy and auditability.",
            "in_scope": "Claims paid & outstanding reconciliation to GL; product mapping; variance report.",
            "out_of_scope": "Actuarial reserving (IBNR) calculations; reinsurance recoveries.",
            "risks": "Source system access delayed\nUndocumented business rules held by one person",
            "next_steps": "Schedule process walkthrough with producer\nObtain redacted sample of artifact\n"
                          "Request read-only access to source systems\nValidate current-state diagram with client",
        })
    N = {}

    def add(key, t, title, x, y, **data):
        N[key] = insert_node(conn, pid, t, title, x, y, data)

    add("claims", "input", "Claims extract.xlsx", 40, 40,
        source_system="Claims admin system (ClaimCenter) \u2013 vw_claims_paid", how_obtained="Manual export, emailed by Claims Ops",
        owner="Claims Operations", format="xlsx", refresh="Monthly, BD+1", access="Requested",
        notes="Export filters are applied by hand; occasionally the wrong date range is selected.")
    add("gl", "input", "GL trial balance", 620, 250,
        source_system="SAP S/4HANA GL", how_obtained="Exported from SAP report FBL3N",
        owner="Financial Accounting", format="csv", refresh="Monthly, BD+2", access="N")
    add("map", "input", "Product mapping lookup", 330, 250,
        source_system="Manual Excel lookup (no system of record)", how_obtained="Static sheet maintained by producer",
        owner="Financial Accountant", format="xlsx", refresh="Ad hoc", access="Y",
        notes="Hand-maintained mapping of product codes to reporting lines. Gap: new products are added late.")
    add("paste", "process", "Paste extracts into 'Raw' tabs", 330, 40,
        description="Copy the claims extract and TB into the Raw tabs of the workbook and refresh pivots.",
        performed_by="Financial Accountant", tool="Excel", time_taken="2 hours", manual="Y",
        risk="Copy-paste ranges truncated when row counts grow.")
    add("rules", "process", "Apply mappings & business rules", 620, 40,
        description="VLOOKUP product mapping; exclude cancelled claims; convert FX.",
        performed_by="Financial Accountant", tool="Excel (VLOOKUP, pivots)", time_taken="4 hours", manual="Y",
        business_rules="BR-01 Exclude cancelled claims (Status <> 'CANC')\nBR-02 Map product codes via lookup\n"
                       "BR-03 Convert AUD claims at month-end FX rate",
        risk="Unmapped product codes silently drop out of totals.")
    add("recon", "process", "Reconcile to GL & investigate variances", 910, 40,
        description="Compare claims totals to GL accounts 5100-5199; investigate and journal variances.",
        performed_by="Financial Accountant", tool="Excel + SAP", time_taken="8 hours", manual="Y",
        business_rules="BR-04 Variance > $1,000 must be explained", risk="Judgement-heavy; key-person risk.")
    add("out", "output", "Monthly Claims Reconciliation.xlsx", 1200, 40,
        location="SharePoint > Finance > Month-End > Claims", format="Excel workbook",
        frequency="Monthly \u2013 by BD+5", consumers="Finance Manager, CFO, Board pack",
        effort="~16 hours / 1 person", pain_points="Late when producer is away; multiple versions in circulation; no audit trail.",
        downstream="Board pack claims section; RBNZ quarterly return")
    add("producer", "validator", "Alex Producer", 40, 470,
        role="Financial Accountant", organisation="Example Insurer", responsibility="Process walkthrough",
        email="alex.producer@example.co.nz", phone="+64 21 000 0001", availability="Tue/Thu",
        notes="Currently produces the artifact; can walk through last month's run.")
    add("fm", "validator", "Sam Reviewer", 910, 470,
        role="Finance Manager", organisation="Example Insurer", responsibility="Validator",
        email="sam.reviewer@example.co.nz", phone="+64 21 000 0002",
        validation_tests="T-01 Completeness: claim row counts match ClaimCenter\n"
                         "T-02 Reconciliation: totals tie to GL 5100-5199\nT-06 Uniqueness: no duplicate claim IDs",
        tolerance="Within $1,000 or 0.01% of GL")
    add("cfo", "validator", "Chris Approver", 1200, 470,
        role="Chief Financial Officer", organisation="Example Insurer", responsibility="Sign-off owner",
        email="chris.approver@example.co.nz",
        validation_tests="T-08 Parallel run: automated output equals manual output",
        tolerance="3 consecutive months matching within tolerance")

    for s, t, label in [("claims", "paste", ""), ("paste", "rules", ""),
                        ("map", "rules", "lookup"), ("rules", "recon", ""), ("gl", "recon", "GL balances"),
                        ("recon", "out", "reconciled"), ("producer", "paste", "walkthrough"), ("producer", "rules", "walkthrough"),
                        ("fm", "recon", "validates"), ("cfo", "out", "signs off")]:
        insert_edge(conn, pid, N[s], N[t], label)
    return pid


STARTER_SKELETON = {
    "nodes": [
        {"id": "i1", "type": "input", "title": "", "x": 40, "y": 60},
        {"id": "i2", "type": "input", "title": "", "x": 40, "y": 260},
        {"id": "p1", "type": "process", "title": "", "x": 330, "y": 60},
        {"id": "p2", "type": "process", "title": "", "x": 330, "y": 260},
        {"id": "o1", "type": "output", "title": "", "x": 620, "y": 160},
        {"id": "v1", "type": "validator", "title": "", "x": 330, "y": 470, "data": {"responsibility": "Process walkthrough"}},
        {"id": "v2", "type": "validator", "title": "", "x": 620, "y": 470, "data": {"responsibility": "Sign-off owner"}},
    ],
    "edges": [
        {"source_id": "i1", "target_id": "p1"}, {"source_id": "i2", "target_id": "p2"},
        {"source_id": "p1", "target_id": "p2"}, {"source_id": "p2", "target_id": "o1"},
        {"source_id": "v1", "target_id": "p1", "label": "walkthrough"},
        {"source_id": "v2", "target_id": "o1", "label": "signs off"},
    ],
}


# --------------------------------------------------------------------------
# Exports
# --------------------------------------------------------------------------
def export_project(conn, pid):
    p = project_dict(get_project_row(conn, pid))
    nodes, edges = load_graph(conn, pid)
    return {"format": "flowkb", "version": 1, "exported_at": now(),
            "project": {k: p[k] for k in ("id", "client", "name", "description", "meta", "created_at", "updated_at")},
            "nodes": nodes, "edges": edges}


def topo_order(nodes, edges):
    by_id = {n["id"]: n for n in nodes}
    indeg = {n["id"]: 0 for n in nodes}
    succ = {n["id"]: [] for n in nodes}
    for e in edges:
        if e["source_id"] in by_id and e["target_id"] in by_id:
            # people (validators) don't define process order
            if by_id[e["source_id"]]["type"] == "validator":
                continue
            succ[e["source_id"]].append(e["target_id"])
            indeg[e["target_id"]] += 1
    key = lambda nid: (by_id[nid]["x"], by_id[nid]["y"])
    ready = sorted([n for n, d in indeg.items() if d == 0], key=key)
    order = []
    while ready:
        nid = ready.pop(0)
        order.append(nid)
        for t in succ[nid]:
            indeg[t] -= 1
            if indeg[t] == 0:
                ready.append(t)
                ready.sort(key=key)
    rest = sorted([n for n in by_id if n not in order], key=key)
    return [by_id[n] for n in order + rest]


def mm_label(text):
    t = (text or "").strip() or "(untitled)"
    t = t.replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;")
    return t.replace("\r", "").replace("\n", "<br/>")


def mm_edge_label(text):
    return mm_label(text).replace("|", "#124;")


def to_mermaid(nodes, edges, direction="LR"):
    nodes = topo_order(nodes, edges)
    rank = {"input": 0, "process": 1, "output": 2, "validator": 3}
    ids = {n["id"]: "n%d" % (i + 1) for i, n in enumerate(sorted(nodes, key=lambda n: rank[n["type"]]))}
    types = {n["id"]: n["type"] for n in nodes}
    lines = ["flowchart %s" % direction]
    groups = [("input", "Inputs & original data sources"), ("process", "Process"),
              ("output", "Artifacts / outputs"), ("validator", "People: validation & sign-off")]
    for t, _title in groups:
        group = [n for n in nodes if n["type"] == t]
        if not group:
            continue
        lines.append("    %% " + _title)
        for n in group:
            label = mm_label(n["title"])
            d = n.get("data") or {}
            if t == "input" and d.get("source_system"):
                label += "<br/><small>" + mm_label(d["source_system"]) + "</small>"
            if t == "process" and str(d.get("manual", "")).upper().startswith("Y"):
                label += "<br/><small>manual</small>"
            if t == "validator" and d.get("responsibility"):
                label += "<br/><small>" + mm_label(d["responsibility"]) + "</small>"
            shape = {"input": '[("%s")]', "process": '["%s"]', "output": '[["%s"]]', "validator": '(["%s"])'}[t]
            lines.append("    %s%s:::%s" % (ids[n["id"]], shape % label, t))
    if edges:
        lines.append("    %% Flows")
    for e in edges:
        s, t = ids.get(e["source_id"]), ids.get(e["target_id"])
        if not s or not t:
            continue
        arrow = "-.->" if "validator" in (types.get(e["source_id"]), types.get(e["target_id"])) else "-->"
        lbl = (e.get("label") or "").strip()
        lines.append("    %s %s%s %s" % (s, arrow, ("|%s|" % mm_edge_label(lbl)) if lbl else "", t))
    lines += [
        "    classDef input fill:#dbeafe,stroke:#2563eb,color:#1e3a8a",
        "    classDef process fill:#d1fae5,stroke:#059669,color:#064e3b",
        "    classDef output fill:#fef3c7,stroke:#d97706,color:#78350f",
        "    classDef validator fill:#ede9fe,stroke:#7c3aed,color:#4c1d95",
    ]
    return "\n".join(lines) + "\n"


def md_cell(v):
    s = "" if v is None else str(v)
    s = s.strip().replace("|", "\\|").replace("\r", "")
    return s.replace("\n", "<br>") if s else "\u2014"


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(md_cell(c) for c in r) + " |")
    return "\n".join(out)


def to_markdown(conn, pid):
    p = project_dict(get_project_row(conn, pid))
    nodes, edges = load_graph(conn, pid)
    meta = p["meta"]
    order = topo_order(nodes, edges)
    by_id = {n["id"]: n for n in nodes}
    title = lambda nid: (by_id[nid]["title"] or "(untitled)") if nid in by_id else "?"
    succ, pred = {}, {}
    for e in edges:
        succ.setdefault(e["source_id"], []).append(e["target_id"])
        pred.setdefault(e["target_id"], []).append(e["source_id"])
    of = lambda t: [n for n in order if n["type"] == t]
    D = lambda n: n.get("data") or {}

    def reachable_outputs(nid):
        seen, stack, outs = set(), [nid], []
        while stack:
            c = stack.pop()
            for t in succ.get(c, []):
                if t not in seen:
                    seen.add(t)
                    if by_id[t]["type"] == "output":
                        outs.append(by_id[t]["title"] or "(untitled)")
                    stack.append(t)
        return outs

    L = []
    L.append("# %s" % (p["name"] or "Untitled project"))
    L.append("")
    L.append("**Data Strategy Limited \u2014 Data Workflow Consulting Report**  ")
    L.append("Client: **%s**  " % (p["client"] or "\u2014"))
    L.append("Generated: %s from Flow KB (project #%s)" % (now()[:16].replace("T", " "), p["id"]))
    if p.get("description"):
        L += ["", "> " + p["description"].replace("\n", "\n> ")]
    L += ["", "## 0. Project Snapshot", ""]
    rows = [("Client", p["client"]), ("Project name", p["name"])]
    for f in PROJECT_META_FIELDS[:5]:
        rows.append((f["label"], meta.get(f["key"])))
    rows.append(("Last updated", p["updated_at"][:10]))
    L.append(md_table(["Field", "Details"], rows))
    L += ["", "**One-line objective:** %s" % (meta.get("objective") or "[not yet captured]"), ""]

    L += ["---", "", "## 1. The Starting Artifact (Automation Target)", ""]
    outs = of("output")
    if not outs:
        L.append("_No output / artifact nodes captured yet._")
    for n in outs:
        d = D(n)
        L += ["### %s" % (n["title"] or "(untitled artifact)"), ""]
        L.append(md_table(["Field", "Details"], [(f["label"], d.get(f["key"])) for f in NODE_TYPES["output"]["fields"]] +
                          [("Fed by", ", ".join(title(x) for x in pred.get(n["id"], []) if by_id[x]["type"] != "validator")),
                           ("Validated / signed off by", ", ".join(title(x) for x in pred.get(n["id"], []) + succ.get(n["id"], []) if by_id[x]["type"] == "validator"))]))
        L.append("")

    L += ["---", "", "## 2. People \u2014 Verification, Validation & Sign-off", ""]
    vals = of("validator")
    if vals:
        L.append(md_table(["Name", "Role / team", "Organisation", "Responsibility", "Email", "Phone", "Availability", "Linked to"],
                          [(n["title"], D(n).get("role"), D(n).get("organisation"), D(n).get("responsibility"),
                            D(n).get("email"), D(n).get("phone"), D(n).get("availability"),
                            ", ".join(title(x) for x in succ.get(n["id"], []) + pred.get(n["id"], [])))
                           for n in vals]))
        signoff = [n["title"] for n in vals if D(n).get("responsibility") == "Sign-off owner"]
        L += ["", "**Sign-off owner(s):** %s" % (", ".join(signoff) if signoff else "[not yet identified]")]
    else:
        L.append("_No validator / people nodes captured yet._")
    L.append("")

    L += ["---", "", "## 3. Inputs & Original Data Sources (Lineage)", ""]
    ins = of("input")
    if ins:
        L.append(md_table(["#", "Input (as used today)", "How it's obtained", "Original source system", "Owner",
                           "Refresh / timing", "Format", "Access granted?"],
                          [(i + 1, n["title"], D(n).get("how_obtained"), D(n).get("source_system"), D(n).get("owner"),
                            D(n).get("refresh"), D(n).get("format"), D(n).get("access")) for i, n in enumerate(ins)]))
        L += ["", "**Lineage notes:**", ""]
        for n in ins:
            nxt = ", ".join(title(x) for x in succ.get(n["id"], [])) or "nothing yet (not connected)"
            reach = ", ".join(sorted(set(reachable_outputs(n["id"])))) or "no output yet"
            L.append("- **%s** \u2192 feeds %s; reaches artifact(s): %s." % (n["title"] or "(untitled)", nxt, reach))
            if D(n).get("notes"):
                L.append("  - Notes: %s" % D(n)["notes"].replace("\n", " "))
        gaps = [n["title"] or "(untitled)" for n in ins if not D(n).get("source_system")]
        if gaps:
            L.append("- Gaps where the original source is unknown: %s." % ", ".join(gaps))
    else:
        L.append("_No input data nodes captured yet._")
    L.append("")

    L += ["---", "", "## 4. The Process & Data Validation Tests", "", "### 4a. Current-State Process (Step by Step)", ""]
    procs = of("process")
    if procs:
        L.append(md_table(["Step", "Name", "Description", "Performed by", "Tool / system", "Time taken", "Manual?", "Risk / pain point"],
                          [(i + 1, n["title"], D(n).get("description"), D(n).get("performed_by"), D(n).get("tool"),
                            D(n).get("time_taken"), D(n).get("manual"), D(n).get("risk")) for i, n in enumerate(procs)]))
        rules = [(i + 1, n) for i, n in enumerate(procs) if D(n).get("business_rules")]
        L += ["", "**Business rules & calculations:**", ""]
        if rules:
            for i, n in rules:
                for line in D(n)["business_rules"].splitlines():
                    if line.strip():
                        L.append("- Step %d (%s): %s" % (i, n["title"] or "untitled", line.strip()))
        else:
            L.append("_None captured yet._")
    else:
        L.append("_No process nodes captured yet._")
    L += ["", "### 4b. Validation Tests on Data Sources & Outputs", ""]
    tests = [n for n in vals if D(n).get("validation_tests") or D(n).get("tolerance")]
    if tests:
        L.append(md_table(["Validator", "Responsibility", "Applies to", "Tests", "Expected result / tolerance"],
                          [(n["title"], D(n).get("responsibility"),
                            ", ".join(title(x) for x in succ.get(n["id"], []) + pred.get(n["id"], [])),
                            D(n).get("validation_tests"), D(n).get("tolerance")) for n in tests]))
    else:
        L.append("_No validation tests captured yet \u2014 add them on validator nodes._")
    L += ["", "---", "", "## 5. Data Flow Diagram", "",
          "Current-state flow (generated from the Flow KB canvas). Paste into any Mermaid renderer, e.g. https://mermaid.live.",
          "", "```mermaid", to_mermaid(nodes, edges).rstrip(), "```", ""]

    L += ["---", "", "## 6. Scope, Risks & Next Steps", "",
          "**In scope:** %s  " % (meta.get("in_scope") or "[ ]"),
          "**Out of scope:** %s" % (meta.get("out_of_scope") or "[ ]"), ""]
    risks = [r.strip() for r in (meta.get("risks") or "").splitlines() if r.strip()]
    L.append(md_table(["Risk / assumption / issue", "Impact", "Owner", "Mitigation"], [(r, "", "", "") for r in risks] or [("[ ]", "", "", "")]))
    L.append("")
    steps = [r.strip() for r in (meta.get("next_steps") or "").splitlines() if r.strip()]
    L.append(md_table(["Next step", "Owner", "Due"], [(r, "", "") for r in steps] or [("[ ]", "", "")]))
    L += ["", "---", "", "## Appendix \u2014 Client Quick-Start Checklist", ""]
    chk = [
        ("Section 0 snapshot completed", bool(p["client"] and meta.get("engagement_lead") and meta.get("objective"))),
        ("Starting artifact captured", bool(outs)),
        ("Process walkthrough contact identified", any(D(n).get("responsibility") == "Process walkthrough" for n in vals)),
        ("Sign-off owner confirmed", any(D(n).get("responsibility") == "Sign-off owner" for n in vals)),
        ("All inputs traced to original sources", bool(ins) and all(D(n).get("source_system") for n in ins)),
        ("Business rules documented", any(D(n).get("business_rules") for n in procs)),
        ("Validation tests captured", bool(tests)),
        ("Every node connected in the flow", bool(nodes) and all(n["id"] in succ or n["id"] in pred for n in nodes)),
    ]
    for label, ok in chk:
        L.append("- [%s] %s" % ("x" if ok else " ", label))
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------
# API handlers
# --------------------------------------------------------------------------
def counts_for(conn):
    res = {}
    for r in conn.execute("SELECT project_id, type, COUNT(*) c FROM nodes GROUP BY project_id, type"):
        res.setdefault(r["project_id"], {})[r["type"]] = r["c"]
    for r in conn.execute("SELECT project_id, COUNT(*) c FROM edges GROUP BY project_id"):
        res.setdefault(r["project_id"], {})["edges"] = r["c"]
    return res


def h_schema(conn, g, q, b):
    return {"app": APP_NAME, "version": APP_VERSION, "node_types": NODE_TYPES,
            "project_meta_fields": PROJECT_META_FIELDS, "responsibilities": RESPONSIBILITIES,
            "known_clients": KNOWN_CLIENTS, "db_path": os.path.relpath(DB_PATH, APP_DIR)}


def h_health(conn, g, q, b):
    return {"ok": True, "app": APP_NAME, "version": APP_VERSION}


def h_list_projects(conn, g, q, b):
    c = counts_for(conn)
    return [project_dict(r, c.get(r["id"], {})) for r in
            conn.execute("SELECT * FROM projects ORDER BY lower(client), lower(name), id")]


def h_clients(conn, g, q, b):
    have = [r[0] for r in conn.execute("SELECT DISTINCT client FROM projects WHERE client <> '' ORDER BY lower(client)")]
    return sorted(set(have + KNOWN_CLIENTS), key=str.lower)


def h_create_project(conn, g, q, b):
    b = b or {}
    name = (b.get("name") or "").strip()
    if not name:
        raise ApiError(400, "Project name is required")
    start = b.get("start_from") or "blank"   # blank | skeleton | project
    src = b.get("source_project_id")
    mode = b.get("copy_mode") or "full"
    meta = b.get("meta") if isinstance(b.get("meta"), dict) else {}
    if start == "project":
        if not src:
            raise ApiError(400, "source_project_id is required when starting from a project")
        srow = get_project_row(conn, int(src))
        if mode == "full":
            meta = dict(loads(srow["meta"], {}), **meta)
        else:
            meta = dict({k: v for k, v in loads(srow["meta"], {}).items() if k in ("in_scope", "out_of_scope")}, **meta)
    pid = insert_project(conn, (b.get("client") or "").strip(), name, b.get("description") or "", meta,
                         int(src) if start == "project" else None)
    if start == "skeleton":
        copy_graph(conn, STARTER_SKELETON["nodes"], STARTER_SKELETON["edges"], pid)
    elif start == "project":
        nodes, edges = load_graph(conn, int(src))
        copy_graph(conn, nodes, edges, pid, mode=mode)
    return 201, h_get_project(conn, (str(pid),), q, None)


def h_get_project(conn, g, q, b):
    pid = int(g[0])
    p = project_dict(get_project_row(conn, pid))
    p["nodes"], p["edges"] = load_graph(conn, pid)
    return p


def h_update_project(conn, g, q, b):
    pid = int(g[0])
    row = get_project_row(conn, pid)
    b = b or {}
    client = b.get("client", row["client"])
    name = b.get("name", row["name"])
    if not (name or "").strip():
        raise ApiError(400, "Project name cannot be empty")
    desc = b.get("description", row["description"])
    meta = loads(row["meta"], {})
    if isinstance(b.get("meta"), dict):
        meta.update(clean_data(b["meta"]))
    conn.execute("UPDATE projects SET client=?, name=?, description=?, meta=?, updated_at=? WHERE id=?",
                 (client, name, desc, json.dumps(meta), now(), pid))
    return project_dict(get_project_row(conn, pid))


def h_delete_project(conn, g, q, b):
    pid = int(g[0])
    get_project_row(conn, pid)
    conn.execute("DELETE FROM projects WHERE id = ?", (pid,))
    return {"deleted": pid}


def h_duplicate_project(conn, g, q, b):
    pid = int(g[0])
    row = get_project_row(conn, pid)
    b = b or {}
    return h_create_project(conn, (), q, {
        "client": b.get("client", row["client"]),
        "name": b.get("name") or ("Copy of " + row["name"]),
        "description": b.get("description", row["description"]),
        "start_from": "project", "source_project_id": pid, "copy_mode": b.get("copy_mode") or "full"})


def h_create_node(conn, g, q, b):
    pid = int(g[0])
    get_project_row(conn, pid)
    b = b or {}
    nid = insert_node(conn, pid, b.get("type"), b.get("title") or "", b.get("x") or 0, b.get("y") or 0, b.get("data"))
    touch_project(conn, pid)
    return 201, node_dict(conn.execute("SELECT * FROM nodes WHERE id=?", (nid,)).fetchone())


def get_node_row(conn, nid):
    row = conn.execute("SELECT * FROM nodes WHERE id = ?", (nid,)).fetchone()
    if not row:
        raise ApiError(404, "Node %s not found" % nid)
    return row


def h_get_node(conn, g, q, b):
    return node_dict(get_node_row(conn, g[0]))


def h_update_node(conn, g, q, b):
    row = get_node_row(conn, g[0])
    b = b or {}
    title = b.get("title", row["title"])
    x = float(b.get("x", row["x"]))
    y = float(b.get("y", row["y"]))
    ntype = b.get("type", row["type"])
    if ntype not in NODE_TYPES:
        raise ApiError(400, "Unknown node type %r" % ntype)
    data = loads(row["data"], {})
    if "data" in b:
        if b.get("replace_data"):
            data = clean_data(b["data"])
        else:
            data.update(clean_data(b["data"] or {}))
            data = {k: v for k, v in data.items() if v != ""} if b.get("drop_empty") else data
    sets = ", ".join("%s = ?" % c for c in KEY_COLUMNS)
    conn.execute("UPDATE nodes SET type=?, title=?, x=?, y=?, data=?, %s, updated_at=? WHERE id=?" % sets,
                 [ntype, title or "", x, y, json.dumps(data)] + key_values(data) + [now(), row["id"]])
    touch_project(conn, row["project_id"])
    return node_dict(get_node_row(conn, row["id"]))


def h_delete_node(conn, g, q, b):
    row = get_node_row(conn, g[0])
    removed = [r["id"] for r in conn.execute("SELECT id FROM edges WHERE source_id=? OR target_id=?", (row["id"], row["id"]))]
    conn.execute("DELETE FROM nodes WHERE id = ?", (row["id"],))
    touch_project(conn, row["project_id"])
    return {"deleted": row["id"], "deleted_edges": removed}


def h_layout(conn, g, q, b):
    pid = int(g[0])
    get_project_row(conn, pid)
    n = 0
    for pos in (b or {}).get("positions", []):
        cur = conn.execute("UPDATE nodes SET x=?, y=?, updated_at=? WHERE id=? AND project_id=?",
                           (float(pos["x"]), float(pos["y"]), now(), pos["id"], pid))
        n += cur.rowcount
    touch_project(conn, pid)
    return {"updated": n}


def h_create_edge(conn, g, q, b):
    pid = int(g[0])
    get_project_row(conn, pid)
    b = b or {}
    eid = insert_edge(conn, pid, b.get("source_id"), b.get("target_id"), b.get("label") or "")
    touch_project(conn, pid)
    return 201, edge_dict(conn.execute("SELECT * FROM edges WHERE id=?", (eid,)).fetchone())


def get_edge_row(conn, eid):
    row = conn.execute("SELECT * FROM edges WHERE id = ?", (eid,)).fetchone()
    if not row:
        raise ApiError(404, "Edge %s not found" % eid)
    return row


def h_update_edge(conn, g, q, b):
    row = get_edge_row(conn, g[0])
    b = b or {}
    conn.execute("UPDATE edges SET label=?, updated_at=? WHERE id=?", (b.get("label", row["label"]) or "", now(), row["id"]))
    touch_project(conn, row["project_id"])
    return edge_dict(get_edge_row(conn, row["id"]))


def h_delete_edge(conn, g, q, b):
    row = get_edge_row(conn, g[0])
    conn.execute("DELETE FROM edges WHERE id = ?", (row["id"],))
    touch_project(conn, row["project_id"])
    return {"deleted": row["id"]}


def slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "_", s or "project").strip("_")[:60] or "project"


def h_export(conn, g, q, b):
    pid = int(g[0])
    fmt = (q.get("format") or ["json"])[0]
    row = get_project_row(conn, pid)
    base = slug(row["client"] + "_" + row["name"])
    if fmt == "json":
        body = json.dumps(export_project(conn, pid), indent=2, ensure_ascii=False)
        return Raw(body, "application/json; charset=utf-8", base + ".flowkb.json")
    if fmt in ("mermaid", "mmd"):
        nodes, edges = load_graph(conn, pid)
        direction = (q.get("direction") or ["LR"])[0].upper()
        direction = direction if direction in ("LR", "TB", "TD", "RL", "BT") else "LR"
        return Raw(to_mermaid(nodes, edges, direction), "text/plain; charset=utf-8", base + ".mmd")
    if fmt in ("markdown", "md"):
        return Raw(to_markdown(conn, pid), "text/markdown; charset=utf-8", base + ".md")
    raise ApiError(400, "Unknown export format %r (json | mermaid | markdown)" % fmt)


def h_export_all(conn, g, q, b):
    ids = [r[0] for r in conn.execute("SELECT id FROM projects ORDER BY id")]
    body = {"format": "flowkb-backup", "version": 1, "exported_at": now(),
            "projects": [export_project(conn, i) for i in ids]}
    return Raw(json.dumps(body, indent=2, ensure_ascii=False), "application/json; charset=utf-8",
               "flowkb_backup_%s.json" % datetime.date.today().isoformat())


def import_one(conn, doc, name_override=None, client_override=None):
    if not isinstance(doc, dict) or not isinstance(doc.get("nodes", []), list):
        raise ApiError(400, "Not a Flow KB project export")
    proj = doc.get("project") or {}
    name = name_override or proj.get("name") or "Imported project"
    pid = insert_project(conn, client_override if client_override is not None else proj.get("client", ""),
                         name, proj.get("description", ""), proj.get("meta") if isinstance(proj.get("meta"), dict) else {})
    nodes = [n for n in doc.get("nodes", []) if isinstance(n, dict) and n.get("type") in NODE_TYPES and n.get("id")]
    edges = [e for e in doc.get("edges", []) if isinstance(e, dict)]
    copy_graph(conn, nodes, edges, pid)
    return pid


def h_import(conn, g, q, b):
    if not isinstance(b, dict):
        raise ApiError(400, "Expected a JSON object")
    if b.get("format") == "flowkb-backup":
        ids = [import_one(conn, d) for d in b.get("projects", [])]
        return 201, {"imported_project_ids": ids}
    name = (b.get("project") or {}).get("name") or "Imported project"
    existing = conn.execute("SELECT 1 FROM projects WHERE name = ?", (name,)).fetchone()
    pid = import_one(conn, b, (name + " (imported)") if existing else None)
    return 201, {"imported_project_ids": [pid], "project": h_get_project(conn, (str(pid),), q, None)}


def h_search(conn, g, q, b):
    ntype = (q.get("type") or [""])[0]
    text = (q.get("q") or [""])[0].strip()
    client = (q.get("client") or [""])[0].strip()
    field = (q.get("field") or [""])[0].strip()
    value = (q.get("value") or [""])[0].strip()
    sql = ("SELECT n.*, p.client AS client, p.name AS project_name FROM nodes n "
           "JOIN projects p ON p.id = n.project_id WHERE 1=1")
    args = []
    if ntype:
        if ntype not in NODE_TYPES:
            raise ApiError(400, "Unknown type")
        sql += " AND n.type = ?"
        args.append(ntype)
    if client:
        sql += " AND p.client = ?"
        args.append(client)
    if text:
        sql += " AND (n.title LIKE ? OR n.data LIKE ? OR p.name LIKE ? OR p.client LIKE ?)"
        args += ["%" + text + "%"] * 4
    if field and value:
        if field not in KEY_COLUMNS:
            raise ApiError(400, "field must be one of: " + ", ".join(KEY_COLUMNS))
        sql += " AND n.%s LIKE ?" % field
        args.append("%" + value + "%")
    sql += " ORDER BY lower(p.client), lower(p.name), n.type, lower(n.title) LIMIT 2000"
    out = []
    for r in conn.execute(sql, args):
        d = node_dict(r)
        d["client"] = r["client"]
        d["project_name"] = r["project_name"]
        out.append(d)
    return out


def h_sql(conn, g, q, b):
    sql = ((b or {}).get("sql") or "").strip().rstrip(";").strip()
    if not sql:
        raise ApiError(400, "Enter a SQL query")
    if not re.match(r"(?is)^\s*(select|with|pragma\s+table_info|explain)\b", sql):
        raise ApiError(400, "Only read-only queries (SELECT / WITH) are allowed here")
    uri = pathlib.Path(DB_PATH).resolve().as_uri() + "?mode=ro"
    ro = sqlite3.connect(uri, uri=True, timeout=10)
    try:
        ro.execute("PRAGMA query_only = ON")
        try:
            cur = ro.execute(sql)
        except (sqlite3.Error, sqlite3.Warning) as e:
            raise ApiError(400, "SQL error: %s" % e)
        cols = [c[0] for c in (cur.description or [])]
        rows = cur.fetchmany(5001)
        truncated = len(rows) > 5000
        return {"columns": cols, "rows": [list(r) for r in rows[:5000]], "truncated": truncated}
    finally:
        ro.close()





def set_db_path(path):
    global DB_PATH
    DB_PATH = os.path.abspath(path)
