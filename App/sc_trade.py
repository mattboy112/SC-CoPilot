import difflib
import json
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import sc_paths as P

APP_DIR = P.APP_DIR
CACHE_FILE = P.cache("sc_uex_commodities.json")
BASES = ["https://api.uexcorp.uk/2.0", "https://api.uexcorp.space/2.0"]
UA = "SC-CoPilot/1.1 (+personal companion app)"
PRICE_TTL = 15 * 60
LIST_TTL = 24 * 3600
SYSTEMS = ["Stanton", "Pyro", "Nyx"]


class UexError(RuntimeError):
    pass


def ago(ts):
    if not ts:
        return "unknown"
    s = int(time.time() - float(ts))
    if s < 3600:
        return f"{max(1, s // 60)}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def where(row):
    bits = []
    for k in ("space_station_name", "outpost_name", "city_name", "moon_name", "planet_name", "orbit_name"):
        v = row.get(k)
        if v and v not in bits and v != row.get("terminal_name"):
            bits.append(v)
        if len(bits) >= 2:
            break
    sysname = row.get("star_system_name") or ""
    return ", ".join(bits + ([sysname] if sysname else []))


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


class Uex:
    def __init__(self):
        self.lock = threading.Lock()
        self.commodities = []
        self.commodities_ts = 0
        self.price_cache = {}
        self.last_error = ""
        self.base = BASES[0]
        try:
            d = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            self.commodities, self.commodities_ts = d.get("data", []), d.get("ts", 0)
        except (OSError, ValueError):
            pass

    def _get(self, resource, **params):
        q = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
        last = None
        for base in [self.base] + [b for b in BASES if b != self.base]:
            url = f"{base}/{resource}" + (f"?{q}" if q else "")
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=12) as r:
                    d = json.loads(r.read().decode("utf-8"))
            except Exception as ex:
                last = ex
                continue
            self.base = base
            st = d.get("status")
            if st == "ok":
                self.last_error = ""
                return d.get("data") or []
            if st == "requests_limit_reached":
                raise UexError("UEX rate limit reached. Try again in a minute.")
            raise UexError(f"UEX said: {d.get('message') or st}")
        self.last_error = f"Couldn't reach UEX ({type(last).__name__ if last else 'no response'})"
        raise UexError(self.last_error + ". Check your internet.")

    def load_commodities(self, force=False):
        with self.lock:
            if self.commodities and not force and time.time() - self.commodities_ts < LIST_TTL:
                return self.commodities
        data = self._get("commodities")
        keep = ("id", "name", "code", "slug", "kind", "price_buy", "price_sell", "is_raw", "is_refined", "is_mineral",
                "is_harvestable", "is_buyable", "is_sellable", "is_illegal", "is_volatile_qt", "is_extractable")
        rows = [{k: c.get(k) for k in keep} for c in data if c.get("name")]
        with self.lock:
            self.commodities, self.commodities_ts = rows, time.time()
        try:
            CACHE_FILE.write_text(json.dumps({"ts": self.commodities_ts, "data": rows}), encoding="utf-8")
        except OSError:
            pass
        return rows

    def find(self, query):
        """Best commodity match for a spoken/typed name. Returns (commodity or None, alternatives)."""
        rows = self.commodities or self.load_commodities()
        q = norm(query)
        if not q:
            return None, []
        q2 = q[:-1] if q.endswith("s") and len(q) > 4 else q
        raw_wanted = "raw" in q.split() or "ore" in q.split()
        q3 = " ".join(w for w in q2.split() if w not in ("raw", "ore", "refined"))
        exact = [c for c in rows if norm(c["name"]) in (q, q2) or norm(c.get("code")) == q]
        if exact:
            return exact[0], []
        base = [c for c in rows if norm(re.sub(r"\(.*?\)", "", c["name"])) == q3]
        if base:
            base.sort(key=lambda c: (bool(c.get("is_raw")) != raw_wanted, len(c["name"])))
            return base[0], [c["name"] for c in base[1:4]]
        starts = [c for c in rows if norm(c["name"]).startswith(q3)]
        contains = starts or [c for c in rows if q3 in norm(c["name"])]
        if contains:
            contains.sort(key=lambda c: (bool(c.get("is_raw")) != raw_wanted, len(c["name"])))
            return contains[0], [c["name"] for c in contains[1:4]]
        names = {norm(c["name"]): c for c in rows}
        bare = {}
        for n, c in names.items():
            bare.setdefault(norm(re.sub(r"\(.*?\)", "", c["name"])), []).append(c)
        close = difflib.get_close_matches(q3, list(bare), n=3, cutoff=0.76)
        if close:
            cands = sorted(bare[close[0]], key=lambda c: (bool(c.get("is_raw")) != raw_wanted, len(c["name"])))
            others = [c["name"] for k in close for c in bare[k] if c is not cands[0]]
            return cands[0], others[:4]
        return None, [c["name"] for c in rows if difflib.SequenceMatcher(None, q3, norm(c["name"])).ratio() > 0.5][:4]

    def prices(self, commodity):
        cid = commodity["id"]
        with self.lock:
            hit = self.price_cache.get(cid)
            if hit and time.time() - hit[0] < PRICE_TTL:
                return hit[1]
        rows = list(self._get("commodities_prices", id_commodity=cid))
        if commodity.get("is_raw"):
            try:
                seen = {(r.get("id_terminal"), r.get("price_sell")) for r in rows}
                for r in self._get("commodities_raw_prices", id_commodity=cid):
                    if (r.get("id_terminal"), r.get("price_sell")) not in seen:
                        rows.append(r)
            except UexError:
                pass
        with self.lock:
            self.price_cache[cid] = (time.time(), rows)
        return rows

    @staticmethod
    def _row(r, side):
        price = float(r.get(f"price_{side}") or 0)
        scu = r.get("scu_buy") if side == "buy" else r.get("scu_sell")
        return {"terminal": r.get("terminal_name") or "?", "where": where(r), "system": r.get("star_system_name") or "",
                "price": round(price), "avg_week": round(float(r.get(f"price_{side}_avg_week") or 0)),
                "scu": int(float(scu)) if scu not in (None, "") else None,
                "updated": ago(r.get("date_modified")), "updated_ts": float(r.get("date_modified") or 0),
                "reports": r.get(f"price_{side}_users_rows")}

    def best(self, query, side="sell", system=None, limit=8):
        c, alts = self.find(query)
        if not c:
            return {"error": f"No commodity called '{query}'." + (f" Did you mean {', '.join(alts)}?" if alts else "")}
        rows = self.prices(c)
        out = []
        for r in rows:
            if float(r.get(f"price_{side}") or 0) <= 0:
                continue
            if system and (r.get("star_system_name") or "").lower() != system.lower():
                continue
            out.append(self._row(r, side))
        out.sort(key=lambda x: -x["price"] if side == "sell" else x["price"])
        systems = sorted({(r.get("star_system_name") or "") for r in rows if float(r.get(f"price_{side}") or 0) > 0} - {""})
        return {"commodity": c["name"], "side": side, "system_filter": system or "all", "results": out[:limit],
                "systems_with_data": systems, "also_matched": alts,
                "commodity_avg": {"buy": round(float(c.get("price_buy") or 0)), "sell": round(float(c.get("price_sell") or 0))},
                "flags": [f for f, k in (("illegal", "is_illegal"), ("volatile in QT", "is_volatile_qt")) if c.get(k)]}

    def route(self, query, system=None, scu=None):
        buys = self.best(query, "buy", system, limit=50)
        if "error" in buys:
            return buys
        sells = self.best(query, "sell", system, limit=50)
        if not buys["results"] or not sells["results"]:
            return {"commodity": buys["commodity"], "error": "Not enough buy and sell data for a route" + (f" in {system}" if system else "") + "."}
        b, s = buys["results"][0], sells["results"][0]
        if system is None:
            pairs = [(bb, ss) for bb in buys["results"][:12] for ss in sells["results"][:12] if bb["system"] == ss["system"]]
            if pairs:
                b, s = max(pairs, key=lambda p: p[1]["price"] - p[0]["price"])
        margin = s["price"] - b["price"]
        out = {"commodity": buys["commodity"], "buy_at": b, "sell_at": s, "margin_per_scu": margin,
               "note": "Community-reported prices (UEX). Check stock and demand at the terminal before loading up."}
        if scu:
            out["profit_for_scu"] = {"scu": scu, "cost": b["price"] * scu, "profit": margin * scu}
        return out


