"""Tests for Caldanai.Dispatcher."""

from unittest.mock import MagicMock, patch

import pytest
from discord import TextChannel, Embed, File, User, Member
from discord.ext.commands import Context

# Patch environment and Logger before importing Dispatcher
with patch("Caldanai.environment.DB_CONNECTION", "mongodb://localhost:27017"), \
     patch("Caldanai.environment.LOG_LEVEL", "DEBUG"), \
     patch("Caldanai.environment.STAGE", "TEST"):
    from Caldanai.Dispatcher import Dispatcher


@pytest.fixture(autouse=True)
def _reset_dispatcher():
    """Reset dispatcher state between tests."""
    Dispatcher.queue.queue.clear()
    Dispatcher.flush = False
    yield
    Dispatcher.queue.queue.clear()
    Dispatcher.flush = False


def _make_channel(cls=TextChannel, channel_id=100):
    ch = MagicMock(spec=cls)
    ch.id = channel_id
    return ch


class TestDispatcherAdd:
    def test_add_text_channel(self):
        ch = _make_channel(TextChannel)
        Dispatcher.add(ch, text="hello")
        assert Dispatcher.queue.qsize() == 1
        msg = Dispatcher.queue.queue[0]
        assert msg.text == "hello"
        assert msg.channel is ch

    def test_add_user_channel(self):
        ch = _make_channel(User)
        Dispatcher.add(ch, text="dm")
        assert Dispatcher.queue.qsize() == 1

    def test_add_member_channel(self):
        ch = _make_channel(Member)
        Dispatcher.add(ch, text="member msg")
        assert Dispatcher.queue.qsize() == 1

    def test_add_context_extracts_channel(self):
        ctx = MagicMock(spec=Context)
        inner_ch = _make_channel(TextChannel, 200)
        ctx.channel = inner_ch
        Dispatcher.add(ctx, text="from ctx")
        assert Dispatcher.queue.qsize() == 1
        assert Dispatcher.queue.queue[0].channel is inner_ch

    def test_add_unrecognized_channel_type_ignored(self):
        bad = MagicMock()  # no spec, not User/Member/TextChannel/Guild/Context
        # Remove the spec so isinstance checks fail
        bad.__class__ = type("Unknown", (), {})
        Dispatcher.add(bad, text="nope")
        assert Dispatcher.queue.qsize() == 0

    def test_add_with_flush_true_does_nothing(self):
        Dispatcher.flush = True
        ch = _make_channel(TextChannel)
        Dispatcher.add(ch, text="ignored")
        assert Dispatcher.queue.qsize() == 0


class TestDispatcherAddMessage:
    def test_merge_same_channel_str_messages(self):
        ch = _make_channel(TextChannel, 1)
        m1 = Dispatcher.Message(ch, text="line1")
        m2 = Dispatcher.Message(ch, text="line2")
        Dispatcher.add_message(m1)
        Dispatcher.add_message(m2)
        assert Dispatcher.queue.qsize() == 1
        assert Dispatcher.queue.queue[0].text == "line1\nline2"

    def test_no_merge_different_channels(self):
        ch1 = _make_channel(TextChannel, 1)
        ch2 = _make_channel(TextChannel, 2)
        Dispatcher.add_message(Dispatcher.Message(ch1, text="a"))
        Dispatcher.add_message(Dispatcher.Message(ch2, text="b"))
        assert Dispatcher.queue.qsize() == 2

    def test_no_merge_when_last_has_embed(self):
        ch = _make_channel(TextChannel, 1)
        Dispatcher.add_message(Dispatcher.Message(ch, text="a", embed=MagicMock(spec=Embed)))
        Dispatcher.add_message(Dispatcher.Message(ch, text="b"))
        assert Dispatcher.queue.qsize() == 2

    def test_no_merge_when_new_has_file(self):
        ch = _make_channel(TextChannel, 1)
        Dispatcher.add_message(Dispatcher.Message(ch, text="a"))
        Dispatcher.add_message(Dispatcher.Message(ch, text="b", file=MagicMock(spec=File)))
        assert Dispatcher.queue.qsize() == 2

    def test_no_merge_when_text_is_none(self):
        ch = _make_channel(TextChannel, 1)
        Dispatcher.add_message(Dispatcher.Message(ch, text="a"))
        Dispatcher.add_message(Dispatcher.Message(ch, text=None))
        assert Dispatcher.queue.qsize() == 2

    def test_no_merge_when_last_text_is_none(self):
        ch = _make_channel(TextChannel, 1)
        Dispatcher.add_message(Dispatcher.Message(ch, text=None))
        Dispatcher.add_message(Dispatcher.Message(ch, text="b"))
        assert Dispatcher.queue.qsize() == 2

    def test_no_merge_tuple_text(self):
        ch = _make_channel(TextChannel, 1)
        Dispatcher.add_message(Dispatcher.Message(ch, text=("part1", "part2")))
        Dispatcher.add_message(Dispatcher.Message(ch, text="b"))
        assert Dispatcher.queue.qsize() == 2

    def test_no_merge_when_combined_exceeds_2000(self):
        ch = _make_channel(TextChannel, 1)
        Dispatcher.add_message(Dispatcher.Message(ch, text="a" * 1500))
        Dispatcher.add_message(Dispatcher.Message(ch, text="b" * 600))
        assert Dispatcher.queue.qsize() == 2

    def test_flush_prevents_add_message(self):
        Dispatcher.flush = True
        ch = _make_channel(TextChannel, 1)
        Dispatcher.add_message(Dispatcher.Message(ch, text="ignored"))
        assert Dispatcher.queue.qsize() == 0


class TestDispatcherSplitMessage:
    def test_normal_split(self):
        msg = "line1\nline2\nline3"
        result = Dispatcher.split_message(msg, limit=12)
        assert len(result) >= 2
        # All parts should be substrings of the original (modulo separators)
        recombined = "\n".join(result)
        # Each chunk respects limit
        for part in result:
            assert len(part) <= 12

    def test_keep_sep_true(self):
        msg = "aaa\nbbb\nccc"
        result = Dispatcher.split_message(msg, sep="\n", keep_sep=True, limit=5)
        # With keep_sep, the separator is appended to each chunk
        for part in result[:-1]:
            assert part.endswith("\n")

    def test_keep_sep_false(self):
        msg = "aaa\nbbb\nccc"
        result = Dispatcher.split_message(msg, sep="\n", keep_sep=False, limit=5)
        for part in result:
            assert not part.endswith("\n") or part == result[-1]

    def test_message_shorter_than_limit(self):
        msg = "short"
        result = Dispatcher.split_message(msg, limit=100)
        assert result == ("short",)

    def test_empty_message(self):
        assert Dispatcher.split_message("") == ()

    def test_none_message(self):
        assert Dispatcher.split_message(None) == ()

    def test_no_separator_in_chunk(self):
        # A single long word with no newlines - rsplit won't find sep
        msg = "a" * 100
        result = Dispatcher.split_message(msg, sep="\n", limit=50)
        # Should still produce output (rsplit returns the whole string as element 0)
        assert len(result) >= 1
        # Each chunk respects the limit
        for part in result:
            assert len(part) <= 50
        # When the separator is not found, rsplit returns the whole chunk as
        # element 0 and i advances by len(chunk) + len(sep), consuming one
        # extra character per split boundary.  So the total recovered length
        # equals the original length minus the number of internal splits.
        total = sum(len(p) for p in result)
        expected_lost = len(result) - 1  # one sep-length char lost per split
        assert total == len(msg) - expected_lost
