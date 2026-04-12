"""Tests for the Reach enum added for Phase 1 body parts.

The Reach enum declares how an attack reaches its target. It is consumed
by ``AttackSource.reach`` (item 1.6) and by body-part ``exposure`` tables
(``Dict[Reach, float]``) that express how reachable a part is by each
attack type — e.g. a dragon's head is
``{Reach.MELEE: 0.05, Reach.THROWN: 0.5, Reach.RANGED: 1.0}``.

Phase 1 item 1.2 only requires the enum itself — no usage.
"""

from enum import Enum


class TestReachEnumExists:
    def test_reach_is_importable_from_enums_module(self):
        from Caldanai.lib.rpg.helpers.enums import Reach  # noqa: F401

    def test_reach_is_an_enum_subclass(self):
        from Caldanai.lib.rpg.helpers.enums import Reach

        assert issubclass(Reach, Enum)


class TestReachEnumMembers:
    def test_has_melee_member(self):
        from Caldanai.lib.rpg.helpers.enums import Reach

        assert hasattr(Reach, "MELEE")

    def test_has_reach_member(self):
        from Caldanai.lib.rpg.helpers.enums import Reach

        assert hasattr(Reach, "REACH")

    def test_has_thrown_member(self):
        from Caldanai.lib.rpg.helpers.enums import Reach

        assert hasattr(Reach, "THROWN")

    def test_has_ranged_member(self):
        from Caldanai.lib.rpg.helpers.enums import Reach

        assert hasattr(Reach, "RANGED")

    def test_member_set_is_exactly_the_phase1_set(self):
        from Caldanai.lib.rpg.helpers.enums import Reach

        assert {m.name for m in Reach} == {
            "MELEE",
            "REACH",
            "THROWN",
            "RANGED",
        }


class TestReachEnumValues:
    def test_values_are_distinct(self):
        from Caldanai.lib.rpg.helpers.enums import Reach

        values = [m.value for m in Reach]
        assert len(values) == len(set(values))

    def test_members_are_usable_as_dict_keys(self):
        from Caldanai.lib.rpg.helpers.enums import Reach

        exposure = {
            Reach.MELEE: 0.05,
            Reach.THROWN: 0.5,
            Reach.RANGED: 1.0,
        }
        assert exposure[Reach.MELEE] == 0.05
        assert exposure[Reach.THROWN] == 0.5
        assert exposure[Reach.RANGED] == 1.0

    def test_all_four_members_are_usable_as_dict_keys(self):
        from Caldanai.lib.rpg.helpers.enums import Reach

        exposure = {
            Reach.MELEE: 1.0,
            Reach.REACH: 0.8,
            Reach.THROWN: 0.6,
            Reach.RANGED: 0.4,
        }
        assert len(exposure) == 4
        assert exposure[Reach.REACH] == 0.8
