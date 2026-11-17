import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
import packs as PK  # noqa: E402

GOOD = {"sc_copilot_lines": 1, "name": "Space Cowboy", "personality": "hauler",
        "lines": {"arm_on": "Holster up, partner.", "arm_off": "Guns out.", "kill_first": "{victim} bit the dust.",
                  "kill_n": "{victim} down. {n} notches.", "greeting": "Howdy.", "ack.gear_down": "Boots on the ground."}}


def issue_body(pack_text, name="Space Cowboy", desc="Yeehaw in space."):
    return (f"### Pack name\n\n{name}\n\n### Description\n\n{desc}\n\n### Pack file (paste the exported JSON)\n\n"
            f"```json\n{pack_text}\n```\n\n### Rules\n\n- [X] I wrote these lines myself\n- [X] No real-person impersonation")


def test_repo_packs_are_valid_and_indexed():
    assert PK.check() == 0


def test_validate_catches_problems():
    bad = json.loads(json.dumps(GOOD))
    bad["lines"]["arm_on"] = "Visit www.example.com"
    bad["lines"]["kill_first"] = "{victim} by {weapon}"
    bad["lines"]["nope"] = "x"
    errs = PK.validate(bad)
    assert any("links" in e for e in errs)
    assert any("{weapon}" in e for e in errs)
    assert any("Unknown line name: nope" in e for e in errs)
    assert PK.validate(GOOD) == []
    assert PK.validate({"lines": {}})


def test_from_issue_adds_pack(tmp_path, monkeypatch):
    monkeypatch.setattr(PK, "PACKS", tmp_path)
    path, errs = PK.from_issue(issue_body(json.dumps(GOOD)), "someone", 42)
    assert not errs and path.name == "space-cowboy.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["author"] == "someone" and saved["issue"] == 42 and saved["description"] == "Yeehaw in space."
    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert index["packs"][0]["id"] == "space-cowboy" and index["packs"][0]["lines"] == 6
    other, errs = PK.from_issue(issue_body(json.dumps(GOOD)), "someone-else", 43)
    assert other.name == "space-cowboy-2.json"


def test_from_issue_rejects_garbage(tmp_path, monkeypatch):
    monkeypatch.setattr(PK, "PACKS", tmp_path)
    path, errs = PK.from_issue(issue_body("not json at all"), "x", 1)
    assert path is None and "valid JSON" in errs[0]
