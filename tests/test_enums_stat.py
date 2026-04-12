"""Tests for the Stat enum added for Phase 1 body parts.

The Stat enum is the canonical key type used by body-part debuff tables
(e.g. ``{Stat.DODGE: -3, Stat.ATTACK: -1}``) and by creature stat-getter
aggregation. Phase 1 item 1.1 only requires the enum itself — no usage.
"""

from enum import Enum


class TestStatEnumExists:
    def test_stat_is_importable_from_enums_module(self):
        from caldanai.lib.rpg.helpers.enums import Stat  # noqa: F401

    def test_stat_is_an_enum_subclass(self):
        from caldanai.lib.rpg.helpers.enums import Stat

        assert issubclass(Stat, Enum)


class TestStatEnumMembers:
    def test_has_attack_member(self):
        from caldanai.lib.rpg.helpers.enums import Stat

        assert hasattr(Stat, "ATTACK")

    def test_has_defense_member(self):
        from caldanai.lib.rpg.helpers.enums import Stat

        assert hasattr(Stat, "DEFENSE")

    def test_has_dodge_member(self):
        from caldanai.lib.rpg.helpers.enums import Stat

        assert hasattr(Stat, "DODGE")

    def test_has_health_max_member(self):
        from caldanai.lib.rpg.helpers.enums import Stat

        assert hasattr(Stat, "HEALTH_MAX")

    def test_has_hit_member(self):
        from caldanai.lib.rpg.helpers.enums import Stat

        assert hasattr(Stat, "HIT")

    def test_member_set_is_exactly_the_phase1_set(self):
        from caldanai.lib.rpg.helpers.enums import Stat

        assert {m.name for m in Stat} == {
            "ATTACK",
            "DEFENSE",
            "DODGE",
            "HEALTH_MAX",
            "HIT",
        }


class TestStatEnumValues:
    def test_values_are_distinct(self):
        from caldanai.lib.rpg.helpers.enums import Stat

        values = [m.value for m in Stat]
        assert len(values) == len(set(values))

    def test_members_are_usable_as_dict_keys(self):
        from caldanai.lib.rpg.helpers.enums import Stat

        debuffs = {Stat.DODGE: -3, Stat.ATTACK: -1}
        assert debuffs[Stat.DODGE] == -3
        assert debuffs[Stat.ATTACK] == -1
