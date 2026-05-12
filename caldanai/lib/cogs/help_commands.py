import re
from random import choice
from typing import Dict, List, Optional, Tuple

import discord
from discord import ButtonStyle, Embed, Interaction
from discord.ui import View, Select, Button, button
from discord.utils import get
from discord.ext.commands import (
    BucketType, Cog, Command, Context, Group, HelpCommand,
    command, cooldown,
)

from caldanai.dispatcher import Dispatcher
from caldanai.logger import get_logger


_log = get_logger(__name__)
paramRegex = re.compile(r":param (?P<name>[^:]+):")


# ----------------------------------------------------------------------------
# Player-facing category mapping
# ----------------------------------------------------------------------------
# Maps Cog class name → (label, blurb, admin_only). The Cog class names
# default to PascalCase Python identifiers (``RpgUserCommands``) which
# don't read well player-side; this dict is the single override surface.
#
# ``admin_only=True`` categories disappear from the category index and
# the Select menu entirely when the invoker can't run any command in
# them (per-command ``can_run`` filtering still applies inside categories
# the player CAN see). The Help cog itself is omitted from the listing —
# typing ``$help`` to find ``$help`` is recursive theater.
COG_CATEGORIES: Dict[str, Tuple[str, str, bool]] = {
    "RpgUserCommands":      ("⚔️ Combat",    "Attack, defend, flee, pray.",                 False),
    "RpgWorldCommands":     ("🌍 World",      "Interact with the world's living surfaces.",  False),
    "RpgSocialCommands":    ("🤝 Social",     "Greet, thank, glare, hug — relational verbs.", False),
    "RpgPresenceCommands":  ("🧘 Presence",   "Self-directed presence verbs.",                False),
    "RpgInventoryCommands": ("🎒 Inventory",  "Loot, equip, stow, sell, favorite.",           False),
    "RpgInfoCommands":      ("📜 Info",       "Look, examine, status queries.",               False),
    "RpgCraftingCommands":  ("🔨 Crafting",   "Craft, salvage, repair.",                      False),
    "GeneralCommands":      ("📖 General",    "Bot-level conveniences.",                      False),
    "RpgAdminCommands":     ("⚙️ Admin",      "Operator tools.",                              True),
    "BotAdminCommands":     ("⚙️ Bot Admin",  "Bot operator tools.",                          True),
}

# Commands per page within a category. Most cogs fit on one page; the
# largest (Social with 15+ verbs) gets two pages with the page nav.
COMMANDS_PER_CATEGORY_PAGE = 10

# Strip the leading emoji from a label for token-match lookups
# (``$help combat`` → look up "⚔️ Combat" by trailing "combat").
_LABEL_LEADING_EMOJI_RX = re.compile(r"^[^A-Za-z0-9]+\s*")


def _label_token(label: str) -> str:
    """Return the lowercased word-form of a category label, emoji
    stripped — used for ``$help <category>`` resolution."""
    return _LABEL_LEADING_EMOJI_RX.sub("", label).strip().lower()


def syntax(cmd: Command, prefix: str, verbose: bool = False, filtered_subs=None):
    """Render a help embed body for ``cmd``. When ``cmd`` is a
    :class:`Group`, ``filtered_subs`` — if provided — replaces
    ``cmd.commands`` as the list of subcommands to display. Callers
    that know the invoker's context should pre-filter via
    ``can_run`` so players don't see admin-only subcommands in help.
    """
    aliases = [*cmd.aliases]
    aliases.sort()
    params = []
    for key, value in cmd.clean_params.items():
        if key not in ("self", "ctx"):
            params.append(f"[{key}]" if "NoneType" in str(value) else f"<{key}>")
    params = " ".join(params)
    subs = []

    if isinstance(cmd, Group):
        sub_source = filtered_subs if filtered_subs is not None else list(cmd.commands)
        subs = [s.name if "_" not in s.name or not len(s.aliases) else choice(s.aliases) for s in sub_source]
        subs.sort()
        subs = ", ".join(subs)

    result = (
        f"```\n{prefix}{cmd.full_parent_name + (' ' if cmd.full_parent_name else '')}"
        f"{cmd.name if '_' not in cmd.name or not len(aliases) else choice(aliases)} {params}```"
    )

    if not verbose:
        result += f"\n__Description__\n{cmd.brief.strip() or 'No description available.'}\n"

    if len(aliases):
        result += f"\n__Aliases__\n{', '.join(aliases)}\n"

    if len(subs) > 0:
        result += f"\n__Subcommands__\n{subs}\n"

    if verbose:
        doc = cmd.callback.__doc__
        if doc:
            while match := paramRegex.search(doc):
                doc = paramRegex.sub(f"*{match.groups('name')[0]}*\n", doc, 1)
            result += f"\n__Details__\n{doc.strip()}"

    return result.strip()


