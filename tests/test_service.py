import pytest

import sc_brain as BR


def test_with_cache_marks_the_last_block_without_touching_history():
    hist = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "{}"}]}]
    out = BR.with_cache(hist)
    assert out[-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in hist[-1]["content"][-1]
    s = BR.with_cache([{"role": "user", "content": "gear down"}])
    assert s[0]["content"] == [{"type": "text", "text": "gear down", "cache_control": {"type": "ephemeral"}}]
    assert BR.with_cache([]) == []


def test_only_the_instructions_and_conversation_carry_cache_markers():
    tools = BR.TOOLS + BR.TRADE_TOOLS + BR.INFO_TOOLS
    assert not any("cache_control" in t for t in tools)


def test_format_account():
    month = {"plan_name": "Pilot", "resets_at": "2026-12-01T00:00:00.000Z",
             "usage": {"replies": 312, "web": 4, "smart": 0}, "limits": {"replies": 2000, "web": 50, "smart": 0}}
    assert BR.format_account(month) == "Pilot · 312 of 2,000 replies this month · 4 of 50 web lookups · resets Dec 1"
    cap = dict(month, plan_name="Captain", usage={"replies": 9, "web": 0, "smart": 3}, limits={"replies": 5000, "web": 150, "smart": 200})
    assert "3 of 200 smart replies" in BR.format_account(cap)
    trial = {"plan_name": "Free trial", "resets_at": None, "usage": {"replies": 12, "web": 1}, "limits": {"replies": 100, "web": 5}}
    assert BR.format_account(trial) == "Free trial · 12 of 100 trial replies used · 1 of 5 web lookups"
    free = {"plan_name": "Free", "resets_at": "2026-12-01T00:00:00Z", "usage": {"replies": 7, "web": 0}, "limits": {"replies": 50, "web": 3}}
    assert BR.format_account(free) == "Free · 7 of 50 replies this month · 0 of 3 web lookups · resets Dec 1"
    assert BR.format_account(None) == ""


@pytest.mark.parametrize("status,body,want", [
    (429, b'{"error":{"type":"quota_exceeded","message":"You\'ve used all 2000 AI replies this month."}}', "Instant commands and callouts still work"),
    (429, b'{"error":{"type":"rate_limit_error","message":"Too many questions at once. Give it a minute."}}', "Give it a minute"),
    (402, b'{"error":{"type":"subscription_inactive","message":"Your Co-Pilot subscription isn\'t active."}}', "isn't active"),
    (403, b'{"error":{"type":"permission_error","message":"This key is already in use on 3 PCs this month."}}', "3 PCs"),
    (401, b"not json", "isn't valid"),
    (503, b"", "busy"),
])
def test_service_errors_read_well(status, body, want):
    with pytest.raises(BR.ApiError) as ex:
        BR._service_fail(status, body)
    assert want in str(ex.value) and ex.value.status == status


def test_device_id_is_stable_and_anonymous():
    a, b = BR.device_id(), BR.device_id()
    assert a == b and len(a) == 24 and all(c in "0123456789abcdef" for c in a)


def test_notices_are_read_once():
    b = BR.Brain.__new__(BR.Brain)
    b.notices = {"web-limit", "smart-limit", "bogus"} & set(BR.NOTICES)
    got = b.take_notices()
    assert len(got) == 2 and b.take_notices() == []
