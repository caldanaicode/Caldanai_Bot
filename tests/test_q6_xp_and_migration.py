"""Q.6 Formula E — XP on hits/misses + skills-schema migration."""

from math import floor
from unittest.mock import MagicMock

from bson.objectid import ObjectId

from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures.player import (
    MIGRATION_RATE_RATIO,
    Player,
    SKILLS_SCHEMA_VERSION,
    _level_threshold,
    _migrate_skills_if_needed,
)


def _player(*, skills=None, schema=None, **kw):
    """Build a Player with test defaults. Bypass the migration pass
    when ``schema=SKILLS_SCHEMA_VERSION`` is supplied."""
    defaults = dict(
        pid=ObjectId(),
        gid=100,
        uid=200,
        health=20,
        health_max=20,
        defense=6,
        dodge=6,
        gender="male",
        pronouns="he,him,his,his",
        weight_limit=100,
        skills=skills or {},
        skills_schema_version=schema,
    )
    defaults.update(kw)
    return Player(**defaults)


class TestHitXpFormula:
    def test_miss_grants_flat_two_xp(self):
        """Miss path: ``hit=False`` grants a flat 2 XP regardless of
        skill level. Explicit hit-flag — doesn't infer from damage."""
        p = _player(schema=SKILLS_SCHEMA_VERSION)
        p.gain_skill_experience("swords", hit=False)
        assert p.skills["swords"] == 2

    def test_miss_xp_is_skill_independent(self):
        """The miss-path grant stays flat even at skill 10."""
        p = _player(schema=SKILLS_SCHEMA_VERSION)
        # Seed to skill level 10 so we're past the noise floor.
        p.skills["swords"] = _level_threshold(10)
        assert p.get_skill_level("swords") == 10
        before = p.skills["swords"]
        p.gain_skill_experience("swords", hit=False)
        assert p.skills["swords"] - before == 2

    def test_zero_damage_hit_grants_base_xp_not_miss_xp(self):
        """Trait-immunity hit: player connected (hit=True) but damage
        was fully absorbed (e.g., physical vs spirit). The swing
        counts as a committed connect and earns base_hit_xp, not the
        miss flat-2. Damage-bonus component goes to zero naturally
        since damage=0."""
        p = _player(schema=SKILLS_SCHEMA_VERSION)
        # Skill 1 (missing skill → level 1): base = 5 + floor(5*1) = 10.
        p.gain_skill_experience("swords", damage=0, bleed_rate=0.7, hit=True)
        # base_hit_xp only, no damage bonus.
        assert p.skills["swords"] == 10

    def test_hit_at_skill_0(self):
        """Level 1 (skill 0 XP): base = 5 + floor(5 * 1) = 10 (since
        floor((5*1)^0.5) = ... wait, skill=1). Actually level 1, so
        ``base = 5 + floor(5 * 1**0.5) = 10``. bonus = int(10 * 0.7 * 1.5)
        = int(10.5) = 10. Total = 20."""
        p = _player(schema=SKILLS_SCHEMA_VERSION)
        p.gain_skill_experience("swords", damage=10, bleed_rate=0.7)
        # get_skill_level on a missing skill returns 1, so base = 5+5 = 10.
        assert p.skills["swords"] == 20

    def test_hit_at_skill_10_calibration(self):
        """Design-doc calibration: skill 10 × torso hit for 15 damage
        should land near 35-36 XP. ``base = 5 + floor(5 * sqrt(10)) =
        5 + 15 = 20``. ``bonus = int(15 * 0.7 * 1.5) = int(15.75) = 15``.
        Total = 35 (the doc's rounded 36 is the floor-truncation edge)."""
        p = _player(schema=SKILLS_SCHEMA_VERSION)
        p.skills["swords"] = _level_threshold(10)
        before = p.skills["swords"]
        p.gain_skill_experience("swords", damage=15, bleed_rate=0.7)
        gained = p.skills["swords"] - before
        assert gained == 35

    def test_two_handed_doubles_both_terms(self):
        """Two-handed skill doubles both base and bonus. Level 1 × 10
        damage × 0.7 bleed: single-handed = 10 + 10 = 20; two-handed
        = 20 + 20 = 40."""
        p = _player(schema=SKILLS_SCHEMA_VERSION)
        p.gain_skill_experience("two-handed swords", damage=10, bleed_rate=0.7)
        assert p.skills["two-handed swords"] == 40

    def test_eye_hit_scales_down(self):
        """Eye bleed_rate 0.1 yields a very small damage bonus."""
        p = _player(schema=SKILLS_SCHEMA_VERSION)
        p.gain_skill_experience("swords", damage=20, bleed_rate=0.1)
        # base 10 + int(20 * 0.1 * 1.5) = 10 + 3 = 13.
        assert p.skills["swords"] == 13

    def test_level_20_cap(self):
        """No XP gained past level 20, including misses."""
        p = _player(schema=SKILLS_SCHEMA_VERSION, skills={"swords": 999999})
        assert p.get_skill_level("swords") == 20
        before = p.skills["swords"]
        p.gain_skill_experience("swords", damage=100, bleed_rate=0.7)
        p.gain_skill_experience("swords", hit=False)
        assert p.skills["swords"] == before

    def test_hit_path_marks_dirty(self):
        p = _player(schema=SKILLS_SCHEMA_VERSION)
        p.is_dirty = False
        p.gain_skill_experience("swords", damage=5, bleed_rate=0.3)
        assert p.is_dirty is True

    def test_miss_path_marks_dirty(self):
        p = _player(schema=SKILLS_SCHEMA_VERSION)
        p.is_dirty = False
        p.gain_skill_experience("swords", hit=False)
        assert p.is_dirty is True


