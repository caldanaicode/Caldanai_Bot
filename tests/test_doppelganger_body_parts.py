"""Tests for Doppelganger body parts — deep-copy, injury transfer, fallback,
pain-cry emission on imitation, and the never-imitate-doppelganger guard."""

import copy
from unittest.mock import MagicMock

import pytest

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.body_parts.arm import ArmPlugin
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.monsters.doppelganger import Doppelganger
from caldanai.lib.rpg.creatures.monsters.goblin import Goblin
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels,
    InjuryLevels,
    Size,
    TimePartitions,
)
from caldanai.lib.rpg.creatures.monsters.doppelganger import _PAIN_CRIES


@pytest.fixture(autouse=True)
def _load_plugins():
    """Ensure body-part and monster plugin registries are populated."""
    BodyPartPlugin.load_plugins()
    MonsterPlugin.load_plugins()
    yield


def _make_player(name="TestPlayer", defense=10, dodge=8, health=20, health_max=20):
    """Build a mock Player with standard stats and no body_parts by default."""
    player = MagicMock(spec=Player)
    player.name = name
    player.get_defense.return_value = defense
    player.get_dodge.return_value = dodge
    player.get_health_max.return_value = health_max
    player.health = health
    player.health_max = health_max
    player.inventory = MagicMock()
    player.inventory.all.return_value = ()
    # Default: no body parts (pre-migration Player)
    player.body_parts = []
    player.flags = set()
    player.__class__ = Player
    return player


def _make_player_with_parts(name="ArmedPlayer", **kwargs):
    """Build a mock Player that HAS body parts (simulates a migrated player)."""
    player = _make_player(name, **kwargs)
    player.body_parts = [
        BodyPart.make("head", name="head"),
        BodyPart.make("torso", name="torso"),
        BodyPart.make("arm", name="arm.left"),
        BodyPart.make("arm", name="arm.right"),
        BodyPart.make("leg", name="leg.left"),
        BodyPart.make("leg", name="leg.right"),
    ]
    return player


# ---------------------------------------------------------------------------
# 1. Default humanoid body parts before imitation
# ---------------------------------------------------------------------------


class TestDoppelgangerDefaultBodyParts:
    def test_fresh_doppelganger_has_six_parts(self):
        d = Doppelganger()
        assert len(d.body_parts) == 6

    def test_has_one_head(self):
        d = Doppelganger()
        heads = [p for p in d.body_parts if isinstance(p, HeadPlugin)]
        assert len(heads) == 1

    def test_has_one_torso(self):
        d = Doppelganger()
        torsos = [p for p in d.body_parts if isinstance(p, TorsoPlugin)]
        assert len(torsos) == 1

    def test_has_two_arms(self):
        d = Doppelganger()
        arms = [p for p in d.body_parts if isinstance(p, ArmPlugin)]
        assert len(arms) == 2

    def test_has_two_legs(self):
        d = Doppelganger()
        legs = [p for p in d.body_parts if isinstance(p, LegPlugin)]
        assert len(legs) == 2


# ---------------------------------------------------------------------------
# 2. Imitate target WITH body parts
# ---------------------------------------------------------------------------


class TestDoppelgangerImitateWithParts:
    def test_part_count_matches_target(self):
        d = Doppelganger()
        target = _make_player_with_parts("Caels")
        d.imitate(target)
        assert len(d.body_parts) == len(target.body_parts)

    def test_parts_are_deep_copies(self):
        """Mutating the target's arm after imitation must NOT affect the
        doppelganger's arm — they are independent deep copies."""
        d = Doppelganger()
        target = _make_player_with_parts("Caels")
        d.imitate(target)

        # Damage the target's first arm
        target_arm = next(
            p for p in target.body_parts if isinstance(p, ArmPlugin)
        )
        target_arm.apply_damage(999)
        assert target_arm.health == 0

        # Doppelganger's corresponding arm is untouched
        doppel_arm = next(
            p for p in d.body_parts if isinstance(p, ArmPlugin)
        )
        assert doppel_arm.health > 0

    def test_reverse_isolation(self):
        """Mutating the doppelganger's part must NOT affect the target's."""
        d = Doppelganger()
        target = _make_player_with_parts("Caels")
        d.imitate(target)

        doppel_leg = next(
            p for p in d.body_parts if isinstance(p, LegPlugin)
        )
        doppel_leg.apply_damage(999)

        target_leg = next(
            p for p in target.body_parts if isinstance(p, LegPlugin)
        )
        assert target_leg.health > 0


