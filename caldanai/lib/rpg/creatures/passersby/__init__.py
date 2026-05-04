"""Passerby NPCs — non-combatant travelers who wander through
clearings to give the world life beyond monsters and the trio.

Why this exists
---------------

Vael's 2026-05-03 design ask (filed in
``project_world_texture_vael_2026-05-03.md``) named three gaps in
Mendholm's texture: landmarks, **people who are not monsters or
us**, and stakes that aren't combat. Passersby answer the second
ask directly and make a partial dent in the third — a witness
giving combat narrative weight beyond loot.

Mechanical shape
----------------

A passerby is NOT a :class:`Creature` and does NOT inherit from
:class:`MonsterPlugin`. It's a separate plugin family with its own
discovery / registry / spawn pipeline:

- **Quiet-window arrival**: when the passerby spawn timer fires
  with no active combat, the NPC arrives via :attr:`ARRIVAL_POOL`,
  emits :attr:`AMBIENT_POOL` lines while present, and departs via
  :attr:`DEPARTURE_POOL`.
- **Silhouette mode**: when the timer fires DURING combat, the NPC
  appears as a distant figure via :attr:`SILHOUETTE_POOL` and
  attaches to the game as a pending silhouette. After combat
  resolves, the silhouette approaches with an outcome-aware
  reaction from one of :attr:`COMBAT_WON_REACTIONS`,
  :attr:`COMBAT_FLED_REACTIONS`, or :attr:`PARTY_DEATH_REACTIONS`.

Players interact via ``$wave`` / ``$nod`` / ``$greet``, which read
the NPC-toward-player warmth from MongoDB and fire the keyed
reaction pool from :attr:`SOCIAL_REACTIONS`. ``$kill <passerby>``
routes to a flee path that drops warmth toward the attacker by
one step (warm → neutral → cool → cold), affecting both future
NPC reactions and that NPC's likelihood of returning to this
channel.

Voice rule (carried from Caels' direction): NPCs **acknowledge but
don't converse.** They react to actions (wave / nod / attack); they
don't process conversational input. When pushed past their pre-
programmed surface, they exit via :attr:`DEPART_WHEN_PUSHED_POOL`
— flatness as a feature, not a bug. Future V2 may layer Claude API
dialogue (per ``project_phase2_api_narration.md``) for genuine
conversation; V1 ships taciturn-by-design.

Acquaintance + name-rendering
-----------------------------

Per (channel, NPC, player) triple, MongoDB tracks three axes:

- ``warmth: Warmth`` — how the NPC feels (cold/cool/neutral/warm/hot)
- ``acquainted: bool`` — does the NPC know what to call this player
- ``met_count: int`` — how many encounters total

Acquaintance learning events (any flips ``acquainted = True`` for
the (NPC, player) pair on this channel):

1. **`$greet <NPC>`** — explicit introduction by the player.
2. **Overheard @mention** — when another player in-channel posts a
   message that ``<@!id>``-mentions this player, with the NPC
   present in the clearing (post-arrival, pre-departure; silhouettes
   count). Pure mention parsing — no fuzzy-name detection from
   prose.
3. **Time osmosis** — ``met_count >= 3`` with ``warmth >= NEUTRAL``
   flips acquainted regardless. Backstop for the silent-but-recurring
   case.

Pool authoring & rendering: pools are authored as if **fully
acquainted** — use ``@1`` freely for player references. At render
time the substitution layer handles both states:

- If NOT acquainted: ``@1`` always resolves to a StrangerActor
  whose ``.name`` is "traveler" (pronouns and verb-agreement still
  pass through from the real player so the NPC never mis-genders).
- If acquainted: roll once per line; with probability
  :attr:`NAMING_BIAS` use the actual player, else fall through to
  the StrangerActor surface.

Authors write one pool per (verb, warmth) tier; the NPC's voice
modulates the surface via NAMING_BIAS. The herbalist's "Walk
careful, @1" mostly renders as "Walk careful, traveler" (her
NAMING_BIAS is low) and occasionally as "Walk careful, Vael" —
which is exactly when name-use should LAND. This is texture, not
a flag.

Plugin pattern mirrors :class:`MonsterPlugin` — filename stem +
optional ``ALIASES`` list; first-write-wins on alias collisions;
:meth:`load_plugins` discovers everything under :attr:`BASEPATH`.
"""

