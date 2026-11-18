import pytest

import sc_brain as BR

CUT = [
    "Prices are player-reported, so double-check before you haul.",
    "Keep in mind this may have changed in the latest patch.",
    "I got this from the internet, so verify it in game.",
    "According to UEX, Laranite sells best at Area18.",
    "Let me check that for you.",
    "Those numbers could be different now.",
    "As of the current patch, it's at Lorville.",
    "You'll want to verify that at the terminal.",
    "Data's a few hours old.",
    "As an AI, I can't be sure.",
]
KEEP = [
    "Best sell is Area18, about thirty aUEC a unit.",
    "I found two refineries in range: CRU-L1 and ARC-L1.",
    "According to the log, you've got three kills this session.",
    "Gear down.",
    "No reading on fuel from here.",
    "Lorville has a refinery and a clinic.",
    "Shields are holding.",
]


@pytest.mark.parametrize("line", CUT)
def test_chatter_is_dropped(line):
    assert BR.drop_chatter(line) == ""


@pytest.mark.parametrize("line", KEEP)
def test_real_answers_survive(line):
    assert BR.drop_chatter(line) == line


def test_prompt_stays_in_character():
    p = BR.SYSTEM.lower()
    assert "never mention the internet" in p and "answer first" in p
    assert "may have changed" not in p.split("no disclaimers")[0]
    assert "hours old" not in p


def make_brain(replies):
    import threading
    import types
    st = types.SimpleNamespace(lock=threading.RLock(), handle="Pilot", snapshot_text=lambda: "Zone: Stanton")
    app = types.SimpleNamespace(settings={"ai_mode": "own_key", "api_key": "x", "model": "claude-haiku-5-5"},
                                state=st, note_system=lambda *a: None)
    b = BR.Brain(app)
    sent = []

    def fake(body, on_text=None):
        sent.append(body)
        r = replies.pop(0)
        if isinstance(r, Exception):
            raise r
        for blk in r["content"]:
            if blk.get("type") == "text" and on_text:
                on_text(blk["text"])
        return r
    b._request = fake
    return b, sent


def text_reply(t):
    return {"content": [{"type": "text", "text": t}], "stop_reason": "end_turn", "usage": {}}


def test_voice_answers_turn_thinking_off_with_room_to_answer():
    b, sent = make_brain([text_reply("The Gladius and the Arrow, both at Area18.")])
    heard = []
    out = b.ask("what fighters are in stanton", on_sentence=heard.append)
    assert out == "The Gladius and the Arrow, both at Area18."
    assert sent[0]["thinking"] == {"type": "disabled"} and sent[0]["max_tokens"] >= 1024


def test_falls_back_when_a_model_refuses_thinking_off():
    refuse = BR.ApiError("bad", 400, "thinking.type: disabled is not supported for this model")
    refuse2 = BR.ApiError("bad", 400, "output_config.effort is not supported")
    b, sent = make_brain([refuse, refuse2, text_reply("Copy.")])
    assert b.ask("status") == "Copy."
    assert sent[0].get("thinking") == {"type": "disabled"}
    assert sent[1].get("output_config") == {"effort": "low"} and "thinking" not in sent[1]
    assert "thinking" not in sent[2] and "output_config" not in sent[2]
    assert b.thinking == "auto"


def test_empty_reply_is_logged(capsys):
    empty = {"content": [{"type": "thinking", "thinking": ""}], "stop_reason": "max_tokens", "usage": {"output_tokens": 1024}}
    b, sent = make_brain([empty])
    b.ask("status")
    assert "[ai] no text in reply: stop=max_tokens" in capsys.readouterr().out