# ---------------------------------------------------------------------------
# 3. Imitate with injured parts — injury state transfers
# ---------------------------------------------------------------------------


class TestDoppelgangerImitateWithInjuredParts:
    def test_injury_state_transferred(self):
        """Target has a SEVERE leg.  After imitation the doppelganger's
        corresponding leg is also SEVERE."""
        d = Doppelganger()
        target = _make_player_with_parts("Wounded")

        # Injure the target's left leg to SEVERE (health < 30% of max).
        # Force a deterministic health_max first to avoid dice-roll edge
        # cases where int(health_max * 0.10) rounds to 0 (USELESS).
        target_leg = next(
            p for p in target.body_parts if p.name == "leg.left"
        )
        target_leg.health_max = 20
        target_leg.health = 2  # 2/20 = 10% => SEVERE band (0 < pct < 0.30)
        assert target_leg.get_injury_level() == InjuryLevels.SEVERE

        d.imitate(target)

        doppel_leg = next(
            p for p in d.body_parts if p.name == "leg.left"
        )
        assert doppel_leg.get_injury_level() == InjuryLevels.SEVERE
        assert doppel_leg.health == 2

    def test_deep_copy_isolation_after_injury_transfer(self):
        """After copying injured parts, further mutation of the doppelganger's
        part must not affect the target's part."""
        d = Doppelganger()
        target = _make_player_with_parts("Wounded")

        target_leg = next(
            p for p in target.body_parts if p.name == "leg.left"
        )
        target_leg.health_max = 20
        target_leg.health = 2  # 2/20 = 10% => SEVERE

        d.imitate(target)

        doppel_leg = next(
            p for p in d.body_parts if p.name == "leg.left"
        )
        # Destroy the doppelganger's leg entirely
        doppel_leg.apply_damage(9999)
        assert doppel_leg.health == 0

        # Target's leg is unchanged
        assert target_leg.health == int(target_leg.health_max * 0.10)


# ---------------------------------------------------------------------------
# 4. Imitate target with NO parts — humanoid fallback
# ---------------------------------------------------------------------------


class TestDoppelgangerImitateNoPartsTarget:
    def test_fallback_to_humanoid(self):
        """When the target has no body parts, the doppelganger gets a
        fresh default humanoid layout."""
        d = Doppelganger()
        target = _make_player("NoParts")
        target.body_parts = []

        d.imitate(target)

        assert len(d.body_parts) == 6
        heads = [p for p in d.body_parts if isinstance(p, HeadPlugin)]
        assert len(heads) == 1
        torsos = [p for p in d.body_parts if isinstance(p, TorsoPlugin)]
        assert len(torsos) == 1
        arms = [p for p in d.body_parts if isinstance(p, ArmPlugin)]
        assert len(arms) == 2
        legs = [p for p in d.body_parts if isinstance(p, LegPlugin)]
        assert len(legs) == 2

    def test_fallback_parts_use_codified_names(self):
        """Fallback parts should use the codified dot-notation names
        regardless of the imitated target's identity."""
        d = Doppelganger()
        target = _make_player("Foxglove")
        target.body_parts = []

        d.imitate(target)

        head = next(p for p in d.body_parts if isinstance(p, HeadPlugin))
        assert head.name == "head"


# ---------------------------------------------------------------------------
# 5. Never imitate another doppelganger
# ---------------------------------------------------------------------------


