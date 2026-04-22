"""Tests for the social-warmth system.

Covers:
    - :mod:`caldanai.lib.rpg.helpers.warmth` resolver + mutators +
      level coercion.
    - :mod:`caldanai.lib.cogs.rpg_social_commands`
      ``$warmth`` command routing, DM privacy invariants, and
      hug / high_five / fistbump narration composition.

Player persistence of the ``social`` field is tested alongside the
existing to_dict / from_dict pins in ``test_player.py``.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from caldanai.lib.cogs.rpg_social_commands import (
    RpgSocialCommands,
    _HUG_ACCEPTANCE_BEATS,
    _HUG_INTENT_BEATS,
    _FISTBUMP_ACCEPTANCE_BEATS,
    _FISTBUMP_INTENT_BEATS,
    _HIGH_FIVE_ACCEPTANCE_BEATS,
    _HIGH_FIVE_INTENT_BEATS,
    _render_social,
)
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers import warmth
from caldanai.lib.rpg.helpers.parser import parse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_player(name="Alice", uid=42):
    """A real Player with a minimal shape — parser-compatible and
    carries a ``social`` dict. Attached to a mock member so command
    handlers that poke ``player.member`` don't explode."""
    from bson.objectid import ObjectId

    p = Player(
        pid=ObjectId(),
        gid=100,
        uid=uid,
        weight_limit=100,
        clarks=0,
        defense=6,
        dodge=6,
        health=20,
        health_max=20,
        gender="female",
        pronouns="she,her,hers,her",
    )
    member = MagicMock()
    member.id = uid
    member.display_name = name
    p.member = member
    p.name = name
    return p


def _make_ctx(author, mentions=None, guild=True):
    ctx = MagicMock()
    ctx.author = author.member
    ctx.prefix = "$"
    ctx.guild = MagicMock() if guild else None
    ctx.channel = MagicMock()
    ctx.message = MagicMock()
    ctx.message.mentions = mentions or []
    ctx.invoked_with = "warmth"
    return ctx


def _dispatched(dispatcher_mock):
    """Flatten Dispatcher.add(...) calls into a list of (channel, text)
    pairs. Useful when a test wants to verify which channel a message
    went to (channel vs. DM / User)."""
    pairs = []
    for call in dispatcher_mock.add.call_args_list:
        args = call.args
        channel = args[0] if args else None
        text = args[1] if len(args) > 1 else call.kwargs.get("text")
        pairs.append((channel, text))
    return pairs


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class TestWarmthResolution:
    def test_both_empty_fall_back_to_system_default(self):
        """No preferences anywhere → both acceptance and intent are
        the system default for the command."""
        actor = _make_player("Alice", uid=1)
        target = _make_player("Bob", uid=2)
        acceptance, intent = warmth.resolve(target, actor, "hug")
        assert acceptance == warmth.SYSTEM_DEFAULTS["hug"]
        assert intent == warmth.SYSTEM_DEFAULTS["hug"]

    def test_unknown_command_defaults_to_neutral(self):
        """Commands not in SYSTEM_DEFAULTS resolve to neutral on both
        sides so the resolver never raises for new verbs."""
        actor = _make_player(uid=1)
        target = _make_player(uid=2)
        acceptance, intent = warmth.resolve(target, actor, "bloop")
        assert acceptance == warmth.Warmth.NEUTRAL
        assert intent == warmth.Warmth.NEUTRAL

    def test_target_default_wins_acceptance(self):
        actor = _make_player("Alice", uid=1)
        target = _make_player("Bob", uid=2)
        warmth.set_default(target, "hug", warmth.Warmth.WARM)
        acceptance, _ = warmth.resolve(target, actor, "hug")
        assert acceptance == warmth.Warmth.WARM

    def test_actor_default_wins_intent(self):
        actor = _make_player("Alice", uid=1)
        target = _make_player("Bob", uid=2)
        warmth.set_default(actor, "hug", warmth.Warmth.HOT)
        _, intent = warmth.resolve(target, actor, "hug")
        assert intent == warmth.Warmth.HOT

    def test_per_player_override_beats_default_on_acceptance(self):
        actor = _make_player("Alice", uid=1)
        target = _make_player("Bob", uid=2)
        warmth.set_default(target, "hug", warmth.Warmth.WARM)
        warmth.set_override(target, actor.user_id, "hug", warmth.Warmth.COLD)
        acceptance, _ = warmth.resolve(target, actor, "hug")
        assert acceptance == warmth.Warmth.COLD

    def test_per_player_override_beats_default_on_intent(self):
        actor = _make_player("Alice", uid=1)
        target = _make_player("Bob", uid=2)
        warmth.set_default(actor, "hug", warmth.Warmth.NEUTRAL)
        warmth.set_override(actor, target.user_id, "hug", warmth.Warmth.HOT)
        _, intent = warmth.resolve(target, actor, "hug")
        assert intent == warmth.Warmth.HOT

    def test_override_is_per_other_player_not_shared(self):
        """An override for player B must not apply when the actor is
        player C. Per-player means per-PER-player."""
        actor_b = _make_player("Bob", uid=2)
        actor_c = _make_player("Cam", uid=3)
        target = _make_player("Alice", uid=1)
        warmth.set_default(target, "hug", warmth.Warmth.NEUTRAL)
        warmth.set_override(target, actor_b.user_id, "hug", warmth.Warmth.HOT)

        acc_from_b, _ = warmth.resolve(target, actor_b, "hug")
        acc_from_c, _ = warmth.resolve(target, actor_c, "hug")
        assert acc_from_b == warmth.Warmth.HOT
        assert acc_from_c == warmth.Warmth.NEUTRAL

    def test_missing_social_field_is_tolerated(self):
        """A creature / monster without a ``social`` attribute (or
        with it set to None) must still resolve cleanly — the
        resolver degrades to system defaults."""
        actor = Creature(name="Wolf", atk="1d4", defense=0, dodge=5, health_max=10)
        target = _make_player("Alice", uid=1)
        acceptance, intent = warmth.resolve(target, actor, "hug")
        assert acceptance == warmth.SYSTEM_DEFAULTS["hug"]
        assert intent == warmth.SYSTEM_DEFAULTS["hug"]

    def test_social_field_with_defaults_only_still_resolves(self):
        """Partial social dicts — e.g. defaults set, no per_player —
        must resolve without KeyError. Defensive against legacy
        saves."""
        actor = _make_player("Alice", uid=1)
        target = _make_player("Bob", uid=2)
        # Simulate a doc with only one sub-key
        target.social = {"defaults": {"hug": warmth.Warmth.WARM}}
        acceptance, _ = warmth.resolve(target, actor, "hug")
        assert acceptance == warmth.Warmth.WARM

    def test_actorless_creature_does_not_collide_on_zero_bucket(self):
        """Regression: actor-less creatures (no ``user_id`` → None)
        must not pick up an override keyed under ``per_player["0"]``
        on the target. Previously ``get_override`` was called with
        ``getattr(actor, "user_id", None) or 0`` which routed every
        actor-less source to the same "0" bucket, so any target
        who'd once overridden against uid 0 would bleed that
        override into every monster-initiated social resolution.
        """
        monster_a = Creature(name="Wolf", atk="1d4", defense=0, dodge=5, health_max=10)
        monster_b = Creature(name="Bear", atk="1d4", defense=0, dodge=5, health_max=10)
        target = _make_player("Alice", uid=1)
        # Planted override against uid 0 — if either monster leaked
        # into the "0" bucket, they'd hit this.
        target.social = {
            "defaults": {},
            "per_player": {"0": {"hug": warmth.Warmth.HOT}},
        }

        acceptance_a, _ = warmth.resolve(target, monster_a, "hug")
        acceptance_b, _ = warmth.resolve(target, monster_b, "hug")

        # Neither monster should have tripped the "0" override;
        # acceptance should fall through to the system default.
        assert acceptance_a == warmth.SYSTEM_DEFAULTS["hug"]
        assert acceptance_b == warmth.SYSTEM_DEFAULTS["hug"]

    def test_get_override_returns_none_for_falsy_uid(self):
        """Direct unit test on the helper itself. Redundant with the
        collision test above but pins the short-circuit so someone
        can't "optimize" it away."""
        p = _make_player(uid=1)
        p.social = {
            "defaults": {},
            "per_player": {"0": {"hug": warmth.Warmth.HOT}},
        }
        assert warmth.get_override(p, None, "hug") is None
        assert warmth.get_override(p, 0, "hug") is None