def _render_command_line(cmd: Command, prefix: str) -> str:
    """One-line render for the value of an embed field inside a
    category page. The bold command-prefix isn't included — the
    embed's field NAME already renders ``$<cmd>``; duplicating it in
    the value reads as a double-render to players (caught live in
    playtest within hours of the help rework shipping). Groups surface
    their subcommand list inline so players see the verb's surface at
    a glance without leaving the listing.

    ``prefix`` retained as a parameter for forward compatibility — a
    future render path may want the prefixed form again (e.g. a flat
    cheat-sheet that doesn't use field names per command)."""
    del prefix  # unused in current render shape; preserved for the
    # signature so callers don't break if the bolded-prefix variant
    # comes back.
    brief = (cmd.brief or "").strip() or "(no description)"
    parts = [brief]
    if cmd.aliases:
        parts.append(f" *(aliases: {', '.join(sorted(cmd.aliases))})*")
    if isinstance(cmd, Group) and cmd.commands:
        sub_names = sorted(s.name for s in cmd.commands)
        parts.append(f" *[group: {', '.join(sub_names)}]*")
    return "".join(parts)


# ----------------------------------------------------------------------------
# View — interactive paginated help
# ----------------------------------------------------------------------------


class HelpView(View):
    """Interactive help with a category Select menu + Prev/Next buttons.

    Two display modes:
    - **Landing** (``self.current_category is None``): the category
      index — one field per visible category showing the label,
      command count, and blurb. The Select picker is the navigation
      surface; Prev/Next are disabled here.
    - **Category page** (``self.current_category`` set to a Cog name):
      one field per command in that cog on the current page. Prev/Next
      paginate inside the category if it has more than
      ``COMMANDS_PER_CATEGORY_PAGE`` commands.

    The invoker is the only authorized driver of the controls — every
    interaction callback rejects non-invokers with an ephemeral
    "this isn't your menu" response. Reaction-based pagination required
    the same gate in spirit; buttons make it cheap to enforce.
    """

    def __init__(self, ctx: Context, categories: List[Tuple[str, str, str, List[Command]]]):
        # 180s timeout — buttons aren't reaction-spam-vulnerable so we
        # can afford a longer window than the old MenuPages 60s default.
        super().__init__(timeout=180.0)
        self.ctx = ctx
        # categories: list of (cog_key, label, blurb, [commands_filtered_by_can_run])
        # already filtered by visibility before construction.
        self.categories = categories
        self.current_category: Optional[str] = None
        self.current_page: int = 0
        self.message: Optional[discord.Message] = None
        self._build_select()
        self._update_button_state()

    # ------------------------------------------------------------------
    # Static UI element factories
    # ------------------------------------------------------------------

    def _build_select(self) -> None:
        """Build the category Select from ``self.categories`` and
        attach it to the View. Called once at construction; the menu's
        option list doesn't change after that (visibility was settled
        pre-construction)."""
        if not self.categories:
            return

        options = [
            discord.SelectOption(
                label=label,
                value=cog_key,
                description=blurb[:100],  # Discord caps description at 100 chars
            )
            for cog_key, label, blurb, _ in self.categories
        ]
        select = Select(
            placeholder="Pick a category…",
            options=options,
            min_values=1,
            max_values=1,
            row=0,
        )
        select.callback = self._on_select
        self.add_item(select)

    def _update_button_state(self) -> None:
        """Enable/disable Prev/Next + back-to-index based on the
        current view mode and page index. Called after every
        interaction so the button row reflects state."""
        cmds_in_category = self._current_commands()
        page_count = max(1, (len(cmds_in_category) + COMMANDS_PER_CATEGORY_PAGE - 1) // COMMANDS_PER_CATEGORY_PAGE)
        is_landing = self.current_category is None

        for child in self.children:
            if not isinstance(child, Button):
                continue
            cid = getattr(child, "custom_id", None)
            if cid == "help_prev":
                child.disabled = is_landing or self.current_page <= 0
            elif cid == "help_next":
                child.disabled = is_landing or self.current_page >= page_count - 1
            elif cid == "help_back":
                child.disabled = is_landing

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _current_commands(self) -> List[Command]:
        if self.current_category is None:
            return []
        for cog_key, _, _, cmds in self.categories:
            if cog_key == self.current_category:
                return cmds
        return []

    async def _gate_interaction(self, interaction: Interaction) -> bool:
        """Reject interactions from anyone other than the invoker.
        Returns True when the interaction should proceed."""
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "This isn't your help menu — run `$help` to start your own.",
                ephemeral=True,
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Embed rendering
    # ------------------------------------------------------------------

    def _render_landing_embed(self) -> Embed:
        embed = Embed(
            title="Caldanai Bot — Help",
            description=(
                "Pick a category below to browse its commands. "
                f"For details on any one command, run `{self.ctx.prefix}help <command>`."
            ),
            color=0xFF7700,
        )
        thumb = self.ctx.guild.me.avatar.url if self.ctx.guild is not None else self.ctx.me.avatar.url
        embed.set_thumbnail(url=thumb)
        for _cog_key, label, blurb, cmds in self.categories:
            embed.add_field(
                name=f"{label} ({len(cmds)})",
                value=blurb,
                inline=False,
            )
        return embed

    def _render_category_embed(self) -> Embed:
        cmds = self._current_commands()
        label = next(
            (lbl for ck, lbl, _, _ in self.categories if ck == self.current_category),
            self.current_category or "?",
        )
        page_count = max(1, (len(cmds) + COMMANDS_PER_CATEGORY_PAGE - 1) // COMMANDS_PER_CATEGORY_PAGE)
        start = self.current_page * COMMANDS_PER_CATEGORY_PAGE
        end = start + COMMANDS_PER_CATEGORY_PAGE
        page_cmds = cmds[start:end]

        embed = Embed(
            title=f"Help — {label}",
            description=(
                f"`{self.ctx.prefix}help <command>` for full details on any one. "
                f"Page {self.current_page + 1} of {page_count}."
            ),
            color=0xFF7700,
        )
        thumb = self.ctx.guild.me.avatar.url if self.ctx.guild is not None else self.ctx.me.avatar.url
        embed.set_thumbnail(url=thumb)
        for cmd in page_cmds:
            embed.add_field(
                name=f"{self.ctx.prefix}{cmd.name}",
                value=_render_command_line(cmd, self.ctx.prefix),
                inline=False,
            )
        embed.set_footer(
            text=(
                f"Showing {start + 1}-{min(end, len(cmds))} of {len(cmds)} "
                f"{label} commands"
            )
        )
        return embed

    def _render_current_embed(self) -> Embed:
        if self.current_category is None:
            return self._render_landing_embed()
        return self._render_category_embed()

    # ------------------------------------------------------------------
    # Interaction callbacks
    # ------------------------------------------------------------------

    async def _on_select(self, interaction: Interaction) -> None:
        if not await self._gate_interaction(interaction):
            return
        # Find the Select on the View to read its selected value
        # (the callback signature in discord.py 2.x doesn't pass the
        # component directly when assigned dynamically).
        for child in self.children:
            if isinstance(child, Select):
                if child.values:
                    self.current_category = child.values[0]
                    self.current_page = 0
                break
        self._update_button_state()
        await interaction.response.edit_message(
            embed=self._render_current_embed(), view=self,
        )

    @button(label="◀ Prev", style=ButtonStyle.secondary, custom_id="help_prev", row=1)
    async def prev_button(self, interaction: Interaction, _btn: Button) -> None:
        if not await self._gate_interaction(interaction):
            return
        self.current_page = max(0, self.current_page - 1)
        self._update_button_state()
        await interaction.response.edit_message(
            embed=self._render_current_embed(), view=self,
        )

    @button(label="Next ▶", style=ButtonStyle.secondary, custom_id="help_next", row=1)
    async def next_button(self, interaction: Interaction, _btn: Button) -> None:
        if not await self._gate_interaction(interaction):
            return
        cmds = self._current_commands()
        page_count = max(1, (len(cmds) + COMMANDS_PER_CATEGORY_PAGE - 1) // COMMANDS_PER_CATEGORY_PAGE)
        self.current_page = min(page_count - 1, self.current_page + 1)
        self._update_button_state()
        await interaction.response.edit_message(
            embed=self._render_current_embed(), view=self,
        )

    @button(label="↩ Back to categories", style=ButtonStyle.primary, custom_id="help_back", row=1)
    async def back_button(self, interaction: Interaction, _btn: Button) -> None:
        if not await self._gate_interaction(interaction):
            return
        self.current_category = None
        self.current_page = 0
        self._update_button_state()
        await interaction.response.edit_message(
            embed=self._render_current_embed(), view=self,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def on_timeout(self) -> None:
        """When the View expires, gray out the controls in place
        rather than deleting the message. Keeps the last-rendered
        embed visible for reference; signals that the menu's gone
        cold by disabling everything."""
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                # Message may have been deleted; ignore.
                pass


# ----------------------------------------------------------------------------
# Cog
# ----------------------------------------------------------------------------


class HelpCommands(Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.remove_command("help")

    @command(
        name="help",
        brief="Browse commands by category, or get details on one command.",
    )
    @cooldown(1, 5, BucketType.member)
    async def show_help(self, ctx: Context, cmd: Optional[str], sub: Optional[str]):
        """
        Browse commands by category, or get details on one command.

        - ``$help`` — interactive category browser
        - ``$help <category>`` — jump straight into a category (e.g. ``$help combat``)
        - ``$help <command>`` — full details on one command
        - ``$help <group> <subcommand>`` — full details on a subcommand
        - ``$help all`` — static dump of every category + all commands

        :param cmd: ``all``, a category name, a command name, or omit for the browser.
        :param sub: If ``cmd`` is a command group, the subcommand to drill into.
        """
        # Bare $help → interactive category browser
        if cmd is None:
            await self._start_browser(ctx)
            return

        cmd_key = cmd.lower()
        sub_key = sub.lower() if sub else None

        # $help all → static dump path (no View, no pagination).
        # Primary use case: automation / tester-bot readouts via
        # ``tail_channel`` — Discord's API doesn't expose component
        # interactions to bot accounts, so a bot can read a View's
        # current page but can't drive its Select / Prev / Next.
        # The static dump gives a one-shot full-surface read.
        if cmd_key == "all" and sub_key is None:
            await self._dump_all_commands(ctx)
            return

        # $help <category> — match against label tokens
        if sub_key is None:
            category_match = await self._resolve_category(ctx, cmd_key)
            if category_match is not None:
                await self._start_browser(ctx, initial_category=category_match)
                return

        # $help <command> / $help <group> <sub> — existing single-command path
        if c := get(self.bot.commands, name=cmd_key):
            if sub_key is None or not isinstance(c, Group):
                await self.cmd_help(ctx, c)
                return
            elif isinstance(c, Group):
                if s := get(c.commands, name=sub_key):
                    await self.cmd_help(ctx, s)
                    return
                # Try sub as alias of a subcommand
                for sub_cmd in c.commands:
                    if sub_key in sub_cmd.aliases:
                        await self.cmd_help(ctx, sub_cmd)
                        return

        # Alias fallback at top level
        for c in self.bot.commands:
            if cmd_key in c.aliases:
                if sub_key is None or not isinstance(c, Group):
                    await self.cmd_help(ctx, c)
                    return
                if isinstance(c, Group):
                    if s := get(c.commands, name=sub_key):
                        await self.cmd_help(ctx, s)
                        return
                    for sub_cmd in c.commands:
                        if sub_key in sub_cmd.aliases:
                            await self.cmd_help(ctx, sub_cmd)
                            return

        Dispatcher.add(ctx, f"No such command exists: {cmd}")

    # ------------------------------------------------------------------
    # Browser starters
    # ------------------------------------------------------------------

    async def _start_browser(
        self,
        ctx: Context,
        initial_category: Optional[str] = None,
    ) -> None:
        """Build the per-invoker filtered category list, instantiate
        the View, dispatch the initial embed. ``initial_category`` is
        the Cog class name to land on when arriving via
        ``$help <category-name>``; ``None`` → landing page."""
        categories = await self._build_categories(ctx)
        if not categories:
            Dispatcher.add(ctx, "No commands available for you to browse.")
            return

        view = HelpView(ctx, categories)
        if initial_category is not None:
            view.current_category = initial_category
            view._update_button_state()

        # Send via the bot's send path so the message is captured and
        # we can write back to it on timeout. ``ctx.send`` is the
        # canonical entrypoint; the embed + view ride together.
        msg = await ctx.send(embed=view._render_current_embed(), view=view)
        view.message = msg

    async def _dump_all_commands(self, ctx: Context) -> None:
        """Static, no-View dump of every visible category and its
        commands. One field per category, command-per-line in each
        field's value. Long categories that would exceed Discord's
        1024-char field-value limit are split into multiple
        ``Label (n/m)`` fields preserving order. Multiple embeds are
        emitted when a single embed's 6000-char total cap would be
        crossed.

        Primary use case: automation that reads the help surface via
        ``tail_channel`` — bots can't drive ``discord.ui.View``
        components, so an interactive paginator misses commands that
        sit on pages a human would have to click through to reach.
        This dump fits the entire visible surface into a single
        ``$help all`` call.
        """
        categories = await self._build_categories(ctx)
        if not categories:
            Dispatcher.add(ctx, "No commands available.")
            return

        # Build (field_name, field_value) pairs per category, chunked
        # by the 1024-char field-value cap.
        fields: List[Tuple[str, str]] = []
        for _cog_key, label, _blurb, cmds in categories:
            lines: List[str] = []
            for cmd in cmds:
                brief = (cmd.brief or "").strip() or "(no description)"
                line = f"**{ctx.prefix}{cmd.name}** — {brief}"
                if cmd.aliases:
                    line += f" *(aliases: {', '.join(sorted(cmd.aliases))})*"
                if isinstance(cmd, Group) and cmd.commands:
                    sub_names = sorted(s.name for s in cmd.commands)
                    line += f" *[group: {', '.join(sub_names)}]*"
                lines.append(line)

            # Chunk lines to fit the 1024-char field-value cap.
            chunks: List[str] = []
            current: List[str] = []
            current_len = 0
            for line in lines:
                # +1 for the newline separator between lines
                line_cost = len(line) + 1
                if current and current_len + line_cost > 1000:
                    chunks.append("\n".join(current))
                    current = [line]
                    current_len = len(line)
                else:
                    current.append(line)
                    current_len += line_cost
            if current:
                chunks.append("\n".join(current))

            total_chunks = len(chunks)
            for idx, chunk_value in enumerate(chunks):
                if total_chunks > 1:
                    name = f"{label} ({len(cmds)} — {idx + 1}/{total_chunks})"
                else:
                    name = f"{label} ({len(cmds)})"
                fields.append((name, chunk_value))

        # Emit embeds, packing fields up to the 6000-char total cap
        # AND the 25-field-per-embed cap. The thumbnail + title +
        # description we account for via the headroom in the cap
        # constant below.
        TOTAL_CAP = 5500  # 500 chars of headroom under Discord's 6000
        FIELDS_PER_EMBED = 25
        thumb_url = (
            ctx.guild.me.avatar.url
            if ctx.guild is not None else ctx.me.avatar.url
        )

        def _new_embed(part_idx: int, part_count: int) -> Embed:
            title = "Caldanai Bot — All commands"
            if part_count > 1:
                title += f" ({part_idx + 1}/{part_count})"
            description = (
                "Full surface, every category. "
                f"Use `{ctx.prefix}help <command>` for per-command details."
            )
            embed = Embed(title=title, description=description, color=0xFF7700)
            embed.set_thumbnail(url=thumb_url)
            return embed

        # First pass: group fields into embeds respecting both caps.
        embed_field_groups: List[List[Tuple[str, str]]] = []
        current_group: List[Tuple[str, str]] = []
        current_size = 0
        for name, value in fields:
            field_cost = len(name) + len(value)
            if (
                current_group
                and (
                    current_size + field_cost > TOTAL_CAP
                    or len(current_group) >= FIELDS_PER_EMBED
                )
            ):
                embed_field_groups.append(current_group)
                current_group = [(name, value)]
                current_size = field_cost
            else:
                current_group.append((name, value))
                current_size += field_cost
        if current_group:
            embed_field_groups.append(current_group)

        part_count = len(embed_field_groups)
        for part_idx, group in enumerate(embed_field_groups):
            embed = _new_embed(part_idx, part_count)
            for name, value in group:
                embed.add_field(name=name, value=value, inline=False)
            Dispatcher.add(ctx, embed=embed)

    async def _build_categories(
        self, ctx: Context,
    ) -> List[Tuple[str, str, str, List[Command]]]:
        """Walk ``COG_CATEGORIES`` in declaration order, building per-
        category command lists filtered by ``can_run`` for the invoker.
        Admin-only categories drop out entirely when the invoker can't
        run any of their commands."""
        out: List[Tuple[str, str, str, List[Command]]] = []
        for cog_key, (label, blurb, admin_only) in COG_CATEGORIES.items():
            cog = self.bot.get_cog(cog_key)
            if cog is None:
                continue
            visible_cmds: List[Command] = []
            for cmd in cog.get_commands():
                if cmd.hidden:
                    continue
                try:
                    if await cmd.can_run(ctx):
                        visible_cmds.append(cmd)
                except Exception:
                    # ``can_run`` raises on failed checks; treat as
                    # not-runnable and skip.
                    pass
            if not visible_cmds:
                # Admin-only categories with no visible commands stay
                # hidden; player categories with no visible commands
                # also hide (rare — usually means all hidden=True).
                continue
            visible_cmds.sort(key=lambda c: c.name)
            out.append((cog_key, label, blurb, visible_cmds))
        return out

    async def _resolve_category(
        self, ctx: Context, token: str,
    ) -> Optional[str]:
        """Resolve ``$help <token>`` against the visible category
        labels. Returns the Cog class name to use as
        ``initial_category``, or ``None`` if no category matches.
        Match rule: case-insensitive equality against the label's
        word-form (emoji stripped). ``$help combat`` → 'RpgUserCommands'.
        """
        categories = await self._build_categories(ctx)
        for cog_key, label, _blurb, _cmds in categories:
            if _label_token(label) == token:
                return cog_key
            # Also allow matching against the cog key itself
            # (case-insensitive) so power users can type
            # ``$help rpgusercommands`` if they want.
            if cog_key.lower() == token:
                return cog_key
        return None

    # ------------------------------------------------------------------
    # Single-command help (unchanged)
    # ------------------------------------------------------------------

    @staticmethod
    async def cmd_help(ctx: Context, cmd: Command):
        """Per-command detail embed. Unchanged from prior behavior
        except the failure message now reflects the View-aware
        listing."""
        if not isinstance(cmd, Group):
            try:
                runnable = await cmd.can_run(ctx)
            except Exception:
                runnable = False
            if not runnable:
                Dispatcher.add(ctx, f"No such command exists: {cmd}")
                return

        filtered_subs = None
        if isinstance(cmd, Group):
            filtered_subs = []
            for sub in cmd.commands:
                try:
                    if await sub.can_run(ctx):
                        filtered_subs.append(sub)
                except Exception:
                    pass

        embed = Embed(
            title=f"Help for `{cmd}`",
            description=syntax(cmd, ctx.prefix, True, filtered_subs=filtered_subs),
            color=0xFF7700,
        )
        Dispatcher.add(ctx, embed=embed)

    @Cog.listener()
    async def on_ready(self):
        _log.info("HelpCommands ready.")


async def setup(bot):
    await bot.add_cog(HelpCommands(bot))
