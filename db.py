"""Database helpers for the AEL dashboard (open code edition).

Credentials are resolved (in order) from:
  1. Streamlit secrets          [mssql]                (when running `streamlit run`)
  2. .streamlit/secrets.toml     [mssql]                (next to this file)
  3. environment variables       DWH_SERVER / DWH_USER / DWH_PASSWORD / ...
  4. ..\\hub\\config\\db.env       (the shared hub config, searched upward)

Nothing here writes to the database - read-only SELECTs only.
"""

from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _hub_env_candidates() -> list[Path]:
    """The shared hub env file may live a level or two above this folder."""
    out = []
    for parent in (HERE, *HERE.parents):
        cand = parent / "hub" / "config" / "db.env"
        out.append(cand)
        if parent == parent.parent:
            break
    return out


def _read_toml(path: Path) -> dict:
    try:
        import tomllib  # Python 3.11+
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_env_file(path: Path) -> dict:
    out = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    except Exception:
        pass
    return out


def _raw() -> dict:
    # 1) Streamlit secrets
    try:
        import streamlit as st
        for key in ("mssql", "database", "db"):
            if key in st.secrets:
                return dict(st.secrets[key])
    except Exception:
        pass

    # 2) local secrets.toml
    data = _read_toml(HERE / ".streamlit" / "secrets.toml")
    for key in ("mssql", "database", "db"):
        if key in data:
            return dict(data[key])

    # 3) environment, then 4) the shared hub env file
    env = dict(os.environ)
    for cand in _hub_env_candidates():
        if cand.exists():
            env.update(_read_env_file(cand))
            break
    if env.get("DWH_SERVER"):
        return dict(
            server=env["DWH_SERVER"],
            port=env.get("DWH_PORT", 1433),
            database=env.get("DWH_DATABASE", "DWH"),
            user=env.get("DWH_USER"),
            password=env.get("DWH_PASSWORD"),
            driver=env.get("DWH_DRIVER", "ODBC Driver 17 for SQL Server"),
        )
    return {}


def get_config() -> dict:
    r = _raw()
    return dict(
        host=r.get("server") or r.get("host") or "",
        port=int(r.get("port") or 1433),
        database=r.get("database") or r.get("db") or "",
        user=r.get("uid") or r.get("user") or r.get("username") or "",
        password=r.get("pwd") or r.get("password") or "",
        driver=r.get("driver") or "ODBC Driver 17 for SQL Server",
    )


def config_is_complete(cfg: dict) -> bool:
    return all(cfg.get(k) for k in ("host", "database", "user", "password"))


def _connect(cfg: dict):
    import pyodbc
    driver = str(cfg["driver"]).strip("{}")
    cs = (
        f"DRIVER={{{driver}}};SERVER={cfg['host']},{cfg['port']};"
        f"DATABASE={cfg['database']};UID={cfg['user']};PWD={cfg['password']};"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(cs, timeout=20)


def heartbeat():
    """Return the SQL Server clock, or None if unreachable."""
    cfg = get_config()
    if not config_is_complete(cfg):
        return None
    try:
        with _connect(cfg) as conn:
            cur = conn.cursor()
            cur.execute("SELECT GETDATE()")
            return cur.fetchone()[0]
    except Exception:
        return None


def run_query(sql: str, params: dict | None = None):
    """Run a SELECT and return a DataFrame. `params` fills {name} placeholders."""
    if not sql:
        raise RuntimeError(
            "AEL queries.py is not configured (SUMMARY_SQL / DETAIL_SQL are None)."
        )
    import pandas as pd

    cfg = get_config()
    if not config_is_complete(cfg):
        raise RuntimeError("AEL database credentials are not configured.")
    text = sql.format(**params) if params else sql
    with _connect(cfg) as conn:
        return pd.read_sql(text, conn)