# ---------------------------------------------------------------------------
# Mutators
# ---------------------------------------------------------------------------


class TestWarmthMutators:
    def test_set_default_marks_dirty(self):
        p = _make_player()
        p.is_dirty = False
        warmth.set_default(p, "hug", warmth.Warmth.WARM)
        assert p.is_dirty is True
        assert p.social["defaults"]["hug"] == warmth.Warmth.WARM

    def test_clear_default_returns_true_when_removed(self):
        p = _make_player()
        warmth.set_default(p, "hug", warmth.Warmth.WARM)
        removed = warmth.clear_default(p, "hug")
        assert removed is True
        assert "hug" not in p.social.get("defaults", {})

    def test_clear_default_returns_false_when_absent(self):
        p = _make_player()
        assert warmth.clear_default(p, "hug") is False

    def test_set_override_stores_under_string_key(self):
        """User ids go into the dict as strings so Mongo doesn't
        choke on large ints."""
        p = _make_player()
        warmth.set_override(p, 12345, "hug", warmth.Warmth.HOT)
        assert "12345" in p.social["per_player"]
        assert p.social["per_player"]["12345"]["hug"] == warmth.Warmth.HOT

    def test_clear_override_cleans_empty_buckets(self):
        """Once the last command override is removed for a user, the
        per-player bucket itself should drop so the document doesn't
        grow forever."""
        p = _make_player()
        warmth.set_override(p, 12345, "hug", warmth.Warmth.HOT)
        warmth.clear_override(p, 12345, "hug")
        assert "12345" not in p.social["per_player"]


# ---------------------------------------------------------------------------
# Level coercion
# ---------------------------------------------------------------------------


class TestLevelCoercion:
    @pytest.mark.parametrize("raw, expected", [
        ("cold", warmth.Warmth.COLD),
        ("COLD", warmth.Warmth.COLD),
        ("cool", warmth.Warmth.COOL),
        ("neutral", warmth.Warmth.NEUTRAL),
        ("  warm ", warmth.Warmth.WARM),
        ("hot", warmth.Warmth.HOT),
    ])
    def test_accepts_canonical_case_insensitive(self, raw, expected):
        """Only the five canonical names are accepted — whitespace
        and case are tolerated, but aliases / synonyms are not (a
        deliberate choice: keeping the vocabulary small means typos
        surface as errors instead of resolving to the wrong bucket)."""
        assert warmth.Warmth.from_str(raw) == expected

    @pytest.mark.parametrize("raw", [
        # Non-canonical words — previously alias-mapped, now rejected.
        "friendly", "aloof", "meh", "fiery", "ardent",
        # Typos / near-misses.
        "hottish", "lukewarm", "fire", "scorching",
        # Empty / whitespace-only.
        "", "  ", "-1",
    ])
    def test_rejects_unknown_levels(self, raw):
        assert warmth.Warmth.from_str(raw) is None

    def test_rejects_non_string(self):
        assert warmth.Warmth.from_str(None) is None
        assert warmth.Warmth.from_str(5) is None


# ---------------------------------------------------------------------------
# Narration pools
# ---------------------------------------------------------------------------


