"""Community line packs: check them, build packs/index.json, and add a pack from an approved GitHub issue.

python packaging/packs.py check                      validate every pack and make sure the index is up to date
python packaging/packs.py build-index                rewrite packs/index.json
python packaging/packs.py from-issue BODY_FILE --author LOGIN --issue N
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packs"
sys.path.insert(0, str(ROOT / "App"))

import sc_lines as LN  # noqa: E402

PLACEHOLDERS = {k: set(re.findall(r"\{(\w+)\}", ph)) for _g, rows in LN.CALLOUTS for k, _l, _d, ph in rows}
MAX_LINE = 300
MIN_LINES = 5


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:40] or "pack"


def validate(pack):
    """List of problems; empty means the pack is fine."""
    errs = []
    if not isinstance(pack, dict):
        return ["The pack must be a JSON object, like the file the app exports."]
    if pack.get("sc_copilot_lines") != 1:
        errs.append('Missing "sc_copilot_lines": 1. Export the pack from the app\'s Personality tab and paste the whole file.')
    name = str(pack.get("name", "")).strip()
    if not 3 <= len(name) <= 40:
        errs.append("The name must be 3 to 40 characters.")
    if len(str(pack.get("description", ""))) > 160:
        errs.append("The description must be 160 characters or less.")
    if pack.get("personality", "standard") not in LN.PERSONALITIES:
        errs.append(f"Unknown base personality: {pack.get('personality')!r}.")
    lines = pack.get("lines")
    if not isinstance(lines, dict):
        return errs + ['"lines" must be an object of line names to text.']
    if len([v for v in lines.values() if str(v).strip()]) < MIN_LINES:
        errs.append(f"A pack needs at least {MIN_LINES} lines.")
    for key, text in lines.items():
        if key not in LN.DEFAULTS:
            errs.append(f"Unknown line name: {key}.")
            continue
        text = str(text)
        if len(text) > MAX_LINE:
            errs.append(f"{key}: longer than {MAX_LINE} characters.")
        if re.search(r"https?://|www\.|\.com\b|discord\.gg", text, re.I):
            errs.append(f"{key}: no links please.")
        used = set(re.findall(r"\{(\w+)\}", text))
        allowed = PLACEHOLDERS.get(key, set())
        if used - allowed:
            errs.append(f"{key}: {{{', '.join(sorted(used - allowed))}}} isn't available in this line"
                        + (f" (you can use {', '.join('{' + a + '}' for a in sorted(allowed))})." if allowed else "."))
    return errs


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def entry(path, pack):
    return {"id": path.stem, "name": pack["name"], "author": pack.get("author", ""), "description": pack.get("description", ""),
            "personality": pack.get("personality", "standard"), "lines": len(pack.get("lines", {})),
            "added": pack.get("added", ""), "file": f"packs/{path.name}"}


def index_data():
    items = [entry(p, load(p)) for p in sorted(PACKS.glob("*.json")) if p.name != "index.json"]
    return {"sc_copilot_packs": 1, "packs": sorted(items, key=lambda e: (e["added"], e["name"]), reverse=True)}


def write_index():
    (PACKS / "index.json").write_text(json.dumps(index_data(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def check():
    bad = 0
    for p in sorted(PACKS.glob("*.json")):
        if p.name == "index.json":
            continue
        try:
            errs = validate(load(p))
        except ValueError as ex:
            errs = [f"not valid JSON: {ex}"]
        for e in errs:
            print(f"{p.name}: {e}")
        bad += len(errs)
    cur = json.loads((PACKS / "index.json").read_text(encoding="utf-8")) if (PACKS / "index.json").exists() else None
    if cur != index_data():
        print("packs/index.json is out of date. Run: python packaging/packs.py build-index")
        bad += 1
    print("packs ok" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


def parse_issue(body):
    """Pull the fields out of a GitHub issue-form body."""
    fields, cur = {}, None
    for raw in body.splitlines():
        m = re.match(r"^###\s+(.*)$", raw)
        if m:
            cur = m.group(1).strip().lower()
            fields[cur] = []
        elif cur:
            fields[cur].append(raw)
    out = {k: "\n".join(v).strip() for k, v in fields.items()}
    js = next((v for k, v in out.items() if "json" in k or "file" in k or "lines" in k), "")
    js = re.sub(r"^```(?:json)?\s*|\s*```$", "", js.strip())
    name = next((v for k, v in out.items() if "name" in k), "").strip()
    desc = next((v for k, v in out.items() if "description" in k), "").strip()
    return name, desc, js


def from_issue(body, author, issue):
    name, desc, js = parse_issue(body)
    try:
        pack = json.loads(js)
    except ValueError as ex:
        return None, [f"The pasted pack isn't valid JSON ({ex}). Paste the whole exported file."]
    if not isinstance(pack, dict):
        return None, ["The pasted pack must be the whole exported file."]
    if name and name != "_No response_":
        pack["name"] = name
    if desc and desc != "_No response_":
        pack["description"] = desc[:160]
    pack["author"] = author
    pack["added"] = date.today().isoformat()
    pack["issue"] = issue
    errs = validate(pack)
    if errs:
        return None, errs
    path = PACKS / f"{slugify(pack['name'])}.json"
    n = 2
    while path.exists() and load(path).get("author") != author:
        path = PACKS / f"{slugify(pack['name'])}-{n}.json"
        n += 1
    ordered = {k: pack[k] for k in ("sc_copilot_lines", "name", "author", "description", "personality", "added", "issue") if k in pack}
    ordered["lines"] = pack["lines"]
    path.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_index()
    return path, []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "build-index", "from-issue"])
    ap.add_argument("body", nargs="?")
    ap.add_argument("--author", default="")
    ap.add_argument("--issue", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "check":
        sys.exit(check())
    if a.cmd == "build-index":
        write_index()
        print("index written")
        return
    path, errs = from_issue(Path(a.body).read_text(encoding="utf-8"), a.author, a.issue)
    result = ROOT / "pack_result.md"
    if errs:
        result.write_text("Thanks! The pack couldn't be added yet:\n\n" + "\n".join(f"- {e}" for e in errs)
                          + "\n\nEdit the issue to fix it, then remove and re-add the `pack-approved` label.", encoding="utf-8")
        sys.exit(1)
    result.write_text(f"Thanks! **{load(path)['name']}** is now in the community gallery. Players can install it from "
                      f"**Personality → Browse community packs** in SC Co-Pilot.", encoding="utf-8")
    print(f"added {path.name}")


if __name__ == "__main__":
    main()