class TestDoppelgangerNeverImitatesSelf:
    def test_on_combat_round_skips_doppelganger_target(self):
        """If the hardest hitter is another doppelganger, re-imitation
        must be skipped — body parts must not change."""
        d = Doppelganger()
        original_parts = d.body_parts[:]

        other_doppel = Doppelganger()
        # Pretend the other doppelganger is a Player for the isinstance
        # check in on_combat_round — but the guard should still fire
        # because the target is a Doppelganger.
        # We call imitate directly to test the guard.
        # First, make it look like a Player so the existing isinstance
        # check doesn't reject it before the doppelganger guard fires.
        # Actually, the guard should be BEFORE the Player isinstance check
        # or alongside it. Let's test via on_combat_round which checks
        # isinstance(hardest_hitter, Player) — the other doppelganger
        # won't pass that check either, so the guard is defense-in-depth.
        # Test the direct imitate path instead:
        result = d.imitate(other_doppel)

        assert result == ""
        # Parts unchanged
        assert len(d.body_parts) == len(original_parts)

    def test_subclass_also_blocked(self):
        """A subclass of Doppelganger should also be blocked."""

        class SuperDoppelganger(Doppelganger):
            pass

        d = Doppelganger()
        sub = SuperDoppelganger()

        result = d.imitate(sub)
        assert result == ""


# ---------------------------------------------------------------------------
# 6. Flags copied from target
# ---------------------------------------------------------------------------


class TestDoppelgangerFlagsCopied:
    def test_flags_copied(self):
        d = Doppelganger()
        target = _make_player("FlyBoy")
        target.flags = {"flying"}

        d.imitate(target)

        assert "flying" in d.flags

    def test_flags_are_independent_copy(self):
        """Mutating target's flags after imitation must not affect doppelganger."""
        d = Doppelganger()
        target = _make_player("FlyBoy")
        target.flags = {"flying"}

        d.imitate(target)

        target.flags.add("invisible")
        assert "invisible" not in d.flags

    def test_flags_reset_on_no_flags_target(self):
        """If the target has no flags attr, doppelganger gets empty set."""
        d = Doppelganger()
        d.flags = {"leftover"}
        target = _make_player("NoFlags")
        # Remove flags attribute to test the hasattr guard
        del target.flags

        d.imitate(target)

        assert d.flags == set()


# ---------------------------------------------------------------------------
# 6b. Gender + pronouns copied from target
# ---------------------------------------------------------------------------


class TestDoppelgangerGenderAndPronounsCopied:
    """Imitation must copy the target's gender and pronouns so
    post-imitation narration — especially the per-part pain cries
    that use ``@1a`` possessive-adjective — reads with the
    imitated player's pronouns, not the doppelganger's default.
    Reported live 2026-04-19 ("Caels winces… behind her eyes"
    when Caels is male)."""

    def _male_target(self, name="Caels"):
        from caldanai.lib.rpg.helpers.enums import Pronouns
        target = _make_player(name)
        target.gender = "male"
        target.pronouns = {
            Pronouns.SUBJECTIVE:  "he",
            Pronouns.OBJECTIVE:   "him",
            Pronouns.POSSESSIVE:  "his",
            Pronouns.REFLEXIVE:   "himself",
        }
        return target

    def test_gender_copied_from_target(self):
        d = Doppelganger()
        d.gender = "female"  # pre-imitation default
        target = self._male_target()

        d.imitate(target)

        assert d.gender == "male"

    def test_pronouns_copied_from_target(self):
        from caldanai.lib.rpg.helpers.enums import Pronouns
        d = Doppelganger()
        target = self._male_target()

        d.imitate(target)

        assert d.pronouns[Pronouns.SUBJECTIVE] == "he"
        assert d.pronouns[Pronouns.OBJECTIVE] == "him"
        assert d.pronouns[Pronouns.POSSESSIVE] == "his"
        assert d.pronouns[Pronouns.REFLEXIVE] == "himself"

    def test_pronouns_are_independent_copy(self):
        """Mutating the target's pronouns after imitation must not
        affect the doppelganger — and vice versa."""
        from caldanai.lib.rpg.helpers.enums import Pronouns
        d = Doppelganger()
        target = self._male_target()

        d.imitate(target)
        target.pronouns[Pronouns.SUBJECTIVE] = "xe"

        assert d.pronouns[Pronouns.SUBJECTIVE] == "he"

    def test_missing_pronouns_does_not_crash(self):
        """Target lacking a ``pronouns`` attr (unlikely but defensive)
        must not take down imitation — the doppelganger keeps its
        own default pronouns."""
        d = Doppelganger()
        target = _make_player("Mystery")
        if hasattr(target, "pronouns"):
            del target.pronouns

        # Should not raise.
        d.imitate(target)


