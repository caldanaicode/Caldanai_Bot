"""Smoke / invariant tests for the monster batch added 2026-04-13:
skeleton, cyclops, minotaur, pixie, werewolf, golem, spirit.

These aren't deep mechanical tests — existing body-parts / emergence /
combat tests cover the systems. They just verify each new monster:

- constructs without raising
- exposes the expected anatomy shape
- has the damage-type traits its flavor implies
- honors the target-preference hook where declared

The goal is morning-review confidence that nothing silently broke,
plus a paper trail of intended behavior for future changes.
"""

from unittest.mock import patch, MagicMock

import pytest

from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
from caldanai.lib.rpg.creatures.monsters.skeleton import Skeleton
from caldanai.lib.rpg.creatures.monsters.cyclops import Cyclops
from caldanai.lib.rpg.creatures.monsters.minotaur import Minotaur
from caldanai.lib.rpg.creatures.monsters.pixie import Pixie
from caldanai.lib.rpg.creatures.monsters.werewolf import Werewolf
from caldanai.lib.rpg.creatures.monsters.golem import Golem
from caldanai.lib.rpg.creatures.monsters.spirit import Spirit
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
from caldanai.lib.rpg.creatures.body_parts.eye import EyePlugin
from caldanai.lib.rpg.creatures.body_parts.wing import WingPlugin
from caldanai.lib.rpg.helpers.enums import DamageTypes, InjuryLevels, Size


def _part_names(monster):
    return {p.name for p in monster.body_parts}


# ---------------------------------------------------------------------------
# Skeleton
# ---------------------------------------------------------------------------


class TestSkeleton:
    def test_constructs(self):
        s = Skeleton()
        assert s.name == "skeleton"
        assert s.size == Size.MEDIUM

    def test_anatomy_is_eyeless_humanoid(self):
        """Empty sockets are the point — no eye parts."""
        s = Skeleton()
        names = _part_names(s)
        assert "head" in names
        assert "torso" in names
        assert not any(n.startswith("eye") for n in names)

    def test_brittle_bones_vulnerable_to_bludgeoning(self):
        s = Skeleton()
        assert s.get_trait_multiplier(DamageTypes.BLUDGEONING) == 2.0

    def test_holy_vulnerable(self):
        s = Skeleton()
        assert s.get_trait_multiplier(DamageTypes.LIGHT) == 2.0

    def test_immune_to_dark(self):
        s = Skeleton()
        assert s.get_trait_multiplier(DamageTypes.DARK) == 0.0

    def test_hit_narration_per_damage_type(self):
        """``HIT_NARRATIONS`` lookup surfaces the right flavor line
        for each damage type via ``get_hit_narration``. The base
        ``Creature`` machinery handles the dispatch — subclasses
        just declare the dict."""
        from caldanai.lib.rpg.combat.attack_result import AttackResult
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        from caldanai.lib.rpg.helpers.roll_data import (
            AttackRoll, DamageRoll, CombinedRoll,
        )
        from caldanai.lib.rpg.helpers.dice import Dice
        from caldanai.lib.rpg.creatures import Creature

        s = Skeleton()
        attacker = Creature(
            name="hero", atk="1d4", defense=0, dodge=5,
            health_max=20, health=20,
        )

        def _hit_with(dmg_type):
            source = NaturalAttackSource(atk="1d4", dmg_type=dmg_type)
            atk = AttackRoll(skill_bonus=0)
            atk.rolls, atk.result = (10,), 10
            atk.isCritical, atk.isFumble = False, False
            dmg = DamageRoll(dice=Dice.d4(), skill_bonus=0, weapon_bonus=0)
            dmg.rolls, dmg.result = (4,), 4
            combined = CombinedRoll(atk, dmg, 5)
            return AttackResult(
                source=source, combined=combined, damage=4,
                multiplier=1.0, defense=0, dodge=5,
                dmg_type=dmg_type,
            )

        # Bludgeoning → "bones crack"
        narration = s.get_hit_narration(
            attacker, _hit_with(DamageTypes.BLUDGEONING).source,
            _hit_with(DamageTypes.BLUDGEONING),
        )
        assert narration and "bones" in narration.lower()

        # Piercing → "whistles between ribs"
        narration = s.get_hit_narration(
            attacker, _hit_with(DamageTypes.PIERCING).source,
            _hit_with(DamageTypes.PIERCING),
        )
        assert narration and ("whistle" in narration.lower() or "ribs" in narration.lower())

        # Light → "holy radiance"
        narration = s.get_hit_narration(
            attacker, _hit_with(DamageTypes.LIGHT).source,
            _hit_with(DamageTypes.LIGHT),
        )
        assert narration and ("holy" in narration.lower() or "radiance" in narration.lower())

    def test_no_narration_on_untyped_attacks(self):
        """Attacks without a damage type get no narration — the
        lookup needs at least one type bit to match against."""
        from caldanai.lib.rpg.combat.attack_result import AttackResult
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        from caldanai.lib.rpg.helpers.roll_data import (
            AttackRoll, DamageRoll, CombinedRoll,
        )
        from caldanai.lib.rpg.helpers.dice import Dice
        from caldanai.lib.rpg.creatures import Creature

        s = Skeleton()
        attacker = Creature(
            name="hero", atk="1d4", defense=0, dodge=5,
            health_max=20, health=20,
        )
        source = NaturalAttackSource(atk="1d4", dmg_type=None)
        atk = AttackRoll(skill_bonus=0)
        atk.rolls, atk.result, atk.isCritical, atk.isFumble = (10,), 10, False, False
        dmg = DamageRoll(dice=Dice.d4(), skill_bonus=0, weapon_bonus=0)
        dmg.rolls, dmg.result = (4,), 4
        combined = CombinedRoll(atk, dmg, 5)
        result = AttackResult(
            source=source, combined=combined, damage=4,
            multiplier=1.0, defense=0, dodge=5, dmg_type=None,
        )
        assert s.get_hit_narration(attacker, source, result) is None


