"""Static object plugins — physical features of an :class:`Area`
that hold state, respond to verbs, contribute to ambience, and
react to weather.

Why this exists
---------------

Caels' 2026-05-03 "world flavor" design ask: some things in the
clearing should persist across spawns and react to play. A
campfire, a stone field, a named tree — each lives in the room,
not in the spawn pipeline. Players can `$gaze` / `$touch` /
`$listen` / `$feed` / `$light` them. Weather affects them. Their
ambience contributions stack with the room's general wildlife
noise.

Distinct from :class:`MonsterPlugin` (transient combat threat),
:class:`PasserbyPlugin` (transient narrative encounter), and
:class:`Area`'s scenery prose (fixed): a static object IS the room
gaining mass over time.

Plugin shape
------------

Subclass :class:`StaticObjectPlugin`, populate the class attributes,
override the verb / ambience / weather hooks. Plugin discovery
follows the same pattern as :class:`PasserbyPlugin`:

- Filename stem at ``caldanai/lib/rpg/world/objects/<stem>.py``
  becomes the registry key (case-insensitive).
- ``ALIASES`` adds extra lookup keys.
- Auto-instantiated per-area at game-load time (one instance per
  area per object plugin).

Verb dispatch
-------------

The world cog (``rpg_world_commands.py``) registers the generic
verbs (``$light``, ``$feed``, ``$gaze``, ``$touch``, ``$listen``).
For each verb, the cog asks the present static objects "do you
handle this?" via :attr:`SUPPORTED_VERBS` and dispatches to
:meth:`on_verb` on the first match. Objects that don't declare a
verb in ``SUPPORTED_VERBS`` are skipped silently — the bot does
not pretend to handle inputs no object accepts.

State + persistence
-------------------

Each instance carries mutable :attr:`state` (dict of plugin-
defined keys; campfire holds a :class:`FireState` enum + fuel
int, etc.). State is in-memory for V1 — defaults reapply on bot
restart. Matches the passerby in-memory pattern; if a future
object needs durable state we'll wire a persistence layer at
that point rather than building it speculatively.
"""

from os import sep
from typing import Dict, List, Optional, TYPE_CHECKING, Type

from caldanai import PluginManager

if TYPE_CHECKING:
    from caldanai.lib.rpg.helpers.enums import WeatherPatterns, WeatherSeverities


