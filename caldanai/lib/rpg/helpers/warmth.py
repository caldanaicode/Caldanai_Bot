"""Social-warmth model.

Players can tune how warmly they receive (and attempt) social gestures
from other players. Five levels — ``cold | cool | neutral | warm |
hot`` — govern both the *acceptance* beat (what the target does with
the gesture) and the *intent* beat (what the actor was going for).

Resolution order for a command ``cmd`` from actor A → target B:

1. **Target's acceptance (authoritative)**:
   ``B.social.per_player[str(A.id)][cmd]`` →
   ``B.social.defaults[cmd]`` →
   system default for ``cmd``.
2. **Actor's intent (flavor-only)**:
   ``A.social.per_player[str(B.id)][cmd]`` →
   ``A.social.defaults[cmd]`` →
   system default for ``cmd``.

The target's preference always wins the acceptance beat so privacy
holds: the actor never sees "they rejected my warm hug" — they only
see their own attempt paired with the target's chosen outcome. The
actor's intent colors the attempt narration so a warm-intent hugger
still reads as warmly trying even if rebuffed.

Per-user keys are stored as *strings* (``str(discord_user_id)``) so
MongoDB doesn't have to juggle the 64-bit ints as JSON numbers.
"""

from enum import StrEnum
from typing import Any, Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Canonical levels
# ---------------------------------------------------------------------------
#
# ``StrEnum`` so members are both enum values (iterable, pattern-
# matchable) *and* plain strings — they interop with dict lookups
# and Mongo-backed JSON payloads without a ``.value`` dance. The
# enum IS the canonical set; there's no parallel tuple / alias map
# to drift out of sync.


class Warmth(StrEnum):
    COLD = "cold"
    COOL = "cool"
    NEUTRAL = "neutral"
    WARM = "warm"
    HOT = "hot"

    @classmethod
    def from_str(cls, value: Any) -> Optional["Warmth"]:
        """Tolerant parse for user / stored input. Accepts the five
        canonical names (case-insensitive, whitespace-tolerant) and
        returns the corresponding member. Returns ``None`` for any
        other input — callers surface a user-facing error listing
        the options rather than guessing a bucket."""
        if not isinstance(value, str):
            return None
        try:
            return cls(value.strip().lower())
        except ValueError:
            return None


# ---------------------------------------------------------------------------
# System defaults per command
# ---------------------------------------------------------------------------
#
# Used when a player hasn't set their own default. Keep this map
# sparse — commands not in the map fall back to ``Warmth.NEUTRAL`` so
# the resolver never raises on an unknown command.

SYSTEM_DEFAULTS: Dict[str, Warmth] = {
    "hug":       Warmth.COOL,     # Celowin-default: inquisitive brow-raise sidestep.
    "high_five": Warmth.NEUTRAL,  # a moment of hesitation before it lands.
    "fistbump":  Warmth.NEUTRAL,
    # V2 interactive verbs. Defaults tuned per-verb to match how each
    # gesture reads in public: respectful acknowledgements (salute,
    # nod, wink) resolve NEUTRAL; a comfort offer defaults WARM because
    # refusing tender reassurance is the exception; pokes and tickles
    # trend COOL (tolerated rarely, annoying usually); glares, shanks,
    # and taunts default COLD because the gesture is hostile or mock-
    # hostile by nature and most players will want to refuse the
    # invitation to play along unless they've opted in.
    "salute":    Warmth.NEUTRAL,
    "comfort":   Warmth.WARM,
    "poke":      Warmth.COOL,
    "nod":       Warmth.NEUTRAL,
    "glare":     Warmth.COLD,
    "shank":     Warmth.COLD,
    "tickle":    Warmth.COOL,
    "taunt":     Warmth.COLD,
    "wink":      Warmth.NEUTRAL,
    "thank":     Warmth.WARM,     # gratitude is warm by default; refusing it is the exception
    # Presence verbs — warmth-aware path lives parallel to social
    # cog's flow (presence cog command body still emits self-directed
    # bare flavor; mention/token paths route through _NARRATION_POOLS
    # via Player.handle_verb's existing lookup). See
    # ``project_presence_verbs_with_target.md`` V2 direction.
    "lean":      Warmth.NEUTRAL,  # quiet companionable presence; refusing is opt-out
    "sit":       Warmth.NEUTRAL,
    "rest":      Warmth.NEUTRAL,
    "ponder":    Warmth.NEUTRAL,  # considering someone in thought; default-neutral acceptance
    "tend":      Warmth.WARM,     # small caretaking — most accept; brushing dirt off a sleeve is intimate
    "bite":      Warmth.NEUTRAL,  # ambiguous-emotion verb; default to neutral so adverb-coloring (backlogged) sets the read
}


