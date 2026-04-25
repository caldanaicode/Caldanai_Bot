"""``Hydra`` monster plugin — four-variant family with per-head elemental
damage types, multi-target combat, per-head attack repertoires, and an
action-economy budget system.

See ``{local-notes}.md`` in the local notes
for the full design rationale and ``combat-pipeline-refactor.md`` for
the Phase-4 port that wires the hydra onto the base pipeline.

Variants
========

1. **hydra** (default grotesque) — crushing fangs, no elemental affinity.
2. **swamp hydra** — venomous, poison-themed (``DARK|AIR``).
3. **hexed hydra** — dark magic, fewer heads but arcane specials.
4. **elemental hydra** — rare, 5 elemental heads, stronger stats.

Action economy
==============

Each round the hydra has a **budget** of action points. It selects
attacks from all available body parts (heads, tail, legs) until the
budget is spent. More heads = more options, not more guaranteed
attacks.

Budget = ``max(2, sum(cheapest action cost per live attackable part) // 2)``

Multi-target combat
===================

The hydra overrides :meth:`Creature.pick_targets` with
:func:`round_robin_assignment` so selected actions distribute
round-robin across combatants. Everything else (selection, narration,
resolution, injury feedback, damage summary, death narration) flows
through the base pipeline stages introduced in Phases 2-3 of the
combat refactor.
"""

from random import choice, choices
from typing import Dict, List, Optional, Tuple

from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
from caldanai.lib.rpg.creatures.body_builder import node, paired
from caldanai.lib.rpg.creatures.body_parts.eye import EyePlugin
from caldanai.lib.rpg.creatures.body_parts.foot import FootPlugin
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_parts.neck import NeckPlugin
from caldanai.lib.rpg.creatures.body_parts.tail import TailPlugin
from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, DamageTypes, Reach, Size, TimePartitions,
)
from caldanai.lib.rpg.helpers.parser import article, parse
from caldanai.lib.rpg.creatures import round_robin_assignment

# ---------------------------------------------------------------------------
# Narrative templates
# ---------------------------------------------------------------------------

# Keyed by action name. ``{article_label}`` is substituted at spawn time
# with the per-variant article + label (e.g. ``"a sulfurous spit"``,
# ``"an elemental breath"``) so the converted template is a literal
# ``@1``/``@2``-tokened string the base parser can render without any
# runtime ``.format()``. Kept as single-template pools for Phase-4 parity
# — richer pools can graduate later (see Phase-3 convention in the
# refactor doc).

_TEMPLATES_BY_ACTION: Dict[str, str] = {
    "bite": "One of @1np heads lunges at @2 with {article_label}.",
    "ram": "One of @1np heads slams into @2.",
    "breath": "One of @1np heads rears back and unleashes {article_label} at @2.",
    "spit": "One of @1np heads hocks a glob of {label} at @2.",
    "hex": "One of @1np heads crackles with dark energy aimed at @2.",
    "sweep": "One of @1np heads gusts a blast of wind at @2.",
    "tail_swipe": "@1D whips its tail at @2.",
    "stomp": "@1D brings a massive leg down on @2.",
    "kick": "@1D lashes out with a hind leg at @2.",
}


# Decapitation-death pool. Fires when every non-critical head is
# destroyed — the HP-based death path (``self.death``) still covers
# the more common bleed-out ending. Kept variant-agnostic; per-variant
# lines are tracked as a follow-up in
# ``memory/project_hydra_decapitation_death_flavor.md``.
_DECAPITATION_DEATH_POOL = [
    "@1dc's last head topples from the neck stump, and what's left of the body crumples into a still, heavy heap.",
    "@1dc's final head falls — the bulk shudders once, then goes still, no mind left to drive it.",
    "@1dc's last head hits the ground with a wet thud. The body lurches, twitches, and gives up the ghost.",
]

# ---------------------------------------------------------------------------
# Variant definitions
# ---------------------------------------------------------------------------

# Each head repertoire action:
#   key: action name (matches _TEMPLATES_BY_ACTION)
#   cost: action budget points
#   weight: selection probability (normalized)
#   dice: attack dice string
#   dmg_type: full override (replaces head element)      } mutually exclusive;
#   dmg_mod: combined with head element via |             } if neither, pure element
#   reach: Reach enum (default MELEE)
#   cooldown: rounds before re-use (breath only)

_REPERTOIRE_GROTESQUE = {
    "bite":   {"cost": 1, "weight": 0.60, "dice": "1d6",
               "label": "bite", "dmg_mod": DamageTypes.PIERCING},
    "ram":    {"cost": 1, "weight": 0.25, "dice": "1d8",
               "label": "headbutt", "dmg_type": DamageTypes.BLUDGEONING},
    "breath": {"cost": 2, "weight": 0.15, "dice": "2d6",
               "label": "sulfurous spit", "cooldown": 3},
}

