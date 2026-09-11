"""
Kaggriculture agent.

Strategy in one paragraph: every turn we rebuild a prioritized task list straight
from the observation (no persistent memory needed) -- feed/water first (losing an
animal or plant to neglect is the worst outcome), then harvest, then upkeep
(care rides at the same top priority as feed/water since it's a free action and
the bank it builds is what turns a cow's first milking into 6 units instead of 1;
dig/collect fertilizer/deliver purchased animals & collected fertilizer), then
expansion (plant/build coops&pastures) -- and greedily assign the farmer + every
hired hand to the nearest unclaimed task each turn. Crop/animal choice for empty
tiles is scored against current market price plus two forward-looking demand
terms: permanent per-shop demand (a shop never closes once unlocked, so its
demand is known the moment it opens, not just once price reacts to it) and, for
the resources priced with a "hinge" scarcity curve (carrot/tomato/egg -- flat
until inventory crosses a threshold below I0, then a hard spike), how far
inventory already sits toward that threshold -- watching price alone catches the
spike after it's under way, watching inventory catches the approach while still
cheap to commit to. Soft per-type tile-share caps keep output diversified so we
never dump everything into one glutted product, with an early-game bias toward
fast-payback crops (wheat/carrot) so we aren't cash-starved while tomato/melon
are still maturing. Land and hires are bought whenever the payoff clearly
justifies the cost given days remaining. Selling is metered against a price
floor except in the final days, when everything is liquidated since unsold
inventory is worth nothing at game end.

Rules were taken from the installed kaggle_environments kaggriculture.py
(v0.1.0), which differs in a few places from earlier drafts of the docs:
market uses a "hinge" shape for a few resources on the scarcity side (doesn't
affect our selling-side math, which uses the "above I0" curve, unchanged),
shedCapacity blocks BUY_PRODUCT/BUY_ANIMAL once the shed is full, town center
demand is a flat 1/day (no day-10/20 ramp), DROP/PICKUP/PLACE work from
shed-adjacent tiles even in a not-yet-purchased (LOCKED) quadrant, and the
animal CARE bank accrues +1/day (not +2 as some drafts of the docs claim).
"""

# ---------------------------------------------------------------------------
# Static game data (mirrors kaggle_environments/envs/kaggriculture/kaggriculture.py)
# ---------------------------------------------------------------------------

CROPS = {
    "WHEAT":      {"seed": 10, "first_yield_day": 2, "max_yield_day": 4, "interval": 0, "max_yield": 6, "ongoing": False},
    "CARROT":     {"seed": 20, "first_yield_day": 2, "max_yield_day": 3, "interval": 0, "max_yield": 4, "ongoing": False},
    "TOMATO":     {"seed": 50, "first_yield_day": 8, "max_yield_day": 8, "interval": 1, "max_yield": 4, "ongoing": True},
    "STRAWBERRY": {"seed": 100, "first_yield_day": 10, "max_yield_day": 10, "interval": 2, "max_yield": 4, "ongoing": True},
    "MELON":      {"seed": 80, "first_yield_day": 10, "max_yield_day": 12, "interval": 0, "max_yield": 6, "ongoing": False},
}

ANIMALS = {
    "GOOSE": {"cost": 300, "structure": "COOP",    "first_yield_day": 4, "interval": 1, "max_held": 4, "product": "EGG"},
    "COW":   {"cost": 400, "structure": "PASTURE", "first_yield_day": 8, "interval": 2, "max_held": 6, "product": "MILK"},
    "SHEEP": {"cost": 500, "structure": "PASTURE", "first_yield_day": 6, "interval": 3, "max_held": 6, "product": "WOOL"},
}

ANIMAL_PRODUCT = {a: ANIMALS[a]["product"] for a in ANIMALS}

BASE_PRICE = {
    "WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120, "MELON": 250,
    "EGG": 50, "MILK": 160, "WOOL": 200, "FERTILIZER": 100,
}

# Town shops: once unlocked a shop never closes and consumes its listed
# products forever (single-product shops pull 2x). This is a deterministic,
# permanent demand signal -- no need to wait for price to catch up once we
# see which shops are open.
SHOPS = {
    "BAKERY":         ["EGG", "WHEAT"],
    "PIZZA_SHOP":     ["MILK", "TOMATO", "WHEAT"],
    "BRUNCH_SPOT":    ["EGG", "WHEAT", "STRAWBERRY"],
    "YARN_STORE":     ["WOOL"],
    "ICE_CREAM_SHOP": ["STRAWBERRY", "MILK", "WHEAT"],
    "PET_CAFE":       ["CARROT"],
    "SMOOTHIE_SHOP":  ["STRAWBERRY", "MILK"],
    "FARMERS_MARKET": ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY"],
}
SHOP_DEMAND_WEIGHT = 15  # $ score per shop-instance-unit of permanent demand

