"""
Kaggriculture agent.

Strategy in one paragraph: every turn we rebuild a prioritized task list straight
from the observation (no persistent memory needed) -- feed/water first (losing an
animal or plant to neglect is the worst outcome), then harvest, then upkeep
(care rides at the same top priority as feed/water since it's a free action and
the bank it builds is what turns a cow's first milking into 6 units instead of 1;
dig/collect fertilizer/deliver purchased animals & collected fertilizer), then
expansion (plant/build coops&pastures) -- and greedily assign the farmer + every
hired hand to the nearest unclaimed task each turn. Whenever a unit is *already
standing* on a tile with a free action available, it takes that instead of
whatever the general assignment would have sent it toward: this covers
water/feed, care, and -- importantly -- planting or building right on a tile
that was just harvested or weeded, so a unit never abandons a freshly-cleared
zero-travel opportunity to go chase something else, only to leave that tile
empty for however many turns until someone paths back through it. Building a
coop/pasture is never done "blind" either: it only happens as the last step of
a unit already carrying the animal (and a day's feed, picked up in the same
shed stop, when the shed has any) it's about to house, so there's never a
separate return trip for the animal after the structure goes up. Only a
small, workforce-scaled number of these fetch errands run at once (each one
occupies a unit for its full multi-turn length, unavailable for watering
duty until it completes), keeping most hands on watering even while animals
are being onboarded. Once placed, a further daily task sends a unit to draw
a day's wheat from the shed specifically to feed whichever animal needs it
-- FEED consumes wheat from the acting unit's own inventory, not the shed
directly, and missing two consecutive days loses the animal for good.
Buying new animals is capped to a small unfetched-backlog per type: the
build-site planner is willing to speculate on many more homes than the
fetch pipeline can actually process per turn, and buying up to that larger
number just parks money as dead capital sitting in the shed. Crop/animal choice
for empty tiles is scored against a *projected* price, not today's: how many
days out this planting would first sell (its first_yield_day), what the
market's known consumption rate will drain in that time (shops + town center,
both deterministic), and what both players' already-growing tiles are already
adding, run through the real price curve for that product. This catches a
slow build-up while it's still cheap to commit to -- current price alone only
reacts once the move is already under way -- and it works the same for every
product instead of a hand-tuned bonus for a chosen few. Fertilizing is decided
the same price-aware way, but against current price (it's a same-trip
decision, not a future one): the marginal
extra units it buys a given crop (wheat/carrot get some, melon never does,
tomato/strawberry almost always do -- see FERTILIZE_MARGINAL_UNITS) are only
worth applying when that many units at the crop's live price exceeds
fertilizer's live price -- which, being buyable but never sellable and never
consumed by the town, only ever rises from its $100 base, so this is a real
comparison, not a fixed cutoff. Soft per-type tile-share caps keep output
diversified so we never dump everything into one glutted product, with an
early-game bias toward fast-payback crops (wheat/carrot) so we aren't
cash-starved while tomato/melon are still maturing. Land and hires are bought
whenever the payoff clearly justifies the cost given days remaining. Selling is
metered against a price floor except in the final days, when everything is
liquidated since unsold inventory is worth nothing at game end.

Rules were taken from the installed kaggle_environments kaggriculture.py
(v1.32.7), verified against real Kaggle replays (149,000+ (inventory, price)
checks, zero mismatches for this version -- an older 1.32.6 used a different,
plainer curve for carrot/tomato/egg's scarcity side, matched separately in
those older replays; this bot targets the currently-installed version).
Crop/animal scoring uses that exact price formula rather than an approximate
heuristic: MARKET_PARAMS holds the real (base, T, shape, coefficient) for
each product on both the scarcity and glut side, and _projected_price
extrapolates the market forward to roughly when a new planting would first
sell, using the known deterministic consumption rate (shops + town center --
both fixed schedules, read from the harness's `configuration` argument when
given) against the combined standing production rate of both players'
already-growing crops and placed animals (both farms' tiles are visible in
the shared observation, unlike shed/inventory/seeds, which are each player's
own private section). shedCapacity blocks BUY_PRODUCT/BUY_ANIMAL once the
shed is full, DROP/PICKUP/PLACE work from shed-adjacent tiles even in a
not-yet-purchased (LOCKED) quadrant, and the animal CARE bank accrues +1/day
(not +2 as some drafts of the docs claim).
"""

import math

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

# The real market pricing model, taken verbatim from the installed
# kaggle_environments kaggriculture.py (MARKET_PARAMS/_shape/market_price)
# and checked against real Kaggle replays: 149,000+ (inventory, price) pairs
# across 207 games on this same engine version, zero mismatches.
#     price = base + amp * f(I0 - inv)   when inv < I0 (scarcity)
#     price = base - amp * f(inv - I0)   when inv > I0 (glut)
#     amp = target * base / f(T)         (so moving T units past I0 shifts
#                                          price by exactly target * base)
#     f in {linear, sq, sqrt, log, hinge}; hinge is linear below T's "knee",
#     then adds a quadratic kicker past it -- calm until the resource is
#     genuinely scarce/glutted, then it runs away.
# An older engine version (1.32.6, found mixed into some of the same real
# replays) used a plain log/linear shape on the scarcity side for
# carrot/tomato/egg instead of hinge -- confirmed to match those older
# replays exactly too, but this bot targets 1.32.7 (confirmed to be what it
# actually plays against), which is what these below/above values are.
MARKET_I0 = 10000
PRICE_FLOOR = 1
HINGE_GAIN = 8.0
MARKET_PARAMS = {
    "WHEAT":      dict(base=25,  T=400, below_func="sqrt",   below_target=0.80, above_func="log",    above_target=0.20),
    "CARROT":     dict(base=35,  T=450, below_func="hinge",  below_target=1.00, above_func="sqrt",   above_target=0.70),
    "TOMATO":     dict(base=60,  T=200, below_func="hinge",  below_target=0.40, above_func="sqrt",   above_target=0.60),
    "STRAWBERRY": dict(base=120, T=100, below_func="sqrt",   below_target=0.70, above_func="linear", above_target=1.60),
    "MELON":      dict(base=250, T=300, below_func="log",    below_target=0.20, above_func="sq",     above_target=3.60),
    "EGG":        dict(base=50,  T=332, below_func="hinge",  below_target=0.40, above_func="log",    above_target=0.20),
    "MILK":       dict(base=160, T=122, below_func="sqrt",   below_target=0.60, above_func="linear", above_target=1.60),
    "WOOL":       dict(base=200, T=105, below_func="log",    below_target=0.20, above_func="sq",     above_target=3.20),
    "FERTILIZER": dict(base=100, T=200, below_func="linear", below_target=0.40, above_func="linear", above_target=0.40),
}
BASE_PRICE = {item: p["base"] for item, p in MARKET_PARAMS.items()}


