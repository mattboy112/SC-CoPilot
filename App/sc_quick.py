import difflib
import re

import sc_macros as M

QUESTION = re.compile(r"^(how|what|whats|where|wheres|when|why|who|whos|which|is|are|am|do|does|did|can i|should|tell|give|list|any|"
                      r"was|were|will|have|has|show me|explain|find|look|check)\b")
FILLER = re.compile(r"\b(please|hey|ok|okay|computer|copilot|co pilot|can you|could you|would you|will you|go ahead and|i need you to|"
                    r"i want you to|i need|i want|for me|now|quick|quickly|the|my|our|a|an|just|right now|real quick|thanks|thank you|"
                    r"let's|lets|all|ship's|ships|ship|some|those|these|that's|get|go|yo|uh|um|like|gimme|give me|his|her|their|its)\b")

OBJECTS = [
    (r"quantum drive|q drive|quantum jump drive", "quantum"),
    (r"landing gear|landing struts|landing legs|undercarriage|struts|skids|wheels", "gear"),
    (r"weapon systems|weapons systems|weapon|guns|gun|armaments|cannons|hardpoints|weps", "weapons"),
    (r"thrusters|thruster|engine|propulsion|main drives", "engines"),
    (r"shield generators|shield generator|deflectors|deflector|shield", "shields"),
    (r"head lights|headlights|spot lights|spotlights|flood lights|floodlights|lamps|lamp|light", "lights"),
    (r"cargo doors|cargo door|airlock|hatches|hatch|ramp|door", "doors"),
    (r"counter measures|countermeasures|countermeasure|decoys|decoy|flairs|flair|flare", "flares"),
    (r"chaff|chaf|noise launcher", "noise"),
    (r"navigation", "nav"),
]
MISHEARS = [("sheilds", "shields"), ("shealds", "shields"), ("shelds", "shields"), ("shield's", "shields"), ("weapon's", "weapons"),
            ("gear dawn", "gear down"), ("gear town", "gear down"), ("vallance", "balance"), ("valance", "balance"),
            ("ballance", "balance"), ("balanced power", "balance power"), ("full power", "max power"), ("mobi glass", "mobiglas"),
            ("mobile glass", "mobiglas"), ("mobiglass", "mobiglas"), ("mobi glas", "mobiglas"), ("star map", "starmap"),
            ("auto land", "autoland"), ("auto landing", "autoland"), ("v tol", "vtol"), ("v toll", "vtol"), ("vtoll", "vtol"),
            ("g safe", "gsafe"), ("q t", "qt"), ("cue tea", "qt"), ("s c m", "scm"), ("s cm", "scm"), ("de couple", "decouple"),
            ("re couple", "recouple"), ("decoupling", "decouple"), ("land gear", "landing gear"), ("night-vision", "night vision"),
            ("auto target", "autotarget"), ("auto targeting", "autotarget"), ("autotargeting", "autotarget"),
            ("sub system", "subsystem"), ("sub systems", "subsystem"), ("subsystems", "subsystem")]