class TestNarrationPools:
    """Each (intent × acceptance) beat pool must exist for every
    level and render cleanly through the parser."""

    @pytest.mark.parametrize("cmd, pool_name, pools", [
        ("hug", "intent", _HUG_INTENT_BEATS),
        ("hug", "acceptance", _HUG_ACCEPTANCE_BEATS),
        ("high_five", "intent", _HIGH_FIVE_INTENT_BEATS),
        ("high_five", "acceptance", _HIGH_FIVE_ACCEPTANCE_BEATS),
        ("fistbump", "intent", _FISTBUMP_INTENT_BEATS),
        ("fistbump", "acceptance", _FISTBUMP_ACCEPTANCE_BEATS),
    ])
    def test_every_level_has_nonempty_pool(self, cmd, pool_name, pools):
        for level in warmth.Warmth:
            assert level in pools, f"{cmd} {pool_name} missing {level}"
            assert pools[level], f"{cmd} {pool_name} {level} is empty"
            assert len(pools[level]) >= 3, (
                f"{cmd} {pool_name} {level} needs >=3 variants"
            )

    @pytest.mark.parametrize("pools", [
        _HUG_INTENT_BEATS, _HUG_ACCEPTANCE_BEATS,
        _HIGH_FIVE_INTENT_BEATS, _HIGH_FIVE_ACCEPTANCE_BEATS,
        _FISTBUMP_INTENT_BEATS, _FISTBUMP_ACCEPTANCE_BEATS,
    ])
    def test_every_line_parses_cleanly(self, pools):
        """Every narration line must resolve @1 / @2 tokens without
        leaving a literal token in the output. Catches typos like
        @2n (missing form) or @1ss (stray char)."""
        actor = _make_player("Alice", uid=1)
        target = _make_player("Bob", uid=2)
        for level, lines in pools.items():
            for line in lines:
                rendered = parse(line, actor, target)
                assert "@1" not in rendered, f"stray @1 in: {rendered!r}"
                assert "@2" not in rendered, f"stray @2 in: {rendered!r}"

    def test_cold_acceptance_reads_as_rejection_for_hug(self):
        """The target-wins-asymmetry invariant: cold-acceptance
        always ends in rejection regardless of how the actor tried.
        Every line in the cold acceptance pool must contain a
        rejection keyword — 'sidesteps', 'no', 'unimpressed', etc.
        Guards against accidentally softening a cold rebuff."""
        rejection_markers = (
            "sidestep", "no.", "unimpressed", "out of reach",
            "finds only air", "steps out of reach",
        )
        for line in _HUG_ACCEPTANCE_BEATS[warmth.Warmth.COLD]:
            lower = line.lower()
            assert any(m in lower for m in rejection_markers), (
                f"cold-accept hug line lacks rejection marker: {line!r}"
            )


# ---------------------------------------------------------------------------
# _render_social — asymmetric narration composition
# ---------------------------------------------------------------------------


class TestHugNarration:
    def test_self_target_short_circuits(self):
        """Warmth to self collapses to the gentle self-hug line —
        no cross-referencing against own preferences."""
        p = _make_player("Alice", uid=1)
        out = _render_social("hug", p, p)
        assert "alice" in out.lower()
        # Token-free
        assert "@1" not in out and "@2" not in out

    def test_warm_intent_cold_accept_ends_in_rejection(self):
        """Asymmetric worst-case: actor tried warmly, target
        rejects. The final clause (what the target did) must still
        be a rejection."""
        actor = _make_player("Alice", uid=1)
        target = _make_player("Bob", uid=2)
        warmth.set_default(actor, "hug", warmth.Warmth.WARM)
        warmth.set_default(target, "hug", warmth.Warmth.COLD)

        # Deterministic: pick the first line in each pool.
        with patch(
            "caldanai.lib.cogs.rpg_social_commands.choice",
            side_effect=lambda pool: pool[0],
        ):
            out = _render_social("hug", actor, target)

        # Intent clause comes from WARM intent pool.
        intent_line = parse(_HUG_INTENT_BEATS[warmth.Warmth.WARM][0], actor, target)
        # Acceptance clause comes from COLD acceptance pool.
        accept_line = parse(
            _HUG_ACCEPTANCE_BEATS[warmth.Warmth.COLD][0], actor, target
        )
        assert intent_line in out
        assert accept_line in out
        # The accept line carries the rejection, as enforced by
        # ``test_cold_acceptance_reads_as_rejection_for_hug``.

    def test_both_hot_is_reciprocal(self):
        actor = _make_player("Alice", uid=1)
        target = _make_player("Bob", uid=2)
        warmth.set_default(actor, "hug", warmth.Warmth.HOT)
        warmth.set_default(target, "hug", warmth.Warmth.HOT)

        with patch(
            "caldanai.lib.cogs.rpg_social_commands.choice",
            side_effect=lambda pool: pool[0],
        ):
            out = _render_social("hug", actor, target)

        intent_line = parse(_HUG_INTENT_BEATS[warmth.Warmth.HOT][0], actor, target)
        accept_line = parse(_HUG_ACCEPTANCE_BEATS[warmth.Warmth.HOT][0], actor, target)
        assert intent_line in out
        assert accept_line in out


# ---------------------------------------------------------------------------
# $warmth command — DM routing, set/clear, privacy
# ---------------------------------------------------------------------------


