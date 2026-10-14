"""Publish the generated dashboard to GitHub using plain ``git``.

Works with whatever authentication you already have for GitHub:
  * Git Credential Manager (the default on Windows - login once, stored), or
  * a Personal Access Token in the ``GITHUB_TOKEN`` environment variable, or
  * ``gh auth login`` (GitHub CLI) if installed.

No third-party libraries required.
"""

from __future__ import annotations

import os
import subprocess
import urllib.parse
from pathlib import Path

import config as C


def _run(args: list[str], cwd: Path, timeout: int = 180, check: bool = True,
         env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=str(cwd), capture_output=True, text=True,
        timeout=timeout, check=check, env=env,
    )


def _git(args: list[str], cwd: Path, **kw) -> subprocess.CompletedProcess:
    return _run(["git", *args], cwd, **kw)


def ensure_repo(repo_dir: Path, remote_url: str = C.GITHUB_REPO,
                branch: str = C.GITHUB_BRANCH) -> list[str]:
    """Initialise the git repo + remote if missing. Returns log lines."""
    log: list[str] = []
    repo_dir.mkdir(parents=True, exist_ok=True)

    if not (repo_dir / ".git").exists():
        _git(["init"], repo_dir)
        log.append("Initialised a new git repository.")
    try:
        _git(["checkout", "-B", branch], repo_dir, check=False)
    except Exception:
        pass

    remotes = _git(["remote"], repo_dir).stdout.split()
    if "origin" in remotes:
        _git(["remote", "set-url", "origin", remote_url], repo_dir)
    else:
        _git(["remote", "add", "origin", remote_url], repo_dir)
    log.append(f"Remote 'origin' -> {remote_url} ({branch}).")
    return log


def _authed_url(remote_url: str) -> str:
    """Inject GITHUB_TOKEN into an https remote URL when available."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token or not remote_url.startswith("https://"):
        return remote_url
    if "@" in remote_url.split("://", 1)[1]:
        return remote_url
    scheme, rest = remote_url.split("://", 1)
    return f"{scheme}://x-access-token:{urllib.parse.quote(token)}@{rest}"


def publish(repo_dir: Path, files: list[str], message: str,
            branch: str = C.GITHUB_BRANCH) -> tuple[bool, str]:
    """Stage ``files``, commit if changed, and push. Never commits secrets."""
    try:
        for f in files:
            if not (repo_dir / f).exists():
                return False, f"Nothing to publish: {f} does not exist."
            _git(["add", "--", f], repo_dir)

        diff = _git(["diff", "--cached", "--quiet"], repo_dir, check=False)
        if diff.returncode == 0:
            return True, "Remote already has the latest dashboard - nothing to push."

        _git(["commit", "-m", message], repo_dir)

        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        target = _authed_url(C.GITHUB_REPO) if token else "origin"
        push = _git(["push", target, f"HEAD:{branch}"], repo_dir,
                    timeout=300, check=False)
        if push.returncode != 0:
            err = (push.stderr or push.stdout or "").strip()
            return False, ("git push failed. Authenticate once with Git Credential "
                           f"Manager or set GITHUB_TOKEN.\n{err}")
        return True, "Pushed to GitHub. Your GitHub Pages link is now updated."
    except subprocess.TimeoutExpired:
        return False, "GitHub publish timed out."
    except subprocess.CalledProcessError as e:
        return False, f"GitHub publish failed: {(e.stderr or e.stdout or str(e)).strip()}"
    except Exception as e:  # noqa: BLE001
        return False, f"GitHub publish failed: {e}"


def _push_env(repo_dir: Path) -> dict:
    """Reserved for future per-run git environment tweaks."""
    return dict(os.environ)


def status() -> str:
    """Human-readable auth/git summary for the console."""
    cwd = C.HERE
    lines = []
    try:
        v = _git(["--version"], cwd, check=False).stdout.strip()
        lines.append(v or "git not found")
    except Exception:
        lines.append("git not found")
    if os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"):
        lines.append("GITHUB_TOKEN is set (token push enabled).")
    else:
        lines.append("Using Git Credential Manager / stored credentials.")
    return "\n".join(lines)
