import json
import random
import re

import sc_quick as Q
from sc_binds import ACTION_INDEX

CALLOUTS = [
    ("Zones", [
        ("arm_on", "Entering armistice", "Entering armistice. Weapons locked.", ""),
        ("arm_off", "Leaving armistice", "Leaving armistice. Weapons free.", ""),
        ("juris_ungoverned", "Ungoverned space", "Ungoverned space. Stay sharp.", ""),
        ("juris_uee", "UEE space", "UEE space.", ""),
        ("juris_other", "Other jurisdiction", "Entering {name} jurisdiction.", "{name}"),
        ("mon_on", "Back in monitored space", "Back in monitored space.", ""),
        ("mon_off", "Leaving monitored space", "Leaving monitored space.", ""),
        ("comms_down", "Comm array down", "Comm array's down here. No security watching.", ""),
        ("private", "Private property", "Private property. Trespassing can earn a CrimeStat.", ""),
    ]),
    ("Travel", [
        ("qt_arrived", "Quantum travel complete", "Quantum travel complete.", ""),
        ("qt_obstructed", "Quantum path blocked", "Quantum path's obstructed. Try another route.", ""),
        ("hangar", "Hangar ready", "Hangar's ready.", ""),
    ]),
    ("Combat", [
        ("kill_first", "Your kill (first)", "{victim} down.", "{victim}"),
        ("kill_n", "Your kill (more)", "{victim} down. That's {n} this session.", "{victim} {n}"),
        ("ship_lost", "Ship lost", "We lost the {victim}.", "{victim}"),
        ("downed", "You're downed", "You're down. Call for help before the timer runs out.", ""),
        ("crime_up", "CrimeStat up", "CrimeStat increased. Security will be hostile.", ""),
        ("crime_down", "CrimeStat down", "CrimeStat going down.", ""),
        ("threat", "Player kill nearby", "{killer} just destroyed {a_victim} nearby.", "{killer} {a_victim}"),
        ("target_shields_down", "Target shields down", "Target's shields are down.", ""),
        ("target_status", "Target status", "Target shields {shields}, hull {hull}.", "{shields} {hull}"),
    ]),
    ("Contracts", [
        ("contract_accepted", "Contract accepted", "Contract accepted. {name}", "{name}"),
        ("contract_complete", "Contract complete", "Contract complete. {name}", "{name}"),
        ("contract_failed", "Contract failed", "Contract failed. {name}", "{name}"),
        ("objective", "New objective", "New objective. {text}", "{text}"),
    ]),
    ("Social and alerts", [
        ("party_join", "Party join", "{who} joined the party.", "{who}"),
        ("party_leave", "Party leave", "{who} left the party.", "{who}"),
        ("money_in", "aUEC received", "{who} sent you {amount} credits.", "{who} {amount}"),
        ("low_fuel", "Low fuel", "Fuel's low.", ""),
        ("disc_idle", "Idle disconnect", "Disconnected for being idle.", ""),
        ("disc", "Disconnected", "We got disconnected.", ""),
        ("crash", "Game crashed", "Looks like the game crashed.", ""),
    ]),
    ("General", [
        ("greeting", "Voice test / greeting", "Co-pilot online. Leaving armistice, weapons free.", ""),
        ("overlay_on", "Overlay on", "Overlay on.", ""),
        ("overlay_off", "Overlay off", "Overlay off.", ""),
        ("macro_busy", "Macro already running", "A macro's already running.", ""),
    ]),
    ("Timers", [
        ("timer_set", "Timer set", "Timer set for {time}. {label}", "{time} {label}"),
        ("timer_done", "Timer finished", "Timer's up. {label}", "{label}"),
        ("timer_cancel", "Timer cancelled", "Timer cancelled. {label}", "{label}"),
    ]),
]


def _ack_defaults():
    out = {}
    for table in ("ENGINEERING", "MODES", "PRESSES", "THREAT"):
        for row in getattr(Q, table, []):
            if len(row) == 3:
                out.setdefault(row[1], row[2] or "")
    for row in Q.STATEFUL:
        for aid, say in zip(row[3:6], row[6]):
            out.setdefault(aid, say)
    out.setdefault("doors_lock", "Doors locked.")
    out.setdefault("doors_unlock", "Doors unlocked.")
    out.setdefault("doorlocks_toggle", "Door locks toggled.")
    return out


ACK_DEFAULTS = _ack_defaults()
DEFAULTS = {k: d for _g, rows in CALLOUTS for k, _l, d, _p in rows}
DEFAULTS.update({f"ack.{a}": s for a, s in ACK_DEFAULTS.items()})