# ---------------------------------------------------------------------------
# 7. Sanity — existing doppelganger fields unchanged
# ---------------------------------------------------------------------------


class TestDoppelgangerSanityUnchanged:
    def test_default_name(self):
        d = Doppelganger()
        assert d.name == "???"

    def test_base_attack_dice(self):
        d = Doppelganger()
        assert d.attack == "2d10"

    def test_aggression(self):
        d = Doppelganger()
        assert d.aggression == AggressionLevels.RAMPAGE

    def test_time_partition(self):
        d = Doppelganger()
        assert d.time_partition == TimePartitions.CATHEMERAL

    def test_loot_table_present(self):
        d = Doppelganger()
        assert "shortsword" in d.loot
        assert "bandanna" in d.loot
        assert "bow" in d.loot

    def test_imitate_still_copies_name(self):
        d = Doppelganger()
        target = _make_player("Caels")
        d.imitate(target)
        assert d.name == "Caels"

    def test_imitate_still_copies_stats(self):
        d = Doppelganger()
        target = _make_player(defense=999, dodge=999)
        d.imitate(target)
        assert d.defense == 999
        assert d.dodge == 999


# ---------------------------------------------------------------------------
# 8. Backwards compatibility — defense/dodge/legacy damage
# ---------------------------------------------------------------------------


class TestDoppelgangerBackwardsCompat:
    def test_get_defense_at_full_health(self):
        d = Doppelganger()
        assert d.get_defense() == d.defense

    def test_get_dodge_at_full_health(self):
        d = Doppelganger()
        assert d.get_dodge() == d.dodge

    def test_legacy_apply_damage(self):
        """apply_damage without target_part still hits main HP."""
        d = Doppelganger()
        d.health_max = 50
        d.health = 50
        d.apply_damage(10)
        assert d.health == 40

    def test_legacy_damage_does_not_touch_parts(self):
        d = Doppelganger()
        d.health_max = 50
        d.health = 50
        part_hps_before = [(p.name, p.health) for p in d.body_parts]
        d.apply_damage(10)
        part_hps_after = [(p.name, p.health) for p in d.body_parts]
        assert part_hps_before == part_hps_after


# ---------------------------------------------------------------------------
# 9. Pain cries on imitation
# ---------------------------------------------------------------------------