# ---------------------------------------------------------------------------
# Cyclops
# ---------------------------------------------------------------------------


class TestCyclops:
    def test_constructs(self):
        c = Cyclops()
        assert c.name == "cyclops"
        assert c.size == Size.HUGE

    def test_has_single_eye_not_pair(self):
        """The signature feature: exactly one eye, named ``eye``
        (not ``eye.left`` / ``eye.right``)."""
        c = Cyclops()
        eye_parts = [p for p in c.body_parts if isinstance(p, EyePlugin)]
        assert len(eye_parts) == 1
        assert eye_parts[0].name == "eye"

    def test_destroying_eye_collapses_hit_modifier(self):
        """When the sole eye goes to 0 HP, HIT emergence drops by
        the full -5 (eyes drive HIT; no fallback to heads while any
        eye still exists)."""
        c = Cyclops()
        baseline = c.get_hit_modifier()
        assert baseline == 0  # full health
        eye = next(p for p in c.body_parts if isinstance(p, EyePlugin))
        eye.health = 0
        assert c.get_hit_modifier() == -5

    def test_normal_state_returns_single_attack_source(self):
        c = Cyclops()
        sources = c.get_attack_sources()
        assert len(sources) == 1

    def test_blind_rage_returns_three_bigger_attack_sources(self):
        """Eye destroyed → three 3d10 wild swings (vs the normal
        single 2d10). HIT -5 still applies via emergence; this test
        only pins the source-count and dice changes."""
        c = Cyclops()
        eye = next(p for p in c.body_parts if isinstance(p, EyePlugin))
        eye.health = 0
        sources = c.get_attack_sources()
        assert len(sources) == 3
        for src in sources:
            # NaturalAttackSource stores the dice string as _atk
            # (private). Tests inspect it directly.
            assert src._atk == "3d10"

    def test_blind_rage_announce_fires_exactly_once(self):
        """The transition bellow fires the first round the eye is
        destroyed and never again — even though ``_is_blind`` stays
        True for every subsequent round."""
        c = Cyclops()
        # Pre-blind: no announcement.
        assert c.on_combat_round([]) == ""

        # Destroy the eye and call the round hook.
        eye = next(p for p in c.body_parts if isinstance(p, EyePlugin))
        eye.health = 0
        first = c.on_combat_round([])
        assert first
        assert "bellows" in first.lower() or "agony" in first.lower()

        # Subsequent rounds: still blind, but no repeat announcement.
        second = c.on_combat_round([])
        assert second == ""


