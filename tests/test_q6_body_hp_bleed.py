"""Q.6 body-HP bleed-through formula + BLEED_MOD + defense_mod.

Covers the three levers the design doc locks in:

- ``compute_body_hp_damage``: per-victim final body-HP subtract with
  per-part ``bleed_rate`` and creature-wide ``BLEED_MOD``. The
  ``num_hits`` floor still applies.
- ``MonsterPlugin.BLEED_MOD`` creature-wide multiplier stacks on top
  of per-part ``bleed_rate``.
- ``BodyPart.defense_mod`` scales the defense stored per-hit on the
  resolved :class:`AttackResult` (display + future per-hit math).
"""

from unittest.mock import MagicMock

from caldanai.lib.rpg.combat.attack_result import AttackResult
from caldanai.lib.rpg.combat.resolution import (
    ResolutionResult,
    compute_body_hp_damage,
)
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_part import BodyPart


def _victim(body_hp: int = 100, bleed_mod: float = 1.0, defense: int = 0):
    """Minimal victim with BLEED_MOD + body HP for the bleed formula."""
    c = MagicMock(spec=Creature)
    c.BLEED_MOD = bleed_mod
    c.health = body_hp
    c.health_max = body_hp
    return c


def _result(damage: int, part: BodyPart) -> AttackResult:
    """Synthetic AttackResult carrying just the fields the bleed
    formula reads (``damage`` + ``target_part``)."""
    r = MagicMock()
    r.damage = damage
    r.target_part = part
    return r


def _resolution(num_hits: int, results):
    """Wrap a list of synthetic results in a ResolutionResult."""
    positive = [r for r in results if r.damage > 0]
    return ResolutionResult(
        body_damage_total=sum(r.damage for r in positive),
        num_hits=num_hits,
        victim_results=positive,
    )


class TestBleedThroughFormula:
    def test_single_torso_hit(self):
        """Torso bleed_rate 0.7 × damage 20 = 14. Defense 0 →
        final = max(num_hits=1, 14) = 14."""
        torso = BodyPart.make("torso", name="torso")
        res = _resolution(1, [_result(20, torso)])
        assert compute_body_hp_damage(res, _victim(), defense=0) == 14

    def test_single_eye_hit_low_bleed(self):
        """Eye bleed_rate 0.1 × damage 20 = 2. Below num_hits floor (1
        is less than 2, so 2 wins)."""
        eye = BodyPart.make("eye", name="eye")
        res = _resolution(1, [_result(20, eye)])
        assert compute_body_hp_damage(res, _victim(), defense=0) == 2

    def test_num_hits_floor_kicks_in_on_tiny_bleed(self):
        """Toe bleed 0.05 × damage 5 = 0 (int truncates from 0.25).
        num_hits=1 is the floor → 1 body HP."""
        toe = BodyPart.make("toe", name="toe")
        res = _resolution(1, [_result(5, toe)])
        assert compute_body_hp_damage(res, _victim(), defense=0) == 1

    def test_defense_arg_is_ignored_post_q62(self):
        """Q.6.2: defense is applied per-hit inside ``resolve_attack``,
        so ``result.damage`` is already post-defense. The ``defense``
        arg on ``compute_body_hp_damage`` is accepted for call-site
        compat but ignored — passing any value yields the same result."""
        torso = BodyPart.make("torso", name="torso")
        res = _resolution(1, [_result(20, torso)])
        # 20 damage × 0.7 bleed = 14; defense arg no longer subtracts.
        assert compute_body_hp_damage(res, _victim(), defense=0) == 14
        assert compute_body_hp_damage(res, _victim(), defense=10) == 14
        assert compute_body_hp_damage(res, _victim(), defense=999) == 14

    def test_multi_source_bucket_sums_across_parts(self):
        """Dual-wield 15 torso + 15 arm = 15*0.7 + 15*0.3 = 15. Two
        hits, defense 0 → max(2, 15) = 15."""
        torso = BodyPart.make("torso", name="torso")
        arm = BodyPart.make("arm", name="arm")
        res = _resolution(2, [_result(15, torso), _result(15, arm)])
        assert compute_body_hp_damage(res, _victim(), defense=0) == 15

    def test_bleed_mod_multiplier_applies(self):
        """Creature-wide ``BLEED_MOD=0.5`` halves the scaled sum.
        Torso 0.7 × 20 = 14; × 0.5 = 7. Defense 0 → 7."""
        torso = BodyPart.make("torso", name="torso")
        res = _resolution(1, [_result(20, torso)])
        victim = _victim(bleed_mod=0.5)
        assert compute_body_hp_damage(res, victim, defense=0) == 7

    def test_bleed_mod_greater_than_one(self):
        """``BLEED_MOD=1.5`` scales bleed-sum by 1.5. Torso 0.7 × 20 = 14;
        × 1.5 = 21. Defense 0 → 21."""
        torso = BodyPart.make("torso", name="torso")
        res = _resolution(1, [_result(20, torso)])
        victim = _victim(bleed_mod=1.5)
        assert compute_body_hp_damage(res, victim, defense=0) == 21

    def test_zero_defense_yields_raw_bleed(self):
        """Sanity: defense=0 path just passes through the scaled sum."""
        torso = BodyPart.make("torso", name="torso")
        res = _resolution(1, [_result(100, torso)])
        assert compute_body_hp_damage(res, _victim(), defense=0) == 70

    def test_zero_num_hits_returns_zero(self):
        """num_hits=0 short-circuits before the sum, so we don't end up
        with ``max(0, -defense)`` producing a negative-ish surprise."""
        res = _resolution(0, [])
        assert compute_body_hp_damage(res, _victim(), defense=50) == 0

    def test_partless_target_falls_back_to_neutral_bleed(self):
        """Results with ``target_part=None`` (partless targets like
        Spirit) use the neutral 1.0 bleed so the pre-Q.6 raw total
        shape still materializes."""
        res = _resolution(1, [_result(10, None)])
        assert compute_body_hp_damage(res, _victim(), defense=0) == 10

    def test_int_cast_guards_against_float_drift(self):
        """Bleed sum is cast to int before the defense subtract so
        float accumulation (0.7 × 3 = 2.0999… in some paths) doesn't
        drift body HP. 10 × 0.7 × 3 hits = 21.0 cleanly; the int cast
        still absorbs tiny float residuals."""
        torso = BodyPart.make("torso", name="torso")
        results = [_result(10, torso) for _ in range(3)]
        res = _resolution(3, results)
        assert compute_body_hp_damage(res, _victim(), defense=0) == 21