ENGINEERING = [
    (r"\b(min|minimum|zero|no) (power )?(to |on )?shields\b|\bshields (to )?(min|minimum|zero)\b", "min_shields", "Shields to minimum."),
    (r"\b(min|minimum|zero|no) (power )?(to |on )?weapons\b|\bweapons (to )?(min|minimum|zero)\b", "min_weapons", "Weapons to minimum."),
    (r"\b(min|minimum|zero|no) (power )?(to |on )?engines\b|\bengines (to )?(min|minimum|zero)\b", "min_engines", "Engines to minimum."),
    (r"\b(lower|less|reduce|drop|decrease|cut|take) power (from |to |on )?shields\b|\b(less|reduce|decrease) (power )?(from |to |on )?shields( power)?\b|\bshields (down one|power down one)\b", "less_shields", None),
    (r"\b(lower|less|reduce|drop|decrease|cut|take) power (from |to |on )?weapons\b|\b(less|reduce|decrease) (power )?(from |to |on )?weapons( power)?\b", "less_weapons", None),
    (r"\b(lower|less|reduce|drop|decrease|cut|take) (power )?(from |to |on )?engines( power)?( down)?\b", "less_engines", None),
    (r"\b(max|maximum|full|all|everything) (power )?(to |on |into )?shields\b|\bshields (to )?(max|full|100)\b|\b(power|juice) (to|into) shields\b|\bmax shields\b", "max_shields", "Max power to shields."),
    (r"\b(max|maximum|full|all|everything) (power )?(to |on |into )?weapons\b|\bweapons (to )?(max|full|100)\b|\b(power|juice) (to|into) weapons\b|\bmax weapons\b", "max_weapons", "Max power to weapons."),
    (r"\b(max|maximum|full|all|everything) (power )?(to |on |into )?engines\b|\bengines (to )?(max|full|100)\b|\b(power|juice) (to|into) engines\b|\bmax engines\b", "max_engines", "Max power to engines."),
    (r"\b(reset|balance|even out|equalize|equalise|even|normal|default) (the )?power\b|\bpower (reset|balanced?|even|normal)\b|\bbalance (it|everything)\b", "power_reset", "Power balanced."),
    (r"\b(one more|pip|bump|more|increase|boost|add) (power )?(to )?shields\b", "more_shields", None),
    (r"\b(one more|pip|bump|more|increase|boost|add) (power )?(to )?weapons\b", "more_weapons", None),
    (r"\b(one more|pip|bump|more|raise|increase|boost|add) (power )?(to )?engines\b", "more_engines", None),
]

MODES = [
    (r"\bnav mode\b|^nav$|\b(go|switch to|swap to) nav\b|\bcruise mode\b", "nav_mode", "NAV mode."),
    (r"\b(scm|combat|fight|fighting|s c m) mode\b|^scm$|\b(go|switch to|swap to) scm\b|\bcombat ready\b", "scm_mode", "SCM mode."),
    (r"\bquantum mode\b|^quantum$|\b(spool|prep|ready) (up )?(the )?quantum\b", "quantum_mode", "Quantum mode."),
    (r"\bmissiles? mode\b|^missiles?$|\b(switch to|go to) missiles?\b", "missile_mode", "Missile mode."),
    (r"\b(weapons|gunnery) mode\b|^weapons$", "guns_mode", "Guns mode."),
    (r"\b(scan|scanning|scanner) mode\b|^scan$|\b(switch to|go to) scan(ning)?\b", "scan_mode", "Scan mode."),
    (r"\bmining mode\b|\b(switch to|go to) mining\b", "mining_mode", "Mining mode."),
    (r"\bsalvage mode\b|\b(switch to|go to) salvage\b", "salvage_mode", "Salvage mode."),
]

