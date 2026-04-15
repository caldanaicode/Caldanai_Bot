"""Tests for creature classification mixins.

Each classification (Undead, future Construct/Fae/Lupine) gets two
flavors of test coverage:

1. Direct unit tests of the mixin itself — applied to a minimal
   creature, does it set the right flag, layer the right traits,
   provide the right narrations?

2. A capability test parametrized over every monster that
   inherits the mixin, verifying the classification's invariants
   hold across the registry. Adding a new Undead automatically
   joins the relevant capability tests.
"""

import pytest

from caldanai import PluginManager
from caldanai.lib.rpg.creatures.classifications import Undead
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.enums import DamageTypes


# Plugins are loaded so the registry walk below sees every monster.
MonsterPlugin.load_plugins()
ALL_MONSTERS = list(PluginManager.LOADED_PLUGINS.get(MonsterPlugin, []))
UNDEAD_MONSTERS = [c for c in ALL_MONSTERS if issubclass(c, Undead)]


# ---------------------------------------------------------------------------
# Undead — direct mixin behavior
# ---------------------------------------------------------------------------


class _MinimalUndead(Undead, MonsterPlugin):
    """Bare-bones undead used to test the mixin in isolation."""

    def __init__(self):
        super().__init__(
            name="test undead",
            atk="1d4", defense=1, dodge=1,
            health_max=10,
        )


class TestUndeadMixinDirectly:
    def test_adds_undead_flag(self):
        u = _MinimalUndead()
        assert "undead" in u.flags

    def test_layers_default_trait_profile_via_setdefault(self):
        u = _MinimalUndead()
        # Standard undead defaults from the mixin.
        assert u.get_trait_multiplier(DamageTypes.LIGHT) == 2.0
        assert u.get_trait_multiplier(DamageTypes.FIRE) == 1.5
        assert u.get_trait_multiplier(DamageTypes.DARK) == 0.0
        # Compound ICE alias (WATER | DARK | COMBINED) only matches
        # compound ice damage, not pure water.
        assert u.get_trait_multiplier(DamageTypes.ICE) == 0.5

    def test_subclass_overrides_win_over_mixin(self):
        """Concrete subclass __init__ runs after the mixin's
        setdefault, so direct trait assignments overwrite the
        mixin's defaults."""

        class FieryUndead(Undead, MonsterPlugin):
            def __init__(self):
                super().__init__(
                    name="fiery undead", atk="1d4",
                    defense=1, dodge=1, health_max=10,
                )
                # Override mixin's FIRE 1.5 default.
                self.traits[DamageTypes.FIRE] = 0.5

        f = FieryUndead()
        assert f.get_trait_multiplier(DamageTypes.FIRE) == 0.5
        # Other defaults still in effect.
        assert f.get_trait_multiplier(DamageTypes.LIGHT) == 2.0