# ---------------------------------------------------------------------------
# Minotaur
# ---------------------------------------------------------------------------


class TestMinotaur:
    def test_constructs(self):
        m = Minotaur()
        assert m.name == "minotaur"
        assert m.size == Size.LARGE

    def test_humanoid_anatomy(self):
        m = Minotaur()
        assert _part_names(m) == {
            "head", "torso",
            "arm.left", "arm.right",
            "leg.left", "leg.right",
        }

    def test_piercing_vulnerable_bludgeoning_resistant(self):
        m = Minotaur()
        assert m.get_trait_multiplier(DamageTypes.PIERCING) == 1.25
        assert m.get_trait_multiplier(DamageTypes.BLUDGEONING) == 0.75

    def test_gore_preference_is_head(self):
        """When the preference RNG fires, target returns 'head'.
        Force the RNG so the coin lands in the 'gore' bucket."""
        m = Minotaur()
        fake_source = MagicMock()
        with patch(
            "caldanai.lib.rpg.creatures.monsters.minotaur.random",
            return_value=0.1,  # below the 0.5 threshold → gore
        ):
            assert m.get_target_part_preference(None, fake_source) == "head"

    def test_preference_sometimes_defers_to_random(self):
        m = Minotaur()
        fake_source = MagicMock()
        with patch(
            "caldanai.lib.rpg.creatures.monsters.minotaur.random",
            return_value=0.9,  # above 0.5 → no preference
        ):
            assert m.get_target_part_preference(None, fake_source) is None


# ---------------------------------------------------------------------------
# Pixie
# ---------------------------------------------------------------------------


class TestPixie:
    def test_constructs(self):
        p = Pixie()
        assert p.name == "pixie"
        assert p.size == Size.TINY

    def test_has_wings_and_flying_flag(self):
        p = Pixie()
        wings = [part for part in p.body_parts if isinstance(part, WingPlugin)]
        assert len(wings) == 2
        assert "flying" in p.flags

    def test_eye_pranks_are_the_preference(self):
        """~30% eye bias — force the RNG below the threshold."""
        p = Pixie()
        fake_source = MagicMock()
        with patch(
            "caldanai.lib.rpg.creatures.monsters.pixie.random",
            return_value=0.1,
        ):
            assert p.get_target_part_preference(None, fake_source) == "eye"

    def test_fragile_tiny_has_low_body_hp(self):
        """TINY creatures get hp_scale=0.25. Body HP (as distinct
        from part HP) is rolled from 2d4, not scaled — so it's
        already low. Verify it's within the expected range."""
        p = Pixie()
        assert 2 <= p.health_max <= 8

    def test_vulnerable_to_fire_and_light(self):
        p = Pixie()
        assert p.get_trait_multiplier(DamageTypes.FIRE) == 2.0
        assert p.get_trait_multiplier(DamageTypes.LIGHT) == 2.0

    def test_magic_resistant(self):
        p = Pixie()
        assert p.get_trait_multiplier(DamageTypes.MAGICAL) == 0.25

    def test_attack_carries_magical_damage_type(self):
        """Pixie touch is faerie magic — bypasses purely-mundane
        armor and triggers magical-resistance traits on targets."""
        p = Pixie()
        sources = p.get_attack_sources()
        assert len(sources) == 1
        assert sources[0].damage_type == DamageTypes.MAGICAL


