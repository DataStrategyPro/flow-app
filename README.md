# Flow KB (local-only build)

Data Strategy Limited's flowchart knowledge base for client data-workflow projects, set up to run only on your own computer.

* **No login.** There is no password, no login page, no rate limit and no stored session key.
* **Local only.** It listens on 127.0.0.1, so nothing outside this computer can reach it.
* **No hosting config.** Never deploy this folder or push it to GitHub. The hosted and public versions keep normal authentication.

## Run

Requires Python 3.10+.

```bash
./start-local.sh
```

Or by hand: `python -m venv .venv`, activate it, `pip install -r requirements.txt`, then `python main.py`.
Open http://127.0.0.1:5001. To use another port, set `FLOWKB_PORT=8080`.

## Data

Everything is in `data/flowkb.db`, a SQLite file created (with an example project) on first run.
To bring projects over from another Flow KB, use **Export > Backup of all projects** there and **Import** here.