class TestHitNarrationsMroMerge:
    """``Creature._resolved_hit_narrations`` walks ``__mro__`` and
    merges entries; subclass overrides win over mixin defaults."""

    def test_minimal_undead_inherits_mixin_narrations(self):
        from caldanai.lib.rpg.combat.attack_result import AttackResult
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        from caldanai.lib.rpg.helpers.roll_data import (
            AttackRoll, DamageRoll, CombinedRoll,
        )
        from caldanai.lib.rpg.helpers.dice import Dice
        from caldanai.lib.rpg.creatures import Creature

        u = _MinimalUndead()
        attacker = Creature(
            name="hero", atk="1d4", defense=0, dodge=5,
            health_max=20, health=20,
        )
        source = NaturalAttackSource(atk="1d4", dmg_type=DamageTypes.LIGHT)
        atk = AttackRoll(skill_bonus=0)
        atk.rolls, atk.result, atk.isCritical, atk.isFumble = (10,), 10, False, False
        dmg = DamageRoll(dice=Dice.d4(), skill_bonus=0, weapon_bonus=0)
        dmg.rolls, dmg.result = (4,), 4
        combined = CombinedRoll(atk, dmg, 5)
        result = AttackResult(
            source=source, combined=combined, damage=4,
            multiplier=2.0, defense=0, dodge=5,
            dmg_type=DamageTypes.LIGHT,
        )
        narration = u.get_hit_narration(attacker, source, result)
        assert narration is not None
        assert "holy" in narration.lower() or "radiance" in narration.lower()

    def test_subclass_overrides_mixin_narration(self):
        """When a concrete subclass declares the same damage-type key
        in its own ``HIT_NARRATIONS``, the subclass's flavor wins."""

        class CustomUndead(Undead, MonsterPlugin):
            HIT_NARRATIONS = {
                # Override mixin's LIGHT entry with custom flavor.
                DamageTypes.LIGHT: "CUSTOM LIGHT NARRATION",
            }

            def __init__(self):
                super().__init__(
                    name="custom", atk="1d4",
                    defense=1, dodge=1, health_max=10,
                )

        from caldanai.lib.rpg.combat.attack_result import AttackResult
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        from caldanai.lib.rpg.helpers.roll_data import (
            AttackRoll, DamageRoll, CombinedRoll,
        )
        from caldanai.lib.rpg.helpers.dice import Dice
        from caldanai.lib.rpg.creatures import Creature

        c = CustomUndead()
        attacker = Creature(
            name="hero", atk="1d4", defense=0, dodge=5,
            health_max=20, health=20,
        )
        source = NaturalAttackSource(atk="1d4", dmg_type=DamageTypes.LIGHT)
        atk = AttackRoll(skill_bonus=0)
        atk.rolls, atk.result, atk.isCritical, atk.isFumble = (10,), 10, False, False
        dmg = DamageRoll(dice=Dice.d4(), skill_bonus=0, weapon_bonus=0)
        dmg.rolls, dmg.result = (4,), 4
        combined = CombinedRoll(atk, dmg, 5)
        result = AttackResult(
            source=source, combined=combined, damage=4,
            multiplier=2.0, defense=0, dodge=5,
            dmg_type=DamageTypes.LIGHT,
        )
        narration = c.get_hit_narration(attacker, source, result)
        assert narration == "CUSTOM LIGHT NARRATION"

    def test_subclass_extends_mixin_with_new_keys(self):
        """A concrete subclass adding a damage type the mixin
        doesn't cover keeps both — its own entry AND the mixin's."""

        class WeirdUndead(Undead, MonsterPlugin):
            HIT_NARRATIONS = {
                DamageTypes.FIRE: "FIRE NARRATION",  # mixin doesn't have FIRE narration
            }

            def __init__(self):
                super().__init__(
                    name="weird", atk="1d4",
                    defense=1, dodge=1, health_max=10,
                )

        merged = WeirdUndead._resolved_hit_narrations()
        # Mixin's LIGHT and DARK still present.
        assert DamageTypes.LIGHT in merged
        assert DamageTypes.DARK in merged
        # Subclass's FIRE added.
        assert merged[DamageTypes.FIRE] == "FIRE NARRATION"


# ---------------------------------------------------------------------------
# Capability test — every Undead in the registry must satisfy invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cls", UNDEAD_MONSTERS, ids=[c.__name__ for c in UNDEAD_MONSTERS],
)
class TestUndeadRegistryInvariants:
    """Every monster that inherits from ``Undead`` should satisfy the
    classification's contract. Fails on the next undead someone adds
    that forgot to call super() or overwrote a critical default."""

    def test_has_undead_flag(self, cls):
        m = cls()
        assert "undead" in m.flags

    def test_holy_is_meaningful(self, cls):
        """Every undead should be at least as vulnerable to LIGHT as
        a normal creature (multiplier ≥ 1.0). Concrete monsters can
        push it higher (skeleton 2.0, spirit 2.5); none should drop
        below baseline."""
        m = cls()
        assert m.get_trait_multiplier(DamageTypes.LIGHT) >= 1.0, (
            f"{cls.__name__} is undead but LIGHT damage doesn't even "
            f"apply normally — "
            f"got multiplier {m.get_trait_multiplier(DamageTypes.LIGHT)}"
        )

    def test_dark_does_not_amplify(self, cls):
        """Undead are dark-aligned; DARK damage shouldn't be worse
        than baseline against them. Most are immune (0.0); some have
        partial resistance (spirit 0.25)."""
        m = cls()
        assert m.get_trait_multiplier(DamageTypes.DARK) <= 1.0


def test_registry_contains_at_least_one_undead():
    """Sanity: if this passes empty, the mixin migration broke
    plugin discovery somewhere."""
    assert len(UNDEAD_MONSTERS) > 0