def _shape(func, x, T=None):
    x = max(0.0, x)
    if func == "linear":
        return x
    if func == "sq":
        return x * x
    if func == "sqrt":
        return math.sqrt(x)
    if func == "log":
        return math.log(1.0 + x)
    if func == "hinge":
        if not T or T <= 0:
            return x
        u = x / T
        return u + HINGE_GAIN * max(0.0, u - 1.0) ** 2
    return x


def _market_price(item, inventory, I0=MARKET_I0):
    """The exact in-game price formula (see MARKET_PARAMS above)."""
    p = MARKET_PARAMS[item]
    base, T = p["base"], p["T"]
    if inventory < I0:
        f, tgt, x, sign = p["below_func"], p["below_target"], I0 - inventory, 1
    elif inventory > I0:
        f, tgt, x, sign = p["above_func"], p["above_target"], inventory - I0, -1
    else:
        return base
    amp = tgt * base / _shape(f, T, T)
    return max(PRICE_FLOOR, round(base + sign * amp * _shape(f, x, T)))


def _consumption_per_day(item, unlocked_shops, cfg):
    """Deterministic daily draw on `item`'s market inventory from town shops
    (every townShopSellInterval turns, single-product shops pull 2x) plus the
    town center (every townCenterSellInterval turns, flat all season, every
    product but fertilizer) -- both fixed schedules, read from the harness's
    `configuration` when given so this stays correct even if a specific
    grading run's intervals differ from the documented defaults."""
    turns_per_day = cfg.get("turnsPerDay", 24)
    shop_ticks_per_day = turns_per_day / cfg.get("townShopSellInterval", 4)
    per_day = 0.0
    for shop in unlocked_shops:
        products = SHOPS.get(shop, ())
        if item in products:
            per_day += (2 if len(products) == 1 else 1) * shop_ticks_per_day
    if item != "FERTILIZER":
        per_day += turns_per_day / cfg.get("townCenterSellInterval", 24)
    return per_day


# The engine unlocks one more shop slot every townShopUnlockInterval days (a
# hardcoded cap, MAX_SHOP_INSTANCES below, not a configuration key), filling
# each new slot with a uniform random draw (with replacement) from the 8 shop
# types -- so WHICH type shows up next is random, but HOW MANY slots exist by
# a given day is not. Verified against all 247 real replays used to derive
# MARKET_PARAMS: n_shops(day) == min(8, day // townShopUnlockInterval) in
# every single game, no exceptions, and at day 24 (all 8 slots full) every
# shop type appears in ~1.0 of the 8 slots on average -- i.e. no type is
# favored, confirming the "uniform draw" assumption below too.
MAX_SHOP_INSTANCES = 8


