"""Resolver depth-walk integration tests.

Exercises :meth:`Creature._walk_to_aim` via the public
:meth:`Creature.resolve_attack` entry point — walk stalling,
big-vs-small roll-up, miss-below-every-threshold, and crit /
fumble short-circuits. The helpers themselves have unit tests
in :mod:`tests.test_effective_stats`; this file tests how they
feed into combat resolution.
"""

from unittest import TestCase
from unittest.mock import MagicMock

from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
from caldanai.lib.rpg.creatures import effective_dodge_for_part
from caldanai.lib.rpg.creatures.monsters.dragon import Dragon
from caldanai.lib.rpg.creatures.monsters.pixie import Pixie
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.dice import Dice
from caldanai.lib.rpg.helpers.enums import DamageTypes, Reach
from caldanai.lib.rpg.helpers.roll_data import AttackRoll, DamageRoll


def _fresh_player() -> Player:
    p = Player(
        pid=1, gid=1, uid=1,
        health=20, health_max=20,
        defense=3, dodge=5,
    )
    p.member = MagicMock()
    p.member.id = 1
    return p


def _source(reach=Reach.MELEE) -> NaturalAttackSource:
    return NaturalAttackSource(
        atk="1d6", dmg_type=DamageTypes.PIERCING,
        label="sting", skill="natural", reach=reach,
    )


def _rolls(atk_value: int, dmg_value: int = 4):
    """Build deterministic AttackRoll / DamageRoll instances by
    constructing, then overriding ``.result`` plus the fumble /
    critical flags (which the constructor sets from the random
    die and CombinedRoll respects even if result is above dodge).
    Tests want the single-knob ``atk_value`` to control hit/miss
    so we pin the flags explicitly."""
    atk = AttackRoll(skill_bonus=0)
    atk.result = atk_value
    atk.isCritical = False
    atk.isFumble = False
    dmg = DamageRoll(Dice(1, 6), 0, 0)
    dmg.result = dmg_value
    return atk, dmg


