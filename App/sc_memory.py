"""Things you ask the co-pilot to remember ("remember my main ship is a Cutlass Black"), kept in your settings where you can edit them."""
import re
from difflib import SequenceMatcher

MAX_ITEMS = 40
MAX_CHARS = 200

REMEMBER = re.compile(r"^(?:please )?(?:remember|note|make a note|keep in mind|don't forget)(?: that| this| about)?[:,]? (?P<fact>.{3,})$", re.I)
FORGET = re.compile(r"^(?:please )?(?:forget|stop remembering|delete the note|remove the note)(?: that| about| the fact that)?[:,]? (?P<fact>.{2,})$",
                    re.I)
RECALL = re.compile(r"^(?:what do you (?:remember|know) about me|what have you remembered|what are your notes|list (?:your |my )?notes"
                    r"|what do you remember)\??$", re.I)


def clean(fact):
    fact = re.sub(r"\s+", " ", str(fact or "")).strip(" .,!?")
    if not fact:
        return ""
    fact = fact[0].upper() + fact[1:]
    return fact[:MAX_CHARS]


def items(settings):
    return [clean(x) for x in (settings.get("memories") or []) if clean(x)]


def add(settings, fact):
    """Save a fact. Returns (saved fact or "", what to say)."""
    fact = clean(fact)
    if len(fact) < 3:
        return "", "Remember what? Say it as one sentence."
    have = items(settings)
    if any(SequenceMatcher(None, fact.lower(), h.lower()).ratio() > 0.9 for h in have):
        return "", "Already got that one."
    if len(have) >= MAX_ITEMS:
        return "", f"My notes are full at {MAX_ITEMS}. Clear some out in Settings."
    settings["memories"] = have + [fact]
    return fact, "Noted."


def best_match(have, fact):
    f = clean(fact).lower()
    if not f or not have:
        return None
    scored = []
    for i, h in enumerate(have):
        hl = h.lower()
        words = set(re.findall(r"[a-z0-9]+", f)) - {"the", "a", "an", "my", "is", "that", "i", "about"}
        overlap = len(words & set(re.findall(r"[a-z0-9]+", hl))) / max(1, len(words))
        scored.append((max(SequenceMatcher(None, f, hl).ratio(), overlap, 1.0 if f in hl else 0.0), i))
    score, i = max(scored)
    return i if score >= 0.6 else None


def forget(settings, fact):
    """Remove the note that best matches. Returns (removed fact or "", what to say)."""
    have = items(settings)
    if re.fullmatch(r"(?:everything|all (?:of )?(?:it|that|your notes)|all notes)", clean(fact).lower()):
        settings["memories"] = []
        return "everything", f"Cleared all {len(have)} notes." if have else "There was nothing to clear."
    i = best_match(have, fact)
    if i is None:
        return "", "I don't have a note like that."
    gone = have.pop(i)
    settings["memories"] = have
    return gone, "Forgotten."


def second_person(fact):
    """What you told it, said back to you: "I mostly do salvage" -> "You mostly do salvage"."""
    swaps = {"i": "you", "i'm": "you're", "im": "you're", "my": "your", "me": "you", "mine": "yours", "am": "are", "myself": "yourself"}
    out = re.sub(r"\b(i'm|im|i|my|me|mine|am|myself)\b", lambda x: swaps[x.group(0).lower()], fact, flags=re.I)
    return out[0].upper() + out[1:] if out else out


def recall(settings):
    have = [second_person(h) for h in items(settings)]
    if not have:
        return "Nothing yet. Say \"remember\" and then what to keep."
    if len(have) <= 3:
        return " ".join(f"{h}." for h in have)
    return f"I've got {len(have)} notes. " + " ".join(f"{h}." for h in have[:3]) + " The rest are in Settings."


def parse_command(text, name=""):
    t = (text or "").strip()
    if name:
        for part in {name, name.replace("-", " "), name.replace("-", "")}:
            t = re.sub(r"^(?:hey |ok |okay )?" + re.escape(part) + r"[ ,]+", "", t, flags=re.I)
    t = t.strip()
    if RECALL.match(t):
        return {"kind": "memory", "op": "recall"}
    m = FORGET.match(t)
    if m:
        return {"kind": "memory", "op": "forget", "fact": m.group("fact")}
    m = REMEMBER.match(t)
    if m:
        fact = m.group("fact")
        if re.match(r"(?:where|what|when|who|how|if|whether)\b", fact, re.I):
            return None
        return {"kind": "memory", "op": "remember", "fact": fact}
    return None


def as_prompt(settings):
    have = items(settings)
    if not have:
        return ""
    return "\n\nThings the pilot asked you to remember:\n" + "\n".join(f"- {h}" for h in have)
