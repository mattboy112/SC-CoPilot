import pytest

import sc_memory as M


@pytest.mark.parametrize("text,want", [
    ("remember that my main ship is a Cutlass Black", ("remember", "my main ship is a Cutlass Black")),
    ("Co-Pilot, remember I run salvage in Stanton", ("remember", "I run salvage in Stanton")),
    ("note: my org is Sea Suns", ("remember", "my org is Sea Suns")),
    ("keep in mind I hate Pyro", ("remember", "I hate Pyro")),
    ("forget that my main ship is a cutlass", ("forget", "my main ship is a cutlass")),
    ("forget everything", ("forget", "everything")),
    ("what do you remember about me?", ("recall", None)),
])
def test_voice_commands(text, want):
    cmd = M.parse_command(text, "Co-Pilot")
    assert (cmd["op"], cmd.get("fact")) == want


@pytest.mark.parametrize("text", ["remember where I parked", "do you remember the patch notes", "gear down", "remember"])
def test_questions_and_other_things_go_to_the_ai(text):
    assert M.parse_command(text) is None


def test_add_skips_repeats_and_has_a_limit():
    s = {}
    assert M.add(s, "my main ship is a Cutlass Black") == ("My main ship is a Cutlass Black", "Noted.")
    assert M.add(s, "My main ship is a cutlass black.")[0] == ""
    assert M.add(s, "hi")[0] == ""
    words = ["Aurora", "Hornet", "Prospector", "Vulture", "Caterpillar", "Constellation", "Freelancer", "Mercury", "Corsair",
             "Hammerhead", "Carrack", "Reclaimer", "Arrow", "Gladius", "Sabre", "Vanguard", "Retaliator", "Starfarer", "Hull C",
             "Polaris", "Perseus", "Idris", "Javelin", "Ironclad", "Galaxy", "Zeus", "Spirit", "Hercules", "Valkyrie", "Raft",
             "Nomad", "Cutter", "Pisces", "Reliant", "Herald", "Terrapin", "Eclipse", "Ares", "Scorpius"]
    for w in words[:M.MAX_ITEMS - 1]:
        assert M.add(s, f"I own a {w}")[1] == "Noted."
    assert len(s["memories"]) == M.MAX_ITEMS
    assert "full" in M.add(s, "one too many facts here")[1]


def test_forget_finds_the_closest_note():
    s = {"memories": ["My main ship is a Cutlass Black", "I mostly do salvage", "My org is Sea Suns"]}
    assert M.forget(s, "the cutlass") == ("My main ship is a Cutlass Black", "Forgotten.")
    assert M.forget(s, "something about quantum drives") == ("", "I don't have a note like that.")
    assert M.forget(s, "everything")[1] == "Cleared all 2 notes."
    assert s["memories"] == []


def test_recall_says_it_back_to_you():
    s = {"memories": ["I mostly do salvage", "My org is Sea Suns"]}
    assert M.recall(s) == "You mostly do salvage. Your org is Sea Suns."
    assert "Nothing yet" in M.recall({})
    many = {"memories": [f"Fact {i}" for i in range(6)]}
    assert M.recall(many).startswith("I've got 6 notes.")


def test_the_ai_sees_the_notes_and_can_change_them():
    import threading
    import types
    import sc_brain as BR
    settings = {"ai_mode": "own_key", "api_key": "x", "memories": ["My main ship is a Cutlass Black"]}
    calls = []
    app = types.SimpleNamespace(settings=settings, remember_fact=lambda f: calls.append(("r", f)) or "Noted.",
                                forget_fact=lambda f: calls.append(("f", f)) or "Forgotten.",
                                state=types.SimpleNamespace(lock=threading.RLock(), handle="P", snapshot_text=lambda: ""),
                                note_system=lambda *a: None)
    b = BR.Brain(app)
    sent = []

    def fake(body, on_text=None):
        sent.append(body)
        return {"content": [{"type": "text", "text": "Copy."}], "stop_reason": "end_turn", "usage": {}}
    b._request = fake
    b.ask("hi")
    system = sent[0]["system"][0]["text"]
    assert "Things the pilot asked you to remember:\n- My main ship is a Cutlass Black" in system
    assert {"remember", "forget"} <= {t["name"] for t in sent[0]["tools"]}
    assert b.run_tool("remember", {"fact": "I fly for Sea Suns"}) == "Noted."
    assert b.run_tool("forget", {"fact": "cutlass"}) == "Forgotten."
    assert calls == [("r", "I fly for Sea Suns"), ("f", "cutlass")]