class TestWarmthCommand:
    @pytest.mark.asyncio
    async def test_bare_warmth_shows_current_settings_via_dm(self):
        cog = RpgSocialCommands(bot=MagicMock())
        player = _make_player("Alice", uid=1)
        ctx = _make_ctx(player)

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(MagicMock(), player)),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands.Dispatcher",
            ) as dispatcher,
        ):
            await cog.warmth.callback(cog, ctx)

        # Must route the settings body to the author (DM). The
        # channel ack goes through Dispatcher.add(ctx, ...) which
        # the real Dispatcher unwraps to ctx.channel — with our
        # mock, ``ctx`` shows up verbatim as the destination arg.
        targets = [c[0] for c in _dispatched(dispatcher)]
        assert ctx.author in targets, "settings body must be DM'd"
        # Channel ack present (ctx passed through; Dispatcher would
        # unwrap to ctx.channel in production).
        assert ctx in targets

    @pytest.mark.asyncio
    async def test_warmth_set_default_persists_and_replies_in_channel(self):
        """Server-invoked ``$warmth set`` routes the confirmation to
        the invocation channel (the action was already public, so
        leaking it into DMs just adds friction). The private settings
        body stays DM-only — that's covered by the bare-``$warmth``
        test, not this one."""
        cog = RpgSocialCommands(bot=MagicMock())
        player = _make_player("Alice", uid=1)
        ctx = _make_ctx(player)  # guild=True by default

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(MagicMock(), player)),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands.Dispatcher",
            ) as dispatcher,
        ):
            await cog.warmth_set.callback(cog, ctx, cmd="hug", level="warm")

        # Persisted
        assert player.social["defaults"]["hug"] == warmth.Warmth.WARM
        assert player.is_dirty is True

        # Confirmation went to the channel (ctx), not the invoker's DM.
        pairs = _dispatched(dispatcher)
        channel_msgs = [t for (c, t) in pairs if c is ctx]
        dm_msgs = [t for (c, t) in pairs if c is ctx.author]
        assert any("warm" in (t or "").lower() for t in channel_msgs), (
            f"expected channel confirmation; got channel={channel_msgs}, dm={dm_msgs}"
        )
        assert not dm_msgs, (
            f"did not expect a DM on server invocation; got: {dm_msgs}"
        )

    @pytest.mark.asyncio
    async def test_warmth_set_from_dm_replies_in_dm(self):
        """DM-invoked ``$warmth set`` routes the confirmation back
        to the same DM (there's no channel to fall back to)."""
        cog = RpgSocialCommands(bot=MagicMock())
        player = _make_player("Alice", uid=1)
        ctx = _make_ctx(player, guild=False)

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(MagicMock(), player)),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands.Dispatcher",
            ) as dispatcher,
        ):
            await cog.warmth_set.callback(cog, ctx, cmd="hug", level="warm")

        pairs = _dispatched(dispatcher)
        dm_msgs = [t for (c, t) in pairs if c is ctx.author]
        assert any("warm" in (t or "").lower() for t in dm_msgs), (
            f"expected DM confirmation; got pairs={pairs}"
        )

    @pytest.mark.asyncio
    async def test_warmth_set_per_player_override(self):
        cog = RpgSocialCommands(bot=MagicMock())
        player = _make_player("Alice", uid=1)
        ctx = _make_ctx(player)
        other = MagicMock()
        other.id = 999
        other.display_name = "Bob"
        other.bot = False

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(MagicMock(), player)),
            ),
            patch("caldanai.lib.cogs.rpg_social_commands.Dispatcher"),
        ):
            await cog.warmth_set.callback(
                cog, ctx, cmd="hug", level="hot", who=other,
            )

        assert player.social["per_player"]["999"]["hug"] == warmth.Warmth.HOT

    @pytest.mark.asyncio
    async def test_warmth_set_rejects_self_target(self):
        """Setting warmth toward yourself is a dead end (the $hug
        self-target path short-circuits regardless of warmth), so the
        handler should refuse rather than silently store a useless
        override."""
        cog = RpgSocialCommands(bot=MagicMock())
        player = _make_player("Alice", uid=1)
        ctx = _make_ctx(player)
        # Same id as the invoker.
        self_mention = MagicMock()
        self_mention.id = ctx.author.id
        self_mention.display_name = "Alice"
        self_mention.bot = False

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(MagicMock(), player)),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands.Dispatcher",
            ) as dispatcher,
        ):
            await cog.warmth_set.callback(
                cog, ctx, cmd="hug", level="hot", who=self_mention,
            )

        # Nothing should have been stored.
        assert player.social.get("per_player", {}).get(str(ctx.author.id)) is None
        # Refusal went to the invocation channel (guild-invoked).
        channel_msgs = [t for (c, t) in _dispatched(dispatcher) if c is ctx]
        assert any(
            t and "yourself" in (t or "").lower()
            for t in channel_msgs
        ), f"expected self-target rejection in channel; got: {channel_msgs}"

    @pytest.mark.asyncio
    async def test_warmth_set_rejects_bot_target(self):
        """Setting warmth toward the bot is a dead end (the $hug
        bot-mention path is a hardcoded scripted reply, warmth never
        consulted). Refuse rather than save a useless override."""
        cog = RpgSocialCommands(bot=MagicMock())
        player = _make_player("Alice", uid=1)
        ctx = _make_ctx(player)
        bot_mention = MagicMock()
        bot_mention.id = 424242
        bot_mention.display_name = "Caldanai Test"
        bot_mention.bot = True  # the key flag

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(MagicMock(), player)),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands.Dispatcher",
            ) as dispatcher,
        ):
            await cog.warmth_set.callback(
                cog, ctx, cmd="hug", level="hot", who=bot_mention,
            )

        # Nothing should have been stored against the bot's id.
        assert player.social.get("per_player", {}).get(str(bot_mention.id)) is None
        # Refusal went to the invocation channel (guild-invoked).
        channel_msgs = [t for (c, t) in _dispatched(dispatcher) if c is ctx]
        assert any(
            t and "narrator" in (t or "").lower()
            for t in channel_msgs
        ), f"expected bot-target rejection in channel; got: {channel_msgs}"

    @pytest.mark.asyncio
    async def test_warmth_clear_default(self):
        cog = RpgSocialCommands(bot=MagicMock())
        player = _make_player("Alice", uid=1)
        warmth.set_default(player, "hug", warmth.Warmth.WARM)
        ctx = _make_ctx(player)

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(MagicMock(), player)),
            ),
            patch("caldanai.lib.cogs.rpg_social_commands.Dispatcher"),
        ):
            await cog.warmth_clear.callback(cog, ctx, cmd="hug")

        assert "hug" not in player.social.get("defaults", {})

    @pytest.mark.asyncio
    async def test_warmth_clear_per_player(self):
        cog = RpgSocialCommands(bot=MagicMock())
        player = _make_player("Alice", uid=1)
        warmth.set_override(player, 999, "hug", warmth.Warmth.HOT)
        ctx = _make_ctx(player)
        other = MagicMock()
        other.id = 999

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(MagicMock(), player)),
            ),
            patch("caldanai.lib.cogs.rpg_social_commands.Dispatcher"),
        ):
            await cog.warmth_clear.callback(cog, ctx, cmd="hug", who=other)

        assert "999" not in player.social.get("per_player", {})

    @pytest.mark.asyncio
    async def test_warmth_set_all_applies_default_across_every_command(self):
        """``$warmth set all <level>`` bulk-sets the default for
        every command in ``SOCIAL_COMMANDS``. Saves typing twelve
        separate invocations."""
        cog = RpgSocialCommands(bot=MagicMock())
        player = _make_player("Alice", uid=1)
        ctx = _make_ctx(player)

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(MagicMock(), player)),
            ),
            patch("caldanai.lib.cogs.rpg_social_commands.Dispatcher"),
        ):
            await cog.warmth_set.callback(
                cog, ctx, cmd="all", level="cold",
            )

        defaults = player.social.get("defaults", {})
        for cmd_name in warmth.SOCIAL_COMMANDS:
            assert defaults.get(cmd_name) == warmth.Warmth.COLD, (
                f"{cmd_name!r} not set by bulk"
            )

    @pytest.mark.asyncio
    async def test_warmth_set_all_with_player_applies_override_across_every_command(self):
        cog = RpgSocialCommands(bot=MagicMock())
        player = _make_player("Alice", uid=1)
        ctx = _make_ctx(player)
        other = MagicMock()
        other.id = 999
        other.display_name = "Bob"
        other.bot = False

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(MagicMock(), player)),
            ),
            patch("caldanai.lib.cogs.rpg_social_commands.Dispatcher"),
        ):
            await cog.warmth_set.callback(
                cog, ctx, cmd="all", level="hot", who=other,
            )

        per_player = player.social.get("per_player", {}).get("999", {})
        for cmd_name in warmth.SOCIAL_COMMANDS:
            assert per_player.get(cmd_name) == warmth.Warmth.HOT, (
                f"{cmd_name!r} override not set by bulk"
            )

    @pytest.mark.asyncio
    async def test_warmth_set_all_rejects_self_target(self):
        """Bulk-set still respects the self-target guard — iterating
        SOCIAL_COMMANDS against yourself would store 12 dead-end
        overrides. Refuse up front."""
        cog = RpgSocialCommands(bot=MagicMock())
        player = _make_player("Alice", uid=1)
        ctx = _make_ctx(player)
        self_mention = MagicMock()
        self_mention.id = ctx.author.id
        self_mention.display_name = "Alice"
        self_mention.bot = False

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(MagicMock(), player)),
            ),
            patch("caldanai.lib.cogs.rpg_social_commands.Dispatcher"),
        ):
            await cog.warmth_set.callback(
                cog, ctx, cmd="all", level="hot", who=self_mention,
            )

        assert player.social.get("per_player", {}).get(str(ctx.author.id)) is None

    @pytest.mark.asyncio
    async def test_warmth_set_all_rejects_bot_target(self):
        cog = RpgSocialCommands(bot=MagicMock())
        player = _make_player("Alice", uid=1)
        ctx = _make_ctx(player)
        bot_mention = MagicMock()
        bot_mention.id = 424242
        bot_mention.display_name = "Caldanai Test"
        bot_mention.bot = True

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(MagicMock(), player)),
            ),
            patch("caldanai.lib.cogs.rpg_social_commands.Dispatcher"),
        ):
            await cog.warmth_set.callback(
                cog, ctx, cmd="all", level="hot", who=bot_mention,
            )

        assert player.social.get("per_player", {}).get(str(bot_mention.id)) is None

    @pytest.mark.asyncio
    async def test_warmth_clear_all_default_wipes_every_command(self):
        cog = RpgSocialCommands(bot=MagicMock())
        player = _make_player("Alice", uid=1)
        for cmd_name in warmth.SOCIAL_COMMANDS:
            warmth.set_default(player, cmd_name, warmth.Warmth.WARM)
        ctx = _make_ctx(player)

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(MagicMock(), player)),
            ),
            patch("caldanai.lib.cogs.rpg_social_commands.Dispatcher"),
        ):
            await cog.warmth_clear.callback(cog, ctx, cmd="all")

        assert player.social.get("defaults") == {}

    @pytest.mark.asyncio
    async def test_warmth_clear_all_per_player_wipes_every_command(self):
        cog = RpgSocialCommands(bot=MagicMock())
        player = _make_player("Alice", uid=1)
        for cmd_name in warmth.SOCIAL_COMMANDS:
            warmth.set_override(player, 999, cmd_name, warmth.Warmth.HOT)
        ctx = _make_ctx(player)
        other = MagicMock()
        other.id = 999

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(MagicMock(), player)),
            ),
            patch("caldanai.lib.cogs.rpg_social_commands.Dispatcher"),
        ):
            await cog.warmth_clear.callback(cog, ctx, cmd="all", who=other)

        # Bucket for player 999 should be gone entirely (the per-cmd
        # ``clear_override`` drops empty buckets for doc tidiness).
        assert "999" not in player.social.get("per_player", {})

    @pytest.mark.asyncio
    async def test_warmth_clear_all_when_nothing_set_is_graceful(self):
        """A user who hasn't set anything should get a friendly DM
        noting there was nothing to clear — not an error."""
        cog = RpgSocialCommands(bot=MagicMock())
        player = _make_player("Alice", uid=1)
        ctx = _make_ctx(player)

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(MagicMock(), player)),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands.Dispatcher",
            ) as dispatcher,
        ):
            await cog.warmth_clear.callback(cog, ctx, cmd="all")

        # Guild-invoked → response lands in channel, not DM.
        channel_msgs = [
            t for (c, t) in _dispatched(dispatcher) if c is ctx
        ]
        assert any("nothing to clear" in (t or "").lower() for t in channel_msgs)

    @pytest.mark.asyncio
    async def test_warmth_clear_bare_mention_routes_to_clear_all_for_player(self):
        """``$warmth clear @player`` — a common mis-type where the
        user omits the cmd arg and the mention lands in ``cmd``.
        Natural intent is "drop every per-player override I have for
        this player", so the handler auto-routes to
        ``clear all @player`` instead of echoing the raw mention tag
        back as an unknown command."""
        cog = RpgSocialCommands(bot=MagicMock())
        player = _make_player("Alice", uid=1)
        # Seed two overrides for target 999 so we can confirm the
        # wildcard sweep actually fires.
        warmth.set_override(player, 999, "hug", warmth.Warmth.HOT)
        warmth.set_override(player, 999, "salute", warmth.Warmth.COLD)
        ctx = _make_ctx(player)
        target_member = MagicMock()
        target_member.id = 999
        ctx.guild.get_member = MagicMock(return_value=target_member)

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(MagicMock(), player)),
            ),
            patch("caldanai.lib.cogs.rpg_social_commands.Dispatcher"),
        ):
            await cog.warmth_clear.callback(
                cog, ctx, cmd="<@999>", who=None,
            )

        assert "999" not in player.social.get("per_player", {})

    @pytest.mark.asyncio
    async def test_warmth_set_mention_as_cmd_gives_tailored_error(self):
        """``$warmth set @player cold`` — mention mis-parsed into the
        ``cmd`` slot. The error must not echo the raw mention tag
        back in backticks (that renders as an ugly raw ``<@id>`` in
        Discord); instead give a hint about correct usage."""
        cog = RpgSocialCommands(bot=MagicMock())
        player = _make_player("Alice", uid=1)
        ctx = _make_ctx(player)

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(MagicMock(), player)),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands.Dispatcher",
            ) as dispatcher,
        ):
            await cog.warmth_set.callback(
                cog, ctx, cmd="<@999>", level="cold", who=None,
            )

        msgs = [t for (_c, t) in _dispatched(dispatcher) if t]
        assert msgs, "expected some response dispatched"
        joined = "\n".join(msgs)
        assert "<@999>" not in joined, (
            f"raw mention tag leaked into error: {joined!r}"
        )
        assert "mention" in joined.lower()

    @pytest.mark.asyncio
    async def test_warmth_set_all_rejects_invalid_level(self):
        """Wildcard doesn't bypass level validation."""
        cog = RpgSocialCommands(bot=MagicMock())
        player = _make_player("Alice", uid=1)
        ctx = _make_ctx(player)

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(MagicMock(), player)),
            ),
            patch("caldanai.lib.cogs.rpg_social_commands.Dispatcher"),
        ):
            await cog.warmth_set.callback(
                cog, ctx, cmd="all", level="scorching",
            )

        # Not a single command should have been touched.
        assert player.social.get("defaults", {}) == {}

    @pytest.mark.asyncio
    async def test_warmth_rejects_invalid_level_with_dm_help(self):
        cog = RpgSocialCommands(bot=MagicMock())
        player = _make_player("Alice", uid=1)
        ctx = _make_ctx(player)

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(MagicMock(), player)),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands.Dispatcher",
            ) as dispatcher,
        ):
            await cog.warmth_set.callback(
                cog, ctx, cmd="hug", level="scorching",
            )

        # Nothing was persisted
        assert "hug" not in player.social.get("defaults", {})
        # Guild-invoked → error message lands in channel, not DM.
        channel_msgs = [
            t for (c, t) in _dispatched(dispatcher) if c is ctx
        ]
        assert any("scorching" in (t or "") for t in channel_msgs)

    @pytest.mark.asyncio
    async def test_warmth_rejects_unknown_command(self):
        cog = RpgSocialCommands(bot=MagicMock())
        player = _make_player("Alice", uid=1)
        ctx = _make_ctx(player)

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(MagicMock(), player)),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands.Dispatcher",
            ) as dispatcher,
        ):
            await cog.warmth_set.callback(
                cog, ctx, cmd="snog", level="hot",
            )

        # Nothing persisted
        assert not player.social.get("defaults")
        # Guild-invoked → error lands in channel, not DM.
        channel_msgs = [
            t for (c, t) in _dispatched(dispatcher) if c is ctx
        ]
        assert any("snog" in (t or "") for t in channel_msgs)

    @pytest.mark.asyncio
    async def test_warmth_display_does_not_leak_other_players(self):
        """Privacy invariant: the DM'd settings view must contain ONLY
        the invoker's own per-player overrides, never another player's
        configured levels."""
        cog = RpgSocialCommands(bot=MagicMock())
        player = _make_player("Alice", uid=1)
        # Alice has an override for Bob.
        warmth.set_override(player, 999, "hug", warmth.Warmth.COLD)
        ctx = _make_ctx(player)

        # Another player is not in scope — but even if the cog had
        # access, it must not reach into any other player's social
        # map. We don't provide one; any accidental access would
        # raise in a narrow mock.
        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(MagicMock(), player)),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands.Dispatcher",
            ) as dispatcher,
        ):
            await cog.warmth.callback(cog, ctx)

        dm_bodies = [
            t for (c, t) in _dispatched(dispatcher) if c == ctx.author
        ]
        # Alice's own override must be present in the DM.
        assert any("cold" in (t or "").lower() for t in dm_bodies), dm_bodies