PERSONALITIES = {
    "standard": {
        "name": "Ship AI (default)",
        "desc": "Calm and to the point.",
        "ai_style": "",
        "wrap": [],
        "lines": {},
    },
    "military": {
        "name": "Fleet officer",
        "desc": "Crisp, clipped, by the book.",
        "ai_style": "Speak like a crisp military flight officer: short clipped sentences, 'copy', 'confirmed', 'negative', no small talk.",
        "wrap": ["Copy. {line}", "{line}", "{line}", "Confirmed. {line}"],
        "lines": {
            "arm_on": "Armistice zone. Weapons safe.",
            "arm_off": "Clear of armistice. Weapons hot.",
            "juris_ungoverned": "Ungoverned space. Eyes open.",
            "qt_arrived": "Quantum complete. On station.",
            "kill_first": "Splash one. {victim} down.",
            "kill_n": "Splash. {victim} down. {n} confirmed this sortie.",
            "ship_lost": "We've lost the {victim}.",
            "downed": "Pilot down. Call for medevac now.",
            "threat": "Contact. {killer} just splashed {a_victim}.",
            "target_shields_down": "Target shields are down. Engage.",
            "contract_accepted": "Orders received. {name}",
            "contract_complete": "Mission complete. {name}",
            "contract_failed": "Mission failed. {name}",
            "objective": "New tasking. {text}",
            "greeting": "Co-pilot online. All systems green. Awaiting orders.",
            "ack.gear_down": "Gear down.|Gear down and locked.",
            "ack.flight_ready": "Flight ready. Systems green.",
            "ack.decoys": "Flares away.|Countermeasures out.",
            "ack.max_shields": "All power to shields.",
            "ack.max_weapons": "All power to weapons.",
            "ack.max_engines": "All power to engines.",
        },
    },
    "hauler": {
        "name": "Laid-back hauler",
        "desc": "Easygoing, been flying cargo for years.",
        "ai_style": "Talk like a relaxed, friendly veteran cargo hauler: casual, warm, a little folksy, never rushed.",
        "wrap": ["{line}", "{line}", "You got it. {line}", "{line} Easy does it."],
        "lines": {
            "arm_on": "Back in armistice. Guns are locked, so relax.",
            "arm_off": "Out of armistice. Keep your head on a swivel.",
            "juris_ungoverned": "No law out here. Stay sharp, friend.",
            "qt_arrived": "And we're here.",
            "qt_obstructed": "Something's in the way of that jump. Let's find another line.",
            "kill_first": "Got 'em. {victim}'s done.",
            "kill_n": "Another one. {victim} down, that's {n} today.",
            "ship_lost": "Aw, we lost the {victim}. Insurance'll sort it.",
            "low_fuel": "We're running on fumes. Let's top off soon.",
            "contract_accepted": "New job on the board. {name}",
            "contract_complete": "Job's done. {name}",
            "greeting": "Hey there. Co-pilot's on and the coffee's hot.",
            "ack.gear_down": "Gear's down.|Wheels out.",
            "ack.gear_up": "Gear's up.|Wheels in.",
            "ack.lights_on": "Lights on.|Let there be light.",
        },
    },
    "deadpan": {
        "name": "Deadpan AI",
        "desc": "Dry, sarcastic, technically helpful.",
        "ai_style": "Talk like a dry, deadpan, slightly sarcastic ship AI: helpful and accurate, but with understated wit. Never mean.",
        "wrap": ["{line}", "{line}", "{line} You're welcome.", "Fine. {line}"],
        "lines": {
            "arm_on": "Entering armistice. Try not to shoot anyone.",
            "arm_off": "Leaving armistice. You may now shoot things. Joy.",
            "juris_ungoverned": "Ungoverned space. Everyone out here is a gentleman, I'm sure.",
            "qt_arrived": "We've arrived. Try to contain your excitement.",
            "kill_first": "{victim} down. I'm sure they had it coming.",
            "kill_n": "{victim} down. That's {n}. I'm keeping count, apparently.",
            "ship_lost": "We lost the {victim}. Noted, with feeling.",
            "downed": "You're down. I'd call for help, if I were you.",
            "low_fuel": "Fuel's low. Walking home is an option, I suppose.",
            "crash": "The game crashed. Shocking, I know.",
            "greeting": "Co-pilot online. Thrilled to be here.",
            "ack.gear_down": "Gear down. Again.",
            "ack.decoys": "Flares out. Very festive.",
        },
    },
    "corporate": {
        "name": "Corporate assistant",
        "desc": "Relentlessly polite customer service.",
        "ai_style": "Talk like an overly polite corporate customer-service assistant: cheerful, formal, thanks the pilot often.",
        "wrap": ["{line}", "{line}", "{line} Thank you for flying with us.", "Certainly! {line}"],
        "lines": {
            "arm_on": "You are now entering an armistice zone. Weapons have been locked for your safety.",
            "arm_off": "You are now leaving the armistice zone. Please fire responsibly.",
            "juris_ungoverned": "Please note: this area is not covered by any security provider.",
            "qt_arrived": "We have arrived at your destination. Thank you for your patience.",
            "kill_first": "{victim} has been successfully neutralized.",
            "kill_n": "{victim} has been neutralized. That brings your session total to {n}.",
            "ship_lost": "We regret to inform you that the {victim} has been lost.",
            "contract_accepted": "Your contract has been confirmed. {name}",
            "contract_complete": "Your contract is complete. {name}",
            "greeting": "Good day! Your co-pilot is online and happy to assist.",
        },
    },
    "outlaw": {
        "name": "Pyro outlaw",
        "desc": "Rough around the edges, lives past the law.",
        "ai_style": "Talk like a gruff frontier outlaw who knows Pyro well: blunt, streetwise, dry humor. Keep it PG-13 and no slurs.",
        "wrap": ["{line}", "{line}", "Done. {line}"],
        "lines": {
            "arm_on": "Armistice. Keep it holstered.",
            "arm_off": "Out of armistice. Open season.",
            "juris_ungoverned": "No law out here. Just how we like it.",
            "mon_off": "Off the grid. Nobody's watching now.",
            "kill_first": "{victim}'s scrap now.",
            "kill_n": "{victim}'s scrap. {n} and counting.",
            "ship_lost": "They got the {victim}. We'll get it back.",
            "crime_up": "CrimeStat's up. Security's gonna want a word.",
            "threat": "{killer} just took out {a_victim}. Watch our six.",
            "target_shields_down": "Shields are down. Light 'em up.",
            "greeting": "Co-pilot's up. Let's go make some money.",
        },
    },
}


