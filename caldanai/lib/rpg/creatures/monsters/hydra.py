"""``Hydra`` monster plugin — four-variant family with per-head elemental
damage types, multi-target combat, per-head attack repertoires, and an
action-economy budget system.

See ``{local-notes}.md`` in the local notes
for the full design rationale.

Variants
========

1. **hydra** (default grotesque) — crushing fangs, no elemental affinity.
2. **swamp hydra** — venomous, poison-themed (``DARK|AIR``).
3. **hexed hydra** — dark magic, fewer heads but arcane specials.
4. **elemental hydra** — rare, 5 elemental heads, stronger stats.

Action economy
==============

Each round the hydra has a **budget** of action points.  It selects
attacks from all available body parts (heads, tail, legs) until the
budget is spent.  More heads = more options, not more guaranteed attacks.

Budget = ``max(2, sum(cheapest action cost per live attackable part) // 2)``

Multi-target combat
===================

Selected actions are distributed round-robin across combatants.  A
narrative paragraph describes what the hydra attempts, then a combined
``AttackSequence`` table resolves the outcomes mechanically.
"""

from collections import defaultdict
from random import choice, choices, sample, random
from typing import Dict, List, Optional, Tuple

from caldanai.lib.rpg.combat.attack_result import AttackResult, AttackSequence
from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_parts.tail import TailPlugin
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, DamageTypes, Reach, Size, TimePartitions,
)
from caldanai.lib.rpg.helpers.parser import parse
from caldanai.lib.rpg.creatures import Creature

# ---------------------------------------------------------------------------
# Per-action narrative sentence templates
# ---------------------------------------------------------------------------
# {display} = part display name, {victim} = target name, {label} = action label.
# @1 is resolved by the parser as the hydra.

_NARRATIVE_TEMPLATES = {
    "bite": "One of @1d's heads lunges at {victim} with {article} {label}.",
    "ram": "One of @1d's heads slams into {victim}.",
    "breath": "One of @1d's heads rears back and unleashes {article} {label} at {victim}.",
    "spit": "One of @1d's heads hocks a glob of {label} at {victim}.",
    "hex": "One of @1d's heads crackles with dark energy aimed at {victim}.",
    "sweep": "One of @1d's heads gusts a blast of wind at {victim}.",
    "tail": "@1dc whips its tail at {victim}.",
    "stomp": "@1dc brings a massive leg down on {victim}.",
    "kick": "@1dc lashes out with a hind leg at {victim}.",
}


def _article(word: str) -> str:
    """Return 'an' if *word* starts with a vowel sound, otherwise 'a'."""
    return "an" if word and word[0].lower() in "aeiou" else "a"

# ---------------------------------------------------------------------------
# Variant definitions
# ---------------------------------------------------------------------------

