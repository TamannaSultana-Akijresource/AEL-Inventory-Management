# AEL — MTD Order Fulfilment & Stock Coverage (open code edition)

A self-contained rebuild of the AEL dashboard. It reads the DWH, builds a
single interactive `index.html`, and pushes it to GitHub so your GitHub Pages
link always shows the latest numbers.

- **Daily / automated path:** `run_daily.bat` → `generate_dashboard.py`
- **Interactive path (with manual editing):** `app.py` (Streamlit)

---

## Quick start

1. **One-time setup** — double-click **`setup.bat`**.
   It creates a private `.venv`, installs the packages, and connects this
   folder to the GitHub repository.

2. **Credentials** — open `.streamlit/secrets.toml` and put your working
   database details under `[mssql]`. (When you first `run_daily.bat`, the push
   will ask you to sign in to GitHub once; Windows remembers it afterwards.)

3. **Daily run** — double-click **`run_daily.bat`**.
   It rebuilds `index.html` and pushes it. Your GitHub Pages URL updates
   automatically (it always serves `index.html` from the `main` branch).

---

## What each file does

| File | Purpose |
|------|---------|
| `run_daily.bat` | The daily button: rebuild + publish. |
| `setup.bat` | One-time environment + git setup. |
| `generate_dashboard.py` | Headless generator: DWH → `index.html` → GitHub. |
| `app.py` | Interactive Streamlit dashboard with manual cell editing. |
| `dashboard.py` | Business rules + the standalone HTML builder. |
| `queries.py` | The SQL (summary + order history). |
| `db.py` | Database connection + credential resolution. |
| `config.py` | Scope, ship points, colours, GitHub settings. |
| `github_publish.py` | `git`-based push helper. |
| `index.html` | The published dashboard (regenerated on every run). |
| `html_exports/` | Timestamped archive of every generated report. |
| `logs/` | Run logs. |

---

## Command-line options

```bat
python generate_dashboard.py            :: real data, stays local
python generate_dashboard.py --push     :: real data, push to GitHub
python generate_dashboard.py --demo     :: synthetic data (no database), local
python generate_dashboard.py --date 2026-10-01 --push
python generate_dashboard.py --open     :: open the report when done
```

Streamlit app:

```bat
streamlit run app.py
```

---

## Run it every day automatically

Once `run_daily.bat` works, schedule it with Windows Task Scheduler:

1. Open **Task Scheduler** → **Create Basic Task**.
2. Trigger: **Daily**, pick a time (e.g. 08:00).
3. Action: **Start a program** → browse to `run_daily.bat`.
4. Tick **Run whether user is logged on or not**.

The dashboard and the GitHub repository are then refreshed unattended.

---

## GitHub authentication

`github_publish.py` uses ordinary `git`, so it works with whatever you already
use for GitHub:

- **Git Credential Manager** (default on Windows) — sign in once interactively.
- **Personal Access Token** — set the `GITHUB_TOKEN` environment variable and
  the push uses it automatically (good for Task Scheduler / headless runs).

The GitHub Pages site must be enabled once: repository **Settings → Pages →
Source: Deploy from a branch → `main` / `/ (root)`**. After that, every push
replaces `index.html` and the site updates within a minute.

---

## Business rules

| Status | Rule |
|--------|------|
| **Risk** | `Diff. < 0` (stock cannot cover open variance) |
| **Pay Attention** | `0 ≤ Diff. ≤ 50` bag |
| **Safe** | `Diff. > 50` bag |
| **Check Again** | `Stock < 0` (ledger gap — verify, not a real shortage) |

`Diff. = Stock − Variance in Order Quantity`. Only **Bag**-UOM order lines are
reported. `TVS` is the source code for **AEL Tejgoan**.

---

## Notes

- The dashboard never writes to the database (read-only `SELECT`s).
- `.streamlit/secrets.toml`, `logs/`, `html_exports/` and `.venv/` are
  git-ignored, so no credentials ever reach GitHub.
- `index.html` is intentionally committed — it is the published artifact.