# ---------------------------------------------------------------------------
# Social cog registration — hug/haunt must live here, not in
# rpg_user_commands anymore.
# ---------------------------------------------------------------------------


class TestSocialCog:
    def test_hug_is_on_social_cog(self):
        assert hasattr(RpgSocialCommands, "hug")

    def test_haunt_is_on_social_cog(self):
        assert hasattr(RpgSocialCommands, "haunt")

    def test_high_five_is_on_social_cog(self):
        assert hasattr(RpgSocialCommands, "high_five")

    def test_fistbump_is_on_social_cog(self):
        assert hasattr(RpgSocialCommands, "fistbump")

    def test_warmth_group_exists(self):
        assert hasattr(RpgSocialCommands, "warmth")

    def test_hug_and_haunt_no_longer_on_user_commands(self):
        """Regression: once the move lands, the old cog must not keep
        stale handlers — a duplicate registration would make
        discord.py throw ``CommandRegistrationError`` at cog-load
        time. The test guards against accidentally leaving the old
        methods in place."""
        from caldanai.lib.cogs.rpg_user_commands import RpgUserCommands
        assert not hasattr(RpgUserCommands, "hug")
        assert not hasattr(RpgUserCommands, "haunt")

    @pytest.mark.asyncio
    async def test_hug_flow_uses_warmth_resolution(self):
        """Integration-ish: the $hug handler routes to the warmth
        narration path for a player mention. Verified by patching
        ``_render_social`` and confirming it got called with the
        actor + target."""
        cog = RpgSocialCommands(bot=MagicMock())
        actor = _make_player("Alice", uid=1)
        target = _make_player("Bob", uid=2)
        mention = MagicMock()
        mention.display_name = "Bob"
        ctx = _make_ctx(actor, mentions=[mention])
        game = MagicMock()
        game.monster = None
        game.channel = MagicMock()

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(game, actor)),
            ),
            patch.object(
                _rpg_util(), "get_player",
                new=AsyncMock(return_value=target),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands._render_social",
                return_value="rendered",
            ) as render_mock,
            patch("caldanai.lib.cogs.rpg_social_commands.Dispatcher"),
        ):
            await cog.hug.callback(cog, ctx)

        render_mock.assert_called_once()
        call_cmd, call_actor, call_target = render_mock.call_args.args
        assert call_cmd == "hug"
        assert call_actor is actor
        assert call_target is target

    @pytest.mark.asyncio
    async def test_dead_invoker_short_circuits_hug(self):
        """The dead-invoker pool must fire when a dead player uses
        $hug, and narration must not route through warmth."""
        cog = RpgSocialCommands(bot=MagicMock())
        actor = _make_player("Alice", uid=1)
        actor.health = 0  # dead
        assert actor.is_dead()
        target = _make_player("Bob", uid=2)
        mention = MagicMock()
        mention.display_name = "Bob"
        ctx = _make_ctx(actor, mentions=[mention])
        game = MagicMock()
        game.monster = None
        game.channel = MagicMock()

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(game, actor)),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands._render_social",
            ) as render_mock,
            patch("caldanai.lib.cogs.rpg_social_commands.Dispatcher"),
        ):
            await cog.hug.callback(cog, ctx)

        # warmth-path must not be consulted for dead invokers.
        render_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_dead_target_hug_routes_through_on_hugged(self):
        """Pre-existing behavior: a live invoker hugging a dead
        target should fire ``target.on_hugged`` (which carries the
        "corpse rolls lifelessly" dead branch), NOT the warmth pool —
        otherwise the corpse would be described as "returning the
        embrace" by the warmth resolver."""
        cog = RpgSocialCommands(bot=MagicMock())
        actor = _make_player("Alice", uid=1)
        target = _make_player("Bob", uid=2)
        target.health = 0  # dead
        assert target.is_dead()
        mention = MagicMock()
        mention.display_name = "Bob"
        ctx = _make_ctx(actor, mentions=[mention])
        ctx.invoked_with = "hug"
        game = MagicMock()
        game.monster = None
        game.channel = MagicMock()

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(game, actor)),
            ),
            patch.object(
                _rpg_util(), "get_player",
                new=AsyncMock(return_value=target),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands._render_social",
            ) as render_mock,
            patch(
                "caldanai.lib.cogs.rpg_social_commands.Dispatcher",
            ) as dispatcher_mock,
        ):
            await cog.hug.callback(cog, ctx)

        # Warmth path MUST NOT fire for dead targets.
        render_mock.assert_not_called()
        # A Dispatcher.add should have been called with the
        # on_hugged-rendered corpse line.
        pairs = _dispatched(dispatcher_mock)
        assert any(
            text and "corpse" in text
            for _, text in pairs
        ), f"Expected corpse-themed narration; got: {pairs}"

    @pytest.mark.asyncio
    async def test_dead_target_high_five_uses_dead_target_pool(self):
        """$high_five against a dead player should pick from the
        dead-target gesture pool, not the warmth narration pools.
        A corpse can't 'meet the palm with a thunderous smack.'"""
        from caldanai.lib.cogs.rpg_social_commands import _DEAD_TARGET_FLAVOR

        cog = RpgSocialCommands(bot=MagicMock())
        actor = _make_player("Alice", uid=1)
        target = _make_player("Bob", uid=2)
        target.health = 0
        assert target.is_dead()
        mention = MagicMock()
        mention.display_name = "Bob"
        ctx = _make_ctx(actor, mentions=[mention])
        ctx.invoked_with = "high_five"
        game = MagicMock()
        game.channel = MagicMock()
        bot_mock = MagicMock()
        bot_mock.user = MagicMock()  # distinct sentinel, not in mentions
        cog.bot = bot_mock

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(game, actor)),
            ),
            patch.object(
                _rpg_util(), "get_player",
                new=AsyncMock(return_value=target),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands._render_social",
            ) as render_mock,
            patch(
                "caldanai.lib.cogs.rpg_social_commands.Dispatcher",
            ) as dispatcher_mock,
        ):
            await cog.high_five.callback(cog, ctx)

        render_mock.assert_not_called()
        pairs = _dispatched(dispatcher_mock)
        # Any dead-target high-five line should contain "corpse" or
        # the unreachable keywords matching the _DEAD_TARGET_FLAVOR.
        assert _DEAD_TARGET_FLAVOR["high_five"], "pool must be non-empty"
        assert any(
            text and (
                "corpse" in text
                or "cannot" in text
                or "still" in text
                or "beyond" in text
                or "hangs in the air" in text
            )
            for _, text in pairs
        ), f"Expected dead-target gesture narration; got: {pairs}"

    @pytest.mark.asyncio
    async def test_dead_target_fistbump_uses_dead_target_pool(self):
        """Sibling to the high_five case above for the fistbump verb.
        Guards against ``_dispatch_two_actor_social`` quietly losing
        the dead-target branch for one command but not the other."""
        from caldanai.lib.cogs.rpg_social_commands import _DEAD_TARGET_FLAVOR

        cog = RpgSocialCommands(bot=MagicMock())
        actor = _make_player("Alice", uid=1)
        target = _make_player("Bob", uid=2)
        target.health = 0
        mention = MagicMock()
        mention.display_name = "Bob"
        ctx = _make_ctx(actor, mentions=[mention])
        ctx.invoked_with = "fistbump"
        game = MagicMock()
        game.channel = MagicMock()
        bot_mock = MagicMock()
        bot_mock.user = MagicMock()
        cog.bot = bot_mock

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(game, actor)),
            ),
            patch.object(
                _rpg_util(), "get_player",
                new=AsyncMock(return_value=target),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands._render_social",
            ) as render_mock,
            patch(
                "caldanai.lib.cogs.rpg_social_commands.Dispatcher",
            ) as dispatcher_mock,
        ):
            await cog.fistbump.callback(cog, ctx)

        render_mock.assert_not_called()
        pairs = _dispatched(dispatcher_mock)
        assert _DEAD_TARGET_FLAVOR["fistbump"], "pool must be non-empty"
        assert any(
            text and (
                "corpse" in text
                or "cannot" in text
                or "still" in text
                or "beyond" in text
                or "hangs in the air" in text
            )
            for _, text in pairs
        ), f"Expected dead-target gesture narration; got: {pairs}"


