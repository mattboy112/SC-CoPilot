import json
import sys
import types

import sc_voice as V


def test_voice_list_per_language_from_one_cache(tmp_path):
    cache = tmp_path / "voices.json"
    cache.write_text(json.dumps([
        ["en-GB-RyanNeural", "Ryan (GB, male)", "en-GB"],
        ["de-DE-ConradNeural", "Conrad (DE, male)", "de-DE"],
        ["de-AT-JonasNeural", "Jonas (AT, male)", "de-AT"],
        ["fr-FR-HenriNeural", "Henri (FR, male)", "fr-FR"],
    ]))
    assert [v for v, _ in V.edge_voice_list(cache, lang="de")] == ["de-AT-JonasNeural", "de-DE-ConradNeural"]
    assert [v for v, _ in V.edge_voice_list(cache, lang="en")] == ["en-GB-RyanNeural"]
    assert V.edge_voice_list(cache, lang="nl") == []


def test_old_english_only_cache_still_works(tmp_path):
    cache = tmp_path / "voices.json"
    cache.write_text(json.dumps([["en-US-AvaNeural", "Ava (US, female)"]]))
    assert V.edge_voice_list(cache, lang="en") == [("en-US-AvaNeural", "Ava (US, female)")]
    assert V.edge_voice_list(tmp_path / "missing.json", lang="en") == list(V.VOICES)


def test_every_language_has_a_default_voice_and_a_name():
    for code, _label in V.LANGUAGES:
        assert V.DEFAULT_VOICE[code].startswith(code + "-")
        assert code in V.LANGUAGE_NAMES


def test_other_languages_use_the_multilingual_speech_model(monkeypatch, tmp_path):
    seen = {}

    class FakeModel:
        def __init__(self, size, **kw):
            seen["size"] = size

        def transcribe(self, audio, language=None, **kw):
            seen.setdefault("langs", []).append(language)
            seen["prompt"] = kw.get("initial_prompt")
            return iter([types.SimpleNamespace(text=" Fahrwerk ausfahren ")]), None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeModel))
    t = V.Transcriber(tmp_path)
    t.load("base.en", "cpu", "de")
    assert seen["size"] == "base" and t.language == "de"
    assert t.transcribe(V.np.zeros(16000, dtype=V.np.float32)) == "Fahrwerk ausfahren"
    assert seen["langs"][-1] == "de" and seen["prompt"] is None
    t2 = V.Transcriber(tmp_path)
    t2.load("base.en", "cpu", "en")
    assert seen["size"] == "base.en"


def test_ai_answers_in_the_chosen_language():
    import threading
    import sc_brain as BR
    app = types.SimpleNamespace(settings={"ai_mode": "own_key", "api_key": "x", "language": "de"},
                                state=types.SimpleNamespace(lock=threading.RLock(), handle="P", snapshot_text=lambda: ""),
                                note_system=lambda *a: None)
    b = BR.Brain(app)
    sent = []
    b._request = lambda body, on_text=None: sent.append(body) or {"content": [{"type": "text", "text": "Verstanden."}],
                                                                   "stop_reason": "end_turn", "usage": {}}
    b.ask("Fahrwerk?")
    assert "Always answer in German" in sent[0]["system"][0]["text"]
    app.settings["language"] = "en"
    b.ask("gear?")
    assert "Always answer in" not in sent[1]["system"][0]["text"]