THREAT = r"(threat|threats|attacker|attackers|aggressor|shooter|whoever is shooting|whos shooting|who is shooting|guy shooting)"
PRESSES = [
    (r"\b(target|lock|lock on|lock onto|select|get|grab|focus) (on |onto )?(the )?((highest|biggest|main|primary|top|worst|nearest|closest) )?" + THREAT + r"\b"
     r"|\b(highest|biggest|main|primary|top) threat\b|\btarget (whos|who is|whoever is) (shooting|attacking|firing|hitting)( at)?( me)?\b", "target_attacker", None),
    (r"\b(target|lock|lock on|lock onto|select|grab) (on |onto )?(the )?((nearest|closest|next) )?(hostile|enemy|enemies|bad guy|bandit|red)\b"
     r"|\bnext (hostile|enemy|target|bandit)\b|\bcycle (targets?|hostiles?|enemies)\b", "target_hostile", None),
    (r"\b(target|lock|select) (what im looking at|what i am looking at|under (the |my )?(reticle|crosshair|cursor)|in front( of me)?|reticle|crosshairs?)\b"
     r"|\btarget (that|this|him|her|them|it)\b|\block (that|this|him|it)( up)?\b", "target_reticle", None),
    (r"\b(target|cycle|next|select) (the )?(subsystem|subsystems|components?|engines|weapons|power plant|shields|parts)\b|\bsubsystem\b", "target_subitem", None),
    (r"\b(target|select) (the )?(next )?(friendly|friend|ally|wingman)\b", "target_friendly", None),
    (r"\bpin (the |that |this )?(target|it|him|them)\b", "target_pin", "Target pinned."),
    (r"\bautotarget\b", "auto_target_toggle", None),
    (r"\b(unlock|clear|drop|release|lose|cancel) (the )?target\b|\bunlock\b", "target_unlock", "Target cleared."),
    (r"\b(engage|spool and engage|punch|hit|activate|fire) (the )?(quantum|qt)\b|\bquantum (jump|engage|go|travel)\b|^punch it$|^hit it$|^engage$|\bjump to quantum\b", "qt_engage", None),
    (r"\b(request|enter|take) (the )?jump\b|\bjump (point|request|gate)\b", "jump_request", None),
    (r"\bflight ready\b|^power (it )?up$|\bstart (up )?(the )?engines\b|^wake (it )?up$|^spin (it )?up$|^fire (it )?up$|^start (it )?up$", "flight_ready", "Flight ready."),
    (r"\b(request|call|ask for|get|need) (landing|takeoff|take off|a pad|pad|hangar|atc|clearance|permission to land|landing permission)\b"
     r"|\b(landing|takeoff) (request|permission|clearance)\b|^atc$|\bcall (the )?tower\b|\b(me |need |want )?(landing )?pad\b|\bclear (me|us) (to|for) (land|takeoff|take off)\b", "request_landing", None),
    (r"\bautoland\b|^land( it| us)?( for me| automatically)?$|\bauto pilot land\b", "autoland", None),
    (r"\b(panic|dump|all|every|empty|unload) (the |all )?(flares)\b|\bflares panic\b|\bdump everything\b", "decoys_panic", None),
    (r"\bflares\b", "decoys", None),
    (r"\bnoise\b", "noise", None),
    (r"\b(radar )?ping\b|\bscan (the )?area\b", "ping", None),
    (r"\bhail\b", "hail", None),
    (r"\bstarmap\b|^map$|\bopen (the )?map\b", "starmap", None),
    (r"\bmobiglas\b", "mobiglas", None),
    (r"\b(third person|change (the )?(view|camera)|cycle (the )?(view|camera)|camera)\b", "camera", None),
    (r"\b(wipe (the |my )?visor|visor wipe|clean (the |my )?visor)\b", "visor_wipe", None),
    (r"\bnight ?vision\b", "night_vision_toggle", None),
    (r"\bgsafe\b", "gsafe_toggle", None),
    (r"\besp\b", "esp_toggle", None),
    (r"\bproximity assist\b", "prox_assist_toggle", None),
    (r"\bport ?locks?\b", "ports_lock_toggle", None),
]

ON_WORDS = r"(on|up|online|enable|enabled|activate|engage|hot|live|arm|armed|power up|bring up|fire up|turn on|switch on|raise|start)"
OFF_WORDS = r"(off|offline|disable|disabled|deactivate|disengage|kill|cut|cold|safe|disarm|power down|turn off|switch off|shut off|shut down|drop|lower|out|stop)"
STATEFUL = [
    (r"\bgear\b", r"\b(down|deploy|lower|out|drop|extend|put down)\b", r"\b(up|retract|raise|in|stow|tuck|pull up)\b",
     "gear_down", "gear_up", "gear_toggle", ("Gear down.", "Gear up.", "Gear toggled.")),
    (r"\blights\b", r"\b(on|enable|activate|switch on|turn on|light up|hit)\b", r"\b(off|disable|kill|cut|out|douse|turn off|switch off|shut off)\b",
     "lights_on", "lights_off", "lights_toggle", ("Lights on.", "Lights off.", "Lights toggled.")),
    (r"\bshields\b", r"\b(on|up|raise|enable|online|activate|bring up|power up|turn on|power)\b", r"\b(off|down|drop|kill|cut|disable|offline|lower|turn off|power down|shut off)\b",
     "shields_on", "shields_off", "shields_toggle", ("Shields up.", "Shields down.", "Shields toggled.")),
    (r"\bweapons\b", r"\b" + ON_WORDS + r"\b", r"\b" + OFF_WORDS + r"\b",
     "weapons_power_on", "weapons_power_off", "weapons_power_toggle", ("Weapons online.", "Weapons offline.", "Weapons power toggled.")),
    (r"\bengines\b", r"\b(on|online|enable|activate|turn on|power up|start)\b", r"\b(off|offline|disable|kill|cut|turn off|power down|shut off|stop)\b",
     "thrusters_on", "thrusters_off", "thrusters_toggle", ("Thrusters on.", "Thrusters off.", "Thrusters toggled.")),
    (r"\bdoors\b", r"\b(open|lower|down|let down)\b", r"\b(close|shut|raise|up|seal)\b",
     "doors_open", "doors_close", "doors_toggle", ("Doors open.", "Doors closed.", "Doors toggled.")),
    (r"\bpower\b", r"\b(on|up|turn on|restore)\b", r"\b(off|down|turn off|kill|cut|shut off|shut down)\b",
     "power_on", "power_off", "power_toggle", ("Power on.", "Power off.", "Power toggled.")),
    (r"\bvtol\b", r"\b(on|enable|engage|activate)\b", r"\b(off|disable|disengage|deactivate)\b",
     "vtol_on", "vtol_off", "vtol_toggle", ("VTOL on.", "VTOL off.", "VTOL toggled.")),
    (r"\b(decouple|decoupled|coupled|recouple)\b", r"\b(on|enable|engage|decouple|decoupled)\b", r"\b(off|disable|coupled|recouple)\b",
     "decouple_on", "decouple_off", "decouple_toggle", ("Decoupled.", "Coupled.", "Decoupled mode toggled.")),
    (r"\bgimbals?\b", r"\b(lock|locked|fixed)\b", r"\b(unlock|unlocked|free|gimballed)\b",
     "gimbals_lock", "gimbals_unlock", "gimbals_toggle", ("Gimbals locked.", "Gimbals free.", "Gimbals toggled.")),
]

