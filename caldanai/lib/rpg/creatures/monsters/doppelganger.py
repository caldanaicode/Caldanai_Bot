import copy
from random import choice

from caldanai.lib.rpg import get_random_direction, Player
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.enums import AggressionLevels, InjuryLevels, Size, TimePartitions, Qualities
from caldanai.lib.rpg.helpers.parser import parse
from caldanai.lib.rpg.creatures import Creature
from caldanai.logger import get_logger


_log = get_logger(__name__)


# Pain cries the doppelganger emits when it imitates a target and inherits
# injured body parts.  Keyed by (base_part_name, InjuryLevels).  The base
# part name is the portion before the dot-qualifier (e.g. "arm" from
# "arm.left").  Parts not listed here (toe, dragon_head, hydra_head, etc.)
# silently produce no cry.
_PAIN_CRIES = {
    ("head", InjuryLevels.MINOR): (
        "@1 winces as a dull ache throbs behind @1a eyes out of nowhere."
    ),
    ("head", InjuryLevels.MODERATE): (
        "@1's head snaps sideways as an invisible blow lands; "
        "blood trickles from @1a nose."
    ),
    ("head", InjuryLevels.SEVERE): (
        "@1 clutches @1a temples as a deep gash opens across "
        "@1a scalp of its own accord."
    ),
    ("head", InjuryLevels.USELESS): (
        "@1's head jerks violently as the imitation completes "
        "itself in the worst possible way."
    ),
    ("torso", InjuryLevels.MINOR): (
        "@1 grunts as an unseen blow presses against @1a ribs."
    ),
    ("torso", InjuryLevels.MODERATE): (
        "@1 doubles over, coughing as bruises bloom across @1a "
        "chest from nowhere."
    ),
    ("torso", InjuryLevels.SEVERE): (
        "@1 staggers, hands pressed to @1a torso as blood seeps "
        "through @1a clothes of its own accord."
    ),
    ("torso", InjuryLevels.USELESS): (
        "@1 collapses, @1a chest caving inward as the "
        "imitation's wound finishes materializing."
    ),
    ("arm", InjuryLevels.MINOR): (
        "@1 flexes @1a arm and winces at an ache that wasn't "
        "there moments ago."
    ),
    ("arm", InjuryLevels.MODERATE): (
        "@1's arm twists at an unnatural angle as sinews pop "
        "beneath @1a skin."
    ),
    ("arm", InjuryLevels.SEVERE): (
        "@1 howls as @1a arm hangs limp, bone pressing visibly "
        "against skin."
    ),
    ("arm", InjuryLevels.USELESS): (
        "@1's arm crumples grotesquely, fingers curling into a "
        "useless claw as the imitation completes."
    ),
    ("leg", InjuryLevels.MINOR): (
        "@1 favors one leg as a phantom ache shoots up @1a "
        "thigh."
    ),
    ("leg", InjuryLevels.MODERATE): (
        "@1 staggers slightly, knee buckling beneath @1a own "
        "weight."
    ),
    ("leg", InjuryLevels.SEVERE): (
        "@1 cries out as @1a leg twists at an impossible "
        "angle, bone pressing through the skin."
    ),
    ("leg", InjuryLevels.USELESS): (
        "@1's leg goes limp, dragging uselessly behind as the "
        "imitation's crippling finishes."
    ),
    ("wing", InjuryLevels.MINOR): (
        "@1's shoulder blades twitch as phantom feathers ripple "
        "beneath @1a skin."
    ),
    ("wing", InjuryLevels.MODERATE): (
        "@1 hunches forward, wet cracking sounds echoing from "
        "@1a back as something tries to unfold."
    ),
    ("wing", InjuryLevels.SEVERE): (
        "@1 howls as a great torn wing rips free of @1a "
        "shoulder, trailing blood that was never there."
    ),
    ("wing", InjuryLevels.USELESS): (
        "@1's wing crumples into a twisted ruin of bone and "
        "membrane as the imitation completes itself."
    ),
    ("tail", InjuryLevels.MINOR): (
        "@1 flicks @1a tail and winces at an unexpected twinge."
    ),
    ("tail", InjuryLevels.MODERATE): (
        "@1's tail lashes erratically as unseen damage works "
        "its way down the vertebrae."
    ),
    ("tail", InjuryLevels.SEVERE): (
        "@1 yelps as @1a tail bends at a sickening angle, "
        "blood matting the fur."
    ),
    ("tail", InjuryLevels.USELESS): (
        "@1's tail drops limp and still, a final twitch "
        "betraying its uselessness as the imitation sets."
    ),
    ("eye", InjuryLevels.MINOR): (
        "@1 blinks rapidly as one eye clouds over with "
        "unexplained tears."
    ),
    ("eye", InjuryLevels.MODERATE): (
        "@1 squints hard, @1a eye going bloodshot and swollen "
        "in an instant."
    ),
    ("eye", InjuryLevels.SEVERE): (
        "@1 claps @1a hand to @1a face as the eye beneath it "
        "splits open without warning."
    ),
    ("eye", InjuryLevels.USELESS): (
        "@1's eye sinks deep into its socket, pupil blown "
        "black as the imitation blinds it."
    ),
}