_REPERTOIRE_SWAMP = {
    "bite":   {"cost": 1, "weight": 0.55, "dice": "1d6",
               "label": "venomous bite", "dmg_mod": DamageTypes.PIERCING},
    "ram":    {"cost": 1, "weight": 0.20, "dice": "1d8",
               "label": "headbutt", "dmg_type": DamageTypes.BLUDGEONING},
    "breath": {"cost": 2, "weight": 0.20, "dice": "2d6",
               "label": "poison cloud", "cooldown": 3},
    "spit":   {"cost": 1, "weight": 0.05, "dice": "1d4",
               "label": "acid spit",
               "dmg_type": DamageTypes.ACID | DamageTypes.RANGED,
               "reach": Reach.RANGED},
}

_REPERTOIRE_HEXED = {
    "bite":   {"cost": 1, "weight": 0.50, "dice": "1d6",
               "label": "arcane bite", "dmg_mod": DamageTypes.PIERCING},
    "ram":    {"cost": 1, "weight": 0.15, "dice": "1d8",
               "label": "headbutt", "dmg_type": DamageTypes.BLUDGEONING},
    "breath": {"cost": 2, "weight": 0.20, "dice": "2d6",
               "label": "dark pulse", "cooldown": 4},
    "hex":    {"cost": 1, "weight": 0.15, "dice": "1d10",
               "label": "hex bolt",
               "dmg_type": DamageTypes.DARK | DamageTypes.MAGICAL | DamageTypes.RANGED,
               "reach": Reach.RANGED},
}

_REPERTOIRE_ELEMENTAL = {
    "bite":   {"cost": 1, "weight": 0.55, "dice": "1d8",
               "label": "elemental bite", "dmg_mod": DamageTypes.SLASHING},
    "ram":    {"cost": 1, "weight": 0.15, "dice": "1d10",
               "label": "horn ram",
               "dmg_type": DamageTypes.BLUDGEONING | DamageTypes.EARTH},
    "breath": {"cost": 2, "weight": 0.25, "dice": "3d6",
               "label": "elemental breath", "cooldown": 2},
    "sweep":  {"cost": 1, "weight": 0.05, "dice": "1d6",
               "label": "wing gust",
               "dmg_type": DamageTypes.AIR | DamageTypes.BLUDGEONING},
}

# Tail and leg actions (shared across all variants).
_ACTION_TAIL_SWIPE = {
    "tail_swipe": {"cost": 2, "weight": 1.0, "dice": "1d8",
                   "label": "tail swipe", "dmg_type": DamageTypes.BLUDGEONING},
}

_ACTION_FORELEG_STOMP = {
    "stomp": {"cost": 1, "weight": 1.0, "dice": "1d4",
              "label": "stomp", "dmg_type": DamageTypes.BLUDGEONING},
}

_ACTION_HINDLEG_KICK = {
    "kick": {"cost": 1, "weight": 1.0, "dice": "1d4",
             "label": "kick", "dmg_type": DamageTypes.BLUDGEONING},
}

# Head exposure values (shared across all variants).
_HEAD_EXPOSURE = {
    Reach.MELEE: 0.4, Reach.REACH: 0.5,
    Reach.THROWN: 0.7, Reach.RANGED: 1.0,
}

