import time

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

JURIS_SAY = {"Ungoverned": "Ungoverned space. Stay sharp.", "UEE": "UEE space.", "Rough & Ready": "Rough and Ready territory.",
             "People's Alliance": "People's Alliance territory.", "Headhunters": "Headhunters territory. Watch yourself.",
             "Citizens for Prosperity": "Citizens for Prosperity territory.", "XenoThreat": "XenoThreat territory. Watch yourself."}


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
        self.app.callout(text)

    def handle(self, name, info):
        st = self.app.state
        info = info or {}
        if name == "armistice" and self.on("zones"):
            self.say("Entering armistice. Weapons locked." if info.get("on") else "Leaving armistice. Weapons free.", key="arm", gap=12)
        elif name == "jurisdiction" and self.on("zones"):
            j = info.get("name", "")
            self.say(JURIS_SAY.get(j, f"Entering {j} jurisdiction."), key="juris", gap=25)
        elif name == "monitored" and self.on("zones"):
            self.say("Back in monitored space." if info.get("on") else "Leaving monitored space.", key="mon", gap=20)
        elif name == "comms_down" and self.on("zones"):
            self.say("Comm array's down here. No security watching.", key="comms", gap=120)
        elif name == "private" and self.on("zones") and info.get("on"):
            self.say("Private property. Trespassing can earn a CrimeStat.", key="priv", gap=60)
        elif name == "qt_arrived" and self.on("travel"):
            self.say("Quantum travel complete.", key="qt", gap=5)
        elif name == "qt_obstructed" and self.on("travel"):
            self.say("Quantum path's obstructed. Try another route.", key="qtx", gap=8)
        elif name == "hangar" and self.on("travel"):
            self.say("Hangar's ready.", key="hangar", gap=10)
        elif name == "kill" and self.on("combat"):
            with st.lock:
                n = len(st.kills)
            self.say(f"{info.get('victim', 'Target')} down. That's {n} this session." if n > 1 else
                     f"{info.get('victim', 'Target')} down.", key="kill", gap=1.5)
        elif name == "ship_lost" and self.on("combat"):
            self.say(f"We lost the {info.get('victim', 'ship')}.", key="lost", gap=5)
        elif name == "downed" and self.on("combat"):
            self.say("You're down. Call for help before the timer runs out.", key="down", gap=30)
        elif name == "crime" and self.on("combat"):
            ch = info.get("change", "")
            if "increase" in ch:
                self.say("CrimeStat increased. Security will be hostile.", key="crime", gap=20)
            elif "clear" in ch or "decrease" in ch:
                self.say("CrimeStat going down.", key="crime", gap=20)
        elif name == "destroyed_nearby" and self.on("threats"):
            if info.get("killer_is_player") and info.get("reason") == "Combat":
                self.say(f"{info['killer']} just destroyed {'an' if info['victim'][:1].lower() in 'aeiou' else 'a'} {info['victim']} nearby.",
                         key="threat", gap=6)
        elif name == "contract_accepted" and self.on("contracts"):
            self.say("Contract accepted. " + end(info.get("name", "")), key="ca", gap=2)
        elif name == "contract_end" and self.on("contracts"):
            status = info.get("status")
            if status == "complete":
                self.say("Contract complete. " + end(info.get("name", "")), key="ce", gap=2)
            elif status == "failed":
                self.say("Contract failed. " + end(info.get("name", "")), key="ce", gap=2)
        elif name == "objective" and self.on("contracts"):
            t = info.get("text", "")
            if t and len(t) < 90:
                self.say("New objective. " + end(t), key="obj", gap=4)
        elif name == "party" and self.on("social"):
            self.say(f"{info.get('who')} {'joined' if info.get('joined') else 'left'} the party.", key="party" + str(info.get("who")), gap=10)
        elif name == "money_in" and self.on("social"):
            self.say(f"{info.get('from')} sent you {spoken_money(info.get('amount'))} credits.", key="money", gap=3)
        elif name == "low_fuel" and self.on("alerts"):
            self.say("Fuel's low.", key="fuel", gap=90)
        elif name == "disconnect" and self.on("alerts"):
            r = info.get("reason", "")
            self.say("Disconnected for being idle." if "inactive" in r else "We got disconnected.", key="disc", gap=30)
        elif name == "crash" and self.on("alerts"):
            self.say("Looks like the game crashed.", key="crash", gap=60)