# ---------------------------------------------------------------------------
# Player persistence of ``social``
# ---------------------------------------------------------------------------


class TestPlayerSocialPersistence:
    def test_new_player_has_empty_social(self):
        p = _make_player()
        assert p.social == {}

    def test_empty_social_is_omitted_from_to_dict(self):
        """An unused ``social`` field must not balloon saved documents
        with an empty nested map."""
        p = _make_player()
        d = p.to_dict()
        assert "social" not in d

    def test_populated_social_round_trips(self):
        """Round-trip of a populated ``social`` field through to_dict /
        from_dict must preserve the structure exactly."""
        from bson.objectid import ObjectId

        from caldanai.lib.rpg.inventory import Inventory

        p = _make_player()
        warmth.set_default(p, "hug", warmth.Warmth.HOT)
        warmth.set_override(p, 555, "hug", warmth.Warmth.COLD)

        d = p.to_dict()
        assert d["social"]["defaults"]["hug"] == warmth.Warmth.HOT
        assert d["social"]["per_player"]["555"]["hug"] == warmth.Warmth.COLD

        # Re-hydrate; d lacks _id-specific context so we supply a
        # minimal shell that from_dict accepts.
        from caldanai.lib.rpg.helpers.enums import EquipmentSlots

        shell = dict(d)
        shell["_id"] = ObjectId()
        shell["pronouns"] = "she,her,hers,her"
        shell["part_equipment"] = {}
        with patch(
            "caldanai.lib.rpg.creatures.player.Inventory.from_list",
            return_value=Inventory(),
        ):
            rehydrated = Player.from_dict(shell)
        assert rehydrated.social["defaults"]["hug"] == warmth.Warmth.HOT
        assert rehydrated.social["per_player"]["555"]["hug"] == warmth.Warmth.COLD

    def test_legacy_player_dict_without_social_loads_as_empty(self):
        """Older saved documents predate the social field — loading
        them must not crash and must produce an empty dict."""
        from bson.objectid import ObjectId

        from caldanai.lib.rpg.helpers.enums import EquipmentSlots
        from caldanai.lib.rpg.inventory import Inventory

        legacy = {
            "_id": ObjectId(),
            "user_id": 1,
            "guild_id": 100,
            "channel_id": None,
            "weight_limit": 100,
            "joined": None,
            "clarks": 0,
            "defense": 6,
            "dodge": 6,
            "health": 20,
            "health_max": 20,
            "items": [],
            "rolls": {"d4":[0]*4,"d6":[0]*6,"d8":[0]*8,"d10":[0]*10,"d12":[0]*12,"d20":[0]*20},
            "skills": {},
            "gender": "female",
            "pronouns": "she,her,hers,her",
            "part_equipment": {},
            "last_active": None,
            "health_regen": 0,
        }
        with patch(
            "caldanai.lib.rpg.creatures.player.Inventory.from_list",
            return_value=Inventory(),
        ):
            p = Player.from_dict(legacy)
        assert p.social == {}


# ---------------------------------------------------------------------------
# Helpers (private)
# ---------------------------------------------------------------------------


def _rpg_util():
    from caldanai.lib.rpg.helpers.utils import RpgUtilities
    return RpgUtilities
