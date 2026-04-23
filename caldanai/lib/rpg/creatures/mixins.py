"""Capability mixins for body-part plugins.

Phase B2 turns the implicit "what kind of contribution does this
part make" encoded as name-matches (``_part_base_name(p) == "eye"``,
``"wing"``, ``"torso"``, etc.) into explicit capability tags via
mixin classes. Every concrete plugin (``HeadPlugin``,
``WingPlugin``, ...) now declares its capabilities via multi-
inheritance, and emergence paths (:meth:`Creature.get_dodge` and
friends) filter body parts with :meth:`Creature.find_all` against
a mixin class rather than by string name.

Zero gameplay change — the per-plugin tags encode exactly what
the name-matches encoded before. The payoff is clean contracts
for Phase B3 (equipment moves onto :class:`Equippable` nodes)
and B4 (emergence rewrites as tree reductions over mixin-filtered
subsets).

Design notes
------------

All mixins are intentionally **empty base classes** for now. The
per-plugin class-level attributes (``IS_PRIMARY_SENSE``,
``MOBILITY_MODE``) carry the fine-grained behavior; the mixin
itself is a marker. This keeps the hierarchy flat and MRO
predictable — Phase B1's ``BodyPart(Node, ABC)`` is already at
the outer edge of multi-inheritance; layering more behavior-
bearing bases risks MRO surprises that the plan explicitly flagged.

The component-pattern escape hatch (``node.components: dict``)
mentioned in the Phase B plan has not been necessary.
"""


class Offensive:
    """Node that contributes attack actions / sources.

    Tag for body parts the creature can attack WITH (not be
    attacked ON). Head (bite / headbutt), arm (punch / wielded
    weapon), tail (hydra swipe once wired).

    Today's mechanism is the per-plugin ``DEFAULT_ACTIONS`` dict
    populated on each Offensive plugin. Phase B2 doesn't change
    that wiring; it just makes the classification explicit. B4
    may rewrite attack-source collection as a tree-walk over
    :class:`Offensive` nodes (the basilisk-eye-as-attack-source
    case) but that's deferred.
    """


class Sensory:
    """Node that contributes to HIT (perception).

    Eyes are the primary sense source; heads are the fallback
    when a creature has no eyes (classic humanoid monsters).

    Phase B4 (2026-04-22): HIT emergence is a weighted tree
    reduction — ALL Sensory nodes contribute simultaneously,
    weighted by :attr:`SENSE_WEIGHT`. Eyes weight 2× heads,
    so when both eyes are destroyed the head's fallback still
    contributes a non-zero HIT value (graceful degradation).
    The pre-B4 behavior switched groups abruptly at "any eye
    present" — that cliff is gone.

    :attr:`IS_PRIMARY_SENSE` is kept as a classifier hook (used
    by :meth:`Creature.has_eyes` to distinguish "this creature
    has eye parts" from "this creature has any perception") but
    no longer drives emergence group-switching.

    Future perception types (hearing → ear, tremorsense → special
    plugin) can ship as new Sensory subclasses with their own
    SENSE_WEIGHT.
    """

    #: Does this sense count as primary? Eye=True, head=False
    #: (fallback only). Classifier (not a weight): used by the
    #: ``has_eyes`` test to distinguish "this creature has
    #: dedicated sense organs" from "this creature senses at
    #: all".
    IS_PRIMARY_SENSE: bool = False

    #: Dict lookup key in a plugin's :attr:`WEIGHTS` dict for
    #: Sensory emergence. ``_mixin_functionality`` walks reachable
    #: Sensory nodes and reads ``node.WEIGHTS.get(WEIGHT_KEY, 1.0)``
    #: per node, so plugins tune with e.g. ``WEIGHTS = {"sense": 2.0}``
    #: (eyes) or leave ``WEIGHTS = {}`` for the uniform default.
    WEIGHT_KEY: str = "sense"


class Mobility:
    """Node that contributes to DODGE (movement).

    Grounded mobility (legs) drives dodge while on the ground;
    airborne mobility (wings) drives dodge while flying. The
    mode is carried on the per-plugin class attribute
    :attr:`MOBILITY_MODE` so :meth:`Creature.get_dodge` can
    pick the right source set based on ``"flying"`` flag state.

    Tail / toe are NOT tagged Mobility for now — they contribute
    DODGE *debuffs* via the per-part debuffs table (destroyed
    tail → -DODGE), not DODGE *sources*. Marking them Mobility
    would pull them into the emergence reduction and change
    balance; that's a design choice for a future phase, not a
    refactor side-effect.

    Phase B4 (2026-04-22): DODGE emergence is a weighted tree
    reduction over mode-filtered Mobility nodes. Per-plugin
    :attr:`MOBILITY_WEIGHT` lets one kind of mobility weigh
    more than another within the same mode (future tuning); all
    current plugins use the default 1.0.
    """

    #: Which locomotion state does this source feed? ``"grounded"``
    #: (legs) or ``"airborne"`` (wings). Classifier (not a weight)
    #: — used to filter the mode-relevant subset at dodge time.
    MOBILITY_MODE: str = "grounded"

    #: Dict lookup key for Mobility emergence. See :class:`Sensory`
    #: for the pattern. Plugins tune with e.g.
    #: ``WEIGHTS = {"mobility": 1.2}`` to weigh one kind of
    #: locomotion over another within the same mode.
    WEIGHT_KEY: str = "mobility"


class Defensive:
    """Node that contributes to DEFENSE.

    Torso primarily. Per-part ``defense_bonus`` and
    ``is_critical`` flags live on :class:`BodyPart` itself —
    the Defensive tag just means "this part is a defense source
    for :meth:`Creature.get_defense`'s emergence math."

    Phase B4 (2026-04-22): DEFENSE emergence is a weighted tree
    reduction over Defensive nodes. :attr:`DEFENSIVE_WEIGHT`
    default is 1.0; creatures with multiple torso-like parts
    (carapace plates, layered armor segments) could override.
    """

    #: Dict lookup key for Defensive emergence. Plugins with
    #: multiple torso-like parts (carapace plates, layered armor
    #: segments) can tune via ``WEIGHTS = {"defense": ...}``.
    WEIGHT_KEY: str = "defense"


class Equippable:
    """Node that owns equipment placement keys.

    Every visible body part today is equippable — head (helm,
    face, ears), torso (chest, cape, belt), arm (held, bracer,
    vambrace, glove, ring), leg (greave, shin, boot), neck
    (amulet). Purely-internal future parts (organs, arteries)
    would NOT be Equippable.

    Phase B3 (2026-04-22): each Equippable node owns a
    ``placements: Dict[str, Optional[Equipment]]`` dict
    populated at materialization time from the plugin's
    :attr:`PLACEMENT_KEYS` declaration. :class:`Player`'s
    ``part_equipment`` is now a computed property returning a
    dict of live references to each node's ``placements``, so
    the tree is authoritative storage and reads/writes through
    the nested-dict shape still work for back-compat.
    """

    #: Per-plugin placement-key list. Declares the slots this
    #: node-kind can hold equipment in. Override on each
    #: Equippable plugin class. Empty by default so the
    #: initializer is a no-op for anything that hasn't opted in.
    PLACEMENT_KEYS: "list[str]" = []
