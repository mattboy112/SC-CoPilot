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