VERBS = (r"\b(toggle|turn|switch|set|put|go|get|deploy|activate|open|close|hit|pop|fire|launch|use|engage|bring|drop|give|me|to|in|on|off|"
         r"up|down|mode|power|it|em|them|out|of|some|now)\b")

EXAMPLES = ["gear down", "gear up", "lights on", "lights off", "shields up", "shields down", "weapons online", "weapons offline",
            "engines on", "engines off", "open doors", "close doors", "lock doors", "unlock doors", "power on", "power off", "vtol on",
            "vtol off", "decouple", "coupled mode", "gimbals locked", "gimbals unlocked", "flight ready", "request landing", "autoland",
            "flares", "dump flares", "noise", "target highest threat", "target attacker", "next hostile", "target under reticle",
            "target subsystem", "unlock target", "pin target", "max power to shields", "max power to weapons", "max power to engines",
            "balance power", "less power to shields", "less power to weapons", "less power to engines", "nav mode", "scm mode",
            "quantum mode", "missile mode", "scan mode", "mining mode", "salvage mode", "engage quantum", "jump point", "ping",
            "starmap", "mobiglas", "night vision", "wipe visor", "autotarget"]


def _clean(text, name):
    t = text.lower()
    t = re.sub(r"[^a-z0-9%' ]+", " ", t)
    t = t.replace("'", "")
    t = re.sub(r"\s+", " ", t).strip()
    for a, b in MISHEARS:
        t = re.sub(r"\b" + re.escape(a.replace("'", "")) + r"\b", b, t)
    for pat, canon in OBJECTS:
        t = re.sub(r"\b(" + pat + r")\b", canon, t)
    if name:
        for part in {name.lower(), name.lower().replace("-", " ")}:
            t = re.sub(r"\b" + re.escape(part) + r"\b", " ", t)
    t = re.sub(r"\bof$", "off", t.strip())
    return re.sub(r"\s+", " ", t).strip()


def _short(t, pat, limit=2):
    left = re.sub(pat + "|" + VERBS, " ", t)
    return len(left.split()) <= limit