# The installed game (not the docs) prices CARROT/TOMATO/EGG with a "hinge"
# curve on the scarcity side: calm while inventory sits within T of I0, then
# a hard quadratic spike once it drops further. Current price alone catches
# the spike late; watching inventory trend toward the T threshold catches it
# while the crop is still cheap to commit to (relevant for tomato especially,
# which takes 8 days to first yield).
MARKET_I0 = 10000
HINGE_SCARCITY = {"CARROT": 450, "TOMATO": 200, "EGG": 332}  # product -> T
SCARCITY_WEIGHT = 30

# Max sellable yield per tile per day at optimal (unfertilized) care -- matches
# the README's own table; used to rank crop/animal ROI.
YIELD_PER_TILE_DAY = {
    "WHEAT": 1.5, "CARROT": 1.333, "TOMATO": 4.0, "STRAWBERRY": 2.0, "MELON": 0.5,
    "GOOSE": 2.0, "COW": 1.0, "SHEEP": 0.67,
}

# Rough amortized upfront-cost-per-day (seed/animal cost spread over a typical
# productive lifetime), so expensive slow-starters don't look artificially
# free next to wheat.
AMORTIZED_COST_PER_DAY = {
    "WHEAT": 10 / 5, "CARROT": 20 / 4, "TOMATO": 50 / 12, "STRAWBERRY": 100 / 17, "MELON": 80 / 13,
    "GOOSE": 300 / 30, "COW": 400 / 30, "SHEEP": 500 / 30,
}

# Soft caps on the share of unlocked tiles any one type may claim, so we never
# self-crash a single glut-sensitive market (strawberry/melon/milk/wool fall to
# the $1 floor fast on oversupply -- see the price table in README.md).
TILE_SHARE_CAP = {
    "WHEAT": 0.22, "CARROT": 0.15, "TOMATO": 0.25, "STRAWBERRY": 0.10, "MELON": 0.10,
    "GOOSE": 0.15, "COW": 0.10, "SHEEP": 0.08,
}

FERTILIZE_WORTHWHILE = {"TOMATO", "STRAWBERRY"}  # wheat/carrot/melon don't pay back the $100

BOOTSTRAP_CROPS = ("WHEAT", "CARROT")  # fast first_yield_day, keeps cash flowing early

LAND_ORDER = ["NE", "SW", "SE"]
LAND_PRICES = [1000, 2000, 4000]

TOTAL_DAYS = 30           # episodeSteps=720 / turnsPerDay=24 default
WIND_DOWN_DAY = 26         # stop starting anything that can't pay back in time
LIQUIDATE_DAY = 28         # start dumping shed contents regardless of price
BOOTSTRAP_DAY = 6          # favor wheat/carrot seed buys through this day
BOOTSTRAP_MONEY = 2500     # ...or while cash is still this tight, whichever is later

FEED_RESERVE_PER_ANIMAL = 3   # keep this many wheat in shed per live animal
CARGO_RETURN_THRESHOLD = 5    # unit inventory (sellables) heavy enough to prioritize a shed trip
ANIMAL_WHEAT_GATE = 8         # don't buy livestock until we can actually feed it


def _fib(n):
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


# ---------------------------------------------------------------------------
# Board helpers
# ---------------------------------------------------------------------------

def _shed_access_tiles(board_size):
    half = board_size // 2
    return [(half - 1, half - 1), (half, half - 1), (half - 1, half), (half, half)]


def _manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _step_towards(cur, target, board_size):
    """One-step greedy move reducing Manhattan distance. No obstacles on this board."""
    cx, cy = cur
    tx, ty = target
    dx, dy = tx - cx, ty - cy
    if dx == 0 and dy == 0:
        return "PASS"
    order = ((dx, "EAST", "WEST", True), (dy, "SOUTH", "NORTH", False)) if abs(dx) >= abs(dy) else \
            ((dy, "SOUTH", "NORTH", False), (dx, "EAST", "WEST", True))
    for delta, pos_move, neg_move, is_x in order:
        if delta > 0:
            nx, ny = (cx + 1, cy) if is_x else (cx, cy + 1)
            if 0 <= nx < board_size and 0 <= ny < board_size:
                return pos_move
        elif delta < 0:
            nx, ny = (cx - 1, cy) if is_x else (cx, cy - 1)
            if 0 <= nx < board_size and 0 <= ny < board_size:
                return neg_move
    return "PASS"