def objective_commodities(texts):
    found = []
    for t in texts:
        for m in re.finditer(r"\bof ([A-Z][A-Za-z ()'-]{2,40}?)(?:$|[,.:;]| to | at | for )", t + "."):
            name = m.group(1).strip()
            if name and name not in found:
                found.append(name)
    return found[:8]


SERVICES = {"refuel": "has_refuel", "fuel": "has_refuel", "repair": "has_repair", "rearm": "has_repair", "refinery": "has_refinery",
            "refine": "has_refinery", "clinic": "has_clinic", "medical": "has_clinic", "hospital": "has_clinic", "shops": "has_shops",
            "shop": "has_shops", "food": "has_food", "habitation": "has_habitation", "hab": "has_habitation", "cargo": "has_cargo_center",
            "cargo_center": "has_cargo_center", "trade": "has_trade_terminal", "trade_terminal": "has_trade_terminal",
            "loading_dock": "has_loading_dock", "docking_port": "has_docking_port", "freight_elevator": "has_freight_elevator"}
PLACE_KEEP = ("id", "name", "nickname", "code", "star_system_name", "planet_name", "orbit_name", "moon_name", "city_name",
              "jurisdiction_name", "faction_name", "pad_types", "is_armistice", "is_monitored", "is_landable", "is_available_live",
              "is_lagrange", "is_jump_point") + tuple(sorted(set(SERVICES.values())))