# Each head repertoire action:
#   key: action name (matches _NARRATIVE_TEMPLATES)
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
               "dmg_type": DamageTypes.EARTH | DamageTypes.WATER | DamageTypes.RANGED,
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
    "tail": {"cost": 2, "weight": 1.0, "dice": "1d8",
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
        "head_dmg_types": [DamageTypes.DARK | DamageTypes.AIR],
        "head_repertoire": _REPERTOIRE_SWAMP,
        "stats": {},
        "traits": {DamageTypes.DARK | DamageTypes.AIR: 0.5},
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
            DamageTypes.FIRE,                          # fire
            DamageTypes.DARK | DamageTypes.WATER,      # ice
            DamageTypes.DARK | DamageTypes.AIR,        # poison
            DamageTypes.LIGHT | DamageTypes.AIR,       # lightning
            DamageTypes.EARTH | DamageTypes.WATER,     # acid
        ],
        "head_repertoire": _REPERTOIRE_ELEMENTAL,
        "stats": {
            "atk": "1d8",
            "defense": "3d6",
            "dodge": "3d8",
            "health_max": "30d10",
        },
        "traits": {
            DamageTypes.FIRE: 0.75,
            DamageTypes.DARK | DamageTypes.WATER: 0.75,
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


class Hydra(MonsterPlugin):
    """Multi-headed monster with variants, action economy, and per-head
    elemental damage types.

    See module docstring and the local design doc for the full design.
    """

    MAX_HEADS = 10

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
            health_max=stats.get("health_max", "20d10"),
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

        # --- Body part composition ---
        # Quadruped body minus the generic head (we add variant heads).
        self.body_parts = [p for p in BodyPart.quadruped() if p.name != "head"]
        for p in self.body_parts:
            if p.name == "torso":
                p.is_critical = True
                break

        # Add variant-specific heads with per-head damage types.
        starting_heads = variant["starting_heads"]
        head_types = variant["head_dmg_types"]
        for i in range(starting_heads):
            dmg_type = head_types[i % len(head_types)]
            self.body_parts.append(self._make_head(f"head.{i + 1}", dmg_type))
        self._next_head_number = starting_heads + 1

        self._scale_part_hp()

        # Breath cooldown tracker: {head_name: rounds_remaining}.
        self._breath_cooldown: Dict[str, int] = {}

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
            hp_scale = self.size.value["hp_scale"]
            if hp_scale != 1.0:
                head.health_max = max(1, int(head.health_max * hp_scale))
                head.health = head.health_max
        return head

    def _get_head_dmg_type(self) -> DamageTypes:
        """Pick a damage type for a regrown head from the variant's pool."""
        return choice(self._variant["head_dmg_types"])

    # ------------------------------------------------------------------
    # Action economy
    # ------------------------------------------------------------------

    def _get_attackable_parts(self) -> List[Tuple["BodyPart", dict]]:
        """Return (part, repertoire) pairs for all parts that can attack.

        Heads use the variant's head repertoire.  Tail and legs use their
        fixed single-action repertoires.
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
        """Compute the action budget for this round.

        Budget = max(2, sum(cheapest action cost per part) // 2).
        """
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
        """Pick an action from the repertoire for a specific part.

        Returns ``(action_name, action_dict)`` or ``None`` if no valid
        actions remain (e.g. all are cooldown-locked).
        """
        available = {}
        for name, action in repertoire.items():
            # Breath requires cooldown to be off.
            if action.get("cooldown") and self._breath_cooldown.get(part.name, 0) > 0:
                continue
            available[name] = action

        if not available:
            return None

        names = list(available.keys())
        weights = [available[n]["weight"] for n in names]
        picked = choices(names, weights=weights, k=1)[0]
        return picked, available[picked]

    def _select_round_actions(self) -> List[Tuple["BodyPart", str, dict]]:
        """Select this round's actions within the budget.

        Returns a list of ``(part, action_name, action_dict)`` triples.
        """
        attackable = self._get_attackable_parts()
        budget = self._compute_budget(attackable)
        if budget <= 0:
            return []

        # Prioritize heads, then tail, then legs — but shuffle within
        # each tier so the specific head/leg that acts is random.
        def _priority(item):
            part, _ = item
            if isinstance(part, HeadPlugin):
                return 0
            if isinstance(part, TailPlugin):
                return 1
            return 2  # legs

        attackable.sort(key=_priority)
        # Shuffle within each priority tier.
        tiers = {}
        for item in attackable:
            p = _priority(item)
            tiers.setdefault(p, []).append(item)
        shuffled = []
        for p in sorted(tiers):
            tier = tiers[p]
            shuffled.extend(sample(tier, len(tier)))

        selected: List[Tuple["BodyPart", str, dict]] = []
        remaining = budget
        for part, repertoire in shuffled:
            if remaining <= 0:
                break
            result = self._select_action_for_part(part, repertoire)
            if result is None:
                continue
            action_name, action = result
            cost = action["cost"]
            if cost > remaining:
                # Too expensive — try to pick a cheaper action.
                cheaper = {
                    n: a for n, a in repertoire.items()
                    if a["cost"] <= remaining
                    and not (a.get("cooldown") and self._breath_cooldown.get(part.name, 0) > 0)
                }
                if not cheaper:
                    continue
                names = list(cheaper.keys())
                weights = [cheaper[n]["weight"] for n in names]
                action_name = choices(names, weights=weights, k=1)[0]
                action = cheaper[action_name]
                cost = action["cost"]

            selected.append((part, action_name, action))
            remaining -= cost

            # Set breath cooldown if applicable.
            if action.get("cooldown"):
                self._breath_cooldown[part.name] = action["cooldown"]

        return selected

    # ------------------------------------------------------------------
    # Damage type resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_dmg_type(
        part: "BodyPart", action: dict
    ) -> Optional[DamageTypes]:
        """Resolve the final damage type for an action.

        - ``dmg_type`` in the action: full override.
        - ``dmg_mod`` in the action: combine with the part's element.
        - Neither: the part's pure element.
        """
        if "dmg_type" in action:
            return action["dmg_type"]
        part_type = getattr(part, "dmg_type", None)
        if "dmg_mod" in action:
            if part_type:
                return part_type | action["dmg_mod"]
            return action["dmg_mod"]
        return part_type

    # ------------------------------------------------------------------
    # Narrative generation
    # ------------------------------------------------------------------

    def _build_narrative(
        self, actions_with_targets: List[Tuple["BodyPart", str, dict, "Creature"]]
    ) -> str:
        """Build the pre-table flavor paragraph from selected actions."""
        lines = []
        for part, action_name, action, victim in actions_with_targets:
            template = _NARRATIVE_TEMPLATES.get(action_name)
            if not template:
                continue
            victim_name = getattr(victim, "name", "someone")
            label = action.get("label", action_name)
            line = template.format(
                display=part.display_name,
                victim=victim_name,
                label=label,
                article=_article(label),
            )
            lines.append(line)

        if not lines:
            return ""
        return parse("\n".join(lines), self)

    # ------------------------------------------------------------------
    # Multi-target distribution
    # ------------------------------------------------------------------

    @staticmethod
    def _assign_to_targets(
        actions: List[Tuple["BodyPart", str, dict]],
        combatants: list,
    ) -> List[Tuple["BodyPart", str, dict, "Creature"]]:
        """Distribute selected actions round-robin across combatants."""
        if not combatants or not actions:
            return []
        shuffled = sample(actions, len(actions))
        result = []
        for i, (part, action_name, action) in enumerate(shuffled):
            victim = combatants[i % len(combatants)]
            result.append((part, action_name, action, victim))
        return result

    # ------------------------------------------------------------------
    # attack_random override
    # ------------------------------------------------------------------

    def attack_random(self, combatants: list, count=1) -> str:
        """Multi-target attack with action economy and narrative."""
        if not combatants:
            return None

        # 1. Select this round's actions within budget.
        actions = self._select_round_actions()
        if not actions:
            return None

        # 2. Assign actions to targets.
        assignments = self._assign_to_targets(actions, combatants)
        if not assignments:
            return None

        # 3. Build narrative paragraph.
        narrative = self._build_narrative(assignments)

        # 4. Resolve each attack mechanically.
        results: List[AttackResult] = []
        hits_per_victim: Dict[int, int] = defaultdict(int)
        raw_per_victim: Dict[int, int] = defaultdict(int)

        for part, action_name, action, victim in assignments:
            dmg_type = self._resolve_dmg_type(part, action)
            reach = action.get("reach", Reach.MELEE)
            label = action.get("label", action_name)
            source = NaturalAttackSource(
                atk=action["dice"],
                dmg_type=dmg_type,
                label=f"{part.display_name.title()} \u2192 {getattr(victim, 'name', '?')} ({label})",
                skill="natural",
                reach=reach,
            )
            atk_roll, dmg_roll = source.make_attack_rolls(self)
            result = victim.resolve_attack(self, source, atk_roll, dmg_roll)
            results.append(result)
            if result.damage > 0:
                raw_per_victim[id(victim)] += result.damage
                hits_per_victim[id(victim)] += 1

        # 5. Build combined AttackSequence.
        first_victim = combatants[0]
        sequence = AttackSequence(
            attacker=self,
            target=first_victim,
            results=results,
            multi_target=True,
        )

        # 6. Render output.
        msg = ""
        if narrative:
            msg += f"\n{narrative}\n"
        msg += sequence.to_markdown()

        # 7. Apply damage per victim (defense subtracted once per victim).
        seen = set()
        for part, action_name, action, victim in assignments:
            vid = id(victim)
            if vid in seen:
                continue
            seen.add(vid)
            raw = raw_per_victim.get(vid, 0)
            num_hits = hits_per_victim.get(vid, 0)
            if num_hits > 0:
                defense = victim.get_defense()
                final = max(num_hits, raw - defense)
                victim_name = getattr(victim, "name", "someone")
                if defense and raw != final:
                    msg += f"{victim_name}: {raw} damage - {defense} defense \u2192 {final} damage\n"
                dmg_msg = victim.apply_damage(final)
                if dmg_msg:
                    msg += parse(dmg_msg, victim)

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
        live_heads = [
            p for p in self.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical
            and not p.is_destroyed()
        ]

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

    def on_combat_round(self, damage_by_player) -> str:
        """Breath cooldown tick, last-head death check, and regrowth."""
        # Tick breath cooldowns.
        for key in list(self._breath_cooldown):
            self._breath_cooldown[key] -= 1
            if self._breath_cooldown[key] <= 0:
                del self._breath_cooldown[key]

        live_heads = [
            p for p in self.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical
            and not p.is_destroyed()
        ]
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

        # 1. Death check — no live heads means death BEFORE regrowth.
        if live_count == 0:
            self.health = 0
            return parse(
                "@1dc's last head falls. With no brain to direct it, @1's "
                "body collapses in a lifeless heap.",
                self,
            )

        # 2. Count destroyed heads.
        destroyed_count = len(destroyed_heads)
        if destroyed_count == 0:
            return ""

        # 3. Regrowth: 2 per destroyed head, capped by MAX_HEADS.
        slots_available = max(0, self.MAX_HEADS - live_count)
        to_spawn = min(destroyed_count * 2, slots_available)

        for _ in range(to_spawn):
            dmg_type = self._get_head_dmg_type()
            self.body_parts.append(
                self._make_head(f"head.{self._next_head_number}", dmg_type, scale=True)
            )
            self._next_head_number += 1

        # Remove destroyed heads from body_parts.
        self.body_parts = [
            p for p in self.body_parts
            if not (isinstance(p, HeadPlugin) and not p.is_critical
                    and p.is_destroyed())
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
