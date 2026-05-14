"""Tests for the :func:`fuzzy_resolve` dispatcher in isolation.

The dispatcher walks a list of converter types in priority order
and returns the first non-None ``try_convert`` result, or ``None``
if every converter misses. These tests pin the contract using
small mock converter classes — keeping the dispatcher tests
independent of any one converter's pool / game / state shape.

Per-converter ``try_convert`` behaviour is covered in
:mod:`tests.test_converters`. Per-command integration (silent
fall-through into a no-target ambient flavor pool) is covered in
per-command tests once the migration lands.
"""

from unittest.mock import MagicMock

import pytest

from caldanai.lib.rpg.helpers.fuzzy_resolve import fuzzy_resolve


# ---------------------------------------------------------------------------
# Mock converter classes — each one exposes only ``try_convert``, the
# only method the dispatcher touches. No game / no ctx state needed.
# ---------------------------------------------------------------------------


class _AlwaysHitsWith:
    """Mock converter that returns a fixed sentinel on every call."""

    sentinel = None  # set per-subclass

    async def try_convert(self, ctx, argument):
        return type(self).sentinel


class _AlwaysMisses:
    async def try_convert(self, ctx, argument):
        return None


class _HitsOnArgument:
    """Returns the argument string itself — useful for asserting which
    converter actually got walked."""

    async def try_convert(self, ctx, argument):
        return f"matched:{argument}"


def _recording_converter(name: str, *, hit: bool, log: list):
    """Build a converter class that appends its name to ``log`` when
    invoked. Lets a test assert that a second converter was NOT
    called when the first one already hit."""

    class _Recorder:
        async def try_convert(self, ctx, argument):
            log.append(name)
            return f"hit:{name}" if hit else None

    _Recorder.__name__ = f"_Recorder<{name}>"
    return _Recorder


# ---------------------------------------------------------------------------
# Dispatcher contract
# ---------------------------------------------------------------------------


class TestFuzzyResolveDispatcher:
    @pytest.mark.asyncio
    async def test_single_type_hit_returns_match(self):
        class _Hit(_AlwaysHitsWith):
            sentinel = "alice"

        result = await fuzzy_resolve(MagicMock(), "alice", _Hit)
        assert result == "alice"

    @pytest.mark.asyncio
    async def test_single_type_miss_returns_none(self):
        result = await fuzzy_resolve(MagicMock(), "alice", _AlwaysMisses)
        assert result is None

    @pytest.mark.asyncio
    async def test_first_type_hits_short_circuits_second(self):
        log: list = []
        First = _recording_converter("first", hit=True, log=log)
        Second = _recording_converter("second", hit=True, log=log)

        result = await fuzzy_resolve(MagicMock(), "bob", First, Second)
        assert result == "hit:first"
        assert log == ["first"], (
            "Second converter must not run once the first one hit."
        )

    @pytest.mark.asyncio
    async def test_first_misses_second_hits(self):
        log: list = []
        First = _recording_converter("first", hit=False, log=log)
        Second = _recording_converter("second", hit=True, log=log)

        result = await fuzzy_resolve(MagicMock(), "bob", First, Second)
        assert result == "hit:second"
        assert log == ["first", "second"]

    @pytest.mark.asyncio
    async def test_all_miss_returns_none(self):
        log: list = []
        First = _recording_converter("first", hit=False, log=log)
        Second = _recording_converter("second", hit=False, log=log)

        result = await fuzzy_resolve(MagicMock(), "bob", First, Second)
        assert result is None
        assert log == ["first", "second"]

    @pytest.mark.asyncio
    async def test_empty_argument_skips_iteration(self):
        log: list = []
        First = _recording_converter("first", hit=True, log=log)

        result = await fuzzy_resolve(MagicMock(), "", First)
        assert result is None
        assert log == [], (
            "Empty-argument short-circuit must not instantiate "
            "converters or call try_convert."
        )

    @pytest.mark.asyncio
    async def test_no_types_returns_none(self):
        result = await fuzzy_resolve(MagicMock(), "alice")
        assert result is None

    @pytest.mark.asyncio
    async def test_non_badargument_exception_propagates(self):
        class _Boom:
            async def try_convert(self, ctx, argument):
                raise RuntimeError("converter blew up")

        with pytest.raises(RuntimeError, match="converter blew up"):
            await fuzzy_resolve(MagicMock(), "alice", _Boom)

    @pytest.mark.asyncio
    async def test_falsy_non_none_result_is_treated_as_hit(self):
        """The dispatcher's "miss" sentinel is ``None`` specifically,
        not falsy-in-general. An empty list / 0 / False from a
        ``try_convert`` is a legitimate hit and must be returned
        unchanged. Pins the ``is not None`` semantic against an
        accidental truthiness check."""

        class _ReturnsEmptyList:
            async def try_convert(self, ctx, argument):
                return []

        result = await fuzzy_resolve(
            MagicMock(), "alice", _ReturnsEmptyList,
        )
        assert result == []
        assert result is not None