def _tile_at(tiles, pos, board_size):
    x, y = pos
    if not (0 <= x < board_size and 0 <= y < board_size):
        return None
    return tiles[y][x]


def _nearest(positions, pos):
    if not positions:
        return None
    return min(positions, key=lambda p: _manhattan(pos, p))


# ---------------------------------------------------------------------------
# Main agent
# ---------------------------------------------------------------------------

def agent(obs):
    farms = obs.get("farms", [])
    player = obs.get("player", 0)
    if not farms or player >= len(farms):
        return {"farmer": ["PASS"], "hands": [], "market": []}

    me = farms[player]
    private = obs.get("private", {}) or {}
    market = obs.get("market", {}) or {}
    town = obs.get("town", {}) or {}
    day = obs.get("day", 0)
    hour = obs.get("hour", 0)

    tiles = me["tiles"]
    board_size = len(tiles)
    shed = private.get("shed", {}) or {}
    seeds = private.get("seeds", {}) or {}
    inventories = list(private.get("inventories", [{}]) or [{}])
    prices = market.get("prices", {}) or {}
    market_inventory = market.get("inventory", {}) or {}
    unlocked_shops = town.get("unlocked_shops", []) or []
    money = me.get("money", 0)

    units = [me["farmer"]] + list(me.get("hands", []))
    n_units = len(units)
    while len(inventories) < n_units:
        inventories.append({})

    remaining_days = TOTAL_DAYS - day
    endgame = day >= LIQUIDATE_DAY
    wind_down = day >= WIND_DOWN_DAY

    n_animals_alive = sum(
        1 for row in tiles for t in row if isinstance(t, dict) and "animal" in t
    )

    # ------------------------------------------------------------------
    # 1. Build the prioritized task list from farm tiles (one grid pass).
    #    tier 1: FEED / WATER (critical -- must happen today)
    #    tier 2: HARVEST (ready produce)
    #    tier 3: CARE / DIG / COLLECT_FERTILIZER / fetch purchased animal
    #            or leftover shed fertilizer
    #    tier 4: PLANT / BUILD_COOP / BUILD_PASTURE (expansion)
    # ------------------------------------------------------------------
    tasks = {1: [], 2: [], 3: [], 4: []}

    plant_targets, animal_build_targets = _plan_expansion(
        tiles, board_size, seeds, prices, money, day, remaining_days, wind_down,
        market_inventory, unlocked_shops,
    )

    empty_structures = {"COOP": [], "PASTURE": []}
    eligible_fertilize_targets = []

    for y in range(board_size):
        for x in range(board_size):
            tile = tiles[y][x]
            if tile is None:
                if (x, y) in plant_targets:
                    tasks[4].append(("PLANT", (x, y), plant_targets[(x, y)]))
                elif (x, y) in animal_build_targets:
                    tasks[4].append((animal_build_targets[(x, y)], (x, y), None))
                continue
            if tile == "LOCKED" or not isinstance(tile, dict):
                continue
            kind = tile.get("kind")
            if kind == "WEED":
                tasks[3].append(("DIG", (x, y), None))
            elif kind == "PLANT":
                if not tile["watered_today"]:
                    tasks[1].append(("WATER", (x, y), None))
                if _plant_ready_to_harvest(tile, day):
                    tasks[2].append(("HARVEST", (x, y), None))
                if tile["crop"] in FERTILIZE_WORTHWHILE and tile.get("fertilized_until_day", -1) < day + 1:
                    eligible_fertilize_targets.append((x, y))
            elif kind in ("COOP", "PASTURE"):
                animal = tile.get("animal")
                if animal is None:
                    empty_structures[kind].append((x, y))
                    continue
                if not tile["fed_today"]:
                    tasks[1].append(("FEED", (x, y), None))
                if tile["yield_units"] > 0:
                    tasks[2].append(("HARVEST", (x, y), None))
                if not tile["cared_today"]:
                    tasks[3].append(("CARE", (x, y), None))
                if tile.get("fertilizer_available"):
                    tasks[3].append(("COLLECT_FERTILIZER", (x, y), None))

    # Fetch tasks: shed has a purchased animal / leftover fertilizer waiting
    # to be carried out. Target a shed-adjacent tile; PICKUP happens on arrival.
    shed_tiles = _shed_access_tiles(board_size)
    for animal_name, data in ANIMALS.items():
        need = min(shed.get(animal_name, 0), len(empty_structures[data["structure"]]))
        for k in range(need):
            tasks[3].append(("FETCH_ANIMAL", shed_tiles[k % 4], animal_name))
    if shed.get("FERTILIZER", 0) > 0 and eligible_fertilize_targets:
        tasks[3].append(("FETCH_FERTILIZER", shed_tiles[0], "FERTILIZER"))

    # ------------------------------------------------------------------
    # 2. Assign actions unit by unit.
    # ------------------------------------------------------------------
    unit_actions = [None] * n_units
    projected_shed = dict(shed)

    # 2z. Absolute top priority, ahead of even cargo/delivery logic below: if a
    # unit is already standing on a tile that needs watering or feeding right
    # now, do it before anything else. This is a free action (no movement, no
    # opportunity cost to whatever else the unit is carrying) and the loss for
    # skipping it can be total -- a plant not watered on the day it's planted
    # turns to a weed at the very next end-of-day refresh (planting itself
    # already counts as one unwatered day), and an animal is only one more
    # missed day from escaping for good. CARE rides along at the same priority
    # when standing on an already-fed animal: it's free, and skipping it costs
    # a whole day of banked bonus toward the animal's next payout (the bank is
    # what turns a fresh cow's first milking into 6 units instead of 1).
    tier1_by_pos = {t[1]: t for t in tasks[1]}
    care_by_pos = {t[1]: t for t in tasks[3] if t[0] == "CARE"}
    for i in range(n_units):
        pos = tuple(units[i])
        if pos in tier1_by_pos:
            op, tpos, extra = tier1_by_pos.pop(pos)
            tasks[1].remove((op, tpos, extra))
            unit_actions[i] = _finalize_tile_action(op, extra)
        elif pos in care_by_pos:
            op, tpos, extra = care_by_pos.pop(pos)
            tasks[3].remove((op, tpos, extra))
            unit_actions[i] = _finalize_tile_action(op, extra)

    # 2a. Units already carrying fertilizer / an animal act on that cargo first
    # (deliver-in-progress takes priority over starting something new).
    for i in range(n_units):
        pos = tuple(units[i])
        inv = inventories[i] if i < len(inventories) else {}
        tile = _tile_at(tiles, pos, board_size)

        if inv.get("FERTILIZER", 0) > 0:
            if tile != "LOCKED" and isinstance(tile, dict) and tile.get("kind") == "PLANT" \
               and tile["crop"] in FERTILIZE_WORTHWHILE and tile.get("fertilized_until_day", -1) < day + 1:
                unit_actions[i] = ["FERTILIZE"]
                continue
            target = _nearest(eligible_fertilize_targets, pos)
            if target is not None:
                unit_actions[i] = [_step_towards(pos, target, board_size)]
                continue

        for animal_name, data in ANIMALS.items():
            if inv.get(animal_name, 0) <= 0:
                continue
            struct = data["structure"]
            if tile != "LOCKED" and isinstance(tile, dict) and tile.get("kind") == struct and "animal" not in tile:
                unit_actions[i] = ["PLACE", animal_name]
            else:
                target = _nearest(empty_structures[struct], pos)
                if target is not None:
                    unit_actions[i] = [_step_towards(pos, target, board_size)]
            break
        if unit_actions[i] is not None:
            continue

    # 2b. Cargo management: a unit sitting on a meaningful harvest should bank
    # it rather than wander off chasing the next-nearest task indefinitely --
    # tasks are plentiful enough on an active farm that "return when idle"
    # never actually triggers. Heavy cargo gets a dedicated trip that preempts
    # tiers 2-4; light cargo is only dropped opportunistically in passing.
    shed_tile_set = set(shed_tiles)

    def _cargo(inv):
        return sum(v for k, v in inv.items() if k not in ANIMALS and k != "FERTILIZER")

    def _do_drop(i, pos, inv):
        unit_actions[i] = ["DROP"]
        for item, n in inv.items():
            if item in ANIMALS or item == "FERTILIZER":
                continue
            room = max(0, 100 - sum(projected_shed.values()))
            take = min(n, room)
            if take > 0:
                projected_shed[item] = projected_shed.get(item, 0) + take

    for i in range(n_units):
        if unit_actions[i] is not None:
            continue
        pos = tuple(units[i])
        inv = inventories[i] if i < len(inventories) else {}
        cargo = _cargo(inv)
        if cargo >= CARGO_RETURN_THRESHOLD:
            if pos in shed_tile_set:
                _do_drop(i, pos, inv)
            else:
                target = _nearest(shed_tiles, pos)
                unit_actions[i] = [_step_towards(pos, target, board_size)]

    # 2c. Opportunistic light drop: already shed-adjacent, some cargo, and
    # nothing more urgent to do on this exact tile right now.
    for i in range(n_units):
        if unit_actions[i] is not None:
            continue
        pos = tuple(units[i])
        inv = inventories[i] if i < len(inventories) else {}
        cargo = _cargo(inv)
        if pos in shed_tile_set and cargo > 0:
            tile = _tile_at(tiles, pos, board_size)
            if not _has_local_urgent_task(tile, day):
                _do_drop(i, pos, inv)

    # 2d. Tiered nearest-task assignment for everyone still free.
    for tier in (1, 2, 3, 4):
        pool = tasks[tier]
        free_units = [i for i in range(n_units) if unit_actions[i] is None]
        for i in free_units:
            if not pool:
                break
            pos = tuple(units[i])
            best_idx = min(range(len(pool)), key=lambda k: _manhattan(pos, pool[k][1]))
            op, tpos, extra = pool.pop(best_idx)
            if pos == tpos:
                unit_actions[i] = _finalize_tile_action(op, extra)
            else:
                unit_actions[i] = [_step_towards(pos, tpos, board_size)]

    # 2e. Anyone still idle (no tasks anywhere): any leftover cargo at all ->
    # head to shed; otherwise hold position.
    for i in range(n_units):
        if unit_actions[i] is not None:
            continue
        pos = tuple(units[i])
        inv = inventories[i] if i < len(inventories) else {}
        if _cargo(inv) > 0 and pos not in shed_tile_set:
            target = _nearest(shed_tiles, pos)
            unit_actions[i] = [_step_towards(pos, target, board_size)]
        else:
            unit_actions[i] = ["PASS"]

    farmer_action = unit_actions[0]
    hands_actions = unit_actions[1:]

    # ------------------------------------------------------------------
    # 3. Market orders.
    # ------------------------------------------------------------------
    market_orders = _plan_market(
        me=me, private=private, market=market, day=day, hour=hour,
        projected_shed=projected_shed, n_animals_alive=n_animals_alive,
        endgame=endgame, wind_down=wind_down, remaining_days=remaining_days,
        animal_build_targets=animal_build_targets, empty_structures=empty_structures,
        tiles=tiles, board_size=board_size, unlocked_shops=unlocked_shops,
    )

    return {"farmer": farmer_action, "hands": hands_actions, "market": market_orders}