# ---------------------------------------------------------------------------
# Registered commands — the short list of verbs the warmth system
# currently knows about. Exposed so the ``$warmth`` command can
# validate user input (and so help text can enumerate them).
# ---------------------------------------------------------------------------

SOCIAL_COMMANDS: Tuple[str, ...] = (
    "hug",
    "high_five",
    "fistbump",
    "salute",
    "comfort",
    "poke",
    "nod",
    "glare",
    "shank",
    "tickle",
    "taunt",
    "wink",
    "thank",
    "lean",
    "sit",
    "rest",
    "ponder",
    "tend",
    "bite",
)


def is_known_command(cmd: str) -> bool:
    """``True`` if ``cmd`` is a registered warmth-aware social command.
    Case-insensitive; accepts canonical command names only. The
    command registry (``SOCIAL_COMMANDS``) is the single source of
    truth so new commands added to the cog become instantly
    addressable by ``$warmth`` without further plumbing."""
    return cmd.lower() in SOCIAL_COMMANDS


# ---------------------------------------------------------------------------
# Level parsing
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Social-dict accessors
# ---------------------------------------------------------------------------
#
# The ``social`` field on a Player is a plain dict:
#
#     {
#       "defaults":   {"<cmd>": "<level>"},
#       "per_player": {"<uid_str>": {"<cmd>": "<level>"}}
#     }
#
# Missing / malformed entries are tolerated everywhere — a stale save
# or partial write shouldn't brick the command.


def _get_social(player) -> Dict[str, Any]:
    """Return the player's ``social`` dict (or ``{}`` if unset). Does
    not mutate the player — read-only view suitable for resolvers."""
    return getattr(player, "social", None) or {}


def _safe_level(raw: Any) -> Optional[Warmth]:
    """Cast a stored string to a :class:`Warmth`, returning ``None``
    for anything that isn't a canonical value. Defensive against
    stale / hand-edited saves."""
    if raw is None:
        return None
    try:
        return Warmth(raw)
    except ValueError:
        return None


def get_default(player, cmd: str) -> Optional[Warmth]:
    """Return the player's per-command default level, or ``None`` if
    they haven't set one."""
    social = _get_social(player)
    defaults = social.get("defaults") or {}
    return _safe_level(defaults.get(cmd))


def get_override(player, other_user_id: Optional[int], cmd: str) -> Optional[Warmth]:
    """Return the player's per-player override for ``cmd`` against
    ``other_user_id``, or ``None`` if none is set.

    ``other_user_id`` is an ``int`` (discord user id). ``None`` /
    falsy is short-circuited to ``None`` to prevent the "0" /
    "None" sentinel buckets from being consulted — actor-less
    creatures (monsters with no ``user_id``) would otherwise
    collide on a shared ``per_player["0"]`` slot and bleed one
    player's override into every monster-initiated resolution.
    """
    if not other_user_id:
        return None
    social = _get_social(player)
    per_player = social.get("per_player") or {}
    entry = per_player.get(str(other_user_id)) or {}
    return _safe_level(entry.get(cmd))


