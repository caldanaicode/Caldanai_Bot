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

    Eyes are the primary sense; heads are the fallback source
    when a creature has no eyes (classic humanoid monsters).
    The distinction is carried on the per-plugin class attribute
    :attr:`IS_PRIMARY_SENSE` (True on eye, False on head) so
    :meth:`Creature.get_hit_modifier` can do:

        primary = [n for n in find_all(Sensory) if n.IS_PRIMARY_SENSE]
        sources = primary if primary else [non-primary Sensory nodes]

    Future perception types (hearing → ear, tremorsense → special
    plugin) will land as new primary Sensory nodes.
    """

    #: Does this sense count as primary? Eye=True, head=False
    #: (fallback only). Override per-plugin.
    IS_PRIMARY_SENSE: bool = False


class Mobility:
    """Node that contributes to DODGE (movement).

    Grounded mobility (legs) drives dodge while on the ground;
    airborne mobility (wings) drives dodge while flying. The
    mode is carried on the per-plugin class attribute
    :attr:`MOBILITY_MODE` so :meth:`Creature.get_dodge` can
    pick the right source set based on ``"flying"`` flag state:

        mode = "airborne" if self.is_flying() else "grounded"
        sources = [n for n in find_all(Mobility) if n.MOBILITY_MODE == mode]

    Tail / toe are NOT tagged Mobility for now — they contribute
    DODGE *debuffs* via the per-part debuffs table (destroyed
    tail → -DODGE), not DODGE *sources*. Marking them Mobility
    would pull them into ``_functionality_ratio`` and change
    balance; that's a design choice for a future phase, not a
    refactor side-effect.
    """

    #: Which locomotion state does this source feed? ``"grounded"``
    #: (legs) or ``"airborne"`` (wings). Override per-plugin.
    MOBILITY_MODE: str = "grounded"


class Defensive:
    """Node that contributes to DEFENSE.

    Torso primarily. Per-part ``defense_bonus`` and
    ``is_critical`` flags live on :class:`BodyPart` itself —
    the Defensive tag just means "this part is a defense source
    for :meth:`Creature.get_defense`'s emergence math."
    """


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