VEH_KEEP = ("id", "name", "name_full", "company_name", "scu", "crew", "mass", "length", "width", "height", "pad_type",
            "fuel_quantum", "fuel_hydrogen", "is_concept", "game_version")
SHIP_DEALER_WORDS = ("ship dealer", "ship dealers", "ship shop", "ship shops", "shipyard", "shipyards", "ships", "ship",
                     "vehicle dealer", "vehicle dealers", "vehicles", "dealer", "dealers", "ship store", "ship sales")
DEALER_HINTS = {"astro armada": "Area 18", "new deal crusader": "Orison", "crusader showroom": "Orison"}
COMBAT_WORDS = ("fight", "combat", "military", "dogfight", "interceptor", "gunship", "bomber", "attack", "pvp", "bounty")
KIND_ROLES = {"cargo": "cargo", "haul": "cargo", "freight": "cargo", "trade": "cargo", "mining": "mining", "miner": "mining",
              "salvage": "salvage", "medical": "medical", "med": "medical", "explor": "exploration", "racing": "racing",
              "racer": "racing", "ground": "ground_vehicle", "buggy": "ground_vehicle", "tank": "ground_vehicle",
              "bike": "ground_vehicle", "starter": "starter", "beginner": "starter", "refuel": "refuel", "repair": "repair",
              "passenger": "passenger", "stealth": "stealth", "data": "datarunner", "science": "science", "scan": "scanning",
              "interdict": "interdiction", "emp": "emp", "boarding": "boarding", "construction": "construction"}


NOT_FIGHTER_ROLES = {"cargo", "carrier", "industrial", "refinery", "medical", "boarding", "scanning", "ground_vehicle"}


