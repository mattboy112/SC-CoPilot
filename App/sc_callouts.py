import time

import sc_lines as LN
from sc_log import spoken_money

CATEGORIES = [
    ("zones", "Zones: armistice, jurisdiction changes, monitored space, private property"),
    ("travel", "Travel: quantum arrivals, blocked quantum paths, hangar ready"),
    ("combat", "Combat: your kills, ship losses, being downed, CrimeStat"),
    ("threats", "Threats: a player destroys a ship near you"),
    ("contracts", "Contracts: accepted, complete, failed, new objectives"),
    ("social", "Social: party joins and leaves, aUEC sent to you"),
    ("alerts", "Alerts: low fuel, disconnects, game crashes"),
]

JURIS_KEY = {"Ungoverned": "juris_ungoverned", "UEE": "juris_uee"}
JURIS_NAME = {"Rough & Ready": "Rough and Ready"}


def end(text):
    text = (text or "").strip()
    return text if text[-1:] in ".!?" else text + "."


class Callouts:
    def __init__(self, app):
        self.app = app
        self.last = {}

    def on(self, cat):
        return self.app.settings.get("callouts", {}).get(cat, True)

    def ok(self, key, gap):
        now = time.time()
        if now - self.last.get(key, 0) < gap:
            return False
        self.last[key] = now
        return True

    def say(self, text, key=None, gap=0.0):
        if key and not self.ok(key, gap):
            return
        if text:
            self.app.callout(text)

    def L(self, key, **vals):
        return LN.line(self.app.settings, key, **vals)

    def handle(self, name, info):
        st = self.app.state
        info = info or {}
        if name == "armistice" and self.on("zones"):
            self.say(self.L("arm_on" if info.get("on") else "arm_off"), key="arm", gap=12)
        elif name == "jurisdiction" and self.on("zones"):
            j = info.get("name", "")
            self.say(self.L(JURIS_KEY[j]) if j in JURIS_KEY else self.L("juris_other", name=JURIS_NAME.get(j, j)), key="juris", gap=25)
        elif name == "monitored" and self.on("zones"):
            self.say(self.L("mon_on" if info.get("on") else "mon_off"), key="mon", gap=20)
        elif name == "comms_down" and self.on("zones"):
            self.say(self.L("comms_down"), key="comms", gap=120)
        elif name == "private" and self.on("zones") and info.get("on"):
            self.say(self.L("private"), key="priv", gap=60)
        elif name == "qt_arrived" and self.on("travel"):
            self.say(self.L("qt_arrived"), key="qt", gap=5)
        elif name == "qt_obstructed" and self.on("travel"):
            self.say(self.L("qt_obstructed"), key="qtx", gap=8)
        elif name == "hangar" and self.on("travel"):
            self.say(self.L("hangar"), key="hangar", gap=10)
        elif name == "kill" and self.on("combat"):
            with st.lock:
                n = len(st.kills)
            victim = info.get("victim", "Target")
            self.say(self.L("kill_n", victim=victim, n=n) if n > 1 else self.L("kill_first", victim=victim), key="kill", gap=1.5)
        elif name == "ship_lost" and self.on("combat"):
            self.say(self.L("ship_lost", victim=info.get("victim", "ship")), key="lost", gap=5)
        elif name == "downed" and self.on("combat"):
            self.say(self.L("downed"), key="down", gap=30)
        elif name == "crime" and self.on("combat"):
            ch = info.get("change", "")
            if "increase" in ch:
                self.say(self.L("crime_up"), key="crime", gap=20)
            elif "clear" in ch or "decrease" in ch:
                self.say(self.L("crime_down"), key="crime", gap=20)
        elif name == "destroyed_nearby" and self.on("threats"):
            if info.get("killer_is_player") and info.get("reason") == "Combat":
                v = info["victim"]
                self.say(self.L("threat", killer=info["killer"], a_victim=("an " if v[:1].lower() in "aeiou" else "a ") + v), key="threat", gap=6)
        elif name == "contract_accepted" and self.on("contracts"):
            self.say(self.L("contract_accepted", name=end(info.get("name", ""))), key="ca", gap=2)
        elif name == "contract_end" and self.on("contracts"):
            status = info.get("status")
            if status == "complete":
                self.say(self.L("contract_complete", name=end(info.get("name", ""))), key="ce", gap=2)
            elif status == "failed":
                self.say(self.L("contract_failed", name=end(info.get("name", ""))), key="ce", gap=2)
        elif name == "objective" and self.on("contracts"):
            t = info.get("text", "")
            if t and len(t) < 90:
                self.say(self.L("objective", text=end(t)), key="obj", gap=4)
        elif name == "party" and self.on("social"):
            self.say(self.L("party_join" if info.get("joined") else "party_leave", who=info.get("who")), key="party" + str(info.get("who")), gap=10)
        elif name == "money_in" and self.on("social"):
            self.say(self.L("money_in", who=info.get("from"), amount=spoken_money(info.get("amount"))), key="money", gap=3)
        elif name == "low_fuel" and self.on("alerts"):
            self.say(self.L("low_fuel"), key="fuel", gap=90)
        elif name == "disconnect" and self.on("alerts"):
            r = info.get("reason", "")
            self.say(self.L("disc_idle" if "inactive" in r else "disc"), key="disc", gap=30)
        elif name == "crash" and self.on("alerts"):
            self.say(self.L("crash"), key="crash", gap=60)
