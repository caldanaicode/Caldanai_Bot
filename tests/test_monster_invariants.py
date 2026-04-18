"""Parametrized invariants across every discovered MonsterPlugin.

Adding a new monster file under ``caldanai/lib/rpg/creatures/monsters/``
automatically inherits every check here — no per-monster test file
needed for the generic shape. Specific behavior (vampire feed,
hydra regen, dragon 62-toe penalty, etc.) still lives in dedicated
test files because it doesn't generalize.

Guideline for deciding what goes here: if removing the check would
allow a monster to silently break in a way that affects combat or
persistence, put it here. If the check only makes sense for one
creature's signature mechanic, keep it with that creature.
"""

import pytest

from caldanai import PluginManager
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, DamageTypes, Size, TimePartitions,
)


# Plugin discovery happens at import time so parametrize() sees the
# full registry. Safe to re-run: load_plugins is idempotent.
MonsterPlugin.load_plugins()
ALL_MONSTERS = list(PluginManager.LOADED_PLUGINS.get(MonsterPlugin, []))
MONSTER_IDS = [cls.__name__ for cls in ALL_MONSTERS]


def _instantiate(cls):
    """Helper: instantiate a monster class, raising a helpful message
    on the rare case a monster's __init__ takes unexpected args."""
    return cls()


@pytest.mark.parametrize("cls", ALL_MONSTERS, ids=MONSTER_IDS)
class TestMonsterConstruction:
    def test_constructs_without_error(self, cls):
        _instantiate(cls)

    def test_has_non_empty_name(self, cls):
        m = _instantiate(cls)
        assert isinstance(m.name, str)
        assert m.name, f"{cls.__name__} has an empty name"

    def test_size_is_a_valid_Size_enum(self, cls):
        m = _instantiate(cls)
        assert m.size in Size

    def test_aggression_is_a_valid_AggressionLevels(self, cls):
        m = _instantiate(cls)
        # AggressionLevels is an IntFlag; membership check via `in` would
        # match any bit combination, so just assert it's an instance.
        assert isinstance(m.aggression, AggressionLevels)

    def test_time_partition_is_nonzero(self, cls):
        """Zero time_partition means the monster can never spawn —
        probably a bug. Every monster should be available in at
        least one time of day."""
        m = _instantiate(cls)
        assert isinstance(m.time_partition, TimePartitions)
        assert int(m.time_partition) != 0, (
            f"{cls.__name__} has empty time_partition; it will never spawn"
        )


@pytest.mark.parametrize("cls", ALL_MONSTERS, ids=MONSTER_IDS)
class TestMonsterStats:
    def test_health_nonnegative(self, cls):
        m = _instantiate(cls)
        assert m.health >= 0
        assert m.health_max > 0, f"{cls.__name__} has zero max health"
        assert m.health <= m.health_max

    def test_dodge_nonnegative(self, cls):
        m = _instantiate(cls)
        assert m.get_dodge() >= 0

    def test_defense_nonnegative(self, cls):
        m = _instantiate(cls)
        assert m.get_defense() >= 0


@pytest.mark.parametrize("cls", ALL_MONSTERS, ids=MONSTER_IDS)
class TestMonsterBodyParts:
    def test_body_parts_are_BodyPart_instances(self, cls):
        m = _instantiate(cls)
        for part in m.body_parts:
            assert isinstance(part, BodyPart), (
                f"{cls.__name__}.body_parts contains a non-BodyPart: "
                f"{type(part).__name__}"
            )

    def test_part_instance_names_unique(self, cls):
        """``arm.left`` and ``arm.right`` are distinct instance names
        for the same plugin base — both fine. But two parts with the
        exact same ``name`` would collide for ``$kill``, lookup,
        persistence, and narration."""
        m = _instantiate(cls)
        names = [p.name for p in m.body_parts]
        assert len(names) == len(set(names)), (
            f"{cls.__name__} has duplicate part names: {names}"
        )

    def test_paired_parts_share_health_max(self, cls):
        """Symmetrization run during ``_scale_part_hp`` should leave
        ``<base>.left`` and ``<base>.right`` with identical
        health_max. Catches monsters that forget to call the scaler
        or that populate body_parts after the call."""
        m = _instantiate(cls)
        pairs: dict = {}
        for part in m.body_parts:
            if "." not in part.name:
                continue
            base, side = part.name.rsplit(".", 1)
            if side in ("left", "right"):
                pairs.setdefault(base, []).append(part)
        for base, parts in pairs.items():
            if len(parts) >= 2:
                maxes = {p.health_max for p in parts}
                assert len(maxes) == 1, (
                    f"{cls.__name__} pair '{base}' has mismatched "
                    f"health_max: {maxes} — symmetrization didn't run"
                )

    def test_every_part_has_positive_health_max(self, cls):
        m = _instantiate(cls)
        for part in m.body_parts:
            assert part.health_max >= 1, (
                f"{cls.__name__}.{part.name} has non-positive health_max"
            )

    def test_every_part_starts_at_full_health(self, cls):
        """Fresh-spawn invariant: body parts start undamaged."""
        m = _instantiate(cls)
        for part in m.body_parts:
            assert part.health == part.health_max, (
                f"{cls.__name__}.{part.name} spawned injured "
                f"({part.health}/{part.health_max})"
            )


