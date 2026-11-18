import json

import sc_brain as BR
import sc_trade as T

PLACES = [
    {"kind": "city", "name": "Area 18", "planet_name": "ArcCorp", "star_system_name": "Stanton"},
    {"kind": "city", "name": "Lorville", "planet_name": "Hurston", "star_system_name": "Stanton"},
    {"kind": "city", "name": "Orison", "planet_name": "Crusader", "star_system_name": "Stanton"},
    {"kind": "station", "name": "Ruin Station", "planet_name": "Pyro VI", "star_system_name": "Pyro"},
]
VEHICLES = [
    {"id": 1, "name_full": "Anvil Arrow", "crew": "1", "roles": ["military"], "length": 17.2, "pad_type": "S"},
    {"id": 2, "name_full": "Aegis Vanguard Warden", "crew": "1", "roles": ["military"], "length": 48, "pad_type": "M"},
    {"id": 3, "name_full": "Drake Cutlass Black", "crew": "1", "roles": ["military", "cargo"], "length": 37.5, "pad_type": "M", "scu": 46},
    {"id": 6, "name_full": "Aegis Hammerhead", "crew": "2", "roles": ["military"], "length": 120, "pad_type": "L", "scu": 40},
    {"id": 7, "name_full": "Anvil Valkyrie", "crew": "1", "roles": ["military"], "length": 48, "pad_type": "M", "scu": 90},
    {"id": 4, "name_full": "MISC Freelancer", "crew": "2", "roles": ["cargo"], "scu": 66},
    {"id": 5, "name_full": "Drake Caterpillar", "crew": "4", "roles": ["cargo"], "scu": 576},
]
VBUY = [
    {"id_vehicle": 1, "terminal_name": "Astro Armada", "price_buy": 1984500},
    {"id_vehicle": 2, "terminal_name": "New Deal Lorville", "price_buy": 5800000},
    {"id_vehicle": 3, "terminal_name": "New Deal Lorville", "price_buy": 2400000},
    {"id_vehicle": 4, "terminal_name": "New Deal Crusader", "price_buy": 2100000},
    {"id_vehicle": 5, "terminal_name": "Ruin Station Dealer", "price_buy": 4100000},
    {"id_vehicle": 6, "terminal_name": "Astro Armada", "price_buy": 34466600},
    {"id_vehicle": 7, "terminal_name": "Astro Armada", "price_buy": 19845000},
]


def extra():
    x = T.UexExtra(T.Uex())
    data = {"vbuy": VBUY, "vehicles": VEHICLES, "places": PLACES}
    x._cached = lambda key, fetch: data[key]
    return x


def test_dealers_are_placed():
    d = extra().dealers()
    assert d["Astro Armada"]["place"].startswith("Area 18") and d["Astro Armada"]["system"] == "Stanton"
    assert d["New Deal Crusader"]["place"].startswith("Orison")
    assert d["Ruin Station Dealer"]["system"] == "Pyro"


def test_fighters_in_stanton_cheapest_first_heavy_priciest_first():
    x = extra()
    f = x.ships_for_sale("Stanton", "fighter")
    assert [s["ship"] for s in f["ships"]] == ["Anvil Arrow", "Aegis Vanguard Warden"]
    h = x.ships_for_sale("Stanton", "heavy fighter")
    assert h["ships"][0]["ship"] == "Aegis Vanguard Warden"
    assert "Astro Armada" in h["dealers"] and "Ruin Station Dealer" not in h["dealers"]


def test_kind_dealer_and_price_filters():
    x = extra()
    assert [s["ship"] for s in x.ships_for_sale(None, "cargo")["ships"]] == ["MISC Freelancer", "Drake Cutlass Black", "Drake Caterpillar"]
    assert [s["ship"] for s in x.ships_for_sale("Stanton", "light fighter")["ships"]] == ["Anvil Arrow"]
    assert [s["ship"] for s in x.ships_for_sale("Stanton", "", dealer="lorville")["ships"]] == ["Drake Cutlass Black", "Aegis Vanguard Warden"]
    assert [s["ship"] for s in x.ships_for_sale(None, "", max_price=2200000)["ships"]] == ["Anvil Arrow", "MISC Freelancer"]


def test_find_services_ship_dealer():
    r = extra().find_services("ship dealers", "Stanton")
    assert r["count"] == 3 and {x["dealer"] for x in r["results"]} == {"Astro Armada", "New Deal Lorville", "New Deal Crusader"}


def test_ai_has_the_tool():
    names = {t["name"] for t in BR.TOOLS + BR.TRADE_TOOLS + BR.INFO_TOOLS}
    assert "ships_for_sale" in names
    assert "ship dealer" in next(t for t in BR.INFO_TOOLS if t["name"] == "find_services")["description"]
    assert "ships_for_sale" in BR.SYSTEM
