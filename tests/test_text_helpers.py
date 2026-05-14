"""Tests for ``caldanai.lib.rpg.helpers.text`` — the shared
text helpers consolidated out of ``BodyPart.gear_drop_flavor``
and ``Doppelganger._oxford_join``.
"""

from caldanai.lib.rpg.helpers.text import oxford_join


class TestOxfordJoin:
    def test_empty_returns_empty(self):
        assert oxford_join([]) == ""

    def test_single_returns_item(self):
        assert oxford_join(["alice"]) == "alice"

    def test_two_uses_and_without_comma(self):
        """Oxford style reserves the comma for 3+ — at two items
        the join is just 'X and Y'."""
        assert oxford_join(["alice", "bob"]) == "alice and bob"

    def test_three_uses_oxford_comma(self):
        assert (
            oxford_join(["alice", "bob", "charlie"])
            == "alice, bob, and charlie"
        )

    def test_four_uses_oxford_comma(self):
        assert (
            oxford_join(["a", "b", "c", "d"])
            == "a, b, c, and d"
        )

    def test_accepts_generator(self):
        """Iterable input shouldn't be exhausted before length checks."""
        assert oxford_join(s for s in ["x", "y"]) == "x and y"
