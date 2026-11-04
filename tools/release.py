"""Build, sign and publish a release that units install over the air.

    python tools/release.py             # build dist/ledgames-<version>.tar.gz + .sig
    python tools/release.py --publish   # …and publish it as a GitHub release

The version is __version__ in ledgames/__init__.py: bump it and commit
first. Only committed code goes into a release, and --publish needs that
commit pushed to GitHub.

Signing key: ~/.config/ledgames/release-key.pem (or $LEDGAMES_RELEASE_KEY).
Keep a backup somewhere safe: units only accept releases signed with it, so
losing it means updating every unit by hand.

GitHub access: $GITHUB_TOKEN, or the login git already uses for github.com.
"""

import argparse
import gzip
import io
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives import serialization

ROOT = Path(__file__).resolve().parent.parent
REPO = "bazy1983/game-pi"
CONTENTS = ["ledgames", "web", "deploy", "requirements.txt", "requirements-pi.txt", "README.md"]
DEFAULT_KEY = Path.home() / ".config" / "ledgames" / "release-key.pem"


def git(*args: str, input: str | None = None) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True, input=input).stdout


def committed_version() -> str:
    m = re.search(r'__version__ = "([^"]+)"', git("show", "HEAD:ledgames/__init__.py"))
    if not m:
        sys.exit("No __version__ in ledgames/__init__.py")
    return m.group(1)


def build(version: str) -> tuple[Path, Path]:
    tar = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD", *CONTENTS], cwd=ROOT, check=True, capture_output=True
    ).stdout
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(tar)
    data = buf.getvalue()

    key_path = Path(os.environ.get("LEDGAMES_RELEASE_KEY", DEFAULT_KEY))
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    archive = dist / f"ledgames-{version}.tar.gz"
    sig = archive.with_name(archive.name + ".sig")
    archive.write_bytes(data)
    sig.write_bytes(key.sign(data))
    return archive, sig


def github_token() -> str:
    if token := os.environ.get("GITHUB_TOKEN"):
        return token
    out = git("credential", "fill", input="protocol=https\nhost=github.com\n\n")
    creds = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    if "password" not in creds:
        sys.exit("No GitHub login found: set GITHUB_TOKEN")
    return creds["password"]


def api(token: str, method: str, url: str, body: bytes | None = None, content_type: str = "application/json"):
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", content_type)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read() or b"{}")


def publish(version: str, files: list[Path], notes: str) -> str:
    if git("status", "--porcelain", "--untracked-files=no").strip():
        sys.exit("Commit your changes first: releases are built from the last commit.")
    head = git("rev-parse", "HEAD").strip()
    git("fetch", "-q", "origin")
    if "origin/" not in git("branch", "-r", "--contains", head):
        sys.exit("Push your commit to GitHub first.")
    token = github_token()
    release = api(
        token,
        "POST",
        f"https://api.github.com/repos/{REPO}/releases",
        json.dumps({"tag_name": f"v{version}", "target_commitish": head, "name": version, "body": notes}).encode(),
    )
    upload = release["upload_url"].split("{")[0]
    for f in files:
        api(token, "POST", f"{upload}?name={f.name}", f.read_bytes(), "application/octet-stream")
    return release["html_url"]


def main() -> None:
    p = argparse.ArgumentParser(description="Build and sign a LED Games release")
    p.add_argument("--publish", action="store_true", help="publish it as a GitHub release")
    p.add_argument("--notes", default="", help="release notes")
    args = p.parse_args()

    version = committed_version()
    archive, sig = build(version)
    print(f"Built {archive.relative_to(ROOT)} ({archive.stat().st_size // 1024} KB) and its signature")
    if args.publish:
        print("Published:", publish(version, [archive, sig], args.notes))


if __name__ == "__main__":
    main()
