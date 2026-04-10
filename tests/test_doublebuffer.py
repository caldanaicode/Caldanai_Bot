"""Tests for Caldanai.DoubleBuffer."""

from Caldanai.DoubleBuffer import DoubleBuffer


class TestDoubleBuffer:
    def test_put_and_get_all(self):
        buf = DoubleBuffer()
        buf.put("a")
        buf.put("b")
        items = buf.get_all()
        assert items == ["a", "b"]

    def test_get_all_empties_passive(self):
        buf = DoubleBuffer()
        buf.put("x")
        buf.get_all()
        # Second call should return empty since active (formerly passive) had nothing
        assert buf.get_all() == []

    def test_empty_buffer_get_all(self):
        buf = DoubleBuffer()
        assert buf.get_all() == []

    def test_swap_changes_queues(self):
        buf = DoubleBuffer()
        original_active = buf.active
        original_passive = buf.passive
        buf.swap()
        assert buf.active is original_passive
        assert buf.passive is original_active

    def test_put_after_get_all_goes_to_new_active(self):
        buf = DoubleBuffer()
        buf.put("first")
        items1 = buf.get_all()
        assert items1 == ["first"]

        buf.put("second")
        items2 = buf.get_all()
        assert items2 == ["second"]

    def test_ordering_preserved(self):
        buf = DoubleBuffer()
        for i in range(5):
            buf.put(i)
        items = buf.get_all()
        assert items == [0, 1, 2, 3, 4]

    def test_multiple_swaps(self):
        buf = DoubleBuffer()
        buf.put("a")
        buf.swap()
        buf.put("b")
        buf.swap()
        # After two swaps, active is back to original q1 which has "a"
        # passive is q2 which has "b"
        # get_all swaps again, so we get from the current active (q1 with "a")
        items = buf.get_all()
        assert items == ["a"]
        items = buf.get_all()
        assert items == ["b"]
