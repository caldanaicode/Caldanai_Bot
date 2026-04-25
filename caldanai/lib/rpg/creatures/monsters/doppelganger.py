import copy
from random import choice

from caldanai.lib.rpg import get_random_direction, Player
from caldanai.lib.rpg.creatures.body_builder import humanoid_tree
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.enums import AggressionLevels, InjuryLevels, Size, TimePartitions, Qualities
from caldanai.lib.rpg.helpers.parser import parse
from caldanai.lib.rpg.creatures import Creature
from caldanai.logger import get_logger


_log = get_logger(__name__)


# Pain summaries the doppelganger emits when it imitates a target and
# inherits injured body parts. Grouped by injury level — at imitate
# time the doppy walks every non-NONE-injured part, groups them by
# level, picks ONE template per level present, and substitutes the
# joined display-name list (e.g. "left arm and right leg") into the
# {parts} placeholder.
#
# Voice trick: every template keeps the verb on ``@1`` (the imitating
# doppy, always singular) and treats body parts as objects of
# prepositions. That sidesteps singular/plural verb agreement on the
# part-count side — "across @1a {parts}" reads correctly whether
# {parts} is "left arm" or "left arm, right leg, and torso".
#
# Pre-2026-04-25 emitted one line per injured part (keyed by
# ``(base_part_name, level)``) — ended up reading like a doctor's
# chart, with left+right pairs producing identical duplicate lines.
# Per-level grouping collapses the noise into one beat per
# severity tier.
_PAIN_SUMMARIES_BY_LEVEL = {
    InjuryLevels.USELESS: [
        "@1 collapses as the imitation finishes its worst across @1a {parts}.",
        "@1 howls as the imitation tears @1a {parts} apart in mirror-image of the original.",
        "Pain rips through @1 as the imitation completes — @1a {parts} now ruined and useless.",
    ],
    InjuryLevels.SEVERE: [
        "@1 staggers as deep wounds tear open across @1a {parts}.",
        "@1 howls as old wounds reopen across @1a {parts}.",
        "Blood seeps through @1a clothes as the imitation drinks the worst of @1a {parts}.",
    ],
    InjuryLevels.MODERATE: [
        "@1 doubles over as bruises bloom across @1a {parts}.",
        "@1 grunts as a chorus of borrowed aches settles into @1a {parts}.",
    ],
    InjuryLevels.MINOR: [
        "@1 rolls @1a shoulders, stiff with phantom aches in @1a {parts}.",
        "@1 winces as faint remembered pains settle in @1a {parts}.",
    ],
}