from os import sep
from typing import Dict, List, Optional, Type

from caldanai import PluginManager
from caldanai.lib.rpg.helpers.gender import GenderMixin
from caldanai.lib.rpg.helpers.spawn_time import SpawnTimeMixin
from caldanai.lib.rpg.helpers.warmth import Warmth


class PasserbyPlugin(GenderMixin, SpawnTimeMixin):
    """Base class for passerby NPC plugins.

    Subclasses populate the flavor pools as class attributes and
    optionally override the hook methods (:meth:`on_arrival`,
    :meth:`on_silhouette`, :meth:`on_combat_resolved`,
    :meth:`on_attacked`, :meth:`on_pushed`) for per-NPC behavior
    that doesn't fit the pool shape.

    The ``name`` attribute is the in-fiction display label; the
    plugin's filename stem is the registry key (case-insensitive).
    Like monsters, passersby use ``uses_article`` to control
    whether the parser renders ``"the wagoneer"`` vs ``"Wagoneer"``
    — default True (passersby are generic-typed, not named).
    """

    BASEPATH: str = sep.join([
        "caldanai", "lib", "rpg", "creatures", "passersby",
    ])

    # Name-keyed registry, populated by :meth:`load_plugins`. Mirrors
    # ``MonsterPlugin._PLUGIN_REGISTRY``.
    _PLUGIN_REGISTRY: Dict[str, Type["PasserbyPlugin"]] = {}

    # Display label for the parser. Subclasses override.
    name: str = "passerby"

    # Whether the parser prepends "the " when rendering this NPC
    # (``"the wagoneer"`` vs ``"Wagoneer"``). True for generic-typed
    # NPCs (V1 default); future named recurring NPCs may flip this.
    uses_article: bool = True

    # Aliases — extra names this plugin should resolve from beyond
    # its filename stem. Same shape as MonsterPlugin.ALIASES.
    ALIASES: List[str] = []

    # ``gender`` and ``pronouns`` defaults inherited from
    # :class:`GenderMixin` (``"neutral"`` / ``"they,them,their,
    # theirs,themself"``). Subclasses override per NPC for
    # gendered passersby. The mixin provides
    # :meth:`get_pronoun_dict` for parser-side consumption,
    # which handles the comma-separated string format here AND
    # the Dict-form Creature builds at __init__ time
    # transparently.

    def __init__(self) -> None:
        """Convert class-level pronoun string declarations into the
        instance-level Dict shape :func:`parser.parse` expects.

        Subclasses declare ``pronouns`` as a comma-separated string
        for ergonomic plugin authoring (matches
        :class:`Creature.__init__`'s input format). The parser does
        ``actor.pronouns[Pronouns.X]`` (square-bracket access on a
        dict), so an instantiated NPC needs ``self.pronouns`` to be
        the keyed dict. The :func:`GenderMixin.get_pronoun_dict`
        accessor parses the class-level string idempotently — if
        ``self.pronouns`` is already a dict (e.g. a subclass that
        overrode at instance level), it's returned as-is.

        Mirrors :class:`Creature.__init__`'s pattern of building the
        pronouns dict once at instantiation. Per-instance dict
        ensures multiple NPC instances don't share dict mutations
        (defensive against future state — e.g. a passerby that
        adopts a player's pronouns post-acquaintance).
        """
        self.pronouns = self.get_pronoun_dict()

    # Per-NPC bias toward using a player's actual name vs the
    # generic "traveler" form when the NPC is acquainted with that
    # player. 1.0 = always uses the name (when known); 0.0 = always
    # uses generic ("traveler") even when acquainted; intermediate
    # values roll per-line to add texture. Default 0.7 — leans
    # name-using when known, with occasional generic for breathing
    # room.
    #
    # Voice differentiation per NPC: a road-friendly wagoneer might
    # set 0.85 (uses names readily), while a mythic herbalist might
    # set 0.15 ("traveler" is in voice; rare name-use lands as
    # weighted emphasis). The bias is what makes name-use *texture*
    # rather than *flag*.
    #
    # Single roll per rendered line so the line stays internally
    # consistent (no "@1d ... @1np" rendering as "Caels ... the
    # traveler's" mid-sentence).
    NAMING_BIAS: float = 0.7

    # ---------------------------------------------------------------
    # Flavor pools — subclasses populate these.
    # ---------------------------------------------------------------

    # Lines fired when the NPC arrives in a quiet window (no active
    # combat). May reference @1 (the NPC self) for parser-driven
    # name / pronoun substitution; otherwise plain text.
    ARRIVAL_POOL: List[str] = []

    # Lines fired periodically while the NPC is present in the
    # clearing (between arrival and departure). Atmospheric — the
    # NPC noticed in the corner of the eye.
    AMBIENT_POOL: List[str] = []

    # Lines fired when the NPC departs of their own accord (timer-
    # driven departure, not flee).
    DEPARTURE_POOL: List[str] = []

    # Lines fired when the NPC arrives DURING active combat — they
    # appear as a distant figure rather than approaching. The NPC
    # is then held in a "silhouette pending" state until combat
    # resolves, at which point the appropriate combat-resolved
    # reaction fires.
    SILHOUETTE_POOL: List[str] = []

    # Reaction pools fired when a pending silhouette resolves after
    # combat ends. ``@1`` = the NPC; ``@2`` = a representative party
    # member (the killing-blow dealer for WON; a still-alive party
    # member for FLED; the fallen for PARTY_DEATH). Subclasses can
    # leave any pool empty — the spawn pipeline picks an outcome
    # whose pool is non-empty, falling through to a generic
    # acknowledgement if all are empty.
    COMBAT_WON_REACTIONS: List[str] = []
    COMBAT_FLED_REACTIONS: List[str] = []
    PARTY_DEATH_REACTIONS: List[str] = []

    # Social reaction pools — keyed first by command name
    # (``wave`` / ``nod`` / ``greet``), then by warmth tier.
    # ``@1`` = the actor (player who used the verb); ``@2`` = the
    # NPC themselves. The acceptance level is the NPC-toward-actor
    # warmth from MongoDB; the actor's intent (player-toward-NPC
    # warmth) tints the actor-side flavor via the existing
    # ``rpg_social_commands`` resolution path, NOT here.
    SOCIAL_REACTIONS: Dict[str, Dict[Warmth, List[str]]] = {}

    # Lines fired when a player tries to engage in genuine dialogue
    # past the NPC's surface — flat-by-design departure cue.
    # ``@1`` = the actor.
    DEPART_WHEN_PUSHED_POOL: List[str] = []

    # Lines fired when the player attempts ``$kill <passerby>``.
    # The NPC flees; warmth toward attacker drops one step.
    # ``@1`` = the NPC; ``@2`` = the attacker.
    FLEE_FROM_ATTACK_POOL: List[str] = []

    # One-line hint inserted into ``$look`` output when this NPC
    # is present. Subclasses override; default is a generic
    # acknowledgement keyed off the NPC's name.
    LOOK_LINE: str = ""

    # Italicized one-liner dispatched when an NPC learns a player's
    # name for the first time — fires on the FIRST $greet, the
    # FIRST overheard @mention, and the moment osmosis acquaintance
    # flips. Without this cue, acquaintance is invisible to the
    # player (especially for low-NAMING_BIAS NPCs whose lines rarely
    # use the name even after they know it). One line per pool;
    # ``@1`` = the NPC, ``@2`` = the just-recognized player.
    # Subclasses override for voice; the default is generic enough
    # to read fine for any NPC.
    ACQUAINTANCE_CUE_POOL: List[str] = [
        "*@1np eyes flick to @2 with quiet recognition.*",
        "*@1d gives @2 a longer second look — the kind that learns a face.*",
        "*Something settles in @1np expression, the way it does when a name takes.*",
    ]

    # ---------------------------------------------------------------
    # Plugin discovery / registry
    # ---------------------------------------------------------------

    @classmethod
    def load_plugins(cls) -> None:
        """Load all passerby plugin files under :attr:`BASEPATH`.

        Same shape as :meth:`MonsterPlugin.load_plugins`: filename
        stem is the canonical key, plus any ``ALIASES`` entries.
        First-write-wins on collisions (deterministic since
        filesystem load order is alphabetical).
        """
        PluginManager.load(PasserbyPlugin, PasserbyPlugin.BASEPATH)

        registry: Dict[str, Type["PasserbyPlugin"]] = {}
        for plugin_cls in PluginManager.LOADED_PLUGINS.get(PasserbyPlugin, []):
            stem = plugin_cls.__module__.rsplit(".", 1)[-1].lower()
            if stem:
                registry.setdefault(stem, plugin_cls)
            for alias in getattr(plugin_cls, "ALIASES", []) or []:
                key = alias.lower().strip()
                if key:
                    registry.setdefault(key, plugin_cls)
        PasserbyPlugin._PLUGIN_REGISTRY = registry

    @classmethod
    def get_plugin_class(
        cls, name: str,
    ) -> Optional[Type["PasserbyPlugin"]]:
        """Look up a loaded passerby plugin class by name.

        Case-insensitive against the filename stem AND any
        class-declared ``ALIASES``. Returns ``None`` for unknown
        names. For fuzzy partial-query lookup, see
        :meth:`find_plugin_classes`.
        """
        if not name:
            return None
        return PasserbyPlugin._PLUGIN_REGISTRY.get(name.lower().strip())

    @classmethod
    def find_plugin_classes(
        cls, query: str,
    ) -> "List[Type[PasserbyPlugin]]":
        """Fuzzy lookup — returns every plugin class whose stem or
        alias matches ``query`` under the standard pass chain
        shared with all other lookup helpers via :func:`fuzzy_match`.

        Same shape and semantics as
        :meth:`MonsterPlugin.find_plugin_classes`: dedupes on
        plugin class, exact > prefix > substring, whitespace-token
        unordered strategy.
        """
        from caldanai.lib.rpg.helpers.fuzzy import fuzzy_match

        registry = PasserbyPlugin._PLUGIN_REGISTRY
        keys_per_class: Dict[
            Type["PasserbyPlugin"], List[str]
        ] = {}
        for k, v in registry.items():
            keys_per_class.setdefault(v, []).append(k)

        return fuzzy_match(
            query,
            list(keys_per_class.keys()),
            keys=lambda c: keys_per_class[c],
            strategy="unordered",
        ).tightest

    # ---------------------------------------------------------------
    # Hook methods — subclasses override for per-NPC custom behavior
    # that doesn't fit the pool shape. Defaults are no-ops returning
    # ``None``; the spawn pipeline ignores ``None`` returns and
    # falls through to pool-based flavor.
    # ---------------------------------------------------------------

    def on_arrival(self, game) -> Optional[str]:
        """Custom flavor at quiet-window arrival. Return ``None`` to
        defer to :attr:`ARRIVAL_POOL` random pick (default)."""
        return None

    def on_silhouette(self, game) -> Optional[str]:
        """Custom flavor for during-combat silhouette appearance.
        Return ``None`` to defer to :attr:`SILHOUETTE_POOL`."""
        return None

    def on_combat_resolved(
        self, game, outcome: str, witness_target=None,
    ) -> Optional[str]:
        """Custom flavor when a pending silhouette approaches after
        combat resolves.

        ``outcome`` is one of ``"won"`` / ``"fled"`` / ``"death"``.
        ``witness_target`` is a representative party member (killing-
        blow dealer for WON, an alive party member for FLED, the
        fallen for DEATH). Return ``None`` to defer to the matching
        reaction pool.
        """
        return None

    def on_attacked(self, game, attacker) -> Optional[str]:
        """Custom flavor when a player runs ``$kill <passerby>``.
        The default flee path applies the warmth-degradation step;
        custom flavor can replace the line text, not the
        consequence."""
        return None

    def on_pushed(self, game, actor) -> Optional[str]:
        """Custom flavor for the depart-when-pushed exit cue. Return
        ``None`` to defer to :attr:`DEPART_WHEN_PUSHED_POOL`."""
        return None