class TestDefenseModWireIn:
    def test_default_one_is_noop(self):
        """Every shipped plugin defaults to ``defense_mod=1.0`` so the
        effective defense stored on AttackResult matches the victim's
        raw ``get_defense()``."""
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        from caldanai.lib.rpg.helpers.dice import Dice
        c = Creature(
            name="target", atk=None, defense=10, dodge=0,
            health_max=100, gender="male",
        )
        torso = BodyPart.make("torso", name="torso")
        c.body_parts = [torso]
        c.size = __import__("caldanai.lib.rpg.helpers.enums", fromlist=["Size"]).Size.MEDIUM
        attacker = Creature(
            name="attacker", atk="1d4", defense=0, dodge=0,
            health_max=10, gender="male",
        )
        source = NaturalAttackSource(atk="1d4", dmg_type=None, label="A", skill="natural")
        atk_roll, dmg_roll = source.make_attack_rolls(attacker)
        result = c.resolve_attack(
            attacker, source, atk_roll, dmg_roll, target_part=torso,
        )
        assert result.defense == c.get_defense()

    def test_defense_mod_scales_stored_defense(self):
        """A part with ``defense_mod=0.5`` halves the defense stored on
        its resolved AttackResult. Wires into ``resolve_attack`` only;
        body-HP formula keeps using flat ``get_defense()`` per the doc."""
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        c = Creature(
            name="target", atk=None, defense=10, dodge=0,
            health_max=100, gender="male",
        )
        torso = BodyPart.make("torso", name="torso")
        # Per-instance override (content populates these on tank
        # monsters via class attrs; the mechanism is instance-safe).
        torso.defense_mod = 0.5
        c.body_parts = [torso]
        c.size = __import__("caldanai.lib.rpg.helpers.enums", fromlist=["Size"]).Size.MEDIUM
        attacker = Creature(
            name="attacker", atk="1d4", defense=0, dodge=0,
            health_max=10, gender="male",
        )
        source = NaturalAttackSource(atk="1d4", dmg_type=None, label="A", skill="natural")
        atk_roll, dmg_roll = source.make_attack_rolls(attacker)
        result = c.resolve_attack(
            attacker, source, atk_roll, dmg_roll, target_part=torso,
        )
        assert result.defense == int(c.get_defense() * 0.5)