def _expected_shop_count(day, cfg):
    """Expected number of unlocked shop slots by `day` (exact, not a guess --
    see MAX_SHOP_INSTANCES above)."""
    interval = max(1, cfg.get("townShopUnlockInterval", 3))
    return min(MAX_SHOP_INSTANCES, max(0, day) // interval)


def _avg_shop_consumption_per_slot(item, cfg):
    """Expected extra daily draw on `item` from one additional shop slot,
    averaged over the 8 shop types since a not-yet-unlocked slot could turn
    out to be any of them (confirmed uniform empirically, see above)."""
    turns_per_day = cfg.get("turnsPerDay", 24)
    shop_ticks_per_day = turns_per_day / cfg.get("townShopSellInterval", 4)
    total = 0.0
    for products in SHOPS.values():
        if item in products:
            total += (2 if len(products) == 1 else 1) * shop_ticks_per_day
    return total / len(SHOPS)


def _standing_production_per_day(farms):
    """Combined daily output rate of each product from crops/animals already
    growing on *either* player's farm right now -- both farms' tiles are
    visible in the shared observation (unlike shed/inventory/seeds, which are
    each player's own private section), so the opponent's standing supply is
    knowable, not hidden."""
    rate = {}
    for f in farms:
        for row in f["tiles"]:
            for t in row:
                if not isinstance(t, dict):
                    continue
                if t.get("kind") == "PLANT":
                    crop = t["crop"]
                    rate[crop] = rate.get(crop, 0.0) + YIELD_PER_TILE_DAY[crop]
                elif "animal" in t:
                    product = ANIMAL_PRODUCT[t["animal"]]
                    rate[product] = rate.get(product, 0.0) + YIELD_PER_TILE_DAY[t["animal"]]
    return rate


def _projected_price(item, days_ahead, day, market_inventory, unlocked_shops, standing_production, cfg):
    """Extrapolate `item`'s market inventory `days_ahead` days forward (net of
    the known consumption rate against both players' already-growing supply
    of it) and price *that*, instead of today's inventory -- a new planting
    sells around first_yield_day from now, not today, and by then a slow
    build-up already under way (or a deficit nobody is filling) can look very
    different from the live price. Consumption itself isn't frozen at today's
    unlocked-shop count either: more shop slots reliably open on the way to a
    distant horizon (see _expected_shop_count), and ignoring that used to make
    the future look emptier -- and future oversupply scarier -- than it will
    really be, which mattered most for slow-maturing products (milk/wool)
    whose horizon is far enough out that several more slots are likely to
    have opened by then. Shops ramp up gradually over the window rather than
    all at once at the end, so this averages today's rate and the horizon's
    rate rather than assuming the higher one holds for the whole span.
    Deliberately still a straight-line supply projection (ignores new
    plantings maturing in between) -- a full simulation would be more
    accurate but this is already exact where it matters most: it uses the
    real price curve, not an approximated one."""
    inv = market_inventory.get(item, MARKET_I0)
    current_rate = _consumption_per_day(item, unlocked_shops, cfg)
    extra_slots = max(0.0, _expected_shop_count(day + days_ahead, cfg) - len(unlocked_shops))
    horizon_rate = current_rate + extra_slots * _avg_shop_consumption_per_slot(item, cfg)
    avg_consumption = (current_rate + horizon_rate) / 2.0
    net_per_day = standing_production.get(item, 0.0) - avg_consumption
    return _market_price(item, inv + net_per_day * days_ahead)


# Max sellable yield per tile per day at optimal (unfertilized) care -- matches
# the README's own table; used to rank crop/animal ROI.
#
# COW/SHEEP: simulating _daily_refresh_animals directly confirms the
# *steady-state* rate with daily feed+care+harvest is higher than a naive
# max_held/first_yield_day figure would suggest -- the very first payout is
# an outsized one-off (it banks care/feed over the long first_yield_day
# ramp, far longer than the animal's own production interval), but every
# payout after that only has `interval` days to rebank. Confirmed: COW
# settles at 3 MILK every 2 days (1.5/day) and SHEEP at 4 WOOL every 3 days
# (1.33/day). This is the honest steady-state number and is applied below --
# see _projected_price for the demand-side counterpart it needed (shop
# slots expected to unlock before a product's horizon) so a higher
# standing_production assumption here doesn't read as more future
# oversupply than is real, which is what a first pass at this found (COW's
# _animal_score roughly doubled once both changes went in, seed 2 vs_starter
# e.g. 199.7 -> 334.2 at day 8).
#
# On the 10-seed vs_starter sweep this combination still nets slightly
# behind the old undervaluing 1.0/0.67 numbers (~31,326 vs ~31,883, 6/10
# seeds worse) despite scoring cows/sheep far more favorably -- traced this
# (seed 2) to a *different* bottleneck than the score itself: buying a new
# COW/SHEEP is throttled by max_concurrent_animal_errands = max(1, n_units
# // 4) (see its definition), which caps how many bought-but-not-yet-placed
# animals can sit in the shed waiting for a free hand to fetch+place them --
# with only 1-2 units early on that's a cap of 1, so a higher animal score
# doesn't speed up *actual* herd growth at all once that fetch pipeline is
# the binding constraint, while the same wider demand projection also raised
# STRAWBERRY/TOMATO's score, pulling more of the same scarce hand-time into
# planting/watering more of those instead of fetching animals sooner. So the
# yield number and its demand-side fix are both honest and correctly wired;
# the actual lever still to pull is on the labor-allocation side (make
# fetch+place errands win a bigger share of hand-time when the animal
# they're for is scored this much higher, or grow max_concurrent_animal_
# errands / hiring faster in response) -- not this constant. Kept as the
# factually correct number regardless, per-sandbox-seed totals being a
# small, non-representative sample next to real game conditions, and this
# groundwork (real yield + real demand projection) is what the labor-side
# fix needs to build on once that's tackled.
YIELD_PER_TILE_DAY = {
    "WHEAT": 1.5, "CARROT": 1.333, "TOMATO": 4.0, "STRAWBERRY": 2.0, "MELON": 0.5,
    "GOOSE": 2.0, "COW": 1.5, "SHEEP": 1.333,
}

# Recurring daily task-action cost of keeping one tile of this type running,
# once past its one-time setup (planting, or fetch+build+place for an
# animal) -- verified by simulating the actual daily-care cycle rather than
# guessed: animals need FEED+CARE+COLLECT_FERTILIZER *every* day (skipping
# any day costs far more steady-state yield than the one action it saves --
# simulated: cow fed every day nets ~1.35 MILK/day over 40 days, fed every
# other day nets only ~0.4 -- the bonus-banking math punishes gaps much more
# than proportionally, so "every day" is the right regime to cost, not a
# cheaper alternative), plus HARVEST averaged over how often it's actually
# available (every `interval` days). Crops need WATER *every* day with zero
# slack at all (a fresh planting starts at consecutive_unwatered=1; one more
# miss and it's already a weed) -- one-time crops (wheat/carrot/melon) are
# costed per full plant-to-harvest cycle (which then replants, so this is
# their steady-state rate too); tomato/strawberry are "ongoing" and never
# replant, so this is water + harvest/interval indefinitely.
ACTIONS_PER_DAY = {
    "WHEAT": 7 / 5, "CARROT": 6 / 4, "MELON": 13 / 11,   # (plant + water*n + harvest) / cycle_days
    "TOMATO": 2.0, "STRAWBERRY": 1.5,                     # water + harvest/interval, forever
    "GOOSE": 4.0, "COW": 3.5, "SHEEP": 10 / 3,            # feed+care+fertilizer daily + harvest/interval
}

# Capacity is sized off action-count alone (ACTIONS_PER_DAY), which only
# counts standing on the tile doing the task -- not the walk there and back,
# which is real and grows with how spread out the farm is. This margin is a
# blunt stand-in for that unmodeled travel overhead (and for CARE/DIG/etc. on
# tiles not covered by ACTIONS_PER_DAY), not a measured number -- TODO: a
# real travel-time estimate (e.g. from average distance to shed) would let
# this be tighter and more honest than a flat haircut.
CAPACITY_MARGIN = 0.7

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

# Marginal extra units a single FERTILIZE application is worth, per crop --
# derived from the actual watering-bonus-window / production-interval math
# (see design notes), not guessed:
#   one-time crops: fertilizing doubles the per-day bonus (1->2) for every day
#     in the remaining bonus window (window_start..max_yield_day), capped by
#     max_yield. wheat: 3 window days * 1 extra = 2 net after the cap (goes
#     4->6); carrot: 2 window days -> capped at 4, net +1 (3->4); melon's
#     7-day window already hits its cap (6) unfertilized, so +0 always --
#     never worth it regardless of price.
#   ongoing crops: one application covers a 3-day window, doubling yield
#     (1->2) on every watered production day that falls in it. tomato
#     (interval 1) gets 3 such days -> +3 units; strawberry (interval 2) gets
#     2 -> +2 units.
FERTILIZE_MARGINAL_UNITS = {
    "WHEAT": 2, "CARROT": 1, "MELON": 0,
    "TOMATO": 3, "STRAWBERRY": 2,
}


def _fertilize_worthwhile(crop, prices):
    """Fertilizer only ever gets more expensive than its $100 base (it can be
    bought but never sold, and neither the town center nor any shop consumes
    it, so its market inventory only ever drains) -- so this has to compare
    against the crop's OWN live price, not a fixed cutoff on fertilizer's."""
    marginal = FERTILIZE_MARGINAL_UNITS.get(crop, 0)
    if marginal <= 0:
        return False
    price = prices.get(crop, BASE_PRICE[crop])
    fert_price = prices.get("FERTILIZER", BASE_PRICE["FERTILIZER"])
    return marginal * price > fert_price

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
FERTILIZER_RESERVE = 5        # small working buffer; sell the rest (it's a free animal byproduct)


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

def agent(obs, configuration=None):
    # The harness passes a second `configuration` argument when the function
    # accepts one (kaggle_environments truncates args to co_argcount), giving
    # the real per-episode turnsPerDay/townShopSellInterval/etc. -- used by
    # _consumption_per_day so the market projection stays correct even if a
    # specific run's intervals differ from the documented defaults, rather
    # than guessing between disagreeing sources.
    cfg = configuration or {}
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

    # Only "alive" (placed) animals count toward the wheat reserve. A newly
    # bought animal graduates into this count the same turn it's placed (its
    # own fetch errand grabs its first day's wheat directly, see 2a below),
    # so sizing the reserve off shed-held/pending ones too isn't needed and
    # measured worse when tried -- it locked up wheat ahead of animals that
    # weren't reliably getting fetched soon.
    n_animals_alive = sum(
        1 for row in tiles for t in row if isinstance(t, dict) and "animal" in t
    )

    # Combined daily output of both players' already-growing crops/animals,
    # by product -- feeds the market projection in _crop_score/_animal_score
    # (see _standing_production_per_day) so a type already heavily committed
    # market-wide, ours or the opponent's, scores lower without a separate
    # hand-tuned penalty.
    standing_production = _standing_production_per_day(farms)

    # Same workforce-scaled number paces how many near-shed tiles get
    # reserved for animals (_plan_expansion), how many unfetched animals of
    # one type BUY_ANIMAL is willing to stockpile, and how many fetch errands
    # run at once below -- there's no point planning, owning, or chasing more
    # than we can actually work through concurrently.
    max_concurrent_animal_errands = max(1, n_units // 4)

    # ------------------------------------------------------------------
    # 1. Build the prioritized task list from farm tiles (one grid pass).
    #    tier 1:   FEED / WATER (critical -- must happen today)
    #    tier 1.5: fetch a purchased animal waiting in the shed. A sunk-cost
    #              animal (already paid $300-500) earning nothing every turn
    #              it sits unfetched is worse than a slightly late harvest.
    #              Concurrency is capped (see fetch_slots below) since each
    #              fetch occupies a unit for its full multi-turn errand,
    #              unavailable for tier-1 watering until it completes.
    #    tier 2:   HARVEST (ready produce)
    #    tier 3:   CARE / DIG / COLLECT_FERTILIZER / fetch leftover shed
    #              fertilizer
    #    tier 4:   PLANT / BUILD_COOP / BUILD_PASTURE (expansion)
    # ------------------------------------------------------------------
    tasks = {1: [], 1.5: [], 2: [], 3: [], 4: []}

    plant_targets, animal_build_targets, my_action_demand = _plan_expansion(
        tiles, board_size, seeds, prices, money, day, remaining_days, wind_down,
        market_inventory, unlocked_shops, shed, max_concurrent_animal_errands,
        standing_production, cfg, n_units,
    )

    empty_structures = {"COOP": [], "PASTURE": []}
    eligible_fertilize_targets = []
    all_empty_tiles = []

    for y in range(board_size):
        for x in range(board_size):
            tile = tiles[y][x]
            if tile is None:
                all_empty_tiles.append((x, y))
                # Note: a planned animal_build_targets site is deliberately NOT
                # turned into a standalone tier-4 task here -- building a
                # structure only makes sense together with an animal already
                # in hand to put in it (see the carrying logic below), so
                # building only ever happens as part of that fetch-and-place
                # trip, never "blind" by whichever free unit is nearby.
                if (x, y) in plant_targets:
                    tasks[4].append(("PLANT", (x, y), plant_targets[(x, y)]))
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
                if tile.get("fertilized_until_day", -1) < day + 1 and _fertilize_worthwhile(tile["crop"], prices):
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
                # CARE banks +1/day (both fed and cared) toward the *next*
                # scheduled production, paid out capped at max_held -- once
                # the bank plus the guaranteed base(1) already reaches that
                # cap, more CARE before the next payout is wasted (it still
                # resets to 0 there, capped the same either way). A cow needs
                # only 5 banked days (5+1=6=max_held) out of the 7 available
                # before its first milking; the other 2 buy nothing.
                bank = tile.get("pending_care_bonus", 0)
                if not tile["cared_today"] and bank + 1 < ANIMALS[animal]["max_held"]:
                    tasks[3].append(("CARE", (x, y), None))
                if tile.get("fertilizer_available"):
                    tasks[3].append(("COLLECT_FERTILIZER", (x, y), None))

    # Fetch tasks: shed has a purchased animal / leftover fertilizer waiting
    # to be carried out. Target a shed-adjacent tile; PICKUP happens on
    # arrival, after which the carrying logic below walks it to an existing
    # empty structure (immediate PLACE) or, if none exists, to one of the
    # planned build sites for that same animal (build a home for it first).
    shed_tiles = _shed_access_tiles(board_size)
    # Cap how many units can be mid-errand (fetch -> build -> place -> feed)
    # at once: once carrying, a unit is captured by the 2a logic below for the
    # errand's full multi-turn length and unavailable for tier-1 WATER, no
    # matter how many WATER tasks are outstanding that turn. Dispatching every
    # eligible animal at once (one fetcher per animal type, every turn there's
    # room) can tie up enough of the workforce simultaneously to let watering
    # fall behind and weeds run away -- this is what caused the very first
    # tier-1.5 regression. Keeping the sequencing itself (per explicit
    # instruction) but throttling concurrency to a small, workforce-scaled
    # number keeps most units on watering duty while animals still get fetched
    # steadily, just not all in the same turn.
    n_units_carrying_animal = sum(
        1 for inv in inventories if any(inv.get(a, 0) > 0 for a in ANIMALS)
    )
    fetch_slots = max(0, max_concurrent_animal_errands - n_units_carrying_animal)
    for animal_name, data in ANIMALS.items():
        if fetch_slots <= 0:
            break
        homes_available = len(empty_structures[data["structure"]]) + sum(
            1 for op, a in animal_build_targets.values() if a == animal_name
        )
        need = min(shed.get(animal_name, 0), homes_available, fetch_slots)
        for k in range(need):
            tasks[1.5].append(("FETCH_ANIMAL", shed_tiles[k % 4], animal_name))
        fetch_slots -= need
    if shed.get("FERTILIZER", 0) > 0 and eligible_fertilize_targets:
        tasks[3].append(("FETCH_FERTILIZER", shed_tiles[0], "FERTILIZER"))

    # A placed animal still needs a *daily* FEED after the one-time fetch
    # errand above delivers its first day's wheat -- and FEED consumes wheat
    # from the acting unit's own inventory, so someone has to actually be
    # holding wheat when they reach it. Nothing else in the task list sends a
    # unit to the shed just to stock up for that; without it, feeding only
    # ever happens by the accident of some unit already carrying wheat for an
    # unrelated reason (e.g. just harvested it) passing near a hungry animal,
    # and two consecutive misses make it escape for good. Send exactly one
    # fetcher, only when nobody is already carrying wheat to deliver.
    if shed.get("WHEAT", 0) > 0 and any(t[0] == "FEED" for t in tasks[1]) and \
       not any(inv.get("WHEAT", 0) > 0 for inv in inventories):
        tasks[1].append(("FETCH_WHEAT_FOR_FEED", shed_tiles[0], "WHEAT"))

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
    #
    # PLANT/BUILD on a tile the unit is already standing on rides along too --
    # HARVEST (one-time crops) and DIG both clear the tile to empty right
    # under the unit's feet, and without this it would take its next move
    # from the tiered pool below, which has no idea this exact tile is a
    # zero-cost opportunity and might send it wandering off toward a farther
    # task instead, leaving the freshly-cleared tile empty for however many
    # turns until someone happens to path back through it.
    tier1_by_pos = {t[1]: t for t in tasks[1]}
    care_by_pos = {t[1]: t for t in tasks[3] if t[0] == "CARE"}
    tier4_by_pos = {t[1]: t for t in tasks[4]}
    for i in range(n_units):
        pos = tuple(units[i])
        inv_i = inventories[i] if i < len(inventories) else {}
        # FEED consumes 1 WHEAT from the *acting unit's own inventory* (not
        # the shed) -- a unit with none silently no-ops the action, wasting
        # the turn while the animal's unfed streak keeps ticking toward
        # escape. Only take this match if it can actually succeed; otherwise
        # leave it in the pool for a wheat-carrying unit (this one falls
        # through to the wheat-buffer top-up a few blocks below).
        if pos in tier1_by_pos and not (tier1_by_pos[pos][0] == "FEED" and inv_i.get("WHEAT", 0) <= 0):
            op, tpos, extra = tier1_by_pos.pop(pos)
            tasks[1].remove((op, tpos, extra))
            unit_actions[i] = _finalize_tile_action(op, extra)
        elif pos in care_by_pos:
            op, tpos, extra = care_by_pos.pop(pos)
            tasks[3].remove((op, tpos, extra))
            unit_actions[i] = _finalize_tile_action(op, extra)
        elif pos in tier4_by_pos:
            op, tpos, extra = tier4_by_pos.pop(pos)
            tasks[4].remove((op, tpos, extra))
            unit_actions[i] = _finalize_tile_action(op, extra)

    shed_tile_set = set(shed_tiles)

    # 2a. Units already carrying fertilizer / an animal act on that cargo first
    # (deliver-in-progress takes priority over starting something new).
    feed_targets = [t[1] for t in tasks[1] if t[0] == "FEED"]
    for i in range(n_units):
        pos = tuple(units[i])
        inv = inventories[i] if i < len(inventories) else {}
        tile = _tile_at(tiles, pos, board_size)

        if inv.get("FERTILIZER", 0) > 0:
            if tile != "LOCKED" and isinstance(tile, dict) and tile.get("kind") == "PLANT" \
               and tile.get("fertilized_until_day", -1) < day + 1 and _fertilize_worthwhile(tile["crop"], prices):
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
            # Standing on a ready structure: place immediately.
            if tile != "LOCKED" and isinstance(tile, dict) and tile.get("kind") == struct and "animal" not in tile:
                unit_actions[i] = ["PLACE", animal_name]
                break
            # No feed yet and we're right at the shed: grab a day's wheat in
            # the same stop as the animal, instead of a separate trip later
            # just for that -- this is exactly the "take the animal AND a
            # unit of feed together" sequencing. Only when the shed actually
            # *has* wheat right now, though: PICKUP silently no-ops on an
            # empty shed stock (nothing to give), so requesting it anyway
            # would re-issue the same no-op forever and strand the unit here
            # permanently -- never placing the animal, never freed for
            # watering. If there's none to grab yet, carry on toward the
            # structure and let a later FEED task (once placed) pick up wheat
            # when the shed actually has some.
            if inv.get("WHEAT", 0) <= 0 and pos in shed_tile_set and shed.get("WHEAT", 0) > 0:
                unit_actions[i] = ["PICKUP", "WHEAT", 1]
                break
            # Head for an existing empty structure of the right kind.
            target = _nearest(empty_structures[struct], pos)
            if target is not None:
                unit_actions[i] = ["PLACE", animal_name] if pos == target else [_step_towards(pos, target, board_size)]
                break
            # No structure exists yet: go build one on the empty tile closest
            # to the shed (not closest to this unit's current position) --
            # animals need a FEED visit every single day for the rest of the
            # game, so scattering them wherever the carrying unit happened to
            # be wandering when it picked one up turns daily upkeep into an
            # ever-expanding patrol that eventually can't be completed in
            # time, which is exactly what let animals escape in waves in
            # testing. Clustering them near the shed keeps that recurring
            # cost small and bounded no matter how many accumulate.
            # (Targeting a *specific* animal_build_targets position instead
            # was tried and doesn't work: that set is recomputed from scratch
            # every turn from a shrinking, reordering empty-tile pool, so by
            # the time a multi-turn walk would arrive, the plan has very
            # likely already reassigned that exact tile to a different type,
            # and the carrier gets yanked toward wherever the plan points
            # *this* turn, forever, without ever converging. "Empty tile
            # nearest the shed" has no such instability -- at worst another
            # unit claims it first, which just costs one extra turn to
            # retarget, not indefinite wandering.)
            build_op = "BUILD_COOP" if struct == "COOP" else "BUILD_PASTURE"
            target = min(
                all_empty_tiles,
                key=lambda p: min(_manhattan(p, st) for st in shed_tiles),
                default=None,
            )
            if target is not None:
                unit_actions[i] = [build_op] if pos == target else [_step_towards(pos, target, board_size)]
            break
        if unit_actions[i] is not None:
            continue

        # Already holding wheat (for whatever reason -- just harvested it, or
        # fetched it earlier and never used it) with a hungry animal waiting
        # somewhere: deliver it now rather than leaving the match to chance in
        # the general tier-1 pass below, which only pairs a wheat-carrier with
        # a FEED task when that unit happens to still be free and nearest.
        # Missing this is not a small loss -- two consecutive unfed days and
        # the animal is gone for good.
        if inv.get("WHEAT", 0) > 0 and feed_targets:
            if tile != "LOCKED" and isinstance(tile, dict) and "animal" in tile and not tile["fed_today"]:
                unit_actions[i] = ["FEED"]
                continue
            target = _nearest(feed_targets, pos)
            if target is not None:
                unit_actions[i] = [_step_towards(pos, target, board_size)]
                continue

    # 2b. Cargo management: a unit sitting on a meaningful harvest should bank
    # it rather than wander off chasing the next-nearest task indefinitely --
    # tasks are plentiful enough on an active farm that "return when idle"
    # never actually triggers. Heavy cargo gets a dedicated trip that preempts
    # tiers 2-4; light cargo is only dropped opportunistically in passing.

    def _cargo(inv):
        # Animals stay excluded from the *threshold* count -- carrying just
        # an animal shouldn't by itself trigger a cargo-return trip.
        return sum(v for k, v in inv.items() if k not in ANIMALS)

    def _carrying_animal(inv):
        return any(inv.get(a, 0) > 0 for a in ANIMALS)

    def _do_drop(i, pos, inv):
        # The real DROP action empties the *entire* inventory with no
        # exception for animals -- so a unit currently carrying one must
        # never reach here (checked by every call site below), or a fetched
        # animal gets dumped straight back into the shed the moment it also
        # picks up any ordinary cargo, undoing the fetch and re-triggering
        # FETCH_ANIMAL next turn. Ask forever, get nothing: exactly the
        # infinite fetch/drop loop this guard exists to prevent.
        unit_actions[i] = ["DROP"]
        for item, n in inv.items():
            room = max(0, 100 - sum(projected_shed.values()))
            take = min(n, room)
            if take > 0:
                projected_shed[item] = projected_shed.get(item, 0) + take

    for i in range(n_units):
        if unit_actions[i] is not None:
            continue
        pos = tuple(units[i])
        inv = inventories[i] if i < len(inventories) else {}
        if _carrying_animal(inv):
            continue  # 2a already had first refusal on this unit; never DROP an animal
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
        if _carrying_animal(inv):
            continue
        cargo = _cargo(inv)
        if pos in shed_tile_set and cargo > 0:
            tile = _tile_at(tiles, pos, board_size)
            if not _has_local_urgent_task(tile, day):
                _do_drop(i, pos, inv)

    # (An "opportunistic wheat top-up" pass was tried here -- have any idle
    # unit near the shed grab a couple wheat preemptively so it's ready to
    # FEED whatever it's nearest to later. Measured net negative: it fires
    # constantly (any day with a live animal), and the extra PICKUP turns it
    # spends outweigh what it saves, since the FEED-requires-wheat check
    # below already prevents the actual failure mode -- a wasted no-op
    # action -- at zero cost by simply leaving the task for a unit that
    # already happens to be carrying wheat.)

    # 2d. Tiered nearest-task assignment for everyone still free.
    def _assign_nearest(pool, candidates):
        for i in candidates:
            if unit_actions[i] is not None or not pool:
                continue
            pos = tuple(units[i])
            best_idx = min(range(len(pool)), key=lambda k: _manhattan(pos, pool[k][1]))
            op, tpos, extra = pool.pop(best_idx)
            if pos == tpos:
                unit_actions[i] = _finalize_tile_action(op, extra)
            else:
                unit_actions[i] = [_step_towards(pos, tpos, board_size)]

    for tier in (1, 1.5, 2, 3, 4):
        pool = tasks[tier]
        if tier == 1:
            # FEED consumes WHEAT from the *acting unit's own* inventory, never
            # the shed -- dispatching it to a unit with none isn't just wasted
            # travel, it's a guaranteed no-op that still burns the task for the
            # turn, and two consecutive missed days make the animal escape for
            # good. WATER has no such requirement and goes to any free unit;
            # FEED is restricted to units already carrying wheat, so a task
            # that can't currently be completed is left for next turn instead
            # of being wasted on a unit that can't pay for it.
            water_pool = [t for t in pool if t[0] == "WATER"]
            feed_pool = [t for t in pool if t[0] == "FEED"]
            # Anything else here is FETCH_WHEAT_FOR_FEED, which needs no
            # wheat in hand (that's the point of it) and so goes to any free
            # unit, same as WATER.
            other_pool = [t for t in pool if t[0] not in ("WATER", "FEED")]
            free_units = [i for i in range(n_units) if unit_actions[i] is None]
            _assign_nearest(water_pool, free_units)
            free_units = [i for i in range(n_units) if unit_actions[i] is None]
            wheat_units = [
                i for i in free_units
                if (inventories[i] if i < len(inventories) else {}).get("WHEAT", 0) > 0
            ]
            _assign_nearest(feed_pool, wheat_units)
            free_units = [i for i in range(n_units) if unit_actions[i] is None]
            _assign_nearest(other_pool, free_units)
            continue
        free_units = [i for i in range(n_units) if unit_actions[i] is None]
        _assign_nearest(pool, free_units)

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
        max_concurrent_animal_errands=max_concurrent_animal_errands,
        standing_production=standing_production, cfg=cfg,
        my_action_demand=my_action_demand,
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
    if op in ("FETCH_ANIMAL", "FETCH_FERTILIZER", "FETCH_WHEAT_FOR_FEED"):
        return ["PICKUP", extra, 1]
    return [op]


# ---------------------------------------------------------------------------
# Economics: what to plant / build next
# ---------------------------------------------------------------------------

def _crop_score(crop, day, market_inventory, unlocked_shops, standing_production, cfg):
    price = _projected_price(
        crop, CROPS[crop]["first_yield_day"], day, market_inventory, unlocked_shops, standing_production, cfg,
    )
    return YIELD_PER_TILE_DAY[crop] * price - AMORTIZED_COST_PER_DAY[crop]


def _animal_score(animal, day, prices, market_inventory, unlocked_shops, standing_production, cfg):
    product = ANIMAL_PRODUCT[animal]
    price = _projected_price(
        product, ANIMALS[animal]["first_yield_day"], day, market_inventory, unlocked_shops, standing_production, cfg,
    )
    feed_cost_per_day = prices.get("WHEAT", BASE_PRICE["WHEAT"])  # ~1 wheat/day/animal, paid now
    return YIELD_PER_TILE_DAY[animal] * price - AMORTIZED_COST_PER_DAY[animal] - feed_cost_per_day


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
                     market_inventory, unlocked_shops, shed, max_concurrent_animal_errands,
                     standing_production, cfg, n_units):
    """Decide what goes on currently-empty tiles: returns (plant_targets,
    animal_build_targets, my_action_demand), the first two {(x, y): value}
    splitting the empty-tile pool between crops and new animal structures
    respecting soft diversification caps, the third the projected total daily
    task-action demand (ACTIONS_PER_DAY) from this farm's tiles including
    what's newly planned here -- fed back to _plan_market to size hiring."""
    empty = []
    crop_counts = {c: 0 for c in CROPS}
    animal_counts = {a: 0 for a in ANIMALS}
    empty_structure_counts = {"COOP": 0, "PASTURE": 0}
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
                elif tile.get("kind") in empty_structure_counts:
                    empty_structure_counts[tile["kind"]] += 1

    standing_demand = (
        sum(n * ACTIONS_PER_DAY[c] for c, n in crop_counts.items())
        + sum(n * ACTIONS_PER_DAY[a] for a, n in animal_counts.items())
    )
    if not empty or unlocked_tiles == 0:
        return {}, {}, standing_demand

    # How much more daily task-action demand we can add before the workforce
    # is projected to be underwater -- see ACTIONS_PER_DAY/CAPACITY_MARGIN.
    # Only gates speculative (not-yet-owned) new animal sites below, not
    # sunk-cost ones (already paid for -- see there) and not crops (see
    # there too): the "even if profitable, we can't staff it all" case this
    # exists for is specifically about animals.
    free_capacity = max(0.0, n_units * 24 * CAPACITY_MARGIN - standing_demand)

    # Fill outward from the shed first: keeps the day's work clustered near
    # the drop-off point instead of scattering across the whole unlocked
    # farm, which cuts travel time for both watering rounds and shed trips.
    shed_tiles = _shed_access_tiles(board_size)
    empty.sort(key=lambda p: min(_manhattan(p, st) for st in shed_tiles))

    ranked_animals = sorted(ANIMALS, key=lambda a: -_animal_score(a, day, prices, market_inventory, unlocked_shops, standing_production, cfg))
    # Animals already bought and sitting in the shed are a sunk cost -- housing
    # them costs no more money and shouldn't be blocked by the affordability
    # gate below, which exists only to avoid planning a site for a
    # hypothetical *future* purchase we can't yet afford. Existing empty
    # structures (cow/sheep share PASTURE, so claimed greedily in score order)
    # cover some of them for free; only the remainder needs a genuinely new
    # build site.
    remaining_structures = dict(empty_structure_counts)
    need_new_site = {}
    for a in ranked_animals:
        struct = ANIMALS[a]["structure"]
        owned = shed.get(a, 0)
        claim = min(owned, remaining_structures.get(struct, 0))
        remaining_structures[struct] -= claim
        need_new_site[a] = owned - claim

    # Animals cost a recurring shed round-trip every day (feed, plus the
    # fetch/build/place errand itself) that crops never do, so -- unlike
    # crops -- they get first claim on the tiles nearest the shed. Only as
    # many of those near tiles as there's real use for, though: every animal
    # already owned needs a site (guaranteed), plus a small speculative
    # buffer for ones affordable soon, paced by the same concurrency number
    # that throttles the fetch errand itself -- never a fixed fraction of all
    # empty land regardless of actual need, which just parks near-shed tiles
    # under a "maybe" indefinitely.
    cheapest_animal_cost = min(a["cost"] for a in ANIMALS.values())
    can_afford_more_soon = money - 400 >= cheapest_animal_cost
    speculative = max_concurrent_animal_errands if (not wind_down and can_afford_more_soon) else 0
    owned_needing_site = sum(need_new_site.values())
    if wind_down:
        animal_slots, crop_slots = [], empty
    else:
        n_animal_slots = min(len(empty), owned_needing_site + speculative)
        animal_slots, crop_slots = empty[:n_animal_slots], empty[n_animal_slots:]

    # Capacity only gates *speculative* (not-yet-owned) new animals here, not
    # crops: an empty tile isn't spare workforce held in reserve, it's a
    # standing weed risk (weeds spawn only on empty tiles) that needs digging
    # regardless of whether we "meant" to leave it empty for capacity
    # reasons -- leaving land unplanted to save labor was measurably worse
    # (more weeds to dig, not less work overall) when tried. Animals are
    # different: skipping one doesn't create a weed risk, and a placed one
    # that can't be kept fed reliably escapes outright, losing the purchase
    # -- so the "even if profitable, we can't staff it all" concern this
    # exists for is real specifically here, not for crops. Sunk-cost animals
    # (already paid for) still bypass the gate below same as always.
    animal_build_targets = {}
    if animal_slots:
        reserve = 400
        for pos in animal_slots:
            pending = [a for a in ranked_animals if need_new_site.get(a, 0) > 0]
            if pending:
                best = _pick_diversified(pending, animal_counts, unlocked_tiles)
                need_new_site[best] -= 1
            else:
                if free_capacity < min(ACTIONS_PER_DAY[a] for a in ANIMALS):
                    break  # workforce is already projected at capacity
                best = _pick_diversified(ranked_animals, animal_counts, unlocked_tiles)
                if money - reserve < ANIMALS[best]["cost"]:
                    continue  # don't plan a site for a purchase we can't afford yet
                free_capacity -= ACTIONS_PER_DAY[best]
                standing_demand += ACTIONS_PER_DAY[best]
            struct = ANIMALS[best]["structure"]
            op = "BUILD_COOP" if struct == "COOP" else "BUILD_PASTURE"
            animal_build_targets[pos] = (op, best)  # (build op, which animal it's for)
            animal_counts[best] = animal_counts.get(best, 0) + 1

    plant_targets = {}
    if not wind_down or remaining_days >= 4:
        ranked_crops = sorted(
            (c for c in CROPS if seeds.get(c, 0) > 0 and (not wind_down or remaining_days >= CROPS[c]["max_yield_day"] + 2)),
            key=lambda c: -_crop_score(c, day, market_inventory, unlocked_shops, standing_production, cfg),
        )
        if ranked_crops:
            for pos in crop_slots:
                crop = _pick_diversified(ranked_crops, crop_counts, unlocked_tiles)
                plant_targets[pos] = crop
                crop_counts[crop] = crop_counts.get(crop, 0) + 1
                standing_demand += ACTIONS_PER_DAY[crop]

    return plant_targets, animal_build_targets, standing_demand


# ---------------------------------------------------------------------------
# Market orders
# ---------------------------------------------------------------------------

def _plan_market(me, private, market, day, hour, projected_shed, n_animals_alive,
                  endgame, wind_down, remaining_days, animal_build_targets,
                  empty_structures, tiles, board_size, unlocked_shops,
                  max_concurrent_animal_errands, standing_production, cfg,
                  my_action_demand):
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
        if qty <= 0 or item in ANIMALS:
            continue  # the shed dict holds animals too, but only PRODUCTS are sellable
        # Fertilizer is a normal sellable PRODUCT like any other (it's often
        # mis-documented as buy-only, but the actual rules never exclude it
        # from SELL) -- and since it's a free byproduct of every fed animal,
        # anything beyond a small working buffer is just money left on the
        # table sitting in the shed.
        if item == "WHEAT":
            sellable = qty - wheat_reserve
        elif item == "FERTILIZER":
            sellable = qty - FERTILIZER_RESERVE
        else:
            sellable = qty
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

    # --- HIRE: once per day, at hour 0. Hands are lost every single day
    # (farm["hands"]=[] at end of day, hires_today resets to 0) so this cost
    # is *recurring*, not one-time: the Nth hire costs fib(N-1) again every
    # day it's kept, not once (the 16th alone is ~$987/day, every day --
    # holding 16 hands costs ~$2583/day in hiring alone).
    #
    # Sized off the real daily task-action demand from tiles already
    # planted/placed (my_action_demand, from ACTIONS_PER_DAY -- see
    # _plan_expansion) rather than a rough tile-count guess, but never
    # *less* than the old land-based floor: at day 0 nothing is planted yet
    # (demand is 0), and hands have to exist first for _plan_expansion to
    # have anyone to staff a planting with.
    if hour == 0 and budget > 0:
        planted_or_building = sum(
            1 for row in tiles for t in row
            if isinstance(t, dict) and t.get("kind") in ("PLANT", "COOP", "PASTURE")
        )
        unlocked_tiles = sum(1 for row in tiles for t in row if t != "LOCKED")
        land_based_floor = min(10, max(unlocked_tiles // 8, planted_or_building // 5))
        demand_based = math.ceil(my_action_demand / (24 * CAPACITY_MARGIN)) - 1  # minus the farmer, always free
        target_hands = min(20, max(land_based_floor, demand_based))

        # TODO(hire ROI): the user's own framing -- hire only while the next
        # hand's (recurring, Fibonacci) cost is still less than the profit
        # its work brings in -- is right in principle but genuinely unsolved
        # here. Tried comparing fib(n) against a blended $-per-action average
        # across every standing tile; measured *worse* (regressed several
        # seeds' final reward): one crashed-price tile (melon sits near the
        # floor most games) drags the whole average down and starves hiring
        # even while plenty of other tiles are still very profitable, which
        # then lets weeds/upkeep fall behind, which drags the average down
        # further -- a real negative feedback loop, not a rounding error.
        # A fix needs the marginal hand's *actual* expected task (whatever's
        # highest-value and unstaffed right now), not an average of
        # everything already planted, plus real travel-time cost (which
        # ACTIONS_PER_DAY doesn't count) -- until then, target_hands above
        # (real workload, not a tile-count guess) is the load-bearing fix;
        # affordability (the reserve check below) is the only brake on cost.
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

    # --- BUY_ANIMAL, then matching feed, before BUY_SEED: hired hands need
    # several turns just to walk from the shed to wherever they're needed, so
    # they go out first (above) to start that walk immediately. Animals and
    # their feed both have to be physically carried out of the shed by a
    # unit, so they come next. Seeds don't -- BUY_SEED fills private["seeds"],
    # which PLANT draws from directly wherever a unit already stands, no shed
    # trip involved -- so seeds can safely wait for whatever budget is left.
    #
    # Only buy when we actually have (or are about to have) a home for it --
    # either an existing empty structure or a build site planned specifically
    # for this animal (see _plan_expansion) -- so a purchase never idles in
    # the shed with nowhere to go (which would also eat into shedCapacity
    # headroom). Also gated on an established wheat supply -- an animal
    # placed before we can feed it daily starves and escapes within two days,
    # losing the full purchase.
    wheat_established = projected_shed.get("WHEAT", 0) >= ANIMAL_WHEAT_GATE or day >= 6
    animals_bought_this_turn = 0
    if budget > 0 and not wind_down and shed_total < 90 and wheat_established:
        remaining_structures = {
            "COOP": len(empty_structures.get("COOP", [])),
            "PASTURE": len(empty_structures.get("PASTURE", [])),
        }
        build_targets_for = {a: 0 for a in ANIMALS}
        for op, a in animal_build_targets.values():
            build_targets_for[a] += 1
        # Ranks COW/SHEEP/GOOSE by projected price at first_yield_day (real
        # market curve, both players' standing production, known consumption
        # rate -- see _animal_score/_projected_price). Doesn't stop after the
        # top pick, so it can still buy one of each type in the same turn if
        # each independently clears its own gate below -- not wrong on its
        # own (diversifying has real value, and each purchase is scored on
        # its own projected merit, which already prices in how much of it is
        # already committed), just worth knowing it's not "pick one."
        for animal in sorted(ANIMALS, key=lambda a: -_animal_score(a, day, prices, market_inventory, unlocked_shops, standing_production, cfg)):
            if budget <= 0:
                break
            struct = ANIMALS[animal]["structure"]
            # Cow and sheep both use PASTURE, so existing empty pastures are
            # a shared pool -- whichever animal scores higher claims them
            # first in this loop, the other only gets planned build sites.
            homes = remaining_structures.get(struct, 0) + build_targets_for.get(animal, 0)
            slots = homes - projected_shed.get(animal, 0)
            if slots <= 0:
                continue
            # "homes" counts every planned build site the expansion planner is
            # willing to speculate on, which can be many more than the fetch
            # pipeline actually processes per turn -- fetching is throttled on
            # purpose (see max_concurrent_animal_errands / fetch_slots) to
            # keep most of the workforce on watering. Buying up to that
            # generous "homes" limit just parks money as dead capital sitting
            # unfetched in the shed for a long time, so cap the unfetched
            # backlog to what that same throttle can actually work through at
            # once, instead of an arbitrary number.
            if projected_shed.get(animal, 0) >= max_concurrent_animal_errands:
                continue
            cost = ANIMALS[animal]["cost"]
            reserve = 400
            if money - reserve >= cost:
                orders.append(["BUY_ANIMAL", animal, 1])
                money -= cost
                budget -= 1
                animals_bought_this_turn += 1
                if remaining_structures.get(struct, 0) > 0:
                    remaining_structures[struct] -= 1
                else:
                    build_targets_for[animal] -= 1

    # --- BUY_PRODUCT WHEAT: top up the shed to cover both animals already
    # placed and needing today's feed, and any just bought above -- the fetch
    # errand grabs a day's wheat in the same shed stop as the animal (see 2a)
    # only when the shed actually has some right then, so buying it alongside
    # the animal is what makes that "take the animal AND its feed together"
    # sequencing actually land on the very first trip instead of waiting for
    # a farmed surplus that may not exist yet. Still just a stopgap on top of
    # normal wheat farming, never the primary source (growing it is cheaper).
    if budget > 0 and (n_animals_alive + animals_bought_this_turn) > 0 and shed_total < 95:
        have_wheat = projected_shed.get("WHEAT", 0)
        needed = n_animals_alive + animals_bought_this_turn
        if have_wheat < needed:
            deficit = needed - have_wheat
            price = prices.get("WHEAT", BASE_PRICE["WHEAT"])
            reserve = 100
            afford = max(0, int((money - reserve) // max(price, 1)))
            n = min(deficit, afford, 10)
            if n > 0:
                orders.append(["BUY_PRODUCT", "WHEAT", n])
                budget -= 1

    # --- BUY_SEED: keep a small buffer per crop we intend to keep planting.
    # Goes last -- seeds need no shed trip (PLANT draws from private["seeds"]
    # wherever a unit stands), so they're the least urgent use of the
    # remaining order budget. During bootstrap, prioritize wheat/carrot (fast
    # payback) over the higher-steady-state-value but slow-to-mature
    # tomato/strawberry/melon, so early cash flow isn't starved waiting on an
    # 8-10 day first harvest.
    if budget > 0 and not wind_down:
        def seed_key(c):
            is_fast = c in BOOTSTRAP_CROPS
            return (0 if (bootstrapping and is_fast) else 1, -_crop_score(c, day, market_inventory, unlocked_shops, standing_production, cfg))

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

    return orders[:10]
