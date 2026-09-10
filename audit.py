#!/usr/bin/env python3
"""Minimal language completeness audit for Geeklog plugins.

The English file (language/english.php) is the reference. The audit checks the
main FR/DE/ES/JA language files and reports missing translation keys.

Language PHP files are parsed as text; they are never executed.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

ORG = os.environ.get("GEEKLOG_ORG", "Geeklog-Plugins")
REPORT = Path(os.environ.get("REPORT_FILE", "REPORT.md"))

LANGUAGES = {
    "FR": ("french",),
    "DE": ("german",),
    "ES": ("spanish",),
    "JA": ("japanese",),
}

Key = Tuple[str, str]


def github_json(url: str):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "geeklog-language-audit",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def list_repositories(org: str) -> List[dict]:
    repos: List[dict] = []
    page = 1
    while True:
        batch = github_json(
            f"https://api.github.com/orgs/{org}/repos?type=public&per_page=100&page={page}"
        )
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return sorted(repos, key=lambda r: r["name"].lower())


def clone_repository(clone_url: str, branch: str, destination: Path) -> bool:
    proc = subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", "--branch", branch, clone_url, str(destination)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc.returncode == 0


def matching_close(text: str, start: int) -> Optional[int]:
    pairs = {"(": ")", "[": "]", "{": "}"}
    opener = text[start]
    closer = pairs[opener]
    stack = [closer]
    i = start + 1
    quote: Optional[str] = None
    line_comment = False
    block_comment = False

    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""

        if line_comment:
            if ch == "\n":
                line_comment = False
            i += 1
            continue
        if block_comment:
            if ch == "*" and nxt == "/":
                block_comment = False
                i += 2
            else:
                i += 1
            continue
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue

        if ch in ("'", '"'):
            quote = ch
            i += 1
            continue
        if ch == "/" and nxt == "/":
            line_comment = True
            i += 2
            continue
        if ch == "#":
            line_comment = True
            i += 1
            continue
        if ch == "/" and nxt == "*":
            block_comment = True
            i += 2
            continue
        if ch in pairs:
            stack.append(pairs[ch])
        elif stack and ch == stack[-1]:
            stack.pop()
            if not stack:
                return i
        i += 1
    return None


def split_top_level(text: str, delimiter: str = ",") -> List[str]:
    parts: List[str] = []
    start = 0
    stack: List[str] = []
    pairs = {"(": ")", "[": "]", "{": "}"}
    i = 0
    quote: Optional[str] = None
    line_comment = False
    block_comment = False

    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if line_comment:
            if ch == "\n":
                line_comment = False
            i += 1
            continue
        if block_comment:
            if ch == "*" and nxt == "/":
                block_comment = False
                i += 2
            else:
                i += 1
            continue
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == "/" and nxt == "/":
            line_comment = True
            i += 1
        elif ch == "#":
            line_comment = True
        elif ch == "/" and nxt == "*":
            block_comment = True
            i += 1
        elif ch in pairs:
            stack.append(pairs[ch])
        elif stack and ch == stack[-1]:
            stack.pop()
        elif ch == delimiter and not stack:
            parts.append(text[start:i])
            start = i + 1
        i += 1
    parts.append(text[start:])
    return parts


def find_top_level_arrow(text: str) -> Optional[int]:
    stack: List[str] = []
    pairs = {"(": ")", "[": "]", "{": "}"}
    i = 0
    quote: Optional[str] = None
    line_comment = False
    block_comment = False
    while i < len(text) - 1:
        ch, nxt = text[i], text[i + 1]
        if line_comment:
            if ch == "\n":
                line_comment = False
            i += 1
            continue
        if block_comment:
            if ch == "*" and nxt == "/":
                block_comment = False
                i += 2
            else:
                i += 1
            continue
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == "/" and nxt == "/":
            line_comment = True
            i += 1
        elif ch == "#":
            line_comment = True
        elif ch == "/" and nxt == "*":
            block_comment = True
            i += 1
        elif ch in pairs:
            stack.append(pairs[ch])
        elif stack and ch == stack[-1]:
            stack.pop()
        elif ch == "=" and nxt == ">" and not stack:
            return i
        i += 1
    return None


def parse_literal_key(text: str) -> Optional[str]:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S).strip()
    text = re.sub(r"(?m)//.*$|#.*$", "", text).strip()
    m = re.fullmatch(r"(['\"])(.*?)\1", text, flags=re.S)
    if m:
        return m.group(2)
    if re.fullmatch(r"-?\d+", text):
        return str(int(text))
    return None


def parse_php_language(path: Path) -> Set[Key]:
    text = path.read_text(encoding="utf-8", errors="replace")
    keys: Set[Key] = set()

    # Standard Geeklog style: $LANG_FOO = array(...) or $LANG_FOO = [...]
    assign = re.compile(r"\$(LANG[A-Za-z0-9_]*)\s*=\s*(?:array\s*\(|\[)", re.I)
    for match in assign.finditer(text):
        var = match.group(1)
        opener_pos = match.end() - 1
        end = matching_close(text, opener_pos)
        if end is None:
            continue
        body = text[opener_pos + 1 : end]
        next_index = 0
        for item in split_top_level(body):
            item = item.strip()
            if not item:
                continue
            arrow = find_top_level_arrow(item)
            if arrow is None:
                key = str(next_index)
                next_index += 1
            else:
                key = parse_literal_key(item[:arrow])
                if key is None:
                    continue
                if re.fullmatch(r"-?\d+", key):
                    next_index = max(next_index, int(key) + 1)
            keys.add((var, key))

    # Also catch direct assignments such as $LANG_FOO['key'] = 'value';
    direct = re.compile(
        r"\$(LANG[A-Za-z0-9_]*)\s*\[\s*(['\"])(.*?)\2\s*\]\s*=",
        re.S | re.I,
    )
    for match in direct.finditer(text):
        keys.add((match.group(1), match.group(3)))

    return keys


def find_language_file(language_dir: Path, prefixes: Iterable[str]) -> Optional[Path]:
    if not language_dir.is_dir():
        return None
    candidates = []
    for path in language_dir.glob("*.php"):
        stem = path.stem.lower().replace("-", "_")
        if any(stem == p or stem.startswith(p + "_") for p in prefixes):
            candidates.append(path)
    if not candidates:
        return None

    # Prefer UTF-8 variants, then the shortest/canonical filename.
    candidates.sort(
        key=lambda p: (
            0 if "utf" in p.stem.lower() else 1,
            len(p.name),
            p.name.lower(),
        )
    )
    return candidates[0]


def cell(status: dict) -> str:
    if status["state"] == "complete":
        return "✅"
    if status["state"] == "missing_file":
        return "❌ missing"
    return f"⚠️ {status['missing']} missing"


def main() -> int:
    repos = list_repositories(ORG)
    rows = []
    audited = 0

    with tempfile.TemporaryDirectory(prefix="geeklog-language-audit-") as tmp:
        root = Path(tmp)
        for repo in repos:
            if repo.get("fork"):
                continue
            target = root / repo["name"]
            if not clone_repository(repo["clone_url"], repo["default_branch"], target):
                continue

            english = target / "language" / "english.php"
            if not english.is_file():
                continue

            reference = parse_php_language(english)
            if not reference:
                continue
            audited += 1
            statuses: Dict[str, dict] = {}
            needs_attention = False

            for code, prefixes in LANGUAGES.items():
                lang_file = find_language_file(english.parent, prefixes)
                if lang_file is None:
                    statuses[code] = {"state": "missing_file", "missing": len(reference)}
                    needs_attention = True
                    continue

                translated = parse_php_language(lang_file)
                missing = reference - translated
                if missing:
                    statuses[code] = {
                        "state": "incomplete",
                        "missing": len(missing),
                        "file": lang_file.name,
                    }
                    needs_attention = True
                else:
                    statuses[code] = {
                        "state": "complete",
                        "missing": 0,
                        "file": lang_file.name,
                    }

            if needs_attention:
                rows.append((repo["name"], statuses))

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Geeklog Plugins — Language Audit",
        "",
        f"Generated: **{now}**  ",
        f"Organization: **{ORG}**  ",
        f"Plugins audited: **{audited}**",
        "",
        "English (`language/english.php`) is the reference. Only plugins/languages requiring attention are listed.",
        "",
        "| Plugin | FR | DE | ES | JA |",
        "|---|---:|---:|---:|---:|",
    ]

    if rows:
        for plugin, statuses in rows:
            lines.append(
                f"| [{plugin}](https://github.com/{ORG}/{plugin}) "
                f"| {cell(statuses['FR'])} | {cell(statuses['DE'])} "
                f"| {cell(statuses['ES'])} | {cell(statuses['JA'])} |"
            )
    else:
        lines.append("| — | ✅ | ✅ | ✅ | ✅ |")

    lines += [
        "",
        "Legend: ✅ complete · ⚠️ language file exists but keys are missing · ❌ language file not found.",
        "",
        "_This is a structural key audit only; it does not assess translation quality._",
        "",
    ]

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {REPORT} ({len(rows)} plugins require attention).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