# ---------------------------------------------------------------------------
# Task-list helpers
# ---------------------------------------------------------------------------

def _plant_ready_to_harvest(tile, day):
    if tile.get("yield_units", 0) <= 0:
        return False
    crop = tile["crop"]
    cd = CROPS[crop]
    age = day - tile["planted_day"]
    if age < cd["first_yield_day"]:
        return False
    if cd["ongoing"]:
        return True  # no reason to delay; nothing is forfeited by harvesting promptly
    # One-time crop: harvesting clears the tile, so ride out the watering-bonus
    # window (ends at max_yield_day) rather than forfeiting future bonus units.
    return age >= cd["max_yield_day"] or tile["yield_units"] >= cd["max_yield"]


def _has_local_urgent_task(tile, day):
    if not isinstance(tile, dict):
        return False
    kind = tile.get("kind")
    if kind == "PLANT":
        return not tile["watered_today"] or _plant_ready_to_harvest(tile, day)
    if kind in ("COOP", "PASTURE") and "animal" in tile:
        return not tile["fed_today"] or tile["yield_units"] > 0
    return False


def _finalize_tile_action(op, extra):
    if op == "PLANT":
        return ["PLANT", extra]
    if op in ("FETCH_ANIMAL", "FETCH_FERTILIZER"):
        return ["PICKUP", extra, 1]
    return [op]