def _match(t):
    for pat, aid, say in ENGINEERING:
        if re.search(pat, t) and _short(t, pat, 1):
            return {"kind": "press", "action": aid, "say": say}
    for pat, aid, say in MODES:
        if re.search(pat, t) and _short(t, pat, 1):
            return {"kind": "press", "action": aid, "say": say}
    if re.search(r"\bdoors\b", t) and re.search(r"\b(lock|unlock|locked|unlocked|secure)\b", t):
        if re.search(r"\b(unlock|unlocked)\b", t):
            return {"kind": "press", "action": "doors_unlock", "say": "Doors unlocked.", "fallback": "doorlocks_toggle",
                    "fallback_say": "Door locks toggled."}
        return {"kind": "press", "action": "doors_lock", "say": "Doors locked.", "fallback": "doorlocks_toggle",
                "fallback_say": "Door locks toggled."}
    for pat, aid, say in PRESSES:
        if re.search(pat, t) and _short(t, pat, 2):
            out = {"kind": "press", "action": aid, "say": say}
            if aid == "target_reticle":
                out.update(fallback="target_ahead")
            return out
    for kw, on_re, off_re, on_a, off_a, tog_a, (s_on, s_off, s_tog) in STATEFUL:
        if not re.search(kw, t):
            continue
        rest = re.sub(kw, " ", t)
        on, off = bool(re.search(on_re, rest)), bool(re.search(off_re, rest))
        if on_a == "decouple_on":
            off = bool(re.search(r"\b(coupled|recouple)\b", t) and not re.search(r"\bdecoupled?\b", t)) or \
                bool(re.search(r"\bdecoupled? off\b|\boff decoupled?\b", t))
            on = bool(re.search(r"\b(decouple|decoupled)\b", t)) and not off
        if not _short(rest, on_re + "|" + off_re, 2):
            return None
        if on and not off:
            return {"kind": "press", "action": on_a, "say": s_on, "fallback": tog_a, "fallback_say": s_tog}
        if off and not on:
            return {"kind": "press", "action": off_a, "say": s_off, "fallback": tog_a, "fallback_say": s_tog}
        if re.search(r"\btoggle\b", t) or len(rest.split()) == 0:
            return {"kind": "press", "action": tog_a, "say": s_tog}
        return None
    return None


TARGET_WORDS = r"(target|targets|his|her|their|enemy|enemys|enemies|bandit|bandits|hostile|hostiles|they|he|she|its|that ships|that ship)"


def hud_request(t):
    """'target status', 'are his shields down', 'how's the target's hull' -> 'both' / 'shields' / 'hull'."""
    if re.search(r"\b(target status|status (on|of) (the )?target|check (the )?target|target report)\b", t):
        return "both"
    m = re.search(r"\b" + TARGET_WORDS + r" (shields|hull)\b", t) or re.search(r"\b(shields|hull) (on|of) (the )?" + TARGET_WORDS + r"\b", t)
    if not m:
        return None
    asking = re.search(r"\b(how|hows|what|whats|are|is|did|does|check|status|left|down|up|gone|holding|at)\b", t)
    if not asking:
        return None
    return "shields" if "shields" in m.group(0) else "hull"


def parse(text, name="Co-Pilot", macros=None):
    raw = text.lower().strip(" .!?")
    m = M.match(text, macros, name)
    if m:
        return {"kind": "macro", "macro": m}
    if re.fullmatch(r"(?:\w+ )?(?:turn |switch |show |hide |toggle )?(?:the )?(overlay|hud)(?: (on|off|show|hide|up|down))?(?: please)?", raw):
        on = None if not re.search(r"\b(on|off|show|hide|up|down)\b", raw) else bool(re.search(r"\b(on|show|up)\b", raw))
        if raw.startswith("show"):
            on = True
        elif raw.startswith("hide"):
            on = False
        return {"kind": "overlay", "on": on}
    if not raw:
        return None
    t0 = _clean(text, name)
    if re.search(r"\b(whos|who is|who the hell is) (shooting|attacking|firing|hitting|on)( at)? (me|us)\b", t0):
        return {"kind": "press", "action": "target_attacker", "say": None}
    hud = hud_request(t0)
    if hud:
        return {"kind": "hud", "what": hud}
    if "?" in text or QUESTION.match(raw) or QUESTION.match(t0):
        return None
    if re.search(r"\b(and|then|after|before|while|but|if|unless)\b", t0):
        return None
    if re.search(r"\b(self ?destruct|eject|bail out)\b", raw):
        return None
    t = re.sub(r"\s+", " ", FILLER.sub(" ", t0)).strip()
    if not t or len(t.split()) > 8:
        return None
    hit = _match(t)
    if hit:
        return hit
    if len(t.split()) <= 5:
        best = difflib.get_close_matches(t, EXAMPLES, n=1, cutoff=0.84)
        if best:
            hit = _match(best[0])
            if hit:
                hit["fuzzy"] = best[0]
                return hit
    return None
