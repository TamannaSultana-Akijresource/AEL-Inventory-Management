"""Quick connection check for the AEL dashboard.

Run:  python check_connection.py

Prints which database/credentials are being used (never the password) and
whether the dashboard can reach the DWH. If the DWH is not reachable it lists
the databases the login *can* see, so you can correct `.streamlit/secrets.toml`.
"""

from __future__ import annotations

import sys

from db import _connect, config_is_complete, get_config


def main() -> int:
    cfg = get_config()
    print("Resolved configuration")
    print(f"  host     : {cfg['host'] or '(missing)'}")
    print(f"  port     : {cfg['port']}")
    print(f"  database : {cfg['database'] or '(missing)'}")
    print(f"  user     : {cfg['user'] or '(missing)'}")
    print(f"  driver   : {cfg['driver']}")
    print(f"  complete : {config_is_complete(cfg)}")
    print()

    if not config_is_complete(cfg):
        print("Result: credentials are incomplete.")
        print("Edit .streamlit/secrets.toml and fill the [mssql] section.")
        return 1

    try:
        with _connect(cfg) as conn:
            cur = conn.cursor()
            cur.execute("SELECT DB_NAME(), SUSER_SNAME(), GETDATE()")
            db, user, now = cur.fetchone()
            print("Result: CONNECTED")
            print(f"  database : {db}")
            print(f"  login    : {user}")
            print(f"  clock    : {now}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print("Result: CONNECT FAILED")
        print(f"  {str(exc)[:300]}")
        print()

    # Fall back to master and list what this login can actually open.
    try:
        cfg2 = dict(cfg, database="master")
        with _connect(cfg2) as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sys.databases WHERE HAS_DBACCESS(name)=1 ORDER BY name")
            names = [r[0] for r in cur.fetchall()]
        print("Databases this login can open:")
        for n in names:
            marker = "  <= current" if n.lower() == cfg["database"].lower() else ""
            print(f"  - {n}{marker}")
        print()
        print("If 'DWH' is not in the list, either the password/account changed or the")
        print("database name is different. Update .streamlit/secrets.toml and re-run.")
    except Exception as exc:  # noqa: BLE001
        print(f"Could not enumerate databases: {str(exc)[:200]}")

    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.exit(130)