# ---------------------------------------------------------------------------
# Economics: what to plant / build next
# ---------------------------------------------------------------------------

def _demand_bonus(product, market_inventory, unlocked_shops):
    """Forward-looking demand beyond current price: permanent per-shop demand
    (deterministic and monotonic -- a shop never closes) plus, for the
    hinge-priced scarcity items, how far inventory already sits toward the
    spike threshold. Current price alone reacts only once the spike is under
    way; this catches the approach while the crop is still cheap to commit
    to, which matters most for the slow-maturing ones (tomato: 8 days)."""
    bonus = 0.0
    for shop in unlocked_shops:
        products = SHOPS.get(shop, ())
        if product in products:
            bonus += SHOP_DEMAND_WEIGHT * (2 if len(products) == 1 else 1)
    T = HINGE_SCARCITY.get(product)
    if T:
        inv = market_inventory.get(product, MARKET_I0)
        ratio = max(0.0, MARKET_I0 - inv) / T
        bonus += SCARCITY_WEIGHT * min(ratio, 1.5)
    return bonus


def _crop_score(crop, prices, market_inventory, unlocked_shops):
    price = prices.get(crop, BASE_PRICE[crop])
    base = YIELD_PER_TILE_DAY[crop] * price - AMORTIZED_COST_PER_DAY[crop]
    return base + _demand_bonus(crop, market_inventory, unlocked_shops)


