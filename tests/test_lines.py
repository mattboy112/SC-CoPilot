import sc_lines as LN


def test_personality_keys_exist():
    for pid, p in LN.PERSONALITIES.items():
        unknown = [k for k in p["lines"] if k not in LN.DEFAULTS]
        assert not unknown, (pid, unknown)


def test_placeholders_fill_and_survive_mistakes():
    assert LN.line({}, "kill_n", victim="Gladius", n=3) == "Gladius down. That's 3 this session."
    assert LN.line({"lines": {"kill_first": "{victim} by {nobody}"}}, "kill_first", victim="X") == "X by"
    assert LN.line({"lines": {"kill_first": "{victim"}}, "kill_first", victim="X") == "{victim"


def test_user_edit_beats_personality():
    s = {"personality": "military", "lines": {"arm_on": "Mine."}}
    assert LN.line(s, "arm_on") == "Mine."
    assert LN.line({"personality": "military"}, "arm_on") == LN.PERSONALITIES["military"]["lines"]["arm_on"]


def test_silent_commands_stay_silent_by_default():
    assert LN.ack({}, "decoys", "") == ""
    assert LN.ack({"personality": "military"}, "decoys", "") in ("Flares away.", "Countermeasures out.")


def test_pack_round_trip():
    s = {"personality": "hauler", "lines": {"kill_first": "Boom.", "not_a_line": "x"}}
    s2 = {}
    assert LN.import_pack(s2, LN.export_pack(s)) == 1
    assert s2 == {"lines": {"kill_first": "Boom."}, "personality": "hauler"}