# ---------------------------------------------------------------------------
# Werewolf
# ---------------------------------------------------------------------------


class TestWerewolf:
    def test_constructs(self):
        w = Werewolf()
        assert w.name == "werewolf"
        assert w.size == Size.LARGE

    def test_flees_dawn(self):
        """Nocturnal creatures that flee at sunrise use the
        ``flees_from_time`` hook."""
        w = Werewolf()
        assert w.flees_from_time is True
        assert "dawn" in w.time_flee.lower() or "light" in w.time_flee.lower()

    def test_quadruped_shape_for_lupine_form(self):
        w = Werewolf()
        names = _part_names(w)
        assert "head" in names
        assert "tail" in names
        assert "foreleg.left" in names
        assert "foreleg.right" in names
        assert "hindleg.left" in names
        assert "hindleg.right" in names

    def test_throat_bite_preference(self):
        w = Werewolf()
        fake_source = MagicMock()
        with patch(
            "caldanai.lib.rpg.creatures.monsters.werewolf.random",
            return_value=0.1,
        ):
            assert w.get_target_part_preference(None, fake_source) == "head"

    # -- Dawn desperation -------------------------------------------

    def _make_clock(self, hours_to_morning: float):
        """Build a mock game clock positioned so that MORNING is
        ``hours_to_morning`` away. The werewolf reads ``get_next_time``
        and ``get_time_components`` to compute the window."""
        clock = MagicMock()
        # Pretend current time is (h=5, m=30) and MORNING hits at
        # (h=5+delta). Remaining is just the delta.
        clock.get_time_components.return_value = (5, 0, 0)
        next_h = 5 + int(hours_to_morning)
        next_m = int((hours_to_morning - int(hours_to_morning)) * 60)
        from caldanai.lib.rpg.helpers.enums import TimesOfDay
        clock.get_next_time.return_value = (TimesOfDay.MORNING.name, next_h, next_m)
        return clock

    def test_is_near_dawn_off_without_clock(self):
        """Without a game, desperation logic must be inert — the
        plugin is constructable in tests and shouldn't fire stateful
        behavior based on missing infrastructure."""
        w = Werewolf()
        assert w._is_near_dawn() is False

    def test_is_near_dawn_true_inside_window(self):
        w = Werewolf()
        w._clock = self._make_clock(0.5)  # 30 min to dawn
        assert w._is_near_dawn() is True

    def test_is_near_dawn_false_outside_window(self):
        w = Werewolf()
        w._clock = self._make_clock(3.0)  # 3h to dawn
        assert w._is_near_dawn() is False

    def test_is_near_dawn_false_when_next_tod_is_not_morning(self):
        """Night → NIGHT transition (or any non-MORNING next-tod)
        must not trigger desperation."""
        w = Werewolf()
        clock = MagicMock()
        clock.get_time_components.return_value = (22, 0, 0)
        from caldanai.lib.rpg.helpers.enums import TimesOfDay
        clock.get_next_time.return_value = (TimesOfDay.NIGHT.name, 23, 0)
        w._clock = clock
        assert w._is_near_dawn() is False

    def test_desperate_adds_bonus_attack(self):
        """Near dawn, ``get_attack_sources`` adds a second source
        alongside the normal bite."""
        w = Werewolf()
        baseline = len(w.get_attack_sources())
        w._clock = self._make_clock(0.5)
        desperate = w.get_attack_sources()
        assert len(desperate) == baseline + 1
        assert any("Lunge" in (s.label or "") for s in desperate)

    def test_desperate_announcement_fires_once(self):
        """``on_combat_round`` returns the announcement the first
        time desperation kicks in, then goes quiet on subsequent
        rounds even while still desperate."""
        w = Werewolf()
        w._clock = self._make_clock(0.5)
        first = w.on_combat_round([])
        second = w.on_combat_round([])
        assert "dawn" in first.lower() or "horizon" in first.lower()
        assert second == ""

    # -- Throat-bite narration --------------------------------------

    def test_throat_bite_narration_on_head_destruction(self):
        w = Werewolf()
        victim = MagicMock()
        victim.name = "adventurer"
        victim.pronouns = "they/them/their/theirs/themself"
        head = MagicMock()
        head.name = "head"
        msg = w.on_target_part_destroyed(victim, head)
        assert msg
        assert "throat" in msg.lower() or "jaws" in msg.lower()

    def test_non_head_destruction_has_no_attacker_beat(self):
        """Only the head triggers the throat-bite line; other parts
        fall through to the base (empty) hook."""
        w = Werewolf()
        leg = MagicMock()
        leg.name = "foreleg.left"
        assert w.on_target_part_destroyed(MagicMock(), leg) == ""

    # -- Flee loot ---------------------------------------------------

    def test_declares_flee_loot(self):
        """Dead-hook declaration that the dawn-flee leaves a shred
        behind. No engine caller yet — this just asserts the
        declaration exists for when the caller is wired."""
        w = Werewolf()
        assert "leather" in w.flee_loot
        assert 0 < w.flee_loot["leather"] <= 1.0

    # -- Partial-human reveal on death ------------------------------

    def test_death_appends_revelation(self):
        """Fatal ``apply_damage`` returns death string + revelation,
        separated by a newline so combat narration reads as two
        beats."""
        w = Werewolf()
        w.health = 1
        msg = w.apply_damage(999)
        assert msg
        assert "\n" in msg
        # Both halves non-empty.
        fatal, revelation = msg.split("\n", 1)
        assert fatal.strip()
        assert revelation.strip()

    def test_non_fatal_damage_no_revelation(self):
        """Partial-health hits must NOT emit the revelation — the
        reveal only reads as earned when the creature actually dies."""
        w = Werewolf()
        w.health = w.health_max  # starts healthy
        msg = w.apply_damage(1)  # scratch
        # apply_damage returns death string only on fatal transitions.
        assert msg == ""


