import pytest

import sc_timers as T


@pytest.mark.parametrize("text,secs,label", [
    ("set a timer for 10 minutes", 600, ""),
    ("set a 25 minute timer for refinery", 1500, "refinery"),
    ("set a 3 hour refinery timer", 10800, "refinery"),
    ("start a timer for an hour and a half called refinery", 5400, "refinery"),
    ("set timer for 1 hour 20 minutes for the bounty", 4800, "bounty"),
    ("set a timer for two and a half hours", 9000, ""),
    ("set a timer for twenty five minutes", 1500, ""),
    ("set a timer for half an hour", 1800, ""),
    ("Co-Pilot, set a timer for ninety seconds", 90, ""),
    ("remind me in 5 minutes to check fuel", 300, "check fuel"),
    ("remind me to sell the cargo in 2 hours", 7200, "sell the cargo"),
    ("10 minute timer", 600, ""),
    ("start a 10 minute countdown", 600, ""),
])
def test_setting_timers_by_voice(text, secs, label):
    assert T.parse_command(text, "Co-Pilot") == {"kind": "timer", "op": "set", "seconds": secs, "label": label}


@pytest.mark.parametrize("text,op,label", [
    ("how long left on the timer", "list", ""),
    ("how long left on the refinery timer", "list", "refinery"),
    ("what are my timers", "list", ""),
    ("cancel the timer", "cancel", ""),
    ("cancel the refinery timer", "cancel", "refinery"),
    ("stop all timers", "cancel", ""),
])
def test_checking_and_cancelling(text, op, label):
    cmd = T.parse_command(text)
    assert cmd["op"] == op and cmd["label"] == label


@pytest.mark.parametrize("text", ["set a timer", "gear down", "what's the time", "remind me later", "timer for nothing"])
def test_not_a_timer_command(text):
    assert T.parse_command(text) is None


def test_vague_time_question_only_counts_if_a_timer_is_running():
    cmd = T.parse_command("how much time is left")
    assert cmd["op"] == "list" and cmd["explicit"] is False


def test_durations_and_how_they_are_said():
    assert T.parse_duration("an hour and a half") == 5400
    assert T.parse_duration("nothing here") is None
    assert T.parse_duration("500 hours") == T.MAX_SECONDS
    assert T.spoken(3725) == "1 hour 2 minutes"
    assert T.spoken(7200) == "2 hours"
    assert T.spoken(150) == "2 and a half minutes"
    assert T.spoken(45) == "45 seconds"
    assert T.clock(3725) == "1:02:05" and T.clock(75) == "1:15"


def test_timers_run_out_in_order_and_survive_a_restart(tmp_path):
    path = tmp_path / "timers.json"
    t = T.Timers(path)
    t.add(600, "refinery", now=1000)
    t.add(60, "", now=1000)
    assert t.rows(now=1000) == [("Timer", "1:00"), ("refinery", "10:00")]
    again = T.Timers(path)
    assert [i["label"] for i in again.items] == ["", "refinery"]
    assert [i["label"] for i in again.due(now=1061)] == [""]
    assert again.due(now=1100) == []
    assert again.describe(now=1100) == "Refinery: 8 minutes left."
    assert [i["label"] for i in again.due(now=1601)] == ["refinery"]
    assert T.Timers(path).items == []


def test_cancel_by_name_or_all():
    t = T.Timers()
    t.add(600, "refinery", now=0)
    t.add(900, "bounty", now=0)
    t.add(30, "", now=0)
    assert [i["label"] for i in t.cancel("refinery")] == ["refinery"]
    assert t.describe("refinery") == "No refinery timer running."
    assert len(t.cancel("")) == 2
    assert t.describe() == "No timers running."


def test_limits():
    t = T.Timers()
    with pytest.raises(ValueError):
        t.add(0)
    with pytest.raises(ValueError):
        t.add(T.MAX_SECONDS + 1)
    for i in range(T.MAX_TIMERS):
        t.add(60 + i, f"t{i}")
    with pytest.raises(ValueError, match="Cancel one first"):
        t.add(60)


def test_a_broken_file_starts_empty(tmp_path):
    p = tmp_path / "timers.json"
    p.write_text("{not json")
    assert T.Timers(p).items == []


def test_ai_can_set_list_and_cancel_timers():
    import threading
    import types
    import sc_brain as BR
    timers = T.Timers()
    said = {}

    def set_timer(secs, label=""):
        item = timers.add(secs, label)
        said["set"] = item
        return f"Timer set for {T.spoken(secs)}."
    app = types.SimpleNamespace(settings={"ai_mode": "own_key", "api_key": "x"}, timers=timers, set_timer=set_timer,
                                cancel_timers=lambda label="": f"cancelled {len(timers.cancel(label))}",
                                state=types.SimpleNamespace(lock=threading.RLock(), handle="P", snapshot_text=lambda: ""),
                                note_system=lambda *a: None)
    b = BR.Brain(app)
    assert {"set_timer", "list_timers", "cancel_timer"} <= {t["name"] for t in b._tools()}
    assert b.run_tool("set_timer", {"minutes": 180, "label": "refinery"}) == "Timer set for 3 hours."
    assert said["set"]["seconds"] == 10800
    assert "refinery: 3 hours left" in b.run_tool("list_timers", {})
    assert b.run_tool("set_timer", {"minutes": "soon"}) == "Give the length in minutes."
    assert b.run_tool("cancel_timer", {"label": "refinery"}) == "cancelled 1"