class TestDefenseModAppliesPerHit:
    """Q.6.2: defense_mod is applied per-hit inside resolve_attack.
    Part HP takes post-defense damage, which means an armored torso
    absorbs more per hit than a less-armored part — actually gating
    critical-part destruction, not just tinting body-HP math."""

    def test_default_defense_mod_full_defense(self):
        """defense_mod=1.0 → full creature.defense subtracted per hit."""
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        c = Creature(
            name="target", atk=None, defense=5, dodge=0,
            health_max=100, gender="male",
        )
        torso = BodyPart.make("torso", name="torso")
        c.body_parts = [torso]
        c.size = __import__("caldanai.lib.rpg.helpers.enums", fromlist=["Size"]).Size.MEDIUM
        attacker = Creature(
            name="attacker", atk="1d4", defense=0, dodge=0,
            health_max=10, gender="male",
        )
        source = NaturalAttackSource(
            atk="1d4", dmg_type=None, label="A", skill="natural",
        )
        atk_roll, dmg_roll = source.make_attack_rolls(attacker)
        result = c.resolve_attack(
            attacker, source, atk_roll, dmg_roll, target_part=torso,
        )
        # Whatever the roll was, result.defense should equal creature.defense
        # (no scaling from default mod=1.0).
        assert result.defense == 5

    def test_defense_mod_scales_stored_defense(self):
        """torso.defense_mod=2.0 doubles the per-hit defense subtract.
        Part takes correspondingly less raw damage per hit."""
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        c = Creature(
            name="target", atk=None, defense=5, dodge=0,
            health_max=100, gender="male",
        )
        torso = BodyPart.make("torso", name="torso")
        torso.defense_mod = 2.0
        c.body_parts = [torso]
        c.size = __import__("caldanai.lib.rpg.helpers.enums", fromlist=["Size"]).Size.MEDIUM
        attacker = Creature(
            name="attacker", atk="1d4", defense=0, dodge=0,
            health_max=10, gender="male",
        )
        source = NaturalAttackSource(
            atk="1d4", dmg_type=None, label="A", skill="natural",
        )
        atk_roll, dmg_roll = source.make_attack_rolls(attacker)
        result = c.resolve_attack(
            attacker, source, atk_roll, dmg_roll, target_part=torso,
        )
        assert result.defense == 10  # 5 × 2.0

    def test_defense_mod_below_one_exposes_part(self):
        """eye.defense_mod=0.5 halves defense → hits pierce easier.
        Include a torso so ``get_defense()`` (which emerges from torso
        functionality) returns a non-zero baseline."""
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        c = Creature(
            name="target", atk=None, defense=10, dodge=0,
            health_max=100, gender="male",
        )
        torso = BodyPart.make("torso", name="torso")
        eye = BodyPart.make("eye", name="eye.left")
        eye.defense_mod = 0.5
        c.body_parts = [torso, eye]
        c.size = __import__("caldanai.lib.rpg.helpers.enums", fromlist=["Size"]).Size.MEDIUM
        attacker = Creature(
            name="attacker", atk="1d4", defense=0, dodge=0,
            health_max=10, gender="male",
        )
        source = NaturalAttackSource(
            atk="1d4", dmg_type=None, label="A", skill="natural",
        )
        atk_roll, dmg_roll = source.make_attack_rolls(attacker)
        result = c.resolve_attack(
            attacker, source, atk_roll, dmg_roll, target_part=eye,
        )
        assert result.defense == 5  # 10 × 0.5


class TestBleedRatePerPartClass:
    """Each shipped body-part plugin carries the bleed rate locked
    in the Q.6 design doc."""

    def test_torso_bleed_rate(self):
        assert BodyPart.make("torso", name="torso").bleed_rate == 0.7

    def test_head_bleed_rate(self):
        assert BodyPart.make("head", name="head").bleed_rate == 0.6

    def test_arm_bleed_rate(self):
        assert BodyPart.make("arm", name="arm").bleed_rate == 0.3

    def test_leg_bleed_rate(self):
        assert BodyPart.make("leg", name="leg").bleed_rate == 0.3

    def test_tail_bleed_rate(self):
        assert BodyPart.make("tail", name="tail").bleed_rate == 0.2

    def test_wing_bleed_rate(self):
        assert BodyPart.make("wing", name="wing").bleed_rate == 0.2

    def test_eye_bleed_rate(self):
        assert BodyPart.make("eye", name="eye").bleed_rate == 0.1

    def test_toe_bleed_rate(self):
        assert BodyPart.make("toe", name="toe").bleed_rate == 0.05

    def test_default_defense_mod_is_one(self):
        """Every shipped plugin defaults to 1.0 defense_mod (no-op)."""
        for plugin in ("torso", "head", "arm", "leg", "tail",
                       "wing", "eye", "toe"):
            assert BodyPart.make(plugin, name=plugin).defense_mod == 1.0


class TestMonsterBleedMod:
    def test_base_default_is_one(self):
        from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
        assert MonsterPlugin.BLEED_MOD == 1.0

    def test_every_shipped_monster_has_neutral_default(self):
        """Q.6 ships the BLEED_MOD mechanism only — no content yet.
        Every loaded monster inherits ``1.0`` by default."""
        from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
        MonsterPlugin.load_plugins()
        # Class-level attr only; instance-level overrides stay empty.
        for cls in MonsterPlugin._PLUGIN_REGISTRY.values():
            assert cls.BLEED_MOD == 1.0, (
                f"{cls.__name__} declares a non-default BLEED_MOD; "
                "Q.6 ships mechanism only."
            )