# ---------------------------------------------------------------------------
# Golem
# ---------------------------------------------------------------------------


class TestGolem:
    def test_constructs(self):
        g = Golem()
        assert g.name == "golem"
        assert g.size == Size.LARGE

    def test_physical_resistance_profile(self):
        """Stone construct: piercing is nearly useless, slashing
        dulled, bludgeoning normal — that's the whole point."""
        g = Golem()
        assert g.get_trait_multiplier(DamageTypes.PIERCING) == 0.25
        assert g.get_trait_multiplier(DamageTypes.SLASHING) == 0.50
        assert g.get_trait_multiplier(DamageTypes.BLUDGEONING) == 1.00

    def test_magical_vulnerable(self):
        """Binding enchantment is the soft underbelly."""
        g = Golem()
        assert g.get_trait_multiplier(DamageTypes.MAGICAL) == 1.50

    def test_does_not_flee_or_die_from_time(self):
        """Stone doesn't care about sunrise."""
        g = Golem()
        assert g.flees_from_time is False
        assert g.dies_from_time is False


# ---------------------------------------------------------------------------
# Spirit
# ---------------------------------------------------------------------------


class TestSpirit:
    def test_constructs(self):
        s = Spirit()
        assert s.name == "spirit"

    def test_has_no_body_parts(self):
        """Spirits are intentionally the one monster without parts.
        Combat falls back to the legacy whole-body damage path, $look
        shows no 'Body Parts' field, target_part stays None on
        attack results."""
        s = Spirit()
        assert s.body_parts == []

    def test_physical_attacks_barely_hurt(self):
        """Sword through a ghost does almost nothing."""
        s = Spirit()
        assert s.get_trait_multiplier(DamageTypes.BLUDGEONING) == 0.10
        assert s.get_trait_multiplier(DamageTypes.SLASHING) == 0.10
        assert s.get_trait_multiplier(DamageTypes.PIERCING) == 0.10

    def test_holy_banishes_strongly(self):
        s = Spirit()
        assert s.get_trait_multiplier(DamageTypes.LIGHT) == 2.50

    def test_flees_dawn(self):
        s = Spirit()
        assert s.flees_from_time is True

    def test_render_body_part_table_is_empty(self):
        """The shared rendering helper returns empty string when
        no parts exist — ``$look spirit`` won't include a Body Parts
        field, which is the intent."""
        s = Spirit()
        assert s.render_body_part_status_table() == ""

    def test_attack_source_carries_drain_ratio(self):
        """Ethereal touch heals 50% of damage dealt."""
        s = Spirit()
        sources = s.get_attack_sources()
        assert len(sources) == 1
        assert sources[0].drain_ratio == 0.5

    def test_drain_heals_when_above_fade_threshold(self):
        """At normal HP, hitting deals damage and drain heals the
        spirit by half. Verify via the base ``_on_attack_resolved``
        plumbing."""
        from caldanai.lib.rpg.combat.attack_result import AttackResult
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        from caldanai.lib.rpg.helpers.roll_data import (
            AttackRoll, DamageRoll, CombinedRoll,
        )
        from caldanai.lib.rpg.helpers.dice import Dice

        s = Spirit()
        s.health = max(1, int(s.health_max * 0.8))  # well above fade
        before = s.health
        # Build a result that "hit for 10 damage" via a draining source.
        source = NaturalAttackSource(atk="2d4", drain_ratio=0.5)
        atk = AttackRoll(skill_bonus=0)
        atk.rolls, atk.result, atk.isCritical, atk.isFumble = (10,), 10, False, False
        dmg = DamageRoll(dice=Dice.d4(), skill_bonus=0, weapon_bonus=0)
        dmg.rolls, dmg.result = (4,), 10
        combined = CombinedRoll(atk, dmg, 5)
        result = AttackResult(
            source=source, combined=combined, damage=10,
            multiplier=1.0, defense=0, dodge=5,
        )
        s._on_attack_resolved(source, result)
        # Healed by 50% of 10 = 5 (clamped to health_max).
        assert s.health == min(s.health_max, before + 5)

    def test_drain_disabled_when_fading(self):
        """At ≤25% HP, drain stops working — the design constraint
        that closes the otherwise-exploitable loop."""
        from caldanai.lib.rpg.combat.attack_result import AttackResult
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        from caldanai.lib.rpg.helpers.roll_data import (
            AttackRoll, DamageRoll, CombinedRoll,
        )
        from caldanai.lib.rpg.helpers.dice import Dice

        s = Spirit()
        s.health = max(1, int(s.health_max * 0.2))  # in fade range
        before = s.health
        source = NaturalAttackSource(atk="2d4", drain_ratio=0.5)
        atk = AttackRoll(skill_bonus=0)
        atk.rolls, atk.result, atk.isCritical, atk.isFumble = (10,), 10, False, False
        dmg = DamageRoll(dice=Dice.d4(), skill_bonus=0, weapon_bonus=0)
        dmg.rolls, dmg.result = (4,), 10
        combined = CombinedRoll(atk, dmg, 5)
        result = AttackResult(
            source=source, combined=combined, damage=10,
            multiplier=1.0, defense=0, dodge=5,
        )
        s._on_attack_resolved(source, result)
        # No heal — fade state suppresses drain.
        assert s.health == before

    def test_melee_attacker_takes_cold_counter(self):
        """``_on_attacked`` deals 1d4 cold to a melee attacker who
        landed a hit. Ranged hits don't trigger."""
        from caldanai.lib.rpg.combat.attack_result import AttackResult
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        from caldanai.lib.rpg.helpers.roll_data import (
            AttackRoll, DamageRoll, CombinedRoll,
        )
        from caldanai.lib.rpg.helpers.dice import Dice
        from caldanai.lib.rpg.helpers.enums import Reach
        from caldanai.lib.rpg.creatures import Creature

        s = Spirit()
        attacker = Creature(
            name="player", atk="1d4", defense=0, dodge=5,
            health_max=20, health=20,
        )
        # Hit landing source at MELEE range.
        source = NaturalAttackSource(atk="1d4", reach=Reach.MELEE)
        atk = AttackRoll(skill_bonus=0)
        atk.rolls, atk.result, atk.isCritical, atk.isFumble = (10,), 10, False, False
        dmg = DamageRoll(dice=Dice.d4(), skill_bonus=0, weapon_bonus=0)
        dmg.rolls, dmg.result = (4,), 4
        combined = CombinedRoll(atk, dmg, 5)
        result = AttackResult(
            source=source, combined=combined, damage=4,
            multiplier=1.0, defense=0, dodge=5,
        )
        before = attacker.health
        s._on_attacked(attacker, source, result)
        assert attacker.health < before, (
            "Melee attacker should take cold counter-damage"
        )
        assert "chill" in result.extra_text.lower() or \
               "saps" in result.extra_text.lower()

    def test_ranged_attacker_no_cold_counter(self):
        """Ranged hits stay outside the spirit's chill aura."""
        from caldanai.lib.rpg.combat.attack_result import AttackResult
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        from caldanai.lib.rpg.helpers.roll_data import (
            AttackRoll, DamageRoll, CombinedRoll,
        )
        from caldanai.lib.rpg.helpers.dice import Dice
        from caldanai.lib.rpg.helpers.enums import Reach
        from caldanai.lib.rpg.creatures import Creature

        s = Spirit()
        attacker = Creature(
            name="archer", atk="1d4", defense=0, dodge=5,
            health_max=20, health=20,
        )
        source = NaturalAttackSource(atk="1d4", reach=Reach.RANGED)
        atk = AttackRoll(skill_bonus=0)
        atk.rolls, atk.result, atk.isCritical, atk.isFumble = (10,), 10, False, False
        dmg = DamageRoll(dice=Dice.d4(), skill_bonus=0, weapon_bonus=0)
        dmg.rolls, dmg.result = (4,), 4
        combined = CombinedRoll(atk, dmg, 5)
        result = AttackResult(
            source=source, combined=combined, damage=4,
            multiplier=1.0, defense=0, dodge=5,
        )
        before = attacker.health
        s._on_attacked(attacker, source, result)
        assert attacker.health == before

    def test_fade_announcement_fires_once(self):
        s = Spirit()
        # Above fade: nothing.
        assert s.on_combat_round([]) == ""
        # Drop below 25%.
        s.health = max(1, int(s.health_max * 0.2))
        first = s.on_combat_round([])
        assert "thins" in first.lower() or "warmth" in first.lower()
        # Stay below 25%, no repeat.
        second = s.on_combat_round([])
        assert "thins" not in second.lower() and "warmth" not in second.lower()


# ---------------------------------------------------------------------------
# Plugin discovery — the monsters actually register at load time
# ---------------------------------------------------------------------------


class TestPluginDiscovery:
    """Confirms that ``MonsterPlugin.load_plugins()`` picks up the new
    monster files. Catches class-name / filename drift that would
    otherwise let a broken plugin go unnoticed until someone tried to
    spawn it in a live game."""

    def test_all_new_monsters_are_discoverable(self):
        from caldanai import PluginManager
        from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
        MonsterPlugin.load_plugins()
        registered = {
            cls.__name__
            for cls in PluginManager.LOADED_PLUGINS.get(MonsterPlugin, [])
        }
        for name in ("Skeleton", "Cyclops", "Minotaur", "Pixie",
                     "Werewolf", "Golem", "Spirit"):
            assert name in registered, (
                f"{name} missing from MonsterPlugin registry — "
                f"plugin loader didn't pick up the file. "
                f"Registered: {sorted(registered)}"
            )