class Doppelganger(MonsterPlugin):
    # Natural form is a plain humanoid. When ``imitate`` runs, the
    # tree is rebuilt from a deep copy of the target's ``body_root``
    # — see that method for the instance-state override pattern.
    BODY_TREE = humanoid_tree()

    """Shapeshifting imitator that inherits its target's form and injuries.

    **Body part design note:** when the doppelganger imitates a target
    it deep-copies the target's body parts *including injury state*,
    then emits ONE pain summary line per non-NONE injury level present.
    Templates live in :data:`_PAIN_SUMMARIES_BY_LEVEL` (one pool per
    severity tier) and substitute a comma-joined list of part display
    names into the ``{parts}`` placeholder. Parts at the same level
    collapse into a single beat — ``"@1 collapses as the imitation
    finishes its worst across @1a left arm and right leg."``.

    Pre-2026-04-25 emitted one line per injured part keyed by
    ``(base_part, InjuryLevels)``; that read like a doctor's chart and
    rendered duplicate lines for left+right pairs. The per-level
    grouping is the narrative compression of that pattern — same
    information, one beat per severity instead of one per body part.
    """

    def __init__(self):
        super().__init__(
            name="???",
            atk="2d10",
            defense="5d4",
            dodge="5d4",
            health_max="20d10"
        )

        self.time_partition = TimePartitions.CATHEMERAL
        self.aggression = AggressionLevels.RAMPAGE
        self.image = None

        self.arrival = choice(
            [
                "A pale creature with dimly-glowing putrid-yellow eyes lopes into the area.",
                "A lumpy, misshapen humanoid slinks into view.",
            ]
        )

        self.flavor = choice(
            [
                "This creature seems to defy definition as it is quite difficult to tell what, exactly, one is looking at.",
                "The flesh of this creature seems to shift both size and shape, disturbingly devoid of description.",
            ]
        )

        self.escape = choice(
            [
                '"Oh yes, I think I\'ll keep this one for a while," the creature exclaims with a creepy squeal of '
                "delight, loping swiftly out of view!",
                f'"You\'ll never catch this one, you meddling kids," the creature shrieks as it escapes to the '
                f"{get_random_direction()}!",
            ]
        )

        self.death = choice(
            [
                "The creature lets out a final cough before dissolving into shapeless ooze.",
                "@1dc coughs blood before collapsing to the ground.",
                '"In another life, you could have been me," @1d gasps with @1a dying breath.',
            ]
        )

        self.loot["shortsword"] = 0.2
        self.loot["bandanna"] = 0.2
        self.loot["bow"] = 0.15
        self.loot["cheese_sandwich"] = 0.2
        self.loot["wallet"] = 0.25

        self.size = Size.MEDIUM
        self._scale_part_hp()

    def on_spawn(self, game) -> str:
        """Imitates a random player on spawn."""
        players = list(game.player_manager.players.values())
        if players:
            target = choice(players)
            return self.imitate(target)
        return ""

    def imitate(self, target: Creature) -> str:
        """
        Assumes a creature's form and stats.

        :param target: The creature being targeted.
        :return: A string indicating the results of the imitation.
        """

        # Never imitate another doppelganger (defensive — prevents infinite
        # mirror-of-mirror composition and nonsensical stats).
        if isinstance(target, type(self)):
            return ""

        if not isinstance(target, Player):
            return ""

        # Already wearing this player's face — no-op. Prevents the
        # per-round re-imitation spam (and stat/HP reset) when the
        # same player lands the hardest hit two rounds running. The
        # name check is sufficient: two players can't share a name
        # inside a guild.
        if self.name == target.name:
            return ""

        self.name = target.name
        # Drop the "the" article the doppelganger carries in natural
        # form. Post-imitation the doppy is posing as a named player
        # — ``@1np`` templates should render "Serena's neck", not
        # "The serena's neck" (combat/resolution.py:299 produces the
        # owner prefix via ``parse("@1npc", target)`` and inherits
        # whichever ``uses_article`` this creature carries).
        self.uses_article = False

        # Copy gender + pronouns alongside the name so post-imitation
        # narration matches the imitated player. Without this, the
        # doppelganger renders with its own default pronouns (often
        # "she/her"), producing beats like "Caels flexes her arm" for
        # a male-gendered Caels — the pain-cry templates here use
        # ``@1a`` possessive-adjective which pulls from ``pronouns``.
        # ``dict(...)`` keeps the two creatures' pronoun maps
        # independent so later updates on either don't bleed.
        self.gender = getattr(target, "gender", self.gender)
        if hasattr(target, "pronouns") and target.pronouns:
            self.pronouns = dict(target.pronouns)

        # Adopt the target's RAW base defense / dodge, not the
        # armor-boosted emergent value. The armor itself flows
        # through the deep-copied body tree below (each cloned
        # Equippable node keeps its ``placements`` dict, so
        # Phase C's ``effective_defense_for_part`` picks up the
        # worn armor as ``local_armor``). Using ``target.get_*()``
        # here would double-count armor — once in the stored base
        # and again via per-part local aggregation.
        #
        # Pre-fix behavior took ``max(self.X, target.X)`` which
        # meant a doppy that copied a tanky player once kept those
        # stats after shifting into a squishier target — unintended
        # accumulation of best-of-all-copies. Fresh-copy-on-switch
        # matches the "become this creature" contract.
        #
        # HP is NOT adopted: the doppy's body is its own (20d10 at
        # spawn). Copying ``health_max`` would trivialize the fight
        # because a 20HP player shift caps the creature at 20HP.
        # "Becoming this creature" is a surface-form effect; the
        # doppy's actual biology tanks damage at its native pool.
        self.defense = getattr(target, "defense", target.get_defense())
        # TODO(Phase C): This stores a pre-computed dodge value that
        # emergence (get_dodge) will re-process through leg functionality
        # and size modifiers, effectively double-applying those factors.
        # Phase C (player integration) should address this.
        self.dodge = getattr(target, "dodge", target.get_dodge())

        # Add the player's inventory items to the loot table with re-rolled rarity
        for item in target.inventory.all():
            quality = choice(list(Qualities))
            base_freq = quality.value["multiplier"] * 0.1
            self.loot[item.plugin] = self.loot.get(item.plugin, 0) + base_freq

        # Deep-copy the target's body tree including injury state.
        # Copying ``body_root`` (instead of each part individually)
        # preserves the parent / children wiring inside the copy so
        # reachability semantics survive the imitation — e.g. if the
        # target has a destroyed arm, the doppelganger's copy of the
        # hand under that arm stays correctly unreachable.
        if getattr(target, "body_root", None) is not None:
            self.body_root = copy.deepcopy(target.body_root)
            self.body_parts = [
                n for n in self.body_root.walk() if isinstance(n, BodyPart)
            ]
        elif hasattr(target, 'body_parts') and target.body_parts:
            # Target has a flat list but no tree (legacy shape).
            # Fall back to the flat deep-copy and clear ``body_root``
            # so the tree and flat view don't diverge — consumers
            # that consult ``body_root`` get ``None`` rather than
            # the stale natural-form humanoid tree built at init.
            self.body_root = None
            self.body_parts = [copy.deepcopy(p) for p in target.body_parts]
        else:
            # Target has no anatomy (pre-migration creature or a slime).
            # Fall back to the natural humanoid form.
            self.body_root = humanoid_tree().build()
            self.body_parts = list(self.body_root.walk())

        # Copy target's flags (e.g. "flying") as an independent set.
        self.flags = set(target.flags) if hasattr(target, 'flags') else set()

        # Copy size and core stats so emergence computes correctly.
        self.size = getattr(target, 'size', Size.MEDIUM)
        self.core_agility = getattr(target, 'core_agility', 0)
        self.core_toughness = getattr(target, 'core_toughness', 0)

        _log.debug(f"Doppelganger imitated {target.name}")

        msg = (
            "\nThe amorphous creature's body begins to shift, stretch, and squash. The form's movements are "
            f"both disturbing and fascinating, as it molds itself slowly into the likeness of {target.name}."
        )

        # Emit ONE pain summary per non-NONE injury level present —
        # parts at the same severity collapse into a single beat
        # (e.g. "left arm and right leg" → one USELESS line, not
        # two duplicate ones). Walks high-to-low severity so the
        # narrative ramps from worst to mildest.
        for line in self._pain_summary_lines():
            msg += "\n" + line

        return msg

    def _pain_summary_lines(self) -> list:
        """Group injured body parts by injury level, render one
        flavor line per level present using a level-tier template +
        the joined display-name list.

        Returns lines in descending-severity order. Empty list when
        no parts are injured (target was at full health).
        """
        by_level: dict = {}
        for part in self.body_parts:
            level = part.get_injury_level()
            if level == InjuryLevels.NONE:
                continue
            by_level.setdefault(level, []).append(part)

        # Order high-to-low so the narrative leads with the worst.
        # USELESS first reads as "the imitation finishes its worst"
        # before "and ALSO inherits these lesser aches" — descending
        # intensity beats the reverse.
        ordered_levels = (
            InjuryLevels.USELESS,
            InjuryLevels.SEVERE,
            InjuryLevels.MODERATE,
            InjuryLevels.MINOR,
        )

        lines = []
        for level in ordered_levels:
            parts = by_level.get(level)
            if not parts:
                continue
            templates = _PAIN_SUMMARIES_BY_LEVEL.get(level)
            if not templates:
                continue
            joined = self._oxford_join([p.display_name for p in parts])
            line = parse(choice(templates).format(parts=joined), self)
            lines.append(line)
        return lines

    @staticmethod
    def _oxford_join(items: list) -> str:
        """Join with Oxford comma + "and" before the last item.
        Matches ``BodyPart.gear_drop_flavor``'s join voice so the
        two narration pipelines read consistently."""
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        if len(items) == 2:
            return f"{items[0]} and {items[1]}"
        return ", ".join(items[:-1]) + f", and {items[-1]}"

    def on_combat_round(self, damage_by_player: list) -> str:
        """Imitate whoever hit the hardest this round."""
        if not damage_by_player:
            return ""

        hardest_hitter, _ = max(damage_by_player, key=lambda x: x[1])
        if isinstance(hardest_hitter, Player):
            return self.imitate(hardest_hitter)
        return ""

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        return choice(
            [
                f"@1 breaks down crying at the first affection @1s has ever known, as @2 {invocation}s @1o.",
                f"@1 sneers at @2's attempt to {invocation} @1o.",
                f"@1 mirrors @2's {invocation} back perfectly, and for a moment it's unclear who is hugging whom.",
                f"@2 reaches out to {invocation} @1, but @1a form shifts uncomfortably and @2's arms pass through thin air.",
                f"@1 accepts the {invocation} with unsettling enthusiasm, @1a features flickering between faces.",
            ]
        )