def _animal_score(animal, prices, market_inventory, unlocked_shops):
    product = ANIMAL_PRODUCT[animal]
    price = prices.get(product, BASE_PRICE[product])
    feed_cost_per_day = prices.get("WHEAT", BASE_PRICE["WHEAT"])  # ~1 wheat/day/animal
    base = YIELD_PER_TILE_DAY[animal] * price - AMORTIZED_COST_PER_DAY[animal] - feed_cost_per_day
    return base + _demand_bonus(product, market_inventory, unlocked_shops)


def _pick_diversified(ranked, counts, unlocked_tiles):
    """Pick the next type to plant/build from a rank-ordered candidate list,
    respecting TILE_SHARE_CAP. If every candidate is already at or over its
    cap, spread the overflow by relative overage instead of piling further
    onto whichever single type currently scores highest -- two near-tied top
    scorers (e.g. tomato/strawberry) would otherwise alternate hitting their
    *own* cap while the fallback kept re-picking the marginally-higher one,
    letting it run away far past its intended share."""
    under_cap = [c for c in ranked if counts.get(c, 0) < TILE_SHARE_CAP[c] * unlocked_tiles]
    if under_cap:
        return under_cap[0]
    return min(ranked, key=lambda c: counts.get(c, 0) / max(TILE_SHARE_CAP[c] * unlocked_tiles, 0.01))


def _plan_expansion(tiles, board_size, seeds, prices, money, day, remaining_days, wind_down,
                     market_inventory, unlocked_shops):
    """Decide what goes on currently-empty tiles: returns (plant_targets, animal_build_targets),
    both {(x, y): value}, splitting the empty-tile pool between crops and new
    animal structures and respecting soft diversification caps."""
    empty = []
    crop_counts = {c: 0 for c in CROPS}
    animal_counts = {a: 0 for a in ANIMALS}
    unlocked_tiles = 0
    for y in range(board_size):
        for x in range(board_size):
            tile = tiles[y][x]
            if tile == "LOCKED":
                continue
            unlocked_tiles += 1
            if tile is None:
                empty.append((x, y))
            elif isinstance(tile, dict):
                if tile.get("kind") == "PLANT":
                    crop_counts[tile["crop"]] = crop_counts.get(tile["crop"], 0) + 1
                elif "animal" in tile:
                    animal_counts[tile["animal"]] = animal_counts.get(tile["animal"], 0) + 1

    if not empty or unlocked_tiles == 0:
        return {}, {}

    # Fill outward from the shed first: keeps the day's work clustered near
    # the drop-off point instead of scattering across the whole unlocked
    # farm, which cuts travel time for both watering rounds and shed trips.
    shed_tiles = _shed_access_tiles(board_size)
    empty.sort(key=lambda p: min(_manhattan(p, st) for st in shed_tiles))

    crop_fraction = 0.8 if day < BOOTSTRAP_DAY else 0.6
    n_crop_slots = max(1, int(len(empty) * crop_fraction)) if not wind_down else len(empty)
    crop_slots = empty[:n_crop_slots]
    animal_slots = [] if wind_down else empty[n_crop_slots:]

    plant_targets = {}
    if not wind_down or remaining_days >= 4:
        ranked_crops = sorted(
            (c for c in CROPS if seeds.get(c, 0) > 0 and (not wind_down or remaining_days >= CROPS[c]["max_yield_day"] + 2)),
            key=lambda c: -_crop_score(c, prices, market_inventory, unlocked_shops),
        )
        if ranked_crops:
            for pos in crop_slots:
                crop = _pick_diversified(ranked_crops, crop_counts, unlocked_tiles)
                plant_targets[pos] = crop
                crop_counts[crop] = crop_counts.get(crop, 0) + 1

    animal_build_targets = {}
    if animal_slots:
        ranked_animals = sorted(ANIMALS, key=lambda a: -_animal_score(a, prices, market_inventory, unlocked_shops))
        reserve = 400
        for pos in animal_slots:
            best = _pick_diversified(ranked_animals, animal_counts, unlocked_tiles)
            if money - reserve < ANIMALS[best]["cost"]:
                continue  # don't pre-build structures we can't staff soon
            struct = ANIMALS[best]["structure"]
            animal_build_targets[pos] = "BUILD_COOP" if struct == "COOP" else "BUILD_PASTURE"
            animal_counts[best] = animal_counts.get(best, 0) + 1

    return plant_targets, animal_build_targets