class ResolverDepthWalkTests(TestCase):
    def test_full_hit_at_aim_when_roll_beats_aim_dodge(self):
        """Roll high enough to beat the eye's effective dodge at
        the deepest depth. Full hit lands at eye."""
        player = _fresh_player()
        pixie = Pixie()
        eye = player.get_part("eye.left")
        src = _source()
        eye_dodge = effective_dodge_for_part(player, eye, pixie, src)
        atk, dmg = _rolls(atk_value=eye_dodge + 5, dmg_value=4)

        result = player.resolve_attack(pixie, src, atk, dmg, target_part=eye)

        self.assertIs(result.target_part, eye)
        self.assertFalse(result.combined.isMiss)

    def test_same_size_stall_becomes_clean_miss(self):
        """Attacker aims at eye, roll beats torso but not head.
        Same-size (player vs player) → MISS, not roll-up."""
        player_attacker = _fresh_player()
        player_defender = _fresh_player()
        player_defender.name = "Defender"
        eye = player_defender.get_part("eye.left")
        torso = player_defender.get_part("torso")
        head = player_defender.get_part("head")
        src = _source()
        torso_dodge = effective_dodge_for_part(
            player_defender, torso, player_attacker, src,
        )
        head_dodge = effective_dodge_for_part(
            player_defender, head, player_attacker, src,
        )
        # Roll between torso and head dodges — beats torso, fails
        # at head, stalls before reaching eye.
        atk_value = (torso_dodge + head_dodge) // 2
        self.assertGreaterEqual(atk_value, torso_dodge)
        self.assertLess(atk_value, head_dodge)
        atk, dmg = _rolls(atk_value=atk_value, dmg_value=4)

        result = player_defender.resolve_attack(
            player_attacker, src, atk, dmg, target_part=eye,
        )

        # Same-size stall → miss. Aim is preserved on the result
        # so narration can still reference "swung at eye."
        self.assertTrue(result.combined.isMiss)
        self.assertEqual(result.damage, 0)

    def test_big_vs_small_stall_rolls_up(self):
        """Dragon (HUGE) vs pixie (TINY) ratio ~ 3.0 clears
        _REGION_COLLAPSE_THRESHOLD (2.0). An attack aimed at
        pixie's arm that stalls at torso rolls up to the torso
        instead of cleanly missing."""
        dragon = Dragon()
        pixie = Pixie()
        # Pixie's BODY_TREE has no eyes, so use arm as the aim.
        arm = pixie.get_part("arm.left")
        torso = pixie.get_part("torso")
        src = _source()
        torso_dodge = effective_dodge_for_part(pixie, torso, dragon, src)
        arm_dodge = effective_dodge_for_part(pixie, arm, dragon, src)
        atk_value = (torso_dodge + arm_dodge) // 2
        if atk_value < torso_dodge:
            atk_value = torso_dodge
        if atk_value >= arm_dodge:
            atk_value = arm_dodge - 1
        atk, dmg = _rolls(atk_value=atk_value, dmg_value=4)

        result = pixie.resolve_attack(dragon, src, atk, dmg, target_part=arm)

        # Big-vs-small rolls up → landed on torso, not arm.
        self.assertFalse(result.combined.isMiss)
        self.assertIs(result.target_part, torso)

    def test_miss_below_every_threshold(self):
        """Roll low enough that even the torso threshold isn't
        beaten. Resolver reports clean miss regardless of size
        ratio."""
        player = _fresh_player()
        pixie = Pixie()
        arm = player.get_part("arm.left")
        src = _source()
        atk, dmg = _rolls(atk_value=-5, dmg_value=4)

        result = player.resolve_attack(pixie, src, atk, dmg, target_part=arm)

        self.assertTrue(result.combined.isMiss)
        self.assertEqual(result.damage, 0)

    def test_crit_auto_lands_at_aim_even_when_walk_would_stall(self):
        """Crit rolls always hit at the aim point regardless of
        depth thresholds. Without the short-circuit, a crit whose
        numeric result falls below head-depth dodge would stall
        mid-walk and (same-size path) return ``None`` — turning
        the auto-hit into a guaranteed miss."""
        player_attacker = _fresh_player()
        player_defender = _fresh_player()
        player_defender.name = "Defender"
        eye = player_defender.get_part("eye.left")
        head = player_defender.get_part("head")
        src = _source()
        head_dodge = effective_dodge_for_part(
            player_defender, head, player_attacker, src,
        )
        atk, dmg = _rolls(atk_value=head_dodge - 1, dmg_value=4)
        atk.isCritical = True

        result = player_defender.resolve_attack(
            player_attacker, src, atk, dmg, target_part=eye,
        )

        self.assertFalse(result.combined.isMiss)
        self.assertIs(result.target_part, eye)

    def test_fumble_auto_misses_even_when_walk_would_land(self):
        """Fumble rolls always miss. Even when the numeric result
        beats every depth threshold in the walk, the walk should
        short-circuit and hand back the aim as reported target so
        narration can still reference "swung at eye." """
        player_attacker = _fresh_player()
        player_defender = _fresh_player()
        player_defender.name = "Defender"
        eye = player_defender.get_part("eye.left")
        src = _source()
        eye_dodge = effective_dodge_for_part(
            player_defender, eye, player_attacker, src,
        )
        atk, dmg = _rolls(atk_value=eye_dodge + 10, dmg_value=4)
        atk.isFumble = True

        result = player_defender.resolve_attack(
            player_attacker, src, atk, dmg, target_part=eye,
        )

        self.assertTrue(result.combined.isMiss)
        self.assertEqual(result.damage, 0)
        self.assertIs(result.target_part, eye)

    def test_body_less_creature_falls_back_to_base_stats(self):
        """Spirit has no body parts; resolver uses creature-wide
        dodge / defense directly instead of walking. Pins the
        body-less fallback branch."""
        from caldanai.lib.rpg.creatures.monsters.spirit import Spirit
        spirit = Spirit()
        player = _fresh_player()
        src = _source()
        atk, dmg = _rolls(atk_value=spirit.get_dodge() + 10, dmg_value=4)

        result = spirit.resolve_attack(player, src, atk, dmg, target_part=None)

        self.assertFalse(result.combined.isMiss)
        self.assertEqual(result.dodge, spirit.get_dodge())