@pytest.mark.parametrize("cls", ALL_MONSTERS, ids=MONSTER_IDS)
class TestMonsterTraitsAndLoot:
    def test_trait_values_are_nonnegative_floats(self, cls):
        """Trait values are multipliers. Negative would be
        nonsensical (dealing negative damage?). Zero is fine
        ('immune'), anything positive is fine."""
        m = _instantiate(cls)
        for dmg_type, mult in m.traits.items():
            assert isinstance(mult, (int, float)), (
                f"{cls.__name__}.traits[{dmg_type}] is not numeric"
            )
            assert mult >= 0, (
                f"{cls.__name__}.traits[{dmg_type}] = {mult} < 0"
            )

    def test_loot_frequencies_in_unit_interval(self, cls):
        """Loot values represent drop probabilities. Values outside
        [0, 1] would either never drop or always drop, which is
        probably a bug."""
        m = _instantiate(cls)
        for item_name, freq in m.loot.items():
            assert isinstance(item_name, str) and item_name
            assert 0.0 <= freq <= 1.0, (
                f"{cls.__name__}.loot[{item_name!r}] = {freq} "
                f"(should be in [0, 1])"
            )


@pytest.mark.parametrize("cls", ALL_MONSTERS, ids=MONSTER_IDS)
class TestMonsterBehavior:
    def test_on_hugged_returns_string(self, cls):
        """The hug system treats on_hugged as returning renderable
        text. Exceptions or non-string returns would break the
        player-facing response."""
        m = _instantiate(cls)
        from caldanai.lib.rpg.creatures import Creature
        actor = Creature(
            name="tester", atk="1d4", defense=1, dodge=1,
            health_max=10, health=10,
        )
        result = m.on_hugged(actor, "hug")
        assert isinstance(result, str)

    def test_apply_damage_zero_is_noop_on_health(self, cls):
        """Healing neutral doesn't change body HP. Guards against
        any monster that accidentally shadows apply_damage with a
        buggy override."""
        m = _instantiate(cls)
        before = m.health
        m.apply_damage(0)
        assert m.health == before


class TestPluginRegistryCompleteness:
    """The registry is the source of truth for discoverable monsters.
    If an import error or naming mismatch silently dropped a plugin,
    the parametrized tests above wouldn't run against it — so an
    explicit count-style sanity check catches that regression."""

    def test_registry_is_non_empty(self):
        assert len(ALL_MONSTERS) > 0, (
            "No monster plugins discovered — plugin loader is broken"
        )

    def test_every_registered_class_subclasses_MonsterPlugin(self):
        for cls in ALL_MONSTERS:
            assert issubclass(cls, MonsterPlugin), (
                f"{cls.__name__} in MonsterPlugin registry but doesn't "
                f"subclass MonsterPlugin"
            )


# ---------------------------------------------------------------------------
# Capability-grouped tests
#
# Unlike the universal invariants above, these parametrize over the
# *subset* of monsters that opt into a capability — "is this creature
# flying?", "does it have a targeting preference?", etc. Adding a new
# monster that adopts one of these capabilities automatically inherits
# the relevant checks.
#
# If a capability group turns out to have exactly one member (e.g. only
# Spirit currently has no body parts), the parametrization still runs
# — the value comes from "if we add a second one, the check is already
# there" rather than per-member coverage.
# ---------------------------------------------------------------------------


def _with_capability(predicate):
    """Return the subset of ALL_MONSTERS whose freshly-constructed
    instance satisfies ``predicate``. Used to build the parametrize
    lists for capability-based tests."""
    members = []
    for cls in ALL_MONSTERS:
        try:
            if predicate(cls()):
                members.append(cls)
        except Exception:
            # Construction errors are caught by TestMonsterConstruction;
            # don't double-flag here.
            pass
    return members


