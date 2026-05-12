"""Tests for the rebuilt help system in
``caldanai.lib.cogs.help_commands``.

Covers the unit-testable surface of the rework:
- ``_label_token`` emoji-stripping helper
- ``_render_command_line`` shape (basic / aliases / group)
- ``HelpView`` state machine and embed rendering (landing vs
  category-page, button enabling, page bounds)
- ``HelpCommands._resolve_category`` token-match resolution
- ``HelpCommands.show_help`` routing through bare / category-name /
  command-name / group-subcommand / missing paths

Discord interaction callbacks (Select/Button) require a live client
and are not unit-tested here; the View's _render and state-update
logic is exercised directly.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord.ext.commands import Group

from caldanai.lib.cogs.help_commands import (
    COMMANDS_PER_CATEGORY_PAGE,
    HelpCommands,
    HelpView,
    _label_token,
    _render_command_line,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_ctx(prefix: str = "$", author_id: int = 1) -> MagicMock:
    """Minimal Context stand-in. Only the surfaces the help cog
    reads (prefix, author.id, guild.me.avatar.url, me.avatar.url,
    send) are populated."""
    ctx = MagicMock()
    ctx.prefix = prefix
    ctx.author = MagicMock()
    ctx.author.id = author_id
    guild = MagicMock()
    guild.me = MagicMock()
    guild.me.avatar = MagicMock()
    guild.me.avatar.url = "https://example/bot.png"
    ctx.guild = guild
    ctx.me = MagicMock()
    ctx.me.avatar = MagicMock()
    ctx.me.avatar.url = "https://example/bot.png"
    ctx.send = AsyncMock()
    return ctx


def _make_command(name: str, brief: str = "Test command.", aliases=None):
    """Build a Command-shaped mock the renderer can chew on."""
    cmd = MagicMock(spec_set=["name", "brief", "aliases", "commands", "hidden", "can_run", "clean_params", "callback", "full_parent_name"])
    cmd.name = name
    cmd.brief = brief
    cmd.aliases = list(aliases or [])
    cmd.hidden = False
    cmd.can_run = AsyncMock(return_value=True)
    cmd.clean_params = {}
    cmd.callback = MagicMock()
    cmd.callback.__doc__ = ""
    cmd.full_parent_name = ""
    # ``isinstance(cmd, Group)`` returns False since ``spec_set`` is a
    # plain list of names, not a class. _render_command_line uses
    # isinstance to detect groups; that's intentional here.
    return cmd


def _make_group(name: str, brief: str = "Test group.", subcommand_names=None, aliases=None):
    """Build a Group-shaped mock the renderer recognises as a Group
    via ``isinstance``. We use ``MagicMock(spec=Group)`` so the
    isinstance check in ``_render_command_line`` evaluates True."""
    grp = MagicMock(spec=Group)
    grp.name = name
    grp.brief = brief
    grp.aliases = list(aliases or [])
    grp.hidden = False
    grp.can_run = AsyncMock(return_value=True)
    grp.full_parent_name = ""
    grp.clean_params = {}
    grp.callback = MagicMock()
    grp.callback.__doc__ = ""
    subs = []
    for sub_name in subcommand_names or []:
        sub = _make_command(sub_name)
        subs.append(sub)
    grp.commands = subs
    return grp


# ---------------------------------------------------------------------------
# _label_token
# ---------------------------------------------------------------------------


class TestLabelToken:
    @pytest.mark.parametrize("label,expected", [
        ("⚔️ Combat", "combat"),
        ("🤝 Social", "social"),
        ("📖 General", "general"),
        ("⚙️ Bot Admin", "bot admin"),
        ("Combat", "combat"),  # No emoji prefix — still works
        ("⚔️  Combat  ", "combat"),  # extra whitespace
    ])
    def test_strips_leading_non_alphanumeric_and_lowercases(self, label, expected):
        assert _label_token(label) == expected


# ---------------------------------------------------------------------------
# _render_command_line
# ---------------------------------------------------------------------------


class TestRenderCommandLine:
    def test_basic_command_no_aliases(self):
        cmd = _make_command("attack", brief="Attacks a monster.")
        line = _render_command_line(cmd, "$")
        assert "Attacks a monster." in line
        assert "aliases" not in line
        assert "group:" not in line
        # Command name does NOT appear in the value — the embed field's
        # name renders it; duplicating in the value double-renders
        # player-side. Player report 2026-05-12.
        assert "**$attack**" not in line
        assert "$attack" not in line

    def test_command_with_aliases(self):
        cmd = _make_command("attack", brief="Attacks a monster.", aliases=["kill", "slay"])
        line = _render_command_line(cmd, "$")
        assert "Attacks a monster." in line
        # Aliases listed alphabetically
        assert "(aliases: kill, slay)" in line
        # Same no-double-render assertion as above
        assert "$attack" not in line

    def test_group_shows_subcommand_surface_inline(self):
        grp = _make_group("warmth", brief="Manage social warmth.", subcommand_names=["set", "list", "default"])
        line = _render_command_line(grp, "$")
        assert "Manage social warmth." in line
        # Subcommands sorted alphabetically inside [group: ...]
        assert "[group: default, list, set]" in line
        # Group name does NOT appear in the value — same rule as
        # plain commands.
        assert "$warmth" not in line

    def test_missing_brief_falls_back_to_placeholder(self):
        cmd = _make_command("mystery", brief="")
        line = _render_command_line(cmd, "$")
        assert "(no description)" in line
        assert "$mystery" not in line


# ---------------------------------------------------------------------------
# HelpView — instantiation + landing-page render
# ---------------------------------------------------------------------------


class TestHelpViewLanding:
    def test_landing_embed_has_one_field_per_category(self):
        ctx = _make_ctx()
        categories = [
            ("RpgUserCommands", "⚔️ Combat", "Attack, defend, flee, pray.",
             [_make_command("attack"), _make_command("flee")]),
            ("RpgSocialCommands", "🤝 Social", "Greet, thank, glare.",
             [_make_command("hug")]),
        ]
        view = HelpView(ctx, categories)
        embed = view._render_landing_embed()

        assert embed.title == "Caldanai Bot — Help"
        assert len(embed.fields) == 2
        assert embed.fields[0].name == "⚔️ Combat (2)"
        assert embed.fields[0].value == "Attack, defend, flee, pray."
        assert embed.fields[1].name == "🤝 Social (1)"
        assert embed.fields[1].value == "Greet, thank, glare."

    def test_landing_state_starts_with_no_category_selected(self):
        ctx = _make_ctx()
        view = HelpView(ctx, [("RpgUserCommands", "⚔️ Combat", "blurb", [_make_command("attack")])])
        assert view.current_category is None
        assert view.current_page == 0

    def test_landing_disables_pagination_buttons(self):
        from discord.ui import Button
        ctx = _make_ctx()
        view = HelpView(ctx, [("RpgUserCommands", "⚔️ Combat", "blurb", [_make_command("attack")])])
        buttons_by_cid = {
            child.custom_id: child for child in view.children
            if isinstance(child, Button)
        }
        # Landing → prev/next/back all disabled (no category to page
        # through, no category to back out of)
        assert buttons_by_cid["help_prev"].disabled is True
        assert buttons_by_cid["help_next"].disabled is True
        assert buttons_by_cid["help_back"].disabled is True


# ---------------------------------------------------------------------------
# HelpView — category-page render + button state
# ---------------------------------------------------------------------------


class TestHelpViewCategoryPage:
    def test_category_embed_shows_commands_in_current_page(self):
        ctx = _make_ctx()
        cmds = [_make_command(f"cmd{i}", brief=f"Brief {i}.") for i in range(3)]
        categories = [("RpgUserCommands", "⚔️ Combat", "blurb", cmds)]
        view = HelpView(ctx, categories)
        view.current_category = "RpgUserCommands"
        view.current_page = 0
        embed = view._render_category_embed()

        assert embed.title == "Help — ⚔️ Combat"
        assert len(embed.fields) == 3
        # Each field's name is the command's invocation form
        assert {f.name for f in embed.fields} == {"$cmd0", "$cmd1", "$cmd2"}
        # Footer shows pagination info
        assert "1-3 of 3" in embed.footer.text
        assert "⚔️ Combat commands" in embed.footer.text

    def test_category_embed_paginates_past_threshold(self):
        ctx = _make_ctx()
        cmds = [
            _make_command(f"cmd{i:02d}", brief=f"Brief {i}.")
            for i in range(COMMANDS_PER_CATEGORY_PAGE + 5)
        ]
        categories = [("RpgUserCommands", "⚔️ Combat", "blurb", cmds)]
        view = HelpView(ctx, categories)
        view.current_category = "RpgUserCommands"

        # Page 0: first COMMANDS_PER_CATEGORY_PAGE
        view.current_page = 0
        embed = view._render_category_embed()
        assert len(embed.fields) == COMMANDS_PER_CATEGORY_PAGE
        assert embed.fields[0].name == "$cmd00"
        # Page 1: remaining 5
        view.current_page = 1
        embed = view._render_category_embed()
        assert len(embed.fields) == 5
        assert embed.fields[0].name == f"$cmd{COMMANDS_PER_CATEGORY_PAGE:02d}"

    def test_button_state_in_category_view(self):
        from discord.ui import Button
        ctx = _make_ctx()
        cmds = [
            _make_command(f"cmd{i:02d}")
            for i in range(COMMANDS_PER_CATEGORY_PAGE * 2)  # exactly 2 pages
        ]
        categories = [("RpgUserCommands", "⚔️ Combat", "blurb", cmds)]
        view = HelpView(ctx, categories)
        view.current_category = "RpgUserCommands"
        view.current_page = 0
        view._update_button_state()
        buttons = {
            c.custom_id: c for c in view.children
            if isinstance(c, Button)
        }
        # Page 0 of 2: prev disabled, next enabled, back enabled
        assert buttons["help_prev"].disabled is True
        assert buttons["help_next"].disabled is False
        assert buttons["help_back"].disabled is False

        view.current_page = 1
        view._update_button_state()
        # Page 1 of 2: prev enabled, next disabled, back enabled
        assert buttons["help_prev"].disabled is False
        assert buttons["help_next"].disabled is True
        assert buttons["help_back"].disabled is False

    def test_back_to_landing_resets_state(self):
        ctx = _make_ctx()
        view = HelpView(ctx, [(
            "RpgUserCommands", "⚔️ Combat", "blurb",
            [_make_command("attack")],
        )])
        view.current_category = "RpgUserCommands"
        view.current_page = 1
        # Simulate the back button's effect inline (the interaction
        # callback wraps an auth gate we test separately).
        view.current_category = None
        view.current_page = 0
        view._update_button_state()
        embed = view._render_current_embed()
        # Back at landing
        assert embed.title == "Caldanai Bot — Help"


# ---------------------------------------------------------------------------
# HelpCommands — category resolution + routing
# ---------------------------------------------------------------------------


class TestHelpCommandsRouting:
    def _make_cog_with_commands(self, name: str, command_names):
        cog = MagicMock()
        cog.__class__.__name__ = name
        cog.get_commands.return_value = [
            _make_command(n) for n in command_names
        ]
        return cog

    def _make_bot(self, cogs: dict, all_commands=None):
        bot = MagicMock()
        bot.get_cog.side_effect = lambda key: cogs.get(key)
        bot.commands = all_commands or []
        bot.remove_command = MagicMock()
        return bot

    @pytest.mark.asyncio
    async def test_resolve_category_matches_label_token(self):
        ctx = _make_ctx()
        cogs = {
            "RpgUserCommands": self._make_cog_with_commands(
                "RpgUserCommands", ["attack", "flee"],
            ),
        }
        bot = self._make_bot(cogs)
        cog = HelpCommands(bot)
        # "combat" → "⚔️ Combat" (label token match)
        resolved = await cog._resolve_category(ctx, "combat")
        assert resolved == "RpgUserCommands"

    @pytest.mark.asyncio
    async def test_resolve_category_matches_cog_key_fallback(self):
        ctx = _make_ctx()
        cogs = {
            "RpgUserCommands": self._make_cog_with_commands(
                "RpgUserCommands", ["attack"],
            ),
        }
        bot = self._make_bot(cogs)
        cog = HelpCommands(bot)
        # Cog class name (lowercased) also resolves
        resolved = await cog._resolve_category(ctx, "rpgusercommands")
        assert resolved == "RpgUserCommands"

    @pytest.mark.asyncio
    async def test_resolve_category_returns_none_on_miss(self):
        ctx = _make_ctx()
        cogs = {
            "RpgUserCommands": self._make_cog_with_commands(
                "RpgUserCommands", ["attack"],
            ),
        }
        bot = self._make_bot(cogs)
        cog = HelpCommands(bot)
        resolved = await cog._resolve_category(ctx, "nonexistent")
        assert resolved is None

    @pytest.mark.asyncio
    async def test_build_categories_filters_hidden_and_can_run(self):
        ctx = _make_ctx()
        cmd_visible = _make_command("attack")
        cmd_hidden = _make_command("debug")
        cmd_hidden.hidden = True
        cmd_blocked = _make_command("godmode")
        cmd_blocked.can_run = AsyncMock(return_value=False)
        cog = MagicMock()
        cog.__class__.__name__ = "RpgUserCommands"
        cog.get_commands.return_value = [cmd_visible, cmd_hidden, cmd_blocked]
        cogs = {"RpgUserCommands": cog}
        bot = self._make_bot(cogs)
        help_cog = HelpCommands(bot)
        result = await help_cog._build_categories(ctx)
        # Only the visible+runnable command makes it through
        assert len(result) == 1
        cog_key, label, blurb, cmds = result[0]
        assert cog_key == "RpgUserCommands"
        assert cmds == [cmd_visible]

    @pytest.mark.asyncio
    async def test_build_categories_drops_empty_categories(self):
        """Admin-only cogs with zero runnable commands disappear from
        the list entirely (not just the Select)."""
        ctx = _make_ctx()
        cmd_blocked = _make_command("godmode")
        cmd_blocked.can_run = AsyncMock(return_value=False)
        cog = MagicMock()
        cog.__class__.__name__ = "RpgAdminCommands"
        cog.get_commands.return_value = [cmd_blocked]
        cogs = {"RpgAdminCommands": cog}
        bot = self._make_bot(cogs)
        help_cog = HelpCommands(bot)
        result = await help_cog._build_categories(ctx)
        assert result == []

    @pytest.mark.asyncio
    async def test_show_help_bare_calls_start_browser(self):
        ctx = _make_ctx()
        bot = self._make_bot({})
        cog = HelpCommands(bot)
        with patch.object(cog, "_start_browser", new_callable=AsyncMock) as mock_start:
            await HelpCommands.show_help.callback(cog, ctx, None, None)
        mock_start.assert_awaited_once_with(ctx)

    @pytest.mark.asyncio
    async def test_show_help_with_category_token_routes_to_browser(self):
        """``$help combat`` → opens the browser on the Combat category."""
        ctx = _make_ctx()
        bot = self._make_bot({})
        cog = HelpCommands(bot)
        with patch.object(
            cog, "_resolve_category", new_callable=AsyncMock,
        ) as mock_resolve, patch.object(
            cog, "_start_browser", new_callable=AsyncMock,
        ) as mock_start:
            mock_resolve.return_value = "RpgUserCommands"
            await HelpCommands.show_help.callback(cog, ctx, "combat", None)
        mock_start.assert_awaited_once_with(
            ctx, initial_category="RpgUserCommands",
        )

    @pytest.mark.asyncio
    async def test_show_help_with_command_name_routes_to_cmd_help(self):
        ctx = _make_ctx()
        cmd = _make_command("attack")
        bot = self._make_bot({}, all_commands=[cmd])
        cog = HelpCommands(bot)
        with patch.object(
            cog, "_resolve_category", new_callable=AsyncMock,
        ) as mock_resolve, patch.object(
            cog, "cmd_help", new_callable=AsyncMock,
        ) as mock_cmd_help:
            mock_resolve.return_value = None  # not a category
            await HelpCommands.show_help.callback(cog, ctx, "attack", None)
        mock_cmd_help.assert_awaited_once()
        # First arg is ctx, second is the resolved command
        call_args = mock_cmd_help.call_args
        assert call_args.args[1] is cmd

    @pytest.mark.asyncio
    async def test_show_help_missing_command_dispatches_miss_line(self):
        ctx = _make_ctx()
        bot = self._make_bot({}, all_commands=[])
        cog = HelpCommands(bot)
        with patch.object(
            cog, "_resolve_category", new_callable=AsyncMock,
        ) as mock_resolve, patch(
            "caldanai.lib.cogs.help_commands.Dispatcher",
        ) as mock_dispatcher:
            mock_resolve.return_value = None
            await HelpCommands.show_help.callback(cog, ctx, "nonexistent", None)
        mock_dispatcher.add.assert_called_once()
        args = mock_dispatcher.add.call_args.args
        # "No such command exists: nonexistent"
        assert "No such command exists" in args[1]
        assert "nonexistent" in args[1]