def is_fighter(v, kind=""):
    """Small, armed, next to no cargo. UEX's crew number is the minimum crew, so size and cargo do the work.
    light/medium/heavy in `kind` narrow it by length (ships with no length on file stay in)."""
    roles = set(v.get("roles") or [])
    if roles & NOT_FIGHTER_ROLES or ("bomber" in roles and "bomber" not in kind):
        return False
    if "module" in str(v.get("name_full") or "").lower() or str(v.get("pad_type") or "").upper() in ("L", "XL"):
        return False
    try:
        length, scu = float(v.get("length") or 0), float(v.get("scu") or 0)
    except ValueError:
        length, scu = 0.0, 0.0
    if scu > 8 or length > 50:
        return False
    if "light" in kind:
        return 0 < length <= 22
    if "medium" in kind:
        return 22 < length <= 30
    if "heavy" in kind:
        return length == 0 or length > 26
    return True


def max_crew(crew):
    nums = [int(n) for n in re.findall(r"\d+", str(crew or ""))]
    return max(nums) if nums else 0


VEH_ROLES = ("is_boarding", "is_bomber", "is_cargo", "is_carrier", "is_civilian", "is_construction", "is_datarunner", "is_emp",
             "is_exploration", "is_ground_vehicle", "is_industrial", "is_interdiction", "is_medical", "is_military", "is_mining",
             "is_passenger", "is_qed", "is_racing", "is_refinery", "is_refuel", "is_repair", "is_salvage", "is_scanning",
             "is_science", "is_stealth", "is_starter", "is_tractor_beam")