VARIANTS = [
    {
        "name": "hydra",
        "weight": 3,
        "size": Size.LARGE,
        "starting_heads": 3,
        "head_dmg_types": [DamageTypes.PIERCING | DamageTypes.SLASHING],
        "head_repertoire": _REPERTOIRE_GROTESQUE,
        "stats": {},
        "traits": {},
        "loot_overrides": {},
        "arrival": (
            "A writhing mass of scales erupts from the murk as @1i looms "
            "into view, heads hissing in unison."
        ),
        "flavor": (
            "A grotesque serpentine @1 coils with surprising grace, its "
            "many heads swaying in a hypnotic unison. The ground around "
            "it is slick with sulfurous runoff."
        ),
        "escape": (
            "@1dc slithers back into the murk, its heads twisting in "
            "mocking farewell."
        ),
        "death": (
            "@1dc's remaining heads sag lifelessly, and with a final "
            "bone-wet shudder, the whole writhing bulk collapses into a "
            "still, steaming mound."
        ),
    },
    {
        "name": "swamp hydra",
        "weight": 3,
        "size": Size.LARGE,
        "starting_heads": 3,
        "head_dmg_types": [DamageTypes.POISON],
        "head_repertoire": _REPERTOIRE_SWAMP,
        "stats": {},
        # Swamp hydra resists ITS OWN poison specifically (compound
        # match via COMBINED in the alias). Pure dark or pure air
        # attacks pass through normally now — previously this trait
        # covered both, which was a quiet over-resistance.
        "traits": {DamageTypes.POISON: 0.5},
        "loot_overrides": {"toad_slime": 1.0, "wool": 0},
        "arrival": (
            "Poisonous vapors roll across the ground as @1i drags "
            "itself from the fetid bog, venom dripping from every fang."
        ),
        "flavor": (
            "@1ic coils in the shallows, its mottled scales slick with "
            "algae. The stench of rot and venom hangs heavy in the air "
            "around it."
        ),
        "escape": (
            "@1dc sinks back into the fetid waters with barely a "
            "ripple, leaving only the acrid smell of venom behind."
        ),
        "death": (
            "@1dc convulses as its venom sacs rupture, spilling "
            "caustic ichor across the ground before it finally lies "
            "still."
        ),
    },
    {
        "name": "hexed hydra",
        "weight": 3,
        "size": Size.LARGE,
        "starting_heads": 2,
        "head_dmg_types": [DamageTypes.DARK | DamageTypes.MAGICAL],
        "head_repertoire": _REPERTOIRE_HEXED,
        "stats": {},
        "traits": {DamageTypes.MAGICAL: 0.5},
        "loot_overrides": {"wand": 0.15, "wool": 0},
        "arrival": (
            "Arcane sigils flare in the air as @1i materializes from "
            "a rift of dark energy, its eyes burning with eldritch "
            "purpose."
        ),
        "flavor": (
            "An unnaturally sleek @1 prowls with feline grace, its "
            "scales shimmering with residual enchantment. Each head "
            "moves with an unsettling independent intelligence."
        ),
        "escape": (
            "@1dc dissolves into wisps of dark mana, its laughter "
            "echoing long after its form has gone."
        ),
        "death": (
            "@1dc unravels in a cascade of spent magic, its scales "
            "flaking away into motes of dying light before the body "
            "collapses."
        ),
    },
    {
        "name": "elemental hydra",
        "weight": 1,
        "size": Size.HUGE,
        "starting_heads": 5,
        "head_dmg_types": [
            DamageTypes.FIRE,         # fire (single bit, no alias needed)
            DamageTypes.ICE,          # ice = WATER | DARK | COMBINED
            DamageTypes.POISON,       # poison = DARK | AIR | COMBINED
            DamageTypes.LIGHTNING,    # lightning = LIGHT | AIR | COMBINED
            DamageTypes.ACID,         # acid = EARTH | WATER | COMBINED
        ],
        "head_repertoire": _REPERTOIRE_ELEMENTAL,
        "stats": {
            "atk": "1d8",
            "defense": "3d6",
            "dodge": "3d8",
            "health_max": "50d12",
        },
        "traits": {
            # Elemental hydra resists fire and ice (its two coldest
            # heads). Pure water and pure dark are no longer
            # incidentally resisted — only compound ice attacks fire
            # the 0.75 multiplier.
            DamageTypes.FIRE: 0.75,
            DamageTypes.ICE:  0.75,
        },
        "loot_overrides": {"small_gem": 0.9, "wand": 0.2, "wool": 0},
        "arrival": (
            "The sky cracks with five colors as @1i descends, each "
            "head wreathed in a different elemental fury. The ground "
            "itself seems to flinch."
        ),
        "flavor": (
            "A {size} @1 radiates raw elemental force from every "
            "scale. Its five heads — flame, frost, venom, lightning, "
            "acid — weave independently, each tracking a different "
            "target."
        ),
        "escape": (
            "@1dc retreats in a storm of elemental fury, its five "
            "heads snapping at the air as it vanishes into a rift of "
            "raw energy."
        ),
        "death": (
            "One by one, the elemental flames die in @1d's maws. "
            "Fire gutters, ice cracks, venom hisses dry, lightning "
            "earths, acid neutralizes. The body crashes down in "
            "silence."
        ),
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_dmg_type(
    part_dmg_type: Optional[DamageTypes], action: dict,
) -> Optional[DamageTypes]:
    """Resolve an action's final damage type against the owning part's
    element.

    Precedence:

    - ``dmg_type`` in the action: full override.
    - ``dmg_mod`` in the action: OR'd with the part's element.
    - Neither: the part's pure element.
    """
    if "dmg_type" in action:
        return action["dmg_type"]
    if "dmg_mod" in action:
        if part_dmg_type:
            return part_dmg_type | action["dmg_mod"]
        return action["dmg_mod"]
    return part_dmg_type


def _narrative_for(action_name: str, label: str) -> List[str]:
    """Return the single converted template for ``action_name`` with
    ``label`` and ``article(label)`` pre-embedded. Returns an empty list
    for unknown action names so :meth:`Creature.narrate_attempt` skips
    the assignment cleanly instead of emitting a blank line."""
    template = _TEMPLATES_BY_ACTION.get(action_name)
    if template is None:
        return []
    return [template.format(article_label=f"{article(label)} {label}", label=label)]


def _convert_to_base_shape(
    entry: dict, action_name: str,
    part_dmg_type: Optional[DamageTypes],
    breath_cooldown_gate,
) -> dict:
    """Project a legacy repertoire entry into the Phase-3 action shape.

    Adds the pre-resolved ``dmg_type`` (combined with the owning part's
    element for ``dmg_mod`` entries), defaults ``reach`` to
    :attr:`Reach.MELEE`, carries label / dice / cost / weight through
    unchanged, and injects an ``is_available`` gate on breath actions so
    the base :meth:`Creature.pick_actions` filters them out while the
    per-head breath cooldown is non-zero. ``narrative`` is populated
    from :func:`_narrative_for` so the converted entry renders through
    the base pipeline's narrative stage without any runtime ``.format()``
    shim.
    """
    label = entry.get("label", action_name)
    converted: Dict = {
        "cost": entry["cost"],
        "weight": entry["weight"],
        "dice": entry["dice"],
        "reach": entry.get("reach", Reach.MELEE),
        "dmg_type": _resolve_dmg_type(part_dmg_type, entry),
        "label": label,
        "narrative": _narrative_for(action_name, label),
    }
    if "cooldown" in entry:
        converted["cooldown"] = entry["cooldown"]
        if breath_cooldown_gate is not None:
            converted["is_available"] = breath_cooldown_gate
    return converted


class Hydra(MonsterPlugin):
    """Multi-headed monster with variants, action economy, and per-head
    elemental damage types.

    See module docstring and the local design docs
    (``{local-notes}.md`` and
    ``combat-pipeline-refactor.md``) for the full design.
    """

    # Every ``VARIANTS[i]["name"]`` is a valid in-fiction display name
    # a player might type. Register all except the bare ``"hydra"`` (which
    # is the filename stem and registered automatically).
    ALIASES = [v["name"] for v in VARIANTS if v["name"] != "hydra"]

    MAX_HEADS = 10

    # Per-hit narration: hydra-class flavor that reads correctly
    # across all variants. Variant-specific resistance overlays
    # (hexed magic-resist, swamp poison-resist) are layered onto
    # ``self.traits`` at __init__ time but the flavor stays generic
    # — overlapping scales, multi-headed serpent body. The dense
    # build cushions blunt blows; sharp points find the seams.
    HIT_NARRATIONS = {
        DamageTypes.BLUDGEONING: "The blow lands on overlapping scales; @1d shifts under the impact but barely flinches.",
        DamageTypes.SLASHING:    "The blade glances off @1a scales, biting only where they overlap unevenly.",
        DamageTypes.PIERCING:    "The point slips between @1a scales and finds the soft serpent body beneath.",
        DamageTypes.FIRE:        "Flame catches at @1a scales and crackles along the seams.",
        DamageTypes.MAGICAL:     "Arcane force ripples across @1a draconic frame, finding only the deep magic that holds @1o together.",
    }

    def __init__(self):
        # Pick variant by weight.
        variant = choices(
            VARIANTS,
            weights=[v["weight"] for v in VARIANTS],
            k=1,
        )[0]
        self._variant = variant

        # Apply stat overrides from variant, or use baseline defaults.
        stats = variant.get("stats", {})
        super().__init__(
            name=variant["name"],
            atk=stats.get("atk", "1d6"),
            defense=stats.get("defense", "2d6"),
            dodge=stats.get("dodge", "2d8"),
            health_max=stats.get("health_max", "30d12"),
        )

        self.time_partition = TimePartitions.CATHEMERAL
        self.image = None
        self.aggression = AggressionLevels.RAMPAGE

        self.arrival = variant["arrival"]
        self.flavor = variant["flavor"].format(size=self.size.name.lower())
        self.escape = variant["escape"]
        self.death = variant["death"]

        # Creature-level traits (elemental resistances).
        for dmg_type, multiplier in variant.get("traits", {}).items():
            self.traits[dmg_type] = multiplier

        # Base loot table.
        self.loot["toad_slime"] = 0.8
        self.loot["leather"] = 0.5
        self.loot["small_gem"] = 0.3
        self.loot["wool"] = 0.2
        # Variant overrides (e.g. swamp guarantees toad_slime).
        for item, freq in variant.get("loot_overrides", {}).items():
            self.loot[item] = freq

        # Set size from variant (must be before body part composition
        # so _scale_part_hp reads the correct scale).
        self.size = variant["size"]

        # Breath cooldown tracker: {head_name: rounds_remaining}. Must
        # exist before ``_wire_part_actions`` runs so the breath
        # ``is_available`` gate can close over ``self`` safely.
        self._breath_cooldown: Dict[str, int] = {}

        # --- Body part composition ---
        # The tree's variant-specific heads are materialized via the
        # ``_materialize_body_tree`` override below. Base ``Creature.__init__``
        # already ran on ``super().__init__(...)`` above WITHOUT our
        # variant state in place, so the default materialization used
        # ``BODY_TREE = None`` and left us body-less. Rebuild here now
        # that ``self._variant`` + ``self.size`` are set.
        self.body_root = self._materialize_body_tree()
        self.body_parts = list(self.body_root.walk()) if self.body_root else []

        # Per-head damage types get attached after materialization so
        # the existing ``_make_head``-style decoration keeps working.
        head_types = variant["head_dmg_types"]
        starting_heads = variant["starting_heads"]
        for i, head in enumerate(
            [p for p in self.body_parts if isinstance(p, HeadPlugin) and not p.is_critical]
        ):
            head.dmg_type = head_types[i % len(head_types)]
        self._next_head_number = starting_heads + 1

        self._scale_part_hp()

        # Project per-variant action pools onto every attackable body
        # part as instance-level DEFAULT_ACTIONS — the base pipeline
        # reads these through ``_collect_part_action_pools``.
        self._wire_part_actions()

    # ------------------------------------------------------------------
    # Body tree (variant-driven anatomy)
    # ------------------------------------------------------------------

    def _materialize_body_tree(self):
        """Build the hydra's body tree from the already-picked variant.

        Instance-state pattern from the Phase B1 plan: anatomy
        depends on ``self._variant["starting_heads"]``, so the tree
        can't live at class level. The method is called twice during
        ``__init__`` — once by base ``Creature.__init__`` (before
        we've set ``self._variant``, returning ``None``) and again
        after we set up variant state (building the real tree).
        """
        variant = getattr(self, "_variant", None)
        if variant is None:
            return None

        starting_heads = variant["starting_heads"]
        # Phase D: each hydra head sits on its own neck with a
        # pair of eyes. The heads share the same exposure profile
        # and non-critical flag regardless of index; eyes are
        # shared across heads so aim targeting hydra.3 eye.left
        # resolves naturally. Legs end in forepaws / hindpaws.
        head_subtrees = []
        for i in range(starting_heads):
            idx = i + 1
            head_subtrees.append(
                node(NeckPlugin, name=f"neck.{idx}", children=[
                    node(HeadPlugin, name=f"head.{idx}",
                         is_critical=False, exposure=dict(_HEAD_EXPOSURE),
                         children=[
                             node(EyePlugin, name=f"eye.{idx}.left"),
                             node(EyePlugin, name=f"eye.{idx}.right"),
                         ]),
                ])
            )
        return node(TorsoPlugin, name="torso", children=[
            *head_subtrees,
            *paired(
                LegPlugin, "foreleg",
                children_builder=lambda side: [
                    node(FootPlugin, name=f"forepaw.{side}"),
                ],
            ),
            *paired(
                LegPlugin, "hindleg",
                children_builder=lambda side: [
                    node(FootPlugin, name=f"hindpaw.{side}"),
                ],
            ),
            node(TailPlugin, name="tail"),
        ]).build()

    # ------------------------------------------------------------------
    # Head factory
    # ------------------------------------------------------------------

    def _make_head(self, name: str, dmg_type: DamageTypes, *, scale: bool = False) -> BodyPart:
        """Create a non-critical head with the given damage type.

        When *scale* is ``True``, applies the creature's size-based HP
        scaling so that heads created after ``__init__`` (regrowth) match
        the initial heads' HP.  During ``__init__``, pass ``scale=False``
        because ``_scale_part_hp()`` handles all parts in bulk.
        """
        head = BodyPart.make(
            "head", is_critical=False, name=name,
            exposure=dict(_HEAD_EXPOSURE),
        )
        head.dmg_type = dmg_type
        if scale:
            # Q.6: regrown heads share the body-HP-relative scaling
            # the initial heads got from ``_scale_part_hp``.
            from caldanai.lib.rpg.creatures import _compute_scaled_part_hp
            head.health_max = _compute_scaled_part_hp(
                head, self.health_max, self.size, self.get_defense(),
            )
            head.health = head.health_max
        return head

    def _get_head_dmg_type(self) -> DamageTypes:
        """Pick a damage type for a regrown head from the variant's pool."""
        return choice(self._variant["head_dmg_types"])

    def _grow_head_subtree(self, dmg_type: DamageTypes) -> HeadPlugin:
        """Grow a fresh neck → head → eye.L / eye.R subtree under
        torso. Returns the new head node so the caller can wire
        its ``DEFAULT_ACTIONS`` pool via :meth:`_wire_head_actions`.

        The "regeneration unit" is the full neck-through-eyes
        chain — regrowing just a head on a pre-existing neck
        would leave the creature with mismatched indices. This
        helper bumps ``_next_head_number`` so regrowth labels
        stay unique across both current and destroyed heads.
        """
        idx = self._next_head_number
        new_head = self._make_head(
            f"head.{idx}", dmg_type, scale=True,
        )
        new_neck = NeckPlugin(name=f"neck.{idx}")
        new_eye_l = EyePlugin(name=f"eye.{idx}.left")
        new_eye_r = EyePlugin(name=f"eye.{idx}.right")
        # Wire the subtree internally first: head gets two eye
        # children; neck gets the head as its sole child.
        new_head.add_child(new_eye_l)
        new_head.add_child(new_eye_r)
        new_neck.add_child(new_head)
        # Anchor the neck under torso via the creature-level
        # helper (keeps body_parts flat view in sync for the
        # neck node). Head and eyes still need manual append
        # because add_body_part only handles the node it's
        # given — not deeper descendants.
        self.add_body_part(new_neck, parent=self.body_root)
        self.body_parts.append(new_head)
        self.body_parts.append(new_eye_l)
        self.body_parts.append(new_eye_r)
        self._next_head_number += 1
        return new_head

    def _live_non_critical_heads(self) -> List[HeadPlugin]:
        """Return the hydra's live, non-critical heads.

        The decap-death path, combat-round bookkeeping, and
        ``get_attack_sources`` all care about the same slice; centralizing
        the filter keeps those three call sites in lockstep."""
        return [
            p for p in self.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical
            and not p.is_destroyed()
        ]

    # ------------------------------------------------------------------
    # Per-part action wiring — feeds the Phase-3 ``DEFAULT_ACTIONS``
    # channel that ``Creature.pick_actions`` reads.
    # ------------------------------------------------------------------

    def _wire_head_actions(self, head: HeadPlugin) -> None:
        """Project the variant's head repertoire onto one head as an
        instance-level ``DEFAULT_ACTIONS`` dict, with per-head elemental
        damage type baked into each entry and the breath ``is_available``
        gate wired to this head's cooldown bucket."""
        head_dmg_type = getattr(head, "dmg_type", None)
        head_name = head.name

        def _breath_gate(actor, _target):
            return actor._breath_cooldown.get(head_name, 0) <= 0

        head.DEFAULT_ACTIONS = {
            action_name: _convert_to_base_shape(
                entry, action_name, head_dmg_type, _breath_gate,
            )
            for action_name, entry in self._variant["head_repertoire"].items()
        }

    def _wire_part_actions(self) -> None:
        """Populate every attackable part's instance-level
        ``DEFAULT_ACTIONS`` from the variant's repertoires. Called once
        at ``__init__`` and again after regrowth so fresh heads pick up
        the variant's action pool."""
        for part in self.body_parts:
            if part.is_destroyed():
                continue
            if isinstance(part, HeadPlugin) and not part.is_critical:
                self._wire_head_actions(part)
            elif isinstance(part, TailPlugin):
                part.DEFAULT_ACTIONS = {
                    name: _convert_to_base_shape(entry, name, None, None)
                    for name, entry in _ACTION_TAIL_SWIPE.items()
                }
            elif isinstance(part, LegPlugin):
                if part.name.startswith("foreleg"):
                    source = _ACTION_FORELEG_STOMP
                elif part.name.startswith("hindleg"):
                    source = _ACTION_HINDLEG_KICK
                else:
                    continue
                part.DEFAULT_ACTIONS = {
                    name: _convert_to_base_shape(entry, name, None, None)
                    for name, entry in source.items()
                }

    # ------------------------------------------------------------------
    # Budget & action-economy helpers retained for
    # ``check_part_driven_death``, tests, and hydra-specific bookkeeping.
    # ``Creature.pick_actions`` no longer calls these — it reads the
    # wired ``DEFAULT_ACTIONS`` directly.
    # ------------------------------------------------------------------

    def _get_attackable_parts(self) -> List[Tuple["BodyPart", dict]]:
        """Return (part, repertoire) pairs for all parts that can attack.

        Heads use the variant's head repertoire.  Tail and legs use
        their fixed single-action repertoires. Retained for the budget
        formula in :meth:`get_action_budget` and its pinning tests —
        the pipeline itself uses the per-part ``DEFAULT_ACTIONS``.
        """
        parts = []
        head_rep = self._variant["head_repertoire"]
        for p in self.body_parts:
            if p.is_destroyed():
                continue
            if isinstance(p, HeadPlugin) and not p.is_critical:
                parts.append((p, head_rep))
            elif isinstance(p, TailPlugin):
                parts.append((p, _ACTION_TAIL_SWIPE))
            elif isinstance(p, LegPlugin):
                if p.name.startswith("foreleg"):
                    parts.append((p, _ACTION_FORELEG_STOMP))
                elif p.name.startswith("hindleg"):
                    parts.append((p, _ACTION_HINDLEG_KICK))
        return parts

    def _compute_budget(self, attackable: List[Tuple["BodyPart", dict]]) -> int:
        """Budget = max(2, sum(cheapest action cost per part) // 2)."""
        if not attackable:
            return 0
        total_cheapest = 0
        for _part, repertoire in attackable:
            cheapest = min(a["cost"] for a in repertoire.values())
            total_cheapest += cheapest
        return max(2, total_cheapest // 2)

    def _select_action_for_part(
        self, part: "BodyPart", repertoire: dict
    ) -> Optional[Tuple[str, dict]]:
        """Weighted-random pick from ``repertoire`` respecting breath
        cooldown for this part. Retained so the breath-cooldown
        invariants stay exercised by
        ``test_breath_excluded_when_on_cooldown`` without demanding the
        test re-learn the pipeline.
        """
        available = {}
        for name, action in repertoire.items():
            if action.get("cooldown") and self._breath_cooldown.get(part.name, 0) > 0:
                continue
            available[name] = action
        if not available:
            return None
        names = list(available.keys())
        weights = [available[n]["weight"] for n in names]
        picked = choices(names, weights=weights, k=1)[0]
        return picked, available[picked]

    # ------------------------------------------------------------------
    # Pipeline overrides — Phase-4 bindings.
    # ------------------------------------------------------------------

    def get_action_budget(self) -> int:
        """Dynamic budget scales with live attackable parts.

        Mirrors the legacy ``_compute_budget`` formula so parity tests
        and playtest balance hold across the Phase-4 flip.
        """
        return self._compute_budget(self._get_attackable_parts())

    def _collect_part_action_pools(self):
        """Priority-sort parts heads → tail → legs with within-tier
        shuffling before feeding the base budget selector, and filter
        out non-attackers (torso, etc.) so budget + pool stay aligned
        with :meth:`_get_attackable_parts`.

        Reproduces the legacy ``_select_round_actions`` ordering — heads
        claim the budget first and always get the chance to act. The
        base ``body_parts`` order alone would pick cheap legs / tail
        first and exhaust the budget before any head is considered; it
        would also include the torso's inherited ``chestbutt``, which
        hydra explicitly never attacks with.
        """
        from random import sample

        pools = super()._collect_part_action_pools()
        pools = [
            (part, merged) for part, merged in pools
            if isinstance(part, (HeadPlugin, TailPlugin, LegPlugin))
            and not (isinstance(part, HeadPlugin) and part.is_critical)
        ]

        def _priority(item):
            part, _ = item
            if isinstance(part, HeadPlugin):
                return 0
            if isinstance(part, TailPlugin):
                return 1
            return 2

        tiers: Dict[int, list] = {}
        for item in pools:
            tiers.setdefault(_priority(item), []).append(item)
        shuffled = []
        for p in sorted(tiers):
            tier = tiers[p]
            shuffled.extend(sample(tier, len(tier)))
        return shuffled

    def pick_targets(self, actions, combatants):
        """Distribute selected actions round-robin across combatants.

        Hydra's defining multi-target behavior: 4 heads vs 2 players
        means each player takes two bites, not the same player eating
        all four.
        """
        return round_robin_assignment(actions, combatants)

    def attack_random(self, combatants: list, count=1) -> Optional[str]:
        """Multi-target retaliation. Thin driver over the Phase 2-3 base
        pipeline stages; ``Game.do_combat`` still invokes this method so
        the outer loop's contract is unchanged.
        """
        if not combatants:
            return None

        actions = self.pick_actions()
        if not actions:
            return None

        assignments = self.pick_targets(actions, combatants)
        if not assignments:
            return None

        # Record breath cooldowns for any breath action that was
        # selected this round. The cooldown field lives on the source's
        # stashed ``_action`` dict (carried through pick_actions).
        for source in actions:
            action = getattr(source, "_action", None) or {}
            part = getattr(source, "_part", None)
            cooldown = action.get("cooldown")
            if cooldown and part is not None:
                self._breath_cooldown[part.name] = cooldown

        narrative = self.narrate_attempt(assignments)
        results = self.resolve(assignments)
        table = self.render_table(results)
        injury_lines = self.narrate_results(results)

        # Preserve the pre-Phase-4 output shape: opening blank line,
        # narrative paragraph, attack table, per-victim injury
        # feedback, per-victim defense-math line (when defense mattered),
        # then per-victim death beats. Summaries / round-death beats
        # land in ``Game.do_combat`` after this method returns —
        # Phase 5 is where the outer loop migrates onto the pipeline
        # composer.
        msg = ""
        if narrative:
            msg += f"\n{narrative}\n"
        msg += table
        if injury_lines:
            msg += "\n".join(injury_lines) + "\n"

        from caldanai.lib.rpg.combat.resolution import (
            compute_body_hp_damage,
        )
        for victim, resolution in (results.per_victim or {}).items():
            num_hits = resolution.num_hits
            # Q.6.2: ``body_damage_total`` is sum of already-post-defense
            # ``result.damage`` values, and ``final`` is that sum
            # bleed-scaled via ``compute_body_hp_damage``. Armor has
            # already bitten per-hit before we get here, so this display
            # surfaces the bleed-through fraction rather than the
            # defense math.
            raw_total = resolution.body_damage_total
            if num_hits > 0:
                final = compute_body_hp_damage(resolution, victim)
                if raw_total != final:
                    victim_name = getattr(victim, "name", "someone")
                    msg += (
                        f"{victim_name}: {raw_total} post-defense "
                        f"\u2192 {final} to body HP (bleed-through)\n"
                    )
                # Body-HP application moved out of ``Creature.resolve``
                # in Phase 6a — the stage is pure part-routing now, so
                # each caller owns the whole-body write plus any
                # death-transition message it surfaces.
                if not victim.is_dead():
                    d_msg = victim.apply_damage(final)
                    if d_msg and not resolution.death_msg:
                        resolution.death_msg = d_msg
            if resolution.death_msg:
                msg += parse(resolution.death_msg, victim)

        return msg

    # ------------------------------------------------------------------
    # get_attack_sources (still used by do_attack for player-targeting)
    # ------------------------------------------------------------------

    def get_attack_sources(self):
        """Return one NaturalAttackSource per live head.

        This is still used when the hydra is targeted by
        ``Creature.do_attack`` (e.g. for body-part targeting resolution).
        The hydra's own retaliation uses ``attack_random`` which bypasses
        this method entirely.
        """
        live_heads = self._live_non_critical_heads()

        if not live_heads:
            return [
                NaturalAttackSource(
                    atk=self.attack,
                    dmg_type=DamageTypes.BLUDGEONING,
                    label=f"{self.name.title()} (headless flailing)",
                    skill="natural",
                )
            ]

        return [
            NaturalAttackSource(
                atk=self.attack,
                dmg_type=getattr(head, "dmg_type", None),
                label=f"{self.name.title()} ({head.display_name})",
                skill="natural",
            )
            for head in live_heads
        ]

    # ------------------------------------------------------------------
    # on_combat_round — cooldown tick + regrowth
    # ------------------------------------------------------------------

    def check_part_driven_death(self) -> Optional[str]:
        """Decapitation death: every non-critical head destroyed
        means dead, regardless of remaining body HP.

        Called by the combat loop before the HP-based ``is_dead``
        branch, so the decap death fires in the same round it
        happened — no post-death retaliation swing, no round-late
        ``$loot`` hint. Zeros ``self.health`` so downstream
        ``is_dead()`` callers agree.
        """
        if self._live_non_critical_heads():
            return None
        self.health = 0
        return parse(choice(_DECAPITATION_DEATH_POOL), self)

    def on_combat_round(self, damage_by_player) -> str:
        """Breath cooldown tick and head regrowth.

        Decapitation-death detection used to live here too, but it
        moved to :meth:`check_part_driven_death` so the combat loop
        sees the death in the same round it happens. By the time
        ``on_combat_round`` runs, a zero-heads hydra has already been
        caught by the death branch — so we only need to tick
        cooldowns and regrow heads for still-living hydras.
        """
        # Tick breath cooldowns.
        for key in list(self._breath_cooldown):
            self._breath_cooldown[key] -= 1
            if self._breath_cooldown[key] <= 0:
                del self._breath_cooldown[key]

        live_heads = self._live_non_critical_heads()
        destroyed_heads = [
            p for p in self.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical
            and p.is_destroyed()
        ]
        live_count = len(live_heads)

        # Clean up cooldown entries for destroyed heads.
        destroyed_names = {p.name for p in destroyed_heads}
        for key in destroyed_names & set(self._breath_cooldown):
            del self._breath_cooldown[key]

        # Count destroyed heads for regrowth.
        destroyed_count = len(destroyed_heads)
        if destroyed_count == 0:
            return ""

        # Regrowth: 2 per destroyed head, capped by MAX_HEADS.
        slots_available = max(0, self.MAX_HEADS - live_count)
        to_spawn = min(destroyed_count * 2, slots_available)

        for _ in range(to_spawn):
            dmg_type = self._get_head_dmg_type()
            new_head = self._grow_head_subtree(dmg_type)
            self._wire_head_actions(new_head)

        # Remove destroyed heads — and their parent neck + child
        # eyes, since the whole "neck → head → eyes" subtree is
        # the regeneration unit. Detach from torso's children and
        # prune from body_parts so neither reachability nor flat
        # iteration see the stumps.
        destroyed_non_critical_heads = [
            p for p in self.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical
            and p.is_destroyed()
        ]
        prune_set = set()
        for dead_head in destroyed_non_critical_heads:
            prune_set.add(id(dead_head))
            for eye in list(dead_head.children):
                prune_set.add(id(eye))
            parent_neck = dead_head.parent
            if parent_neck is not None:
                prune_set.add(id(parent_neck))
                if (
                    self.body_root is not None
                    and parent_neck in self.body_root.children
                ):
                    self.body_root.children.remove(parent_neck)
        self.body_parts = [
            p for p in self.body_parts if id(p) not in prune_set
        ]

        if to_spawn == 0:
            return parse(
                "@1dc's severed stumps writhe but produce nothing — "
                "it has reached its biological limit.",
                self,
            )
        if to_spawn == 1:
            return parse(
                "A single new head forces its way from a severed stump "
                "— @1d is nearing its biological limit.",
                self,
            )
        return parse(
            f"Where the severed heads fell, {to_spawn} more burst from "
            f"the stumps with bone-wet cracks.",
            self,
        )
