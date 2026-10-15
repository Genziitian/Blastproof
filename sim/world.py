"""The synthetic company both tenants share in shape.

Both companies use IDENTICAL service names and keys, with different people and
canary values, so isolation tests can't pass by accident.
"""
from __future__ import annotations

# Scenario clock starts here (ms since epoch, 2026-10-01T00:00:00Z).
WORLD_START_MS = 1_790_812_800_000

SERVICES = {
    # name: (tier, customer_facing)
    "web-gateway": ("edge", True),
    "checkout-api": ("core", True),
    "cart-svc": ("core", True),
    "payments-gw": ("core", True),
    "orders-svc": ("core", False),
    "menu-svc": ("core", True),
    "search-svc": ("core", True),
    "auth-svc": ("core", False),
    "notify-svc": ("core", False),
}

DATASTORES = {
    # name: kind
    "postgres-orders": "postgres",
    "postgres-payments": "postgres",
    "redis-cache": "redis",
    "kafka-events": "kafka",
}

# (from, to): `from` DEPENDS_ON `to`
DEPENDS_ON = [
    ("web-gateway", "checkout-api"), ("web-gateway", "cart-svc"),
    ("web-gateway", "menu-svc"), ("web-gateway", "search-svc"),
    ("web-gateway", "auth-svc"),
    ("checkout-api", "cart-svc"), ("checkout-api", "payments-gw"),
    ("checkout-api", "orders-svc"), ("checkout-api", "auth-svc"),
    ("cart-svc", "redis-cache"), ("cart-svc", "postgres-orders"),
    ("payments-gw", "postgres-payments"), ("payments-gw", "kafka-events"),
    ("orders-svc", "postgres-orders"), ("orders-svc", "kafka-events"),
    ("menu-svc", "redis-cache"), ("search-svc", "redis-cache"),
    ("auth-svc", "redis-cache"), ("notify-svc", "kafka-events"),
]

TEAMS = {
    # team: (channel, owned nodes)
    "platform-data": ("#platform-data", ["postgres-orders", "postgres-payments",
                                         "redis-cache", "kafka-events"]),
    "checkout": ("#checkout", ["checkout-api", "cart-svc", "orders-svc"]),
    "payments": ("#payments", ["payments-gw"]),
    "discovery": ("#discovery", ["menu-svc", "search-svc"]),
    "identity": ("#identity", ["auth-svc"]),
    "edge": ("#edge", ["web-gateway", "notify-svc"]),
}

# Same handles in both companies (isolation test), different people.
PEOPLE = {
    "a": {
        "priya": ("Priya Sharma", "platform-data"),
        "rohan": ("Rohan Mehta", "checkout"),
        "ananya": ("Ananya Rao", "payments"),
        "vikram": ("Vikram Iyer", "discovery"),
        "meera": ("Meera Pillai", "identity"),
        "arjun": ("Arjun Das", "edge"),
        "kabir": ("Kabir Singh", "platform-data"),
    },
    "b": {
        "priya": ("Priya Nair", "platform-data"),
        "rohan": ("Rohan Kapoor", "checkout"),
        "ananya": ("Ananya Bose", "payments"),
        "vikram": ("Vikram Shah", "discovery"),
        "meera": ("Meera Joshi", "identity"),
        "arjun": ("Arjun Menon", "edge"),
        "kabir": ("Kabir Gill", "platform-data"),
    },
}

# The first person listed for each team is on call at world start (see scripts/seed.py).
# Canary values: if one company's value ever shows up in the other's output, isolation failed.
CANARY = {"a": "A-7f3e", "b": "B-91c2"}


def key(kind: str, name: str) -> str:
    return f"{kind}:{name}"
