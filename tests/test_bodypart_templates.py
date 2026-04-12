"""Tests for BodyPart template class methods (humanoid, quadruped, quadruped_winged)."""

from caldanai.lib.rpg.creatures.body_part import BodyPart


class TestBodyPartTemplates:
    def test_humanoid_returns_six_parts(self):
        parts = BodyPart.humanoid()
        assert len(parts) == 6

    def test_humanoid_returns_fresh_list_each_call(self):
        a = BodyPart.humanoid()
        b = BodyPart.humanoid()
        assert a is not b
        assert a[0] is not b[0]  # different instances

    def test_quadruped_returns_seven_parts(self):
        parts = BodyPart.quadruped()
        assert len(parts) == 7

    def test_quadruped_includes_tail(self):
        parts = BodyPart.quadruped()
        assert any(p.name == "tail" for p in parts)

    def test_quadruped_winged_returns_nine_parts(self):
        parts = BodyPart.quadruped_winged()
        assert len(parts) == 9

    def test_quadruped_winged_includes_wings(self):
        parts = BodyPart.quadruped_winged()
        assert any(p.name == "wing.left" for p in parts)
        assert any(p.name == "wing.right" for p in parts)

    def test_quadruped_winged_returns_fresh_list(self):
        a = BodyPart.quadruped_winged()
        b = BodyPart.quadruped_winged()
        assert a is not b
