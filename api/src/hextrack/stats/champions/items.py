"""Item classification for champion builds, from one patch's Data Dragon ``item.json``.

Pure (no I/O): :meth:`ItemCatalog.from_item_json` takes the parsed payload, so it is
testable offline; :meth:`hextrack.riot.ddragon.DDragon.item_catalog` fetches and caches it.

Rules (checked against the 16.x item.json):

* **Canonical item.** Transforms and free upgrades fold into the item they came from,
  repeatedly: an item with ``specialRecipe`` (Muramana -> Manamune, Seraph's Embrace ->
  Archangel's Staff, Fimbulwinter -> Winter's Approach, Diadem of Songs -> Whispering
  Circlet, Runic Compass -> World Atlas) folds into that item, and an item that costs no gold
  of its own (``gold.base == 0``) and is built from exactly one item folds into it (tier-3
  boots such as Gunmetal Greaves -> Berserker's Greaves, Forever Forward -> Synchronized
  Souls -> Symbiotic Soles, and the support quest's final items -> Bounty of Worlds ->
  Runic Compass -> World Atlas). Jungle pets have no upgrade items in Data Dragon, so they
  are their own canonical item. Unknown ids are their own canonical item.
* **Boots.** A canonical item tagged "Boots" or built from Boots (1001).
* **Completed.** Tier-2 boots (canonical boots built from something), or a finished
  legendary: built from components (``from``), not an ingredient of another Summoner's Rift
  item (no item on map 11 lists it in its ``from``; transforms don't count, they have no
  ``from``), not a consumable or trinket, and worth at least :data:`LEGENDARY_MIN_GOLD`
  in total (this drops cheap end-of-tree items such as Shattered Armguard). Mejai's
  Soulstealer is the one cheaper finished item that counts (:data:`EXTRA_COMPLETED`).
  Starter items, components, support-quest items and jungle pets are never completed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

#: Plain Boots (tier 1).
BOOTS_ID: Final = 1001
#: A finished legendary costs at least this much in total.
LEGENDARY_MIN_GOLD: Final = 2000
#: Finished items below :data:`LEGENDARY_MIN_GOLD` that still count as completed.
EXTRA_COMPLETED: Final = frozenset({3041})  # Mejai's Soulstealer
#: Folding stops after this many steps (guards against cycles in odd data).
_MAX_FOLD_STEPS: Final = 8
SUMMONERS_RIFT: Final = "11"


def _int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _ids(values: object) -> list[int]:
    if not isinstance(values, list):
        return []
    return [i for i in (_int(v) for v in values) if i is not None]


@dataclass(frozen=True, slots=True)
class _Entry:
    item_id: int
    builds_from: tuple[int, ...]
    tags: frozenset[str]
    base_gold: int
    total_gold: int
    special_recipe: int | None
    on_rift: bool
    consumable: bool


def _parse(item_id: int, raw: Mapping[str, Any]) -> _Entry:
    gold = raw.get("gold") if isinstance(raw.get("gold"), Mapping) else {}
    maps = raw.get("maps") if isinstance(raw.get("maps"), Mapping) else {}
    tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
    return _Entry(
        item_id=item_id,
        builds_from=tuple(_ids(raw.get("from"))),
        tags=frozenset(t for t in tags if isinstance(t, str)),
        base_gold=_int(gold.get("base")) or 0,
        total_gold=_int(gold.get("total")) or 0,
        special_recipe=_int(raw.get("specialRecipe")),
        # Missing "maps" means "everywhere" in practice; only an explicit false excludes.
        on_rift=maps.get(SUMMONERS_RIFT, True) is not False,
        consumable=raw.get("consumed") is True or "Consumable" in tags,
    )


@dataclass(frozen=True, slots=True)
class ItemCatalog:
    """Classification of one patch's items. Every method accepts any item id (transforms
    included) and canonicalises it first; unknown ids are neither boots nor completed."""

    version: str
    #: item id -> canonical item id, only where they differ.
    folds: Mapping[int, int]
    #: Canonical ids of completed items (finished legendaries and tier-2 boots).
    completed: frozenset[int]
    #: Canonical ids of boots (tier 1 included).
    boots: frozenset[int]
    trinkets: frozenset[int]

    @classmethod
    def from_item_json(cls, payload: Any, version: str | None = None) -> ItemCatalog:
        """Build from a parsed ``item.json``; ValueError when it has no item data."""
        data = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(data, Mapping) or not data:
            raise ValueError("item.json has no 'data' object")
        entries: dict[int, _Entry] = {}
        for key, raw in data.items():
            item_id = _int(key)
            if item_id is not None and isinstance(raw, Mapping):
                entries[item_id] = _parse(item_id, raw)
        if not entries:
            raise ValueError("item.json has no items")
        resolved = version or (payload.get("version") if isinstance(payload, Mapping) else None)
        return cls._build(entries, str(resolved or "unknown"))

    @classmethod
    def _build(cls, entries: Mapping[int, _Entry], version: str) -> ItemCatalog:
        def step(entry: _Entry) -> int | None:
            target = entry.special_recipe
            if target is not None and target != entry.item_id and target in entries:
                return target
            parents = set(entry.builds_from)
            if entry.base_gold == 0 and len(parents) == 1:
                (parent,) = parents
                if parent != entry.item_id and parent in entries:
                    return parent
            return None

        folds: dict[int, int] = {}
        for item_id, entry in entries.items():
            current, seen = entry, {item_id}
            for _ in range(_MAX_FOLD_STEPS):
                nxt = step(current)
                if nxt is None or nxt in seen:
                    break
                seen.add(nxt)
                current = entries[nxt]
            if current.item_id != item_id:
                folds[item_id] = current.item_id

        # Items some other Summoner's Rift item is built from (i.e. components).
        ingredients: set[int] = set()
        for entry in entries.values():
            if entry.on_rift:
                ingredients.update(entry.builds_from)

        boots = frozenset(
            item_id
            for item_id, entry in entries.items()
            if item_id not in folds
            and ("Boots" in entry.tags or item_id == BOOTS_ID or BOOTS_ID in entry.builds_from)
        )
        completed: set[int] = set()
        for item_id, entry in entries.items():
            if item_id in folds or not entry.builds_from:
                continue
            if item_id in boots:
                completed.add(item_id)  # tier 2 (tier 1 has no "from")
                continue
            if item_id in ingredients or entry.consumable or "Trinket" in entry.tags:
                continue
            if entry.total_gold >= LEGENDARY_MIN_GOLD or item_id in EXTRA_COMPLETED:
                completed.add(item_id)
        trinkets = frozenset(i for i, e in entries.items() if "Trinket" in e.tags)
        return cls(
            version=version,
            folds=folds,
            completed=frozenset(completed),
            boots=boots,
            trinkets=trinkets,
        )

    def canonical(self, item_id: int) -> int:
        return self.folds.get(item_id, item_id)

    def is_completed(self, item_id: int) -> bool:
        """Finished legendary or tier-2 boots (after folding transforms)."""
        return self.canonical(item_id) in self.completed

    def is_boots(self, item_id: int) -> bool:
        return self.canonical(item_id) in self.boots

    def is_legendary(self, item_id: int) -> bool:
        """Completed and not boots: what core builds and the ``item`` kind count."""
        canonical = self.canonical(item_id)
        return canonical in self.completed and canonical not in self.boots

    def is_trinket(self, item_id: int) -> bool:
        return item_id in self.trinkets

    def canonical_all(self, item_ids: Iterable[int]) -> list[int]:
        return [self.canonical(i) for i in item_ids]
