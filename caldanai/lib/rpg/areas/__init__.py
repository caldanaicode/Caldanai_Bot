"""Areas — physical rooms / zones the game uses for scenery,
ambience, and (now) hosting static objects.

Until 2026-05-03 ``Area`` was a passive scenery container — name,
brief, verbose, directional descriptions. The static-objects
addition gave Area the responsibility for managing physical
features that live in the room (a campfire, a stone field, a
named tree) and for emitting room-flavored ambience that combines
with each object's own ambience contribution.

Hosting on Area (instead of Game) is forward-compatible with
threaded dungeons: each thread / dungeon area has its own static
objects, weather-reaction wiring stays per-area, and a future
multi-room game model can move players between areas without
having to migrate object state across the Game surface.
"""

import importlib
import random
from typing import Callable, Dict, List, Optional, TYPE_CHECKING, Union

from caldanai.logger import get_logger
from caldanai.lib.rpg.helpers.enums import Directions

if TYPE_CHECKING:
    from caldanai.lib.rpg.world.objects import StaticObjectPlugin


_log = get_logger(__name__)


# An ambience-pool entry is either a plain string or a no-arg
# callable that returns one — the callable form lets a line draw
# from random helpers (e.g. directional flavor) without forcing a
# per-line render pipeline.
AmbienceEntry = Union[str, Callable[[], str]]


# Cadence: 1 / N tick chance for the room's general ambience to
# emit. 1/3000 matches the legacy ``Game.do_ambience`` cadence so
# the migration doesn't change the perceived rate of wildlife /
# breeze flavor in-channel. Per-static-object cadences live on
# each plugin and can be tuned independently.
DEFAULT_AMBIENCE_ROLL = 3000


class Area:
    """Base scenery container. Per-area ``AreaPlugin`` subclasses
    populate ``name`` / ``verbose`` / ``directions`` and (now)
    ``AMBIENCE_POOL``. Static objects are added at game-load time
    via :meth:`add_static_object`.

    The ``room0`` field on ``Game`` holds the active area; future
    multi-room game models will hold a mapping or path through a
    set of Area instances.
    """

    # Per-area ambience pool. Default empty; ``AreaPlugin`` subclasses
    # populate. Each entry is either a string or a no-arg callable
    # returning a string — the callable form is for lines that draw
    # from helpers (random direction, scent, etc.) without per-line
    # render plumbing.
    AMBIENCE_POOL: List[AmbienceEntry] = []

    def __init__(self):
        self.name = ""
        self.brief = ""
        self.verbose = ""
        self.directions = {}
        # Static objects keyed by stem (e.g. ``"campfire"``).
        # Populated by ``RpgUtilities.add_game`` after area construction
        # so plugin discovery has run. Each area has its own object set
        # — when threaded dungeons land, each thread's area will hold
        # its own.
        self.static_objects: Dict[str, "StaticObjectPlugin"] = {}

    def get_look_direction(self, direction: Directions):
        if direction in self.directions:
            return self.directions[direction]

        filtered = list(filter(lambda d: d & direction, self.directions.keys()))
        if len(filtered):
            return self.directions[filtered[0]]

        return "There is nothing of note in that direction."

    @classmethod
    def from_plugin(cls, plugin_name: str):
        """Creates a new area from a plugin."""

        try:
            room = importlib.import_module(f"caldanai.lib.rpg.areas.{plugin_name}").AreaPlugin()
            return room

        except Exception as e:
            _log.error(f"Unable to load AreaPlugin: {plugin_name}\n\t{e}")
            raise

    # ------------------------------------------------------------------
    # Static object management
    # ------------------------------------------------------------------

    def add_static_object(self, obj: "StaticObjectPlugin") -> None:
        """Install a static object into this area, keyed by its
        plugin stem. Idempotent — replacing an existing entry of
        the same stem swaps the instance (useful for plugin
        reload). Auto-registers the object's weather-change
        callback at install time."""
        stem = type(obj).__name__.lower()
        self.static_objects[stem] = obj

    def find_static_object(
        self, target: str,
    ) -> "Optional[StaticObjectPlugin]":
        """Resolve a token to a present static object via name +
        aliases + fuzzy-match pass chain. Returns ``None`` for
        unknown tokens. Used by the world cog's verb dispatch +
        the StaticObjectConverter."""
        if not target:
            return None
        from caldanai.lib.rpg.helpers.fuzzy import fuzzy_match

        objects = list(self.static_objects.values())
        if not objects:
            return None

        def _keys(o):
            keys = [type(o).__name__.lower(), o.name.lower()]
            keys.extend(a.lower() for a in (getattr(o, "aliases", None) or []))
            return keys

        result = fuzzy_match(
            target, objects, keys=_keys, strategy="unordered",
        )
        return result.tightest[0] if result.tightest else None

    # ------------------------------------------------------------------
    # Ambience collection
    # ------------------------------------------------------------------

    def collect_ambience(self, game) -> List[str]:
        """Walk every ambience source in this area for one tick and
        return whatever lines emitted. Caller (``Game.do_ambience``)
        combines + dispatches.

        Sources:
        - The area's own ``AMBIENCE_POOL`` (wildlife, breezes, etc.)
          rolled at ``DEFAULT_AMBIENCE_ROLL`` chance.
        - Each present static object's ``maybe_emit_ambience(game)``
          — that hook owns its own cadence (per-object pacing means
          a roaring fire and a passive stone field don't share a
          single global rate).

        Returns a list of lines (may be empty). Order of sources is
        deterministic — area pool first, then static objects in
        insertion order — so the caller's combining heuristic
        produces stable phrasing across emissions.
        """
        emissions: List[str] = []

        if self.AMBIENCE_POOL and random.randint(1, DEFAULT_AMBIENCE_ROLL) == DEFAULT_AMBIENCE_ROLL:
            entry = random.choice(self.AMBIENCE_POOL)
            line = entry() if callable(entry) else entry
            if line:
                emissions.append(line)

        for obj in self.static_objects.values():
            line = obj.maybe_emit_ambience(game)
            if line:
                emissions.append(line)

        return emissions