class UexExtra:
    """Locations/services, ships, items and refinery yields from UEX, cached on disk."""
    TTL = {"places": 24 * 3600, "vehicles": 24 * 3600, "vbuy": 12 * 3600, "vrent": 12 * 3600, "items": 12 * 3600, "yields": 12 * 3600}

    def __init__(self, uex):
        self.uex = uex
        self.mem = {}
        self.lock = threading.Lock()

    def _cached(self, key, fetch):
        with self.lock:
            hit = self.mem.get(key)
            if hit and time.time() - hit[0] < self.TTL[key]:
                return hit[1]
        f = P.cache(f"sc_uex_{key}.json")
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if time.time() - d.get("ts", 0) < self.TTL[key] and d.get("data"):
                with self.lock:
                    self.mem[key] = (d["ts"], d["data"])
                return d["data"]
        except (OSError, ValueError):
            pass
        data = fetch()
        ts = time.time()
        with self.lock:
            self.mem[key] = (ts, data)
        try:
            f.write_text(json.dumps({"ts": ts, "data": data}), encoding="utf-8")
        except OSError:
            pass
        return data

    def places(self):
        def fetch():
            out = []
            for kind, res in (("station", "space_stations"), ("city", "cities"), ("outpost", "outposts")):
                try:
                    rows = self.uex._get(res)
                except UexError:
                    continue
                for r in rows:
                    if str(r.get("is_available_live", 1)) == "0":
                        continue
                    d = {k: r.get(k) for k in PLACE_KEEP if r.get(k) not in (None, "")}
                    d["kind"] = kind
                    out.append(d)
            if not out:
                raise UexError("Couldn't load locations from UEX.")
            return out
        return self._cached("places", fetch)

    @staticmethod
    def _place_text(p):
        parts = []
        for x in (p.get("moon_name") or p.get("orbit_name"), p.get("planet_name"), p.get("star_system_name")):
            if x and x not in parts and x != p.get("name"):
                parts.append(x)
        loc = ", ".join(parts)
        return f"{p['name']}" + (f" ({loc})" if loc else "")

    @staticmethod
    def _flags(p):
        return [k[4:].replace("_", " ") for k in sorted(set(SERVICES.values())) if str(p.get(k, 0)) == "1"]

    def dealers(self):
        """Every ship dealer seen in the price data, with where it is (UEX's price rows only carry the shop name)."""
        vb = self._cached("vbuy", lambda: self.uex._get("vehicles_purchases_prices_all"))
        places = self.places()
        out = {}
        for name in sorted({r.get("terminal_name") for r in vb if r.get("terminal_name")}):
            tn = norm(name)
            hint = norm(next((v for k, v in DEALER_HINTS.items() if k in tn), ""))
            best = None
            for p in places:
                for key in ("name", "nickname", "city_name"):
                    c = norm(p.get(key))
                    if len(c) > 3 and ((hint and c.replace(" ", "") == hint.replace(" ", "")) or re.search(rf"\b{re.escape(c)}\b", tn)):
                        if best is None or len(c) > best[0] or (len(c) == best[0] and p["kind"] == "city"):
                            best = (len(c), p)
            if best:
                p = best[1]
                out[name] = {"place": self._place_text(p), "system": p.get("star_system_name") or ""}
                continue
            for p in places:
                pl = norm(p.get("planet_name"))
                if len(pl) > 3 and re.search(rf"\b{re.escape(pl)}\b", tn):
                    out[name] = {"place": f"{p['planet_name']}, {p.get('star_system_name')}", "system": p.get("star_system_name") or ""}
                    break
            else:
                out[name] = {"place": "", "system": ""}
        return out

    def ships_for_sale(self, system=None, kind="", dealer="", max_price=None, limit=50):
        """Ships you can buy in game, narrowed by star system, type (fighter, cargo, mining...) or name, cheapest first."""
        vb = self._cached("vbuy", lambda: self.uex._get("vehicles_purchases_prices_all"))
        vehicles = {v.get("id"): v for v in self.vehicles()}
        dealers = self.dealers()
        k, dn = norm(kind), norm(dealer)
        combat = any(w in k for w in COMBAT_WORDS)
        role = next((r for w, r in KIND_ROLES.items() if w in k), None) if not combat else None
        ships = {}
        for r in vb:
            price = float(r.get("price_buy") or 0)
            v = vehicles.get(r.get("id_vehicle"))
            d = dealers.get(r.get("terminal_name"), {"place": "", "system": ""})
            if price <= 0 or not v:
                continue
            if system and d["system"].lower() != system.lower():
                continue
            if dn and dn not in norm(f"{r.get('terminal_name')} {d['place']}"):
                continue
            if max_price and price > float(max_price):
                continue
            roles = v.get("roles") or []
            if combat:
                if "ground_vehicle" in roles or not ({"military", "bomber"} & set(roles)):
                    continue
                if "bomber" in k and "bomber" not in roles:
                    continue
                if any(w in k for w in ("fight", "interceptor", "dogfight")) and not is_fighter(v, k):
                    continue
            elif role:
                if role not in roles:
                    continue
            elif k and k not in norm(f"{v.get('name_full')} {v.get('company_name')}"):
                continue
            s = ships.setdefault(v["id"], {"ship": v.get("name_full") or v.get("name"), "crew": v.get("crew"),
                                           "pad": v.get("pad_type"), "shops": []})
            if v.get("scu"):
                s["cargo_scu"] = v.get("scu")
            s["shops"].append((round(price), r.get("terminal_name")))
        out = []
        for s in ships.values():
            s["shops"].sort()
            s["price"] = s["shops"][0][0]
            s["at"] = [f"{w} {p:,}" for p, w in s.pop("shops")[:3]]
            out.append(s)
        out.sort(key=lambda s: s["price"], reverse="heavy" in k)
        here = {n: d["place"] for n, d in dealers.items() if not system or d["system"].lower() == system.lower()}
        return {"system": system or "all", "kind": kind or "any", "count": len(out), "ships": out[:limit],
                "dealers": here,
                "note": "Only lists ships sold in game for aUEC. Roles are broad; use your own knowledge of each ship's class "
                        "(light, medium or heavy fighter, bomber and so on) to pick from this list."}

    def find_services(self, service, system=None, near="", limit=12):
        if norm(service) in SHIP_DEALER_WORDS:
            here = [{"dealer": n, "where": d["place"], "system": d["system"]} for n, d in self.dealers().items()
                    if not system or d["system"].lower() == system.lower()]
            return {"service": "ship dealer", "system_filter": system or "all", "count": len(here), "results": here,
                    "tip": "Use ships_for_sale to see which ships each dealer sells and the prices."}
        key = SERVICES.get(norm(service).replace(" ", "_")) or SERVICES.get(norm(service).split(" ")[0])
        if not key:
            return {"error": f"Don't know the service '{service}'. Try: refuel, repair, refinery, clinic, shops, food, habitation, cargo, trade, ship dealer."}
        rows = [p for p in self.places() if str(p.get(key, 0)) == "1"]
        if system:
            rows = [p for p in rows if (p.get("star_system_name") or "").lower() == system.lower()]
        n = norm(near)
        if n:
            def score(p):
                hay = norm(" ".join(str(p.get(k) or "") for k in ("name", "nickname", "planet_name", "moon_name", "orbit_name")))
                return -sum(1 for w in n.split() if len(w) > 2 and w in hay)
            rows.sort(key=score)
        out = [{"place": self._place_text(p), "type": p["kind"], "armistice": str(p.get("is_armistice", 0)) == "1",
                "pads": p.get("pad_types"), "jurisdiction": p.get("jurisdiction_name"), "services": self._flags(p)} for p in rows[:limit]]
        return {"service": key[4:], "system_filter": system or "all", "count": len(rows), "results": out}

    def place_info(self, name):
        rows = self.places()
        q = norm(name)
        best, score = None, 0.0
        for p in rows:
            for cand in (p.get("name"), p.get("nickname"), p.get("code")):
                if not cand:
                    continue
                c = norm(cand)
                s = 1.0 if c == q else 0.92 if q and (q in c or c in q) else difflib.SequenceMatcher(None, q, c).ratio()
                if s > score:
                    best, score = p, s
        if not best or score < 0.6:
            return {"error": f"No location matching '{name}'."}
        p = best
        return {"place": self._place_text(p), "type": p["kind"], "jurisdiction": p.get("jurisdiction_name"),
                "faction": p.get("faction_name"), "armistice": str(p.get("is_armistice", 0)) == "1",
                "monitored": str(p.get("is_monitored", 0)) == "1", "pads": p.get("pad_types"), "services": self._flags(p)}

    def vehicles(self):
        def fetch():
            out = []
            for r in self.uex._get("vehicles"):
                d = {k: r.get(k) for k in VEH_KEEP if r.get(k) not in (None, "")}
                d["roles"] = [k[3:] for k in VEH_ROLES if str(r.get(k, 0)) == "1"]
                out.append(d)
            return out
        return self._cached("vehicles", fetch)

    def _find_named(self, rows, query, keys=("name", "name_full")):
        q = norm(query)
        best, score = None, 0.0
        for r in rows:
            for k in keys:
                c = norm(r.get(k))
                if not c:
                    continue
                s = 1.0 if c == q else 0.93 if (q in c and len(q) > 2) else 0.9 if (c in q and len(c) > 3) else \
                    difflib.SequenceMatcher(None, q, c).ratio()
                if s > score:
                    best, score = r, s
        return (best, score) if score >= 0.62 else (None, score)

    def ship(self, query):
        v, _ = self._find_named(self.vehicles(), query)
        if not v:
            return {"error": f"No ship or vehicle matching '{query}'."}
        buys = [r for r in self._cached("vbuy", lambda: self.uex._get("vehicles_purchases_prices_all")) if r.get("id_vehicle") == v["id"]]
        rents = [r for r in self._cached("vrent", lambda: self.uex._get("vehicles_rentals_prices_all")) if r.get("id_vehicle") == v["id"]]
        buys.sort(key=lambda r: float(r.get("price_buy") or 9e12))
        rents.sort(key=lambda r: float(r.get("price_rent") or 9e12))
        return {"ship": v.get("name_full") or v.get("name"), "maker": v.get("company_name"), "cargo_scu": v.get("scu"),
                "crew": v.get("crew"), "pad": v.get("pad_type"), "roles": v.get("roles"),
                "size_m": [v.get("length"), v.get("width"), v.get("height")], "quantum_fuel": v.get("fuel_quantum"),
                "in_game_buy": [{"where": r.get("terminal_name"), "price": round(float(r.get("price_buy") or 0)),
                                 "updated": ago(r.get("date_modified"))} for r in buys[:8] if float(r.get("price_buy") or 0) > 0],
                "rent_per_day": [{"where": r.get("terminal_name"), "price": round(float(r.get("price_rent") or 0)),
                                  "updated": ago(r.get("date_modified"))} for r in rents[:8] if float(r.get("price_rent") or 0) > 0],
                "note": "In-game aUEC prices reported to UEX. Empty lists mean it isn't sold or rented in game (or nobody's reported it)."}

    def item(self, query, limit=10):
        rows = self._cached("items", lambda: [{k: r.get(k) for k in ("id_item", "item_name", "price_buy", "price_sell", "terminal_name",
                                                                      "date_modified")} for r in self.uex._get("items_prices_all")])
        names = {}
        for r in rows:
            names.setdefault(r.get("item_name") or "", []).append(r)
        q = norm(query)
        scored = []
        for n in names:
            c = norm(n)
            if not c:
                continue
            s = 1.0 if c == q else 0.95 if q in c else difflib.SequenceMatcher(None, q, c).ratio()
            scored.append((s, n))
        scored.sort(reverse=True)
        if not scored or scored[0][0] < 0.6:
            return {"error": f"No item matching '{query}'."}
        name = scored[0][1]
        hits = [r for r in names[name] if float(r.get("price_buy") or 0) > 0]
        hits.sort(key=lambda r: float(r["price_buy"]))
        return {"item": name, "also_matched": [n for s, n in scored[1:5] if s >= 0.7],
                "where_to_buy": [{"where": r.get("terminal_name"), "price": round(float(r["price_buy"])),
                                  "updated": ago(r.get("date_modified"))} for r in hits[:limit]],
                "note": "In-game shop prices reported to UEX."}

    def yields(self, commodity=None, system=None, limit=10):
        rows = self._cached("yields", lambda: self.uex._get("refineries_yields"))
        if system:
            rows = [r for r in rows if (r.get("star_system_name") or "").lower() == system.lower()]
        if commodity:
            c, _ = self.uex.find(commodity)
            if not c:
                return {"error": f"No commodity '{commodity}'."}
            base = norm(re.sub(r"\(.*?\)", "", c["name"]))
            rows = [r for r in rows if norm(re.sub(r"\(.*?\)", "", r.get("commodity_name") or "")) == base]
            rows.sort(key=lambda r: -float(r.get("value") or 0))
            return {"commodity": c["name"], "best_refineries": [
                {"refinery": r.get("terminal_name"), "where": ", ".join(x for x in (r.get("space_station_name") or r.get("city_name"),
                                                                                    r.get("planet_name"), r.get("star_system_name")) if x),
                 "yield_bonus_pct": r.get("value")} for r in rows[:limit]],
                "note": "Refinery yield bonus (or penalty) in percent for that material, reported to UEX."}
        best = {}
        for r in rows:
            t = r.get("terminal_name")
            best.setdefault(t, []).append((float(r.get("value") or 0), r.get("commodity_name")))
        return {"refineries": [{"refinery": t, "top_bonuses": [f"{n} {v:+.0f}%" for v, n in sorted(v, reverse=True)[:4]]}
                               for t, v in list(best.items())[:limit]]}