class StaticObjectPlugin:
    """Base class for room-resident static object plugins.

    Subclasses populate :attr:`name`, :attr:`aliases`,
    :attr:`SUPPORTED_VERBS`, and the various flavor pools, then
    override :meth:`on_verb`, :meth:`get_look_line`,
    :meth:`maybe_emit_ambience`, and :meth:`on_weather_change` as
    needed. The base class provides discovery + registry only;
    behavior is the subclass's.

    The subclass is responsible for state initialization (in
    ``__init__``) and for state mutation in response to verbs and
    weather. Per-instance state lives on ``self.state`` (a dict
    by convention, but plugins may use any attribute shape they
    prefer — the base class doesn't introspect it).
    """

    BASEPATH: str = sep.join([
        "caldanai", "lib", "rpg", "world", "objects",
    ])

    # Name-keyed registry, populated by :meth:`load_plugins`. Mirrors
    # ``PasserbyPlugin._PLUGIN_REGISTRY``.
    _PLUGIN_REGISTRY: Dict[str, Type["StaticObjectPlugin"]] = {}

    # Display label rendered in $look output and verb-target prose.
    name: str = "object"

    # Extra lookup tokens beyond the filename stem — players can
    # type any of these as a verb target (e.g. ``$light fire`` should
    # resolve to the campfire even though stem is "campfire").
    aliases: List[str] = []

    # Which generic world-verbs this plugin handles. The world cog
    # consults this list at dispatch time; missing entries cause the
    # cog to skip this object as a candidate for that verb. Use
    # exact verb names ("light", "feed", "gaze", "touch", "listen").
    SUPPORTED_VERBS: List[str] = []

    def __init__(self) -> None:
        """Subclasses override to initialize per-instance state.
        Default implementation gives the plugin an empty state
        dict — fine for stateless objects (e.g. a stone the player
        can ``$touch`` for flavor only)."""
        self.state: dict = {}

    # ---------------------------------------------------------------
    # Verb dispatch hook — subclasses override.
    # ---------------------------------------------------------------

    def on_verb(
        self, verb: str, game, actor, *args,
    ) -> Optional[str]:
        """Handle a verb invocation. Return the narration line for
        the cog to dispatch (already parser-rendered if needed),
        or ``None`` to silently consume the input.

        ``verb`` is the verb name (e.g. ``"light"``); the cog will
        only call this when ``verb in SUPPORTED_VERBS``. ``actor``
        is the invoking player. ``*args`` carries verb-specific
        extras (e.g. for ``$feed campfire <fuel>`` the resolved
        fuel item lands here).

        Subclasses should branch on ``verb`` internally rather than
        registering per-verb methods — keeps the dispatch surface
        small and the plugin's verb logic colocated.
        """
        return None

    # ---------------------------------------------------------------
    # $look hook — subclasses override.
    # ---------------------------------------------------------------

    def get_look_line(self, game) -> Optional[str]:
        """Return a state-aware short line for inclusion in bare
        ``$look`` output. ``None`` hides the object from $look (for
        objects that don't want to surface visually — rare).

        Convention: one sentence, present-tense, scene-setting
        rather than action-narrating. State-aware: a lit campfire
        reads differently from one burnt out and damp.
        """
        return None

    # ---------------------------------------------------------------
    # Ambience hook — subclasses override and own their cadence.
    # ---------------------------------------------------------------

    def maybe_emit_ambience(self, game) -> Optional[str]:
        """Per-tick ambience hook. Subclasses roll their own
        cadence (state- and time-of-day-aware) and return a flavor
        line when the roll fires, or ``None`` otherwise.

        Called once per tick by :meth:`Area.collect_ambience`. The
        per-object roll lets a roaring fire be more vocal than a
        passive stone field without a global rate cap.
        """
        return None

    # ---------------------------------------------------------------
    # Weather hook — subclasses override to react to transitions.
    # ---------------------------------------------------------------

    def on_weather_change(
        self,
        game,
        old_patterns: "WeatherPatterns",
        new_patterns: "WeatherPatterns",
        old_severities: "Dict[WeatherPatterns, WeatherSeverities]",
        new_severities: "Dict[WeatherPatterns, WeatherSeverities]",
    ) -> Optional[str]:
        """Fire when weather patterns transition. Return a narration
        line for the channel (e.g. "the campfire hisses out") or
        ``None`` for no narration.

        Both pattern flags and severity dicts are passed so plugins
        can distinguish "rain started" from "rain intensified" or
        "wind picked up to gusts". Default implementation is no-op.
        """
        return None

    # ---------------------------------------------------------------
    # Plugin discovery / registry
    # ---------------------------------------------------------------

    @classmethod
    def load_plugins(cls) -> None:
        """Load all static-object plugin files under :attr:`BASEPATH`.
        Same shape as :meth:`PasserbyPlugin.load_plugins`: filename
        stem is the canonical key, plus any ``aliases`` entries
        (case-insensitive). First-write-wins on collisions.
        """
        PluginManager.load(StaticObjectPlugin, StaticObjectPlugin.BASEPATH)

        registry: Dict[str, Type["StaticObjectPlugin"]] = {}
        for plugin_cls in PluginManager.LOADED_PLUGINS.get(StaticObjectPlugin, []):
            stem = plugin_cls.__module__.rsplit(".", 1)[-1].lower()
            if stem:
                registry.setdefault(stem, plugin_cls)
            for alias in getattr(plugin_cls, "aliases", []) or []:
                key = alias.lower().strip()
                if key:
                    registry.setdefault(key, plugin_cls)
        StaticObjectPlugin._PLUGIN_REGISTRY = registry

    @classmethod
    def get_plugin_class(
        cls, name: str,
    ) -> Optional[Type["StaticObjectPlugin"]]:
        """Look up a loaded plugin class by stem or alias.
        Case-insensitive. Returns ``None`` for unknown names. For
        fuzzy / partial-query lookup against PRESENT objects in an
        area, use :meth:`Area.find_static_object` instead."""
        if not name:
            return None
        return StaticObjectPlugin._PLUGIN_REGISTRY.get(name.lower().strip())
