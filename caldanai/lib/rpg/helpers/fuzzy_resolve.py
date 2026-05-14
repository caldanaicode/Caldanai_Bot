"""Dispatcher for command-declared target-type resolution.

A command names the target types it accepts, in priority order; the
dispatcher walks them and returns the first non-None result, or
``None`` if every converter misses. The command decides what to do
with the ``None`` — silent fall-through to a no-target flavor pool,
italic-text "nothing here by that name" line, hard error, whatever
fits the verb's UX. Returning ``None`` instead of raising is the
contract that makes silent-fallback shapes possible without
``try / except BadArgument`` at every call site.

Call site shape::

    haunted = await fuzzy_resolve(
        ctx, target, MonsterConverter, PlayerConverter,
    )
    if haunted is None:
        # fall through to no-target ambient flavor
        ...

The dispatcher itself stays trivially simple — one string, N target
types, first match wins. Per-verb parsing complexity (splitting on
``@``, peeling tokens, handling variadic args) lives at the call
site. The burden is on the caller, not on the converter or the
dispatcher.

Each converter type must expose an ``async try_convert(ctx,
argument) -> Optional[T]`` method that returns the resolved object
on a hit and ``None`` on any miss (no-match, no game state,
ambiguous, underlying converter raised BadArgument, etc.).
``try_convert`` raising any exception — ``BadArgument`` included —
is a contract violation: the dispatcher propagates it rather than
swallowing, so the failing converter gets noticed instead of
silently coercing into a miss.
"""

from typing import Any, Optional


async def fuzzy_resolve(ctx, argument: str, *types) -> Optional[Any]:
    """Walk ``types`` in priority order; return the first
    converter's resolved object, or ``None`` if all miss.

    Empty ``argument`` short-circuits to ``None`` without
    instantiating any converter — saves the per-converter
    "is the argument empty?" guard.
    """
    if not argument or not types:
        return None
    for converter_type in types:
        result = await converter_type().try_convert(ctx, argument)
        if result is not None:
            return result
    return None