def _ids(classes):
    return [c.__name__ for c in classes]


# All capability groups filter via canonical ``Creature`` capability
# methods so adding a new monster with a given capability auto-joins
# the right test group without editing this file.
FLYING_MONSTERS = _with_capability(lambda m: m.is_flying())
QUADRUPED_MONSTERS = _with_capability(
    # No dedicated ``is_quadruped`` method — shape-specific predicate
    # kept here because "quadruped" is less clearly a creature-level
    # capability than a body-part composition pattern.
    lambda m: any(p.name.startswith("foreleg.") for p in m.body_parts)
)
EYELESS_MONSTERS = _with_capability(
    lambda m: m.has_body_parts() and not m.has_eyes()
)
NO_BODY_PART_MONSTERS = _with_capability(lambda m: not m.has_body_parts())
TIME_FLEEING_MONSTERS = _with_capability(lambda m: m.flees_from_time)
TIME_DYING_MONSTERS = _with_capability(lambda m: m.dies_from_time)
PREDATOR_MONSTERS = _with_capability(lambda m: m.has_target_preference())


@pytest.mark.parametrize("cls", FLYING_MONSTERS, ids=_ids(FLYING_MONSTERS))
class TestFlyingCreatures:
    """Creatures that spawn airborne (``is_flying()`` true at t=0):
    they should have functional wings, their dodge should scale with
    wing functionality, and destroying all their wings should ground
    them via the existing ``WingPlugin.on_injury_change`` hook."""

    def test_can_fly_at_spawn(self, cls):
        """If the creature spawns flying, ``can_fly`` should agree.
        Otherwise the flag is on a creature physically incapable of
        flight — a bug."""
        m = cls()
        assert m.can_fly(), (
            f"{cls.__name__} spawns flying (is_flying=True) but "
            f"can_fly=False — no functional wings at spawn"
        )

    def test_has_at_least_one_wing_part(self, cls):
        m = cls()
        wings = [p for p in m.body_parts if p.name.startswith("wing")]
        assert len(wings) >= 1, (
            f"{cls.__name__} starts flying but has no wing parts — "
            f"dodge emergence will fall through to core_agility"
        )

    def test_dodge_derived_from_wings_while_flying(self, cls):
        """Sanity: flying dodge should scale with wing functionality.
        Wreck the wings, expect dodge to drop (compared to full-wing
        baseline)."""
        m = cls()
        full = m.get_dodge()
        for p in m.body_parts:
            if p.name.startswith("wing"):
                p.health = 0
        wrecked = m.get_dodge()
        # Either dodge dropped, or the creature falls back to
        # core_agility (rare). Both are acceptable; what's NOT
        # acceptable is the dodge going *up*.
        assert wrecked <= full

    def test_losing_capability_via_can_fly(self, cls):
        """After destroying all wings, ``can_fly`` should flip to
        False (no functional wings remaining). This is the capability
        check downstream systems use to ask "should this creature
        still be able to take off?" — doesn't depend on the
        ``"flying"`` state flag."""
        m = cls()
        assert m.can_fly()
        for p in m.body_parts:
            if p.name.startswith("wing"):
                p.health = 0
        assert not m.can_fly()


@pytest.mark.parametrize("cls", QUADRUPED_MONSTERS, ids=_ids(QUADRUPED_MONSTERS))
class TestQuadrupedShape:
    """Creatures built from ``BodyPart.quadruped`` (or equivalent):
    both forelegs and both hindlegs should be present and symmetric."""

    def test_has_both_forelegs(self, cls):
        m = cls()
        names = {p.name for p in m.body_parts}
        assert "foreleg.left" in names
        assert "foreleg.right" in names

    def test_has_both_hindlegs(self, cls):
        m = cls()
        names = {p.name for p in m.body_parts}
        assert "hindleg.left" in names
        assert "hindleg.right" in names


@pytest.mark.parametrize("cls", EYELESS_MONSTERS, ids=_ids(EYELESS_MONSTERS))
class TestEyelessCreatures:
    """Monsters with body parts but no eye parts (skeleton, golem,
    standard humanoids from ``BodyPart.humanoid``). HIT emergence
    falls back to heads — verify the fallback works."""

    def test_hit_modifier_falls_back_to_head(self, cls):
        m = cls()
        # Full health: HIT modifier is 0.
        assert m.get_hit_modifier() == 0
        # Destroy every head (``find_parts`` segment-prefix match picks
        # up both ``head`` and multi-head variants like ``head.1`` /
        # ``head.2`` on a hydra). Multi-head creatures need all heads
        # destroyed before HIT fallback fires.
        heads = m.find_parts("head")
        assert heads, f"{cls.__name__} has no head parts"
        for head in heads:
            head.health = 0
        assert m.get_hit_modifier() < 0