def _pick(text):
    options = [o.strip() for o in str(text).split("|") if o.strip()]
    return random.choice(options) if options else ""


_PLACEHOLDER = re.compile(r"\{(\w{1,40})\}")


def _fill(text, vals):
    out = _PLACEHOLDER.sub(lambda m: str(vals.get(m.group(1), "")), str(text))
    return re.sub(r"\s+", " ", out).strip()


def personality(settings):
    p = (settings or {}).get("personality") or "standard"
    return PERSONALITIES.get(p, PERSONALITIES["standard"])


def raw(settings, key):
    """The text that would be used for key, before picking a variant: your edit, else the personality's, else the default."""
    mine = ((settings or {}).get("lines") or {}).get(key)
    if mine and str(mine).strip():
        return str(mine)
    return personality(settings)["lines"].get(key) or DEFAULTS.get(key, "")


def line(settings, key, **vals):
    return _fill(_pick(raw(settings, key)), vals)


def ack(settings, action_id, default=None):
    """What the co-pilot says after an instant command. Your edit or the personality's line wins; otherwise the default,
    sometimes wrapped in the personality's flavor."""
    key = f"ack.{action_id}"
    mine = ((settings or {}).get("lines") or {}).get(key)
    if mine and str(mine).strip():
        return _pick(mine)
    p = personality(settings)
    if key in p["lines"]:
        return _pick(p["lines"][key])
    base = default if default is not None else ACK_DEFAULTS.get(action_id, "")
    if not base:
        return base
    wraps = p.get("wrap") or []
    return _fill(random.choice(wraps), {"line": base}) if wraps else base


def ai_style(settings):
    return personality(settings).get("ai_style", "")


def editor_rows():
    """[(group, [(key, label, default, placeholders)])] for the line editor."""
    groups = [(g, list(rows)) for g, rows in CALLOUTS]
    acks = []
    for aid, say in sorted(ACK_DEFAULTS.items(), key=lambda kv: ACTION_INDEX.get(kv[0], {}).get("label", kv[0])):
        acks.append((f"ack.{aid}", ACTION_INDEX.get(aid, {}).get("label", aid.replace("_", " ")), say, "" if say else "silent by default"))
    groups.append(("Replies to instant commands", acks))
    return groups


def export_pack(settings, name="My co-pilot"):
    p = (settings or {}).get("personality") or "standard"
    lines = {k: v for k, v in ((settings or {}).get("lines") or {}).items() if str(v).strip()}
    return {"sc_copilot_lines": 1, "name": name, "personality": p, "lines": lines}


_PACK_PATH = re.compile(r"^packs/[a-z0-9][a-z0-9-]{0,80}\.json$")


def safe_pack_path(path):
    return isinstance(path, str) and bool(_PACK_PATH.fullmatch(path)) and path != "packs/index.json"


def import_pack(settings, data):
    if not isinstance(data, dict) or "lines" not in data:
        raise ValueError("That file isn't an SC Co-Pilot lines pack.")
    known = set(DEFAULTS)
    lines = {k: str(v)[:400] for k, v in (data.get("lines") or {}).items() if k in known and str(v).strip()}
    settings["lines"] = lines
    if data.get("personality") in PERSONALITIES:
        settings["personality"] = data["personality"]
    return len(lines)


def dumps_pack(settings, name="My co-pilot"):
    return json.dumps(export_pack(settings, name), indent=2, ensure_ascii=False)
