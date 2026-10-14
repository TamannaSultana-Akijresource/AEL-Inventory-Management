"""Client for the enterprise API gateway (MCP over HTTP).

The AEL dashboard reads the DWH through the gateway's read-only query tool
(``execute_readonly_query``) instead of connecting to SQL Server directly.

Credentials are resolved (in order):
  1. environment variables   AEL_GATEWAY_URL / AEL_GATEWAY_TOKEN / AEL_GATEWAY_DEVICE_ID
  2. .streamlit/secrets.toml  [gateway]  (url / token / device_id)
  3. an opencode.json / opencode.jsonc that declares the
     "enterprise-api-gateway" MCP server (searched in common locations)

The token is a secret - keep it out of git (secrets.toml is git-ignored).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

DEFAULT_URL = "https://enterprise-api-gateway.ibos.agency/mcp"
DEFAULT_SOURCE = "dwh"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def _from_env() -> dict:
    return {
        "url": os.environ.get("AEL_GATEWAY_URL"),
        "token": os.environ.get("AEL_GATEWAY_TOKEN"),
        "device_id": os.environ.get("AEL_GATEWAY_DEVICE_ID"),
    }


def _from_secrets() -> dict:
    path = HERE / ".streamlit" / "secrets.toml"
    try:
        import tomllib
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    g = data.get("gateway") or {}
    return {"url": g.get("url"), "token": g.get("token"), "device_id": g.get("device_id")}


def _candidate_opencode_files() -> list[Path]:
    out = []
    for base in (HERE, *HERE.parents):
        out.append(base / "opencode.json")
        out.append(base / "opencode.jsonc")
    out.append(Path.home() / ".config" / "opencode" / "opencode.json")
    out.append(Path.home() / ".config" / "opencode" / "opencode.jsonc")
    if os.environ.get("APPDATA"):
        out.append(Path(os.environ["APPDATA"]) / "opencode" / "opencode.json")
    return out


def _strip_jsonc(text: str) -> str:
    import re
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(^|\s)//.*?$", r"\1", text, flags=re.M)
    return text


def _from_opencode() -> dict:
    for path in _candidate_opencode_files():
        if not path.exists():
            continue
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except Exception:
            try:
                data = json.loads(_strip_jsonc(raw))
            except Exception:
                continue
        mcp = (data.get("mcp") or {}).get("enterprise-api-gateway")
        if not mcp:
            continue
        url = mcp.get("url")
        headers = mcp.get("headers") or {}
        auth = headers.get("Authorization", "")
        token = auth.split(" ", 1)[1] if auth.lower().startswith("bearer ") else auth
        return {"url": url, "token": token or None,
                "device_id": headers.get("X-Device-Id")}
    return {}


def get_config() -> dict:
    cfg = {"url": None, "token": None, "device_id": None}
    for source in (_from_env(), _from_secrets(), _from_opencode()):
        for k, v in source.items():
            if v and not cfg.get(k):
                cfg[k] = v
    cfg["url"] = cfg["url"] or DEFAULT_URL
    return cfg


def config_is_complete(cfg: dict | None = None) -> bool:
    cfg = cfg or get_config()
    return bool(cfg.get("url") and cfg.get("token"))


def describe(cfg: dict | None = None) -> str:
    cfg = cfg or get_config()
    tok = cfg.get("token") or ""
    masked = (tok[:10] + "..." + tok[-4:]) if len(tok) > 16 else ("(set)" if tok else "(missing)")
    return (f"url={cfg.get('url')}\ntoken={masked}\n"
            f"device_id={cfg.get('device_id') or '(none)'}")


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------
def _post(payload: dict, cfg: dict, timeout: int = 120) -> dict:
    url = cfg["url"]
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    req.add_header("Authorization", f"Bearer {cfg['token']}")
    if cfg.get("device_id"):
        req.add_header("X-Device-Id", cfg["device_id"])
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            ctype = (resp.headers.get("Content-Type") or "").lower()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"Gateway HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Gateway unreachable: {e.reason}") from e

    if "text/event-stream" in ctype:
        result = None
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if not chunk or chunk == "[DONE]":
                continue
            try:
                obj = json.loads(chunk)
            except Exception:
                continue
            if isinstance(obj, dict) and ("result" in obj or "error" in obj):
                result = obj
        if result is None:
            raise RuntimeError("Gateway returned an empty event stream.")
        return result
    return json.loads(raw)


def call_tool(name: str, arguments: dict, cfg: dict | None = None) -> dict:
    """Call an MCP tool and return the parsed JSON object it produced."""
    cfg = cfg or get_config()
    if not config_is_complete(cfg):
        raise RuntimeError("Gateway credentials are not configured (url/token).")
    resp = _post({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }, cfg)

    if "error" in resp and resp["error"]:
        raise RuntimeError(f"Gateway error: {resp['error']}")
    result = resp.get("result") or {}
    if result.get("isError"):
        text = _text_of(result)
        raise RuntimeError(f"Gateway tool error: {text[:400]}")
    text = _text_of(result)
    return json.loads(text) if text else {}


def _text_of(result: dict) -> str:
    parts = [c.get("text", "") for c in (result.get("content") or [])
             if isinstance(c, dict) and c.get("type") == "text"]
    return "".join(parts)


# ---------------------------------------------------------------------------
# Query helper
# ---------------------------------------------------------------------------
def run_query(sql: str, source: str = DEFAULT_SOURCE, limit: int = 500,
              max_bytes: int = 4_000_000, cfg: dict | None = None) -> list[dict]:
    """Run a read-only SELECT through the gateway and return a list of row dicts."""
    data = call_tool("execute_readonly_query", {
        "sql": sql, "source": source, "limit": limit,
        "format": "rows", "max_bytes": max_bytes,
    }, cfg)
    return data.get("rows", [])


def ping() -> str:
    """Cheap connectivity check - returns a short status string."""
    rows = run_query("SELECT TOP 1 GETDATE() AS now", limit=1)
    return f"Gateway OK - server time {rows[0]['now']}" if rows else "Gateway OK (no rows)"


if __name__ == "__main__":
    cfg = get_config()
    print("Gateway configuration")
    print(describe(cfg))
    if not config_is_complete(cfg):
        print("\nIncomplete. Set AEL_GATEWAY_URL / AEL_GATEWAY_TOKEN or the [gateway] "
              "section in .streamlit/secrets.toml.")
        raise SystemExit(1)
    try:
        print("\n" + ping())
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAILED: {exc}")
        raise SystemExit(2)