class TestDoppelgangerPainCries:
    def test_no_pain_cries_when_target_uninjured(self):
        """Imitating a fully healthy target produces no pain-cry lines."""
        d = Doppelganger()
        target = _make_player_with_parts("Healthy")
        result = d.imitate(target)
        # The base imitation message is always present; pain cries would
        # appear as extra lines after it.
        lines = result.strip().split("\n")
        assert len(lines) == 1

    def test_pain_cry_emitted_for_injured_part(self):
        """Imitating a target with an injured leg emits a pain cry."""
        d = Doppelganger()
        target = _make_player_with_parts("Wounded")
        leg = next(p for p in target.body_parts if p.name == "leg.left")
        leg.health_max = 20
        leg.health = 2  # SEVERE
        result = d.imitate(target)
        assert "leg" in result.lower() or "thigh" in result.lower() or "bone" in result.lower()

    def test_multiple_injured_parts_produce_multiple_cries(self):
        """Each injured part gets its own pain cry line."""
        d = Doppelganger()
        target = _make_player_with_parts("Battered")
        for part in target.body_parts:
            part.health_max = 20
            part.health = 2  # SEVERE for all
        result = d.imitate(target)
        lines = result.strip().split("\n")
        # 1 base message + 6 pain cries (head, torso, 2 arms, 2 legs)
        assert len(lines) == 7

    def test_no_cry_for_none_injury_level(self):
        """Parts at full health (NONE) produce no cry."""
        d = Doppelganger()
        target = _make_player_with_parts("Fresh")
        # All parts at full health by default
        result = d.imitate(target)
        lines = result.strip().split("\n")
        assert len(lines) == 1

    def test_get_pain_cry_uses_base_name(self):
        """``_get_pain_cry`` strips the dot-qualifier to find the base part
        name, so ``"arm.left"`` resolves to ``"arm"``."""
        d = Doppelganger()
        arm = BodyPart.make("arm", name="arm.left", health_max=20)
        arm.health = 2  # SEVERE
        cry = d._get_pain_cry(arm, InjuryLevels.SEVERE)
        assert cry != ""
        assert cry == _PAIN_CRIES[("arm", InjuryLevels.SEVERE)]

    def test_get_pain_cry_returns_empty_for_unknown_part(self):
        """Parts not in the lookup (e.g. toe, dragon_head) return empty."""
        d = Doppelganger()
        toe = BodyPart.make("toe")
        assert d._get_pain_cry(toe, InjuryLevels.USELESS) == ""

    def test_get_pain_cry_returns_empty_for_none_level(self):
        """NONE injury level always returns empty."""
        d = Doppelganger()
        arm = BodyPart.make("arm", health_max=20)
        assert d._get_pain_cry(arm, InjuryLevels.NONE) == ""

    def test_pain_cries_table_covers_all_standard_parts(self):
        """Every standard part type (head, torso, arm, leg, wing, tail, eye)
        has entries for MINOR through USELESS."""
        expected_parts = {"head", "torso", "arm", "leg", "wing", "tail", "eye"}
        injury_levels = {
            InjuryLevels.MINOR,
            InjuryLevels.MODERATE,
            InjuryLevels.SEVERE,
            InjuryLevels.USELESS,
        }
        for part_name in expected_parts:
            for level in injury_levels:
                cry = _PAIN_CRIES.get((part_name, level), "")
                assert cry != "", f"missing pain cry for ({part_name}, {level})"

    def test_pain_cries_are_distinct_per_part_and_level(self):
        """No two entries in the pain cry table share the same text."""
        values = list(_PAIN_CRIES.values())
        assert len(values) == len(set(values)), "duplicate pain cry text found"


# ---------------------------------------------------------------------------
# 10. Size and core stats copied on imitation
# ---------------------------------------------------------------------------


class TestDoppelgangerCopiesSizeAndCoreStats:
    def test_size_copied_from_target(self):
        d = Doppelganger()
        target = _make_player("BigGuy")
        target.size = Size.LARGE
        d.imitate(target)
        assert d.size == Size.LARGE

    def test_core_agility_copied_from_target(self):
        d = Doppelganger()
        target = _make_player("Nimble")
        target.core_agility = 5
        d.imitate(target)
        assert d.core_agility == 5

    def test_core_toughness_copied_from_target(self):
        d = Doppelganger()
        target = _make_player("Tough")
        target.core_toughness = 3
        d.imitate(target)
        assert d.core_toughness == 3

    def test_defaults_when_target_lacks_attributes(self):
        """If target lacks size/core stats, doppelganger gets safe defaults."""
        d = Doppelganger()
        d.size = Size.LARGE  # pre-existing non-default
        d.core_agility = 10
        d.core_toughness = 10
        target = _make_player("Plain")
        # Remove the attributes to test getattr fallback
        del target.size
        del target.core_agility
        del target.core_toughness
        d.imitate(target)
        assert d.size == Size.MEDIUM
        assert d.core_agility == 0
        assert d.core_toughness == 0