# ---------------------------------------------------------------------------
# Market orders
# ---------------------------------------------------------------------------

def _plan_market(me, private, market, day, hour, projected_shed, n_animals_alive,
                  endgame, wind_down, remaining_days, animal_build_targets,
                  empty_structures, tiles, board_size, unlocked_shops):
    orders = []
    money = me.get("money", 0)
    prices = market.get("prices", {}) or {}
    market_inventory = market.get("inventory", {}) or {}
    seeds = private.get("seeds", {}) or {}
    unlocked = me.get("unlocked_quadrants", ["NW"])
    shed_total = sum(projected_shed.values())
    bootstrapping = day < BOOTSTRAP_DAY or money < BOOTSTRAP_MONEY

    # --- SELL: convert shed stock to cash every turn, metered against a price
    # floor except right before game end (unsold inventory is worth 0 at the
    # final step, so liquidate everything then) or when the shed is filling up
    # (holding back risks losing overflow, or blocking future purchases since
    # a full shed refuses BUY_PRODUCT/BUY_ANIMAL).
    sell_candidates = []
    wheat_reserve = FEED_RESERVE_PER_ANIMAL * max(n_animals_alive, 0)
    for item, qty in projected_shed.items():
        if item == "FERTILIZER" or qty <= 0:
            continue
        sellable = qty - wheat_reserve if item == "WHEAT" else qty
        if sellable <= 0:
            continue
        price = prices.get(item, BASE_PRICE.get(item, 1))
        base = BASE_PRICE.get(item, price)
        if not endgame and shed_total < 70 and price < 0.35 * base and sellable < 20:
            continue  # crashed price, small stash, room to spare: let it recover
        sell_candidates.append((sellable * price, item, sellable))
    sell_candidates.sort(key=lambda c: -c[0])

    budget = 10
    for _, item, qty in sell_candidates:
        if budget <= 1:  # keep at least one slot free for a buy order
            break
        orders.append(["SELL", item, qty])
        budget -= 1

    # --- HIRE: once per day, at hour 0, scaled to how much land/work exists.
    if hour == 0 and budget > 0:
        planted_or_building = sum(
            1 for row in tiles for t in row
            if isinstance(t, dict) and t.get("kind") in ("PLANT", "COOP", "PASTURE")
        )
        unlocked_tiles = sum(1 for row in tiles for t in row if t != "LOCKED")
        # Coverage, not cash, is the binding constraint on a spread-out farm --
        # an idle tile earns nothing regardless of how much money sits in the
        # bank, and hiring stays cheap (fib-scaled from $1) well past the
        # point where it pays for itself in a single day's extra harvesting.
        target_hands = min(10, max(unlocked_tiles // 8, planted_or_building // 5))
        # Hiring is cheap (fib-scaled from $1) and hands are the single best
        # lever for covering more tiles -- don't let a large fixed reserve
        # block it the way a flat $300 floor would once cash is tight.
        reserve = min(150, max(20, money * 0.1))
        spend = 0
        hires = 0
        n = 0
        while hires < target_hands and budget > 0:
            cost = _fib(n)
            if money - reserve - spend < cost:
                break
            orders.append(["HIRE"])
            spend += cost
            hires += 1
            n += 1
            budget -= 1
        money -= spend

    # --- BUY_LAND: opportunistic, always leave a reserve, only with enough
    # runway left to earn the purchase back, and only once the land we
    # already have is mostly developed -- buying a whole new 25-tile
    # quadrant while half the current farm is still empty just spreads the
    # existing workforce thinner instead of adding real throughput (the
    # quadrant then sits idle for a week or more before it's filled).
    if budget > 0 and not wind_down and len(unlocked) - 1 < len(LAND_ORDER):
        cost = LAND_PRICES[len(unlocked) - 1]
        reserve = 500
        unlocked_tile_count = sum(1 for row in tiles for t in row if t != "LOCKED")
        developed = sum(1 for row in tiles for t in row if isinstance(t, dict))
        utilization = developed / max(unlocked_tile_count, 1)
        if money - reserve >= cost and remaining_days >= 10 and utilization >= 0.55:
            orders.append(["BUY_LAND"])
            budget -= 1
            money -= cost

    # --- BUY_SEED: keep a small buffer per crop we intend to keep planting.
    # During bootstrap, prioritize wheat/carrot (fast payback) over the
    # higher-steady-state-value but slow-to-mature tomato/strawberry/melon,
    # so early cash flow isn't starved waiting on an 8-10 day first harvest.
    if budget > 0 and not wind_down:
        def seed_key(c):
            is_fast = c in BOOTSTRAP_CROPS
            return (0 if (bootstrapping and is_fast) else 1, -_crop_score(c, prices, market_inventory, unlocked_shops))

        for crop in sorted(CROPS, key=seed_key):
            if budget <= 0:
                break
            have = seeds.get(crop, 0)
            target_buffer = 4
            if have >= target_buffer:
                continue
            need = target_buffer - have
            cost_each = CROPS[crop]["seed"]
            reserve = 200
            afford = max(0, int((money - reserve) // cost_each)) if cost_each > 0 else 0
            n = min(need, afford, 6)
            if n > 0:
                orders.append(["BUY_SEED", crop, n])
                money -= n * cost_each
                budget -= 1

    # --- BUY_ANIMAL: only when we actually have (or are about to have) an
    # empty matching structure waiting, so purchases don't idle in the shed
    # (which would also eat into shedCapacity headroom). Also gated on an
    # established wheat supply -- an animal placed before we can feed it
    # daily starves and escapes within two days, losing the full purchase.
    wheat_established = projected_shed.get("WHEAT", 0) >= ANIMAL_WHEAT_GATE or day >= 6
    if budget > 0 and not wind_down and shed_total < 90 and wheat_established:
        waiting = {
            "COOP": len(empty_structures.get("COOP", [])),
            "PASTURE": len(empty_structures.get("PASTURE", [])),
        }
        for op in animal_build_targets.values():
            struct = "COOP" if op == "BUILD_COOP" else "PASTURE"
            waiting[struct] = waiting.get(struct, 0) + 1
        for animal in sorted(ANIMALS, key=lambda a: -_animal_score(a, prices, market_inventory, unlocked_shops)):
            if budget <= 0:
                break
            struct = ANIMALS[animal]["structure"]
            slots = waiting.get(struct, 0) - projected_shed.get(animal, 0)
            if slots <= 0:
                continue
            cost = ANIMALS[animal]["cost"]
            reserve = 400
            if money - reserve >= cost:
                orders.append(["BUY_ANIMAL", animal, 1])
                money -= cost
                waiting[struct] -= 1
                budget -= 1

    # --- BUY_PRODUCT WHEAT: emergency feed stopgap only, never the primary
    # source (growing wheat is far cheaper than buying it back).
    if budget > 0 and n_animals_alive > 0 and shed_total < 95:
        have_wheat = projected_shed.get("WHEAT", 0)
        if have_wheat < n_animals_alive:
            deficit = n_animals_alive - have_wheat
            price = prices.get("WHEAT", BASE_PRICE["WHEAT"])
            reserve = 100
            afford = max(0, int((money - reserve) // max(price, 1)))
            n = min(deficit, afford, 10)
            if n > 0:
                orders.append(["BUY_PRODUCT", "WHEAT", n])
                budget -= 1

    return orders[:10]
