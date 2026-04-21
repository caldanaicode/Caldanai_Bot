"""Q.6 body-HP bleed-through formula + BLEED_MOD + defense_bonus.

Covers the three levers the design doc locks in:

- ``compute_body_hp_damage``: per-victim final body-HP subtract with
  per-part ``bleed_rate`` and creature-wide ``BLEED_MOD``. The
  ``num_hits`` floor still applies.
- ``MonsterPlugin.BLEED_MOD`` creature-wide multiplier stacks on top
  of per-part ``bleed_rate``.
- ``BodyPart.defense_bonus`` — Q.6.3 additive integer adjustment to
  base_def per hit, applied in :meth:`Creature.resolve_attack`. Pre-
  Q.6.3 this was a ``defense_mod`` multiplier; integer additive
  eliminated truncation drama and reads more directly.
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
        """Eye bleed_rate 0.1 × damage 20 = 2. Below num_hits floor
        (1 is less than 2, so 2 wins)."""
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
        """Dual-wield 15 torso + 15 arm = 15*0.7 + 15*0.3 = 15.
        Two hits, defense 0 → max(2, 15) = 15."""
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
        """``BLEED_MOD=1.5`` scales bleed-sum by 1.5. Torso 0.7 × 20
        = 14; × 1.5 = 21. Defense 0 → 21."""
        torso = BodyPart.make("torso", name="torso")
        res = _resolution(1, [_result(20, torso)])
        victim = _victim(bleed_mod=1.5)
        assert compute_body_hp_damage(res, victim, defense=0) == 21

    def test_zero_defense_yields_raw_bleed(self):
        """Sanity: defense=0 path just passes through the scaled sum.
        Torso 100 × 0.7 = 70."""
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


class TestDefenseBonusAppliesPerHit:
    """Q.6.3: ``defense_bonus`` is an additive integer applied
    per-hit inside resolve_attack. Part HP takes post-defense damage,
    which means an armored torso absorbs more per hit than a less-
    armored part — actually gating critical-part destruction.
    Replaces the earlier ``defense_mod`` multiplicative approach,
    which suffered from integer truncation at small base_def."""

    def _setup(self, base_def: int, part_name: str, bonus: int):
        """Build a MEDIUM target + matching part with an overridden
        ``defense_bonus``, then resolve one attack against that part.
        Returns the resolved :class:`AttackResult`."""
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        c = Creature(
            name="target", atk=None, defense=base_def, dodge=0,
            health_max=100, gender="male",
        )
        torso = BodyPart.make("torso", name="torso")
        part = BodyPart.make(part_name, name=part_name) if part_name != "torso" else torso
        part.defense_bonus = bonus
        c.body_parts = [torso] if part_name == "torso" else [torso, part]
        c.size = __import__("caldanai.lib.rpg.helpers.enums", fromlist=["Size"]).Size.MEDIUM
        attacker = Creature(
            name="attacker", atk="1d4", defense=0, dodge=0,
            health_max=10, gender="male",
        )
        source = NaturalAttackSource(
            atk="1d4", dmg_type=None, label="A", skill="natural",
        )
        atk_roll, dmg_roll = source.make_attack_rolls(attacker)
        return c.resolve_attack(
            attacker, source, atk_roll, dmg_roll, target_part=part,
        )

    def test_zero_bonus_yields_base_defense(self):
        """defense_bonus=0 → stored defense equals creature.get_defense()."""
        result = self._setup(base_def=5, part_name="torso", bonus=0)
        assert result.defense == 5

    def test_positive_bonus_adds_to_base(self):
        """torso.defense_bonus=+3 → base_def + 3."""
        result = self._setup(base_def=5, part_name="torso", bonus=3)
        assert result.defense == 8

    def test_negative_bonus_subtracts_from_base(self):
        """Squishy part (bonus=-2) → base_def - 2."""
        result = self._setup(base_def=10, part_name="arm", bonus=-2)
        assert result.defense == 8

    def test_bonus_clamps_at_zero(self):
        """defense_bonus low enough to drive total negative clamps
        at 0 — a SOFT_PART (-999) can't become a damage-amplifier."""
        result = self._setup(base_def=5, part_name="eye", bonus=-999)
        assert result.defense == 0


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

    def test_every_plugin_defaults_to_soft_part(self):
        """Q.6.3: every shipped plugin inherits ``SOFT_PART`` so an
        unarmored creature's parts clamp to 0 defense. Monster tanks
        opt specific parts in via instance override."""
        from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
        for plugin in ("torso", "head", "arm", "leg", "tail",
                       "wing", "eye", "toe"):
            part = BodyPart.make(plugin, name=plugin)
            assert part.defense_bonus == BodyPartPlugin.SOFT_PART, (
                f"{plugin} declares a non-default defense_bonus; "
                "Q.6.3 expects opt-in armor per monster."
            )


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
