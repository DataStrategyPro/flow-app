# Flow KB (FastHTML edition)

**Data Strategy Limited.** Flow KB is an interactive flowchart knowledge base for client data-workflow projects, such as Example Client A and Example Client B. It replaces the Word/Markdown *Project Starter Template*. You type directly onto the nodes, and every change autosaves to SQLite. Earlier projects can seed new ones.

The app is built with **FastHTML**, which serves the pages, the login and the JSON API, and uses HTMX on the login form. The canvas is plain JavaScript/SVG served from `static/`. The app is ready for **Plash** (https://pla.sh) at **https://flow.datastrategypro.com**.

## Features

* **Projects** have a client and a name. You can create, rename, duplicate and delete them. A new project can start from:
  * a **blank canvas**,
  * the **DSL starter skeleton**, or
  * **an earlier project**:
    * *Structure only* keeps node types, titles, systems and roles but clears details and people's names.
    * *Everything* copies all fields.
* **Canvas:** add nodes from the toolbar or by double-clicking the background, drag them to move, and drag the **●** handle onto another node to connect them. Connections can have labels. **Delete** removes the selected item. Drag the background to pan and use the mouse wheel to zoom; **Fit** and **Tidy** are on the toolbar.
* **Node types:**

  | Node type | Shape and colour | Fields |
  |---|---|---|
  | **Input data** | blue | source system, how obtained, owner, format, refresh, access, notes |
  | **Process** | green | description, performed by, tool, time, manual Y/N, business rules, risk, notes |
  | **Output** | amber; this is the month-end artifact | location, format, frequency, consumers, effort, pain points, downstream, notes |
  | **Validator** | purple | name, role, organisation, responsibility, email, phone, availability, validation tests, tolerance |

  Responsibility is one of: walkthrough, validator, sign-off owner, SME or controls reviewer.
* **Editing:** type on the node title. Click **▸** on a node to edit its fields in place, or use the side panel. Everything autosaves.
* **Exports:**
  * **Markdown report** following template sections 0–6, with the Mermaid diagram and an auto-ticked checklist.
  * **Mermaid flowchart**.
  * **Project JSON**.
  * **Backup of all projects**.
* **Import** reads a project JSON or a backup and always creates new projects.
* **Search KB** searches across projects. Presets cover validators and contacts, sign-off owners, inputs by source system, manual steps, steps by tool, and artifacts.
* **SQL** is a read-only console. Queries run on a `mode=ro` connection with `query_only`, one statement per run. It includes CSV download.
* **Seed data:** the example project *"Example – Month-end claims reconciliation"* (10 nodes) is created on first run.

## Security

* **Every page, static file and API route requires login.** The only exceptions are `/login` and `/favicon.ico`.
* The password comes from the **`FLOWKB_PASSWORD`** environment variable. **The app refuses to start if it's missing or shorter than 8 characters.** There is no default password.
* Sessions use a signed cookie (`flowkb_session`):
  * HttpOnly, SameSite=Lax.
  * Secure (HTTPS-only) on Plash.
  * Valid for 30 days.
  * Changing the password logs everyone out.
* **Signing key:** `data/.sesskey` (persisted), or `FLOWKB_SESSION_SECRET` if you set it.
* **Wrong passwords:** each failure is delayed by 1 s. After 10 failures in 15 minutes, that IP is blocked with HTTP 429.
* **CSRF:** state-changing API calls must be `application/json`, which forces a CORS preflight for cross-site requests. Together with SameSite=Lax cookies, this blocks CSRF.
* There is a single shared password. There are no per-user accounts.

## Run locally

Requires Python 3.10+.

```bash
cd flow-kb-fasthtml
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Option A: environment variable
FLOWKB_PASSWORD='a-long-passphrase' python main.py
#   Windows PowerShell:  $env:FLOWKB_PASSWORD='a-long-passphrase'; python main.py
# Option B: copy plash.env.example to plash.env, edit the password, then:
python main.py
```

Open **http://localhost:5001** and log in. To use another local port, set `FLOWKB_PORT=8080`. Production always uses 5001.

## Deploy to Plash (flow.datastrategypro.com)

Plash conventions this app follows:

* **Entry point:** `main.py`, which calls FastHTML `serve()`.
* **Dependencies:** `requirements.txt`.
* **Port:** **5001**, the only port Plash exposes. It's pinned in production.
* **Persistent files:** only `data/` survives redeploys.
* **Secrets:** go in `plash.env`, as `export KEY=VALUE` lines.
* **Production flag:** Plash sets `PLASH_PRODUCTION=1` automatically.

1. **Install and log in to the CLI.** This needs a Plash account at https://pla.sh with an active subscription.
   ```bash
   pip install plash-cli
   plash-login            # opens the browser to authenticate
   ```
   Current plash-cli (0.3.x) commands are hyphenated: `plash-deploy`, `plash-login`, `plash-view` and `plash-logs`. Older docs show `plash_deploy`.
2. **Set the password.**
   ```bash
   cp plash.env.example plash.env
   # edit plash.env:  export FLOWKB_PASSWORD='a-long-random-passphrase'
   ```
   `plash.env` is uploaded with the app and becomes environment variables on Plash. Keep it out of git; `.gitignore` already excludes it.
3. **Point DNS at Plash.** At the DNS provider for **datastrategypro.com**, add:

   | Type | Name / Host | Value / Target | TTL |
   |---|---|---|---|
   | CNAME | `flow` | `pla.sh` | Auto / 3600 |

   If you use Cloudflare, set the record to **DNS only** (grey cloud) unless you know Plash works behind Cloudflare's proxy. Check propagation with `nslookup flow.datastrategypro.com` or `dig CNAME flow.datastrategypro.com`. It can take up to 48 hours but is usually quicker.
4. **Deploy.** The included **`.plash`** file already contains:
   ```bash
   export PLASH_APP_NAME='flow.datastrategypro.com'
   ```
   Then run:
   ```bash
   plash-deploy
   ```
   If `.plash` goes missing, the equivalent is `plash-deploy --name flow.datastrategypro.com`. Without either, Plash would generate a random `*.pla.sh` name.
5. **Verify.** Run `plash-view`, or open https://flow.datastrategypro.com. It should redirect to the login page. Run `plash-logs` if the build or startup fails. A missing `FLOWKB_PASSWORD` shows as "Flow KB refuses to start".

### Redeploying and your data

* `plash-deploy` replaces all app files **but keeps the production `data/` folder**: the database `data/flowkb.db` and the session key. The local `data/` folder is **not** uploaded.
* `plash-deploy --force-data` **deletes the production `data/` folder and replaces it with your local one.** Only use it deliberately, for example to seed production with a local database. It overwrites everything captured on the live site. Make a backup first with **Export ▾ → Backup of all projects**.
* Plash also keeps automatic backups of `data/`: hourly for 5 hours, plus 2-day, 2-week and 2-month snapshots. `plash-download` fetches the deployed app, including data.
* **To change the password:** edit `plash.env`, then run `plash-deploy`. Existing sessions are logged out.

## Where the data lives

`data/flowkb.db` is a single SQLite file. It's created, with the seeded example project, on first run. Override the location with `FLOWKB_DB=/path/file.db`.

| Table | Columns |
|---|---|
| `projects` | id, client, name, description, meta (JSON: snapshot/scope/risks/next steps), source_project_id (the project it was seeded from), created_at, updated_at |
| `nodes` | id, project_id, type (`input`/`process`/`output`/`validator`), title, x, y, **data** (JSON with all fields), created_at, updated_at |
| `edges` | id, project_id, source_id, target_id, label, created_at, updated_at |

`nodes` also has indexed key columns copied from `data`: source_system, owner, format, refresh, performed_by, tool, manual, frequency, location, role, organisation, email, phone, responsibility.

Views: `v_nodes`, `v_inputs`, `v_processes`, `v_outputs`, `v_validators`, `v_edges`. Each includes `client` and `project`.

### Example SQL

Run these in the in-app **SQL** console, or locally with `sqlite3 data/flowkb.db`.

```sql
-- Every validator / sign-off contact across all clients
SELECT client, project, name, role, responsibility, email, phone
FROM v_validators ORDER BY client, responsibility;

-- Which source systems feed our projects, and for which clients?
SELECT source_system, COUNT(*) AS inputs, GROUP_CONCAT(DISTINCT client) AS clients
FROM v_inputs GROUP BY source_system ORDER BY inputs DESC;

-- Manual steps and the time they take
SELECT client, project, step, performed_by, tool, json_extract(data, '$.time_taken') AS time_taken
FROM v_processes WHERE manual = 'Y';

-- Full lineage of one project
SELECT source_type, source, label, target_type, target FROM v_edges WHERE project LIKE '%claims%';

-- Reusable validation tests from earlier engagements
SELECT client, name, json_extract(data, '$.validation_tests') AS tests, json_extract(data, '$.tolerance') AS tolerance
FROM v_validators WHERE json_extract(data, '$.validation_tests') IS NOT NULL;

-- Which projects were seeded from which
SELECT p.client, p.name, s.name AS seeded_from FROM projects p LEFT JOIN projects s ON s.id = p.source_project_id;
```

## API (login required; JSON)

| Endpoint | Purpose |
|---|---|
| `GET/POST /api/projects` | list projects / create one. Body: `client`, `name`, `start_from` = `blank`/`skeleton`/`project`, `source_project_id`, `copy_mode` = `full`/`structure` |
| `GET/PATCH/DELETE /api/projects/{id}` | read, update or delete a project. `POST /api/projects/{id}/duplicate` copies it. `PUT /api/projects/{id}/layout` saves node positions |
| `POST /api/projects/{id}/nodes` | add a node. Use `GET/PATCH/DELETE /api/nodes/{id}` to read, change or remove it |
| `POST /api/projects/{id}/edges` | add an edge. Use `PATCH/DELETE /api/edges/{id}` to change or remove it |
| `GET /api/projects/{id}/export?format=json\|mermaid\|markdown[&download=1]` | export a project |
| `GET /api/export-all` | back up every project |
| `POST /api/import` | import a project JSON or backup |
| `GET /api/search?type=&q=&client=&field=&value=` | search across projects |
| `POST /api/sql` | read-only SQL |

Log in for scripted use:

```bash
curl -c jar -d 'password=...' https://flow.datastrategypro.com/login
curl -b jar https://flow.datastrategypro.com/api/projects
```

## Files

| File | Purpose |
|---|---|
| `main.py` | FastHTML app: login, pages, API routes, `serve()` on port 5001 |
| `flowkb_core.py` | schema, seed data, handlers, Markdown/Mermaid/JSON exports. Uses stdlib `sqlite3` |
| `static/app.js`, `static/style.css` | the canvas UI (vanilla JS/SVG) |
| `requirements.txt` | `python-fasthtml` |
| `.plash` | `PLASH_APP_NAME='flow.datastrategypro.com'` |
| `plash.env.example` | template for `plash.env`, which holds the password |
| `.gitignore` | excludes `data/`, `plash.env` and the venv |
| `data/` | created at runtime; persistent on Plash |