def resolve(
    target,
    actor,
    cmd: str,
) -> Tuple[Warmth, Warmth]:
    """Resolve ``(acceptance, intent)`` levels for ``cmd`` when
    ``actor`` uses it on ``target``.

    Acceptance (what happens) is governed by the target; intent (how
    the actor reads as attempting) is governed by the actor. Both
    fall back through per-player → per-command default → system
    default → ``Warmth.NEUTRAL``.

    Safe on bare ``Creature`` actors / targets that lack a ``social``
    field (e.g. monsters being hugged by a player): the accessors
    tolerate the missing attribute and the call degrades to the
    system default.
    """
    system_default = SYSTEM_DEFAULTS.get(cmd, Warmth.NEUTRAL)

    # Pass raw ``user_id`` (may be ``None`` for actor-less creatures).
    # ``get_override`` short-circuits on falsy ids so missing-uid
    # monsters don't collide on a ``per_player["0"]`` sentinel.
    actor_uid = getattr(actor, "user_id", None)
    target_uid = getattr(target, "user_id", None)

    acceptance = (
        get_override(target, actor_uid, cmd)
        or get_default(target, cmd)
        or system_default
    )
    intent = (
        get_override(actor, target_uid, cmd)
        or get_default(actor, cmd)
        or system_default
    )
    return acceptance, intent


# ---------------------------------------------------------------------------
# Mutations — produce a *new* social dict rather than mutating in
# place, so callers can decide whether to write back + set dirty.
# ---------------------------------------------------------------------------


def _ensure_shape(social: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of ``social`` guaranteed to have both sub-dicts.
    Missing / wrong-typed slots reset to empty dicts (defensive
    against corrupted saves)."""
    result: Dict[str, Any] = {
        "defaults":   {},
        "per_player": {},
    }
    if isinstance(social, dict):
        if isinstance(social.get("defaults"), dict):
            result["defaults"] = dict(social["defaults"])
        if isinstance(social.get("per_player"), dict):
            # shallow-copy the inner maps too so mutation in one slot
            # doesn't bleed into the other.
            result["per_player"] = {
                str(k): dict(v) if isinstance(v, dict) else {}
                for k, v in social["per_player"].items()
            }
    return result


def set_default(player, cmd: str, level: Warmth) -> None:
    """Set the player's per-command default to ``level``. Marks the
    player dirty. ``level`` must be a canonical value (use
    :meth:`Warmth.from_str` first)."""
    social = _ensure_shape(_get_social(player))
    # Stored as a plain string so the BSON document stays
    # enum-agnostic — Mongo doesn't know about ``Warmth``.
    social["defaults"][cmd] = str(level)
    player.social = social
    player.is_dirty = True


def clear_default(player, cmd: str) -> bool:
    """Remove the player's default for ``cmd``. Returns ``True`` if a
    value was removed, ``False`` if there was nothing to clear."""
    social = _ensure_shape(_get_social(player))
    if cmd in social["defaults"]:
        del social["defaults"][cmd]
        player.social = social
        player.is_dirty = True
        return True
    return False


def set_override(player, other_user_id: int, cmd: str, level: Warmth) -> None:
    """Set the player's per-player override for ``cmd`` against
    ``other_user_id``. ``level`` must be canonical."""
    social = _ensure_shape(_get_social(player))
    key = str(other_user_id)
    bucket = social["per_player"].setdefault(key, {})
    bucket[cmd] = str(level)
    player.social = social
    player.is_dirty = True


def clear_override(player, other_user_id: int, cmd: str) -> bool:
    """Remove the player's per-player override for ``cmd`` against
    ``other_user_id``. Returns ``True`` if a value was removed.
    Cleans up the per-player entry when it becomes empty so the
    saved document stays tidy."""
    social = _ensure_shape(_get_social(player))
    key = str(other_user_id)
    bucket = social["per_player"].get(key) or {}
    if cmd not in bucket:
        return False
    del bucket[cmd]
    if bucket:
        social["per_player"][key] = bucket
    else:
        # Drop empty per-player bucket so the document doesn't
        # accumulate noise for every player that was ever overridden
        # and then cleared.
        social["per_player"].pop(key, None)
    player.social = social
    player.is_dirty = True
    return True


def summarize(player) -> Dict[str, Any]:
    """Return a defensive copy of the player's social dict, shape-
    normalized. Safe to hand to a presentation layer — the caller
    can't accidentally mutate the Player by writing to the result."""
    return _ensure_shape(_get_social(player))