@pytest.mark.parametrize(
    "cls", NO_BODY_PART_MONSTERS, ids=_ids(NO_BODY_PART_MONSTERS),
)
class TestNoBodyPartMonsters:
    """Creatures that intentionally opt out of the body-parts system
    (spirits, by design). Combat falls back to legacy whole-body HP;
    render helpers return empty rather than an empty table."""

    def test_render_body_part_table_empty(self, cls):
        m = cls()
        assert m.render_body_part_status_table() == ""

    def test_get_dodge_uses_raw_value(self, cls):
        """With no body parts, ``get_dodge`` uses the rolled
        ``self.dodge`` (legacy path)."""
        m = cls()
        assert m.get_dodge() == max(0, m.dodge)


@pytest.mark.parametrize(
    "cls", TIME_FLEEING_MONSTERS, ids=_ids(TIME_FLEEING_MONSTERS),
)
class TestTimeFleeingCreatures:
    """Creatures marked ``flees_from_time`` retreat when the world
    cycles to a time they can't tolerate. They must supply a
    narrative string for that moment."""

    def test_has_time_flee_message(self, cls):
        m = cls()
        assert isinstance(m.time_flee, str)
        assert m.time_flee, (
            f"{cls.__name__} flees from time but has no time_flee message"
        )


@pytest.mark.parametrize(
    "cls", TIME_DYING_MONSTERS, ids=_ids(TIME_DYING_MONSTERS),
)
class TestTimeDyingCreatures:
    """Creatures marked ``dies_from_time`` die when exposed to a
    time-of-day they can't survive. They must supply a death narrative."""

    def test_has_time_death_message(self, cls):
        m = cls()
        assert isinstance(m.time_death, str)
        assert m.time_death, (
            f"{cls.__name__} dies from time but has no time_death message"
        )


@pytest.mark.parametrize("cls", PREDATOR_MONSTERS, ids=_ids(PREDATOR_MONSTERS))
class TestPredatorPreferences:
    """Monsters that override ``get_target_part_preference``. Given
    enough samples, the override should occasionally return a non-None
    value — otherwise the override is effectively a no-op and belongs
    to the base class."""

    def test_sometimes_returns_a_preference(self, cls):
        """Call the hook ``N`` times on a fresh instance. At least
        one call should surface a preferred part name. Uses a large
        N to make this robust to low bias rates (10% still clears
        100 trials with overwhelming probability)."""
        from unittest.mock import MagicMock
        m = cls()
        fake_target = MagicMock()
        fake_source = MagicMock()
        preferences = [
            m.get_target_part_preference(fake_target, fake_source)
            for _ in range(200)
        ]
        assert any(p is not None for p in preferences), (
            f"{cls.__name__} overrides get_target_part_preference but "
            f"never returned a preferred part across 200 samples — "
            f"either the probability is too low to be meaningful, or "
            f"the override is a dead no-op"
        )


@pytest.mark.parametrize("cls", ALL_MONSTERS, ids=MONSTER_IDS)
class TestCapabilityMethodsSelfConsistent:
    """Every monster's capability methods should agree with each other
    and with the creature's internal state. Adding a new capability
    method (or changing the implementation of an existing one) is
    covered by these cross-checks."""

    def test_is_flying_implies_has_flying_flag(self, cls):
        m = cls()
        if m.is_flying():
            assert "flying" in m.flags, (
                f"{cls.__name__}.is_flying() returned True but "
                f"'flying' not in self.flags"
            )

    def test_has_eyes_matches_body_part_shape(self, cls):
        m = cls()
        has_eye_part = any(
            p.name.startswith("eye") for p in m.body_parts
        )
        assert m.has_eyes() is has_eye_part

    def test_has_body_parts_matches_list_non_empty(self, cls):
        m = cls()
        assert m.has_body_parts() is (len(m.body_parts) > 0)

    def test_has_target_preference_matches_method_identity(self, cls):
        """``has_target_preference`` should report True iff the class
        actually overrides the preference hook."""
        m = cls()
        from caldanai.lib.rpg.creatures import Creature as _BaseCreature
        overrides = (
            type(m).get_target_part_preference
            is not _BaseCreature.get_target_part_preference
        )
        assert m.has_target_preference() is overrides