class Doppelganger(MonsterPlugin):
    """Shapeshifting imitator that inherits its target's form and injuries.

    **Body part design note:** when the doppelganger imitates a target
    it deep-copies the target's body parts *including injury state*,
    then emits a per-part "pain cry" for each inherited injury via
    :data:`_PAIN_CRIES`. There is one flavor string per
    ``(base_part, InjuryLevels)`` pair across every base part in the
    plugin set (head, torso, arm, leg, wing, tail, eye), escalating
    from a mysterious ache at MINOR up through a visibly crippling
    wound at USELESS. This is the reason base-part docstrings mention
    "pain cries" as a design expectation: it's a doppelganger feature
    implemented here on the monster, not on the parts themselves.
    Parts not keyed in :data:`_PAIN_CRIES` (toe, dragon_head,
    hydra_head, etc.) silently produce no cry.
    """

    def __init__(self):
        super().__init__(
            name="???",
            atk="2d10",
            defense="5d4",
            dodge="5d4",
            health_max="20d6"
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

        self.body_parts = BodyPart.humanoid()

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

        self.name = target.name

        # Copy stats, taking the better of current vs target
        defense = target.get_defense()
        dodge = target.get_dodge()
        health_max = target.get_health_max()
        self.defense = max(self.defense, defense)
        # TODO(Phase C): This stores a pre-computed dodge value that
        # emergence (get_dodge) will re-process through leg functionality
        # and size modifiers, effectively double-applying those factors.
        # Phase C (player integration) should address this.
        self.dodge = max(self.dodge, dodge)
        # Take the min of current HP vs the new max so we don't heal
        new_max = max(self.health_max, health_max)
        self.health = min(self.health, new_max)
        self.health_max = new_max

        # Add the player's inventory items to the loot table with re-rolled rarity
        for item in target.inventory.all():
            quality = choice(list(Qualities))
            base_freq = quality.value["multiplier"] * 0.1
            self.loot[item.plugin] = self.loot.get(item.plugin, 0) + base_freq

        # Deep-copy the target's body parts including injury state.
        if hasattr(target, 'body_parts') and target.body_parts:
            self.body_parts = [copy.deepcopy(p) for p in target.body_parts]
        else:
            # Fallback: target has no parts (pre-migration creature or a slime).
            self.body_parts = BodyPart.humanoid()

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

        # Emit per-part pain cries for any inherited injuries.
        for part in self.body_parts:
            level = part.get_injury_level()
            if level != InjuryLevels.NONE:
                cry = self._get_pain_cry(part, level)
                if cry:
                    msg += "\n" + parse(cry, self)

        return msg

    @staticmethod
    def _get_pain_cry(part: BodyPart, level: InjuryLevels) -> str:
        """Look up a pain cry for a body part at a given injury level.

        The key is the base part name (before the dot-qualifier), so
        ``"arm.left"`` and ``"arm.right"`` both resolve to ``"arm"``.
        Returns an empty string for unknown parts or NONE level.
        """
        base = part.name.split(".")[0]
        return _PAIN_CRIES.get((base, level), "")

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