class TestAttackResolvedWiring:
    """``Player._on_attack_resolved`` plumbs damage + bleed through to
    ``gain_skill_experience`` for both hit and miss paths."""

    def _make_result(self, damage: int, hit: bool, part: BodyPart = None):
        combined = MagicMock()
        combined.isMiss = not hit
        combined.isCritical = False
        combined.isFumble = False
        combined.result = damage
        combined.attack = MagicMock()
        combined.attack.rolls = [10]
        combined.attack.isCritical = False
        combined.damage = MagicMock()
        combined.damage.result = damage
        combined.damage.sides = 8
        combined.damage.rolls = [damage]
        source = NaturalAttackSource(
            atk="1d8", dmg_type=None, label="L", skill="natural",
        )
        r = MagicMock()
        r.damage = damage
        r.combined = combined
        r.hit = lambda: hit
        r.target_part = part
        return source, r

    def test_hit_passes_damage_and_bleed(self):
        p = _player(schema=SKILLS_SCHEMA_VERSION)
        torso = BodyPart.make("torso", name="torso")
        source, result = self._make_result(damage=10, hit=True, part=torso)
        p._on_attack_resolved(source, result)
        # base 10 + int(10 * 0.7 * 1.5) = 10 + 10 = 20.
        assert p.skills["natural"] == 20

    def test_hit_with_partless_result_uses_neutral_bleed(self):
        """No target_part → bleed_rate 1.0 fallback."""
        p = _player(schema=SKILLS_SCHEMA_VERSION)
        source, result = self._make_result(damage=10, hit=True, part=None)
        p._on_attack_resolved(source, result)
        # base 10 + int(10 * 1.0 * 1.5) = 10 + 15 = 25.
        assert p.skills["natural"] == 25

    def test_miss_grants_flat_two(self):
        p = _player(schema=SKILLS_SCHEMA_VERSION)
        source, result = self._make_result(damage=0, hit=False)
        p._on_attack_resolved(source, result)
        assert p.skills["natural"] == 2


class TestSkillsMigration:
    def test_fresh_player_starts_at_current_schema(self):
        """Brand-new players skip the migration (no skills to rescale)."""
        p = _player()
        assert p.skills_schema_version == SKILLS_SCHEMA_VERSION
        assert p.is_dirty is False

    def test_legacy_doc_triggers_migration(self):
        """Existing doc with skills but no ``skills_schema_version`` is
        treated as v1 and rescales."""
        old = 1000
        p = _player(skills={"swords": old})
        assert p.skills_schema_version == SKILLS_SCHEMA_VERSION
        # Level 2 threshold is 1000, so all progress was at the level-2
        # floor — rescale of 0 stays 0, and the stored XP lands at the
        # threshold exactly.
        assert p.skills["swords"] == _level_threshold(2)

    def test_migration_rescale_midlevel(self):
        """A mid-level-2 skill rescales by ``1 / MIGRATION_RATE_RATIO``."""
        # Level 2 threshold is 1000; add 500 in-level progress.
        floor_xp = _level_threshold(2)
        p = _player(skills={"swords": floor_xp + 500})
        expected = int(floor_xp + 500 / MIGRATION_RATE_RATIO)
        assert p.skills["swords"] == expected

    def test_migration_is_idempotent(self):
        """Running migration twice doesn't double-rescale."""
        floor_xp = _level_threshold(2)
        p = _player(skills={"swords": floor_xp + 500})
        after_once = p.skills["swords"]
        _migrate_skills_if_needed(p)  # second pass = no-op
        assert p.skills["swords"] == after_once

    def test_migration_preserves_level(self):
        """Rescale keeps the player at the same level they were at,
        even though the XP number shifts."""
        for level in range(1, 20):
            floor_xp = _level_threshold(level)
            p = _player(skills={"swords": floor_xp + 10})
            # Still at the same level after migration.
            assert p.get_skill_level("swords") == level

    def test_migration_round_trips_through_persistence(self):
        """``to_dict`` + ``from_dict`` preserves the schema version."""
        p = _player(schema=SKILLS_SCHEMA_VERSION, skills={"swords": 5000})
        d = p.to_dict()
        assert d["skills_schema_version"] == SKILLS_SCHEMA_VERSION
        p2 = Player.from_dict(d)
        assert p2.skills_schema_version == SKILLS_SCHEMA_VERSION
        # No migration should run on the re-load.
        assert p2.skills["swords"] == 5000

    def test_migration_marks_dirty_so_next_save_persists(self):
        p = _player(skills={"swords": 5000})
        # Legacy doc rescaled → dirty, next save writes the v2 XP.
        assert p.is_dirty is True

    def test_level_threshold_inverts_get_skill_level(self):
        """``_level_threshold(N)`` returns the minimum XP for level N."""
        p = _player(schema=SKILLS_SCHEMA_VERSION)
        for level in range(1, 21):
            xp = _level_threshold(level)
            p.skills["swords"] = xp
            assert p.get_skill_level("swords") == level

    def test_level_threshold_level_1_is_zero(self):
        assert _level_threshold(1) == 0
        assert _level_threshold(0) == 0  # clamped
