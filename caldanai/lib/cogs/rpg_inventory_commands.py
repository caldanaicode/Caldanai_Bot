from discord.ext.commands import Cog, command, cooldown, group, BucketType, guild_only, Context
from discord.ext.commands.errors import MissingRequiredArgument
from discord import Embed
from typing import Union, List, Optional

from caldanai.dispatcher import Dispatcher
from caldanai.logger import get_logger
from caldanai.lib.rpg.helpers.parser import item_list_to_string
from caldanai.lib.rpg.helpers.utils import RpgUtilities
from caldanai.lib.rpg.helpers.enums import EquipmentSlots
from caldanai.lib.rpg.inventory import Armor, Item
from caldanai.lib.rpg.inventory.equipment import Equipment
from caldanai.lib.rpg.inventory.stackables import Stackable
from caldanai.lib.rpg.inventory.equipment.weapons import Weapon


_log = get_logger(__name__)


# Shared dead-invoker flavor pool for every inventory command —
# the original code repeated one identical line across four
# handlers (equip / stow / sell / etc.). One module-level pool +
# the ``dead_invoker_guard`` helper collapse all four to a single
# source of truth, and the pool shape (list of parse templates)
# gives the usual random-variety feel.
_DEAD_INVOKER_INVENTORY_FLAVOR = [
    "A frustrated wail escapes the corpse of @1.",
    "@1np fingers twitch at the idea of gear, but the corpse has no use for it.",
    "The remains of @1 cannot lift a pebble, let alone sort an inventory.",
    "A dry rattle — @1np final thought on the matter.",
    "@1 would very much like to handle that, but @1 is presently dead.",
    "The inventory of @1 is not going anywhere, and neither is @1.",
]


class RpgInventoryCommands(Cog):
    def __init__(self, bot):
        self.bot = bot

    # Slot-hint shortcuts that can appear as a standalone trailing
    # arg in the legacy 2-arg form ``$equip <item> <hint>``. Kept
    # for back-compat; new callers should prefer the per-item
    # ``<item>@<hint>`` binding form which works for any arg count.
    _LEGACY_TRAILING_SLOT_HINTS = {"l", "left", "r", "right", "_"}

    @command(name='equip', aliases=['wield', 'ready'], brief='Equips one or more items.')
    @cooldown(1, 2, BucketType.member)
    async def equip(self, ctx: Context, *queries: str):
        """
        Equip one or more items. Accepts the same query grammar
        as ``$stow`` / ``$item`` / ``$sell``::

            $equip <item>                     # auto-slot
            $equip <item>@<hint>              # item to placement
            $equip <item1> <item2> ...        # multi-equip, each auto-slots
            $equip <item1>@l <item2>@r ...    # multi-equip, per-item placement
            $equip <item> l|r|left|right|_    # legacy 2-arg form

        Item queries support ``item.n`` (nth of item),
        ``item.quality``, ``item.quality.n``, and ``item.best``
        (highest-quality variant).

        Placement hints (the part after ``@``):
        ``l``/``left``/``r``/``right``/``_`` (wildcard), or any
        placement key — ``worn`` / ``outer`` / ``hand.left.held``.

        Ambiguous queries surface the candidate list so you can
        retry with a narrower selector.

        (2-second cool-down)
        """
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return

        channel = RpgUtilities.resolve_reply_channel(ctx, game)

        if RpgUtilities.dead_invoker_guard(
            channel, player, _DEAD_INVOKER_INVENTORY_FLAVOR,
        ):
            return

        if not queries:
            Dispatcher.add(channel, "You must specify at least one item to equip.")
            return

        query_list = list(queries)

        # Legacy 2-arg shortcut: ``$equip <item> <l|r|left|right|_>``
        # preserves the old trailing-hint UX by treating the last
        # arg as a whole-invocation slot hint when it's exactly a
        # recognized short-form. Multi-arg invocations lose the
        # special case — every arg is a full ``<item>[@<hint>]``
        # query. This drops the ambiguity the trailing-hint rule
        # would otherwise introduce (``$equip wand dagger r`` —
        # does ``r`` bind to dagger only, both, or is it an item?).
        if (
            len(query_list) == 2
            and query_list[1].lower() in self._LEGACY_TRAILING_SLOT_HINTS
            and "@" not in query_list[0]
        ):
            # Rewrite to the explicit form so the resolver path is
            # uniform. ``$equip sword left`` → ``$equip sword@left``.
            query_list = [f"{query_list[0]}@{query_list[1]}"]

        # Resolve + equip per-query so each subsequent query sees
        # the updated equipped state. Batch-resolving all queries
        # up front made ``$equip wand.b wand.b`` pick the SAME
        # superior wand twice — the second resolution didn't know
        # the first query was about to claim it. Interleaving the
        # equip means the second ``wand.b`` now sees the superior
        # as already-equipped and falls back to the next-best.
        for raw in query_list:
            resolved = RpgUtilities.resolve_items_or_notify(
                channel, player, [raw], mode="equip",
            )
            if not resolved:
                continue

            for _item, hint_slot in resolved:
                if not isinstance(_item, Equipment):
                    Dispatcher.add(
                        channel, f"{_item.get_full_name()} cannot be equipped.",
                    )
                    continue

                # ``hint_slot`` from the helper is a ``LEFT_SIDE`` /
                # ``RIGHT_SIDE`` aggregate or a specific placement slot.
                # Narrow to the item's compatible mask before passing
                # down — the old behavior did this intersection inline.
                final_slot = (
                    EquipmentSlots(hint_slot & _item.slots)
                    if hint_slot is not None
                    else None
                )
                success, replaced_msg = player.equip(_item, final_slot)
                if success:
                    if replaced_msg:
                        Dispatcher.add(
                            channel,
                            f"{player.name} equipped {_item.get_full_name()}, replacing {replaced_msg}.",
                        )
                    else:
                        Dispatcher.add(
                            channel,
                            f"{player.name} equipped {_item.get_full_name()}.",
                        )
                else:
                    Dispatcher.add(channel, replaced_msg)

    @staticmethod
    def _resolve_best(base, player, channel):
        """Pick the highest-quality equipment matching ``base`` from
        inventory, applying the no-demote rule: if an equipped item of
        the same type is already equal-or-better, keep it."""
        candidates = [
            i for i in player.inventory.filter(base)
            if i is not None and isinstance(i, Equipment)
        ]
        if not candidates:
            Dispatcher.add(channel, "You don't seem to have such an item.")
            return None

        candidates.sort(
            key=lambda i: i.quality.value["multiplier"], reverse=True,
        )
        best = candidates[0]

        # Walk every ``(part, key)`` placement. Multi-placement
        # items (two-handed weapons, paired gear) share references
        # so checking identity against the "best" candidate would
        # false-positive; identity here is fine because a freshly-
        # picked inventory candidate is distinct from anything
        # already equipped.
        for equipped in player._iter_equipped_items():
            if (
                equipped.plugin == best.plugin
                and equipped.quality.value["multiplier"] >= best.quality.value["multiplier"]
            ):
                Dispatcher.add(
                    channel,
                    f"{player.name} is already wielding the finest {base}.",
                )
                return None

        return best

    @command(aliases=['slots', 'gear'], brief="Shows a player's equipment.")
    @cooldown(1, 10, BucketType.member)
    async def equipment(self, ctx: Context, options: str = None, gid: int = None):
        """
        Shows a player's equipment.

        (10-second cool-down)

        :param options: Specify the word 'all' if you want to show all inventory slots, even if empty.
        :param gid: For use in DMs when playing on more than one server. Specify the game's index for which information is to be displayed. The game indices can be determined by using the `games` command.
        """
        game, player = await RpgUtilities.get_game_and_player(ctx, gid)

        if not game or not player:
            return

        show_all = bool(options and options.lower() == 'all')
        channel = RpgUtilities.resolve_reply_channel(ctx, game)
        embed = player.get_equipment(game.guild.name, show_all)
        embed.set_thumbnail(url=game.guild.icon.url)
        Dispatcher.add(channel, embed=embed)

    @command(name='stow', aliases=['disarm', 'unequip'], brief='Un-equip one or more items.')
    @cooldown(1, 2, BucketType.member)
    async def stow(self, ctx: Context, *queries: str):
        """
        Un-equip one or more items.

        (2-second cool-down)

        Each query can be:

        - An item name (``$stow wand``), with the usual
          ``.n`` / ``.quality`` / ``.best`` selectors.
        - A placement key (``$stow worn``, ``$stow outer``) —
          short form picks first anatomy-order occupied match.
        - A full ``part.key`` placement (``$stow head.worn``,
          ``$stow hand.left.held``) — unambiguous.
        - The literal ``all`` — unequip every placement at once.

        Placement form binds with ``@`` too: ``$stow worn@head``
        (pick just the helm when multiple worn layers are on) or
        ``$stow held@l`` to pick the left hand's held item
        specifically when dual-wielding.
        """
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return

        channel = RpgUtilities.resolve_reply_channel(ctx, game)

        if RpgUtilities.dead_invoker_guard(
            channel, player, _DEAD_INVOKER_INVENTORY_FLAVOR,
        ):
            return

        if not queries:
            Dispatcher.add(
                channel,
                "You must specify the item(s) or placement(s) which "
                "you would like to un-equip.",
            )
            return

        # Special keyword ``all`` — unequip every occupied
        # placement. Collect unique items first (two-handed
        # weapons share an Item across both arms; dedupe by
        # identity so ``remove()`` isn't called twice).
        normalized = [q.lower().strip() for q in queries]
        if any(q == "all" for q in normalized):
            seen_ids = set()
            unique_items = []
            for item in player._iter_equipped_items():
                if id(item) in seen_ids:
                    continue
                seen_ids.add(id(item))
                unique_items.append(item)
            if not unique_items:
                Dispatcher.add(channel, f"{player.name} has nothing equipped.")
                return
            for item in unique_items:
                msg = player.remove(item)
                if msg:
                    Dispatcher.add(channel, msg)
            return

        # Resolve + remove per-query so each subsequent query sees
        # the updated equipped state. ``$stow wand.b wand.b`` on a
        # dual-wield of wands now removes BOTH wands (best first,
        # then next-best) rather than removing the same wand twice
        # via dedup. Inner dedupe still applies per-resolve so a
        # single bare-key match like ``$stow held`` (returns both
        # arms' items in one resolution) doesn't double-call
        # ``remove()`` on a two-handed weapon's shared Item ref.
        for raw in queries:
            resolved = RpgUtilities.resolve_items_or_notify(
                channel, player, [raw], mode="stow",
            )
            if not resolved:
                continue
            seen_ids = set()
            for item, _slot in resolved:
                if id(item) in seen_ids:
                    continue
                seen_ids.add(id(item))
                msg = player.remove(item)
                if msg:
                    Dispatcher.add(channel, msg)

    @command(
        name='inventory',
        aliases=['inv', 'items', 'bag'],
        brief='Sends a DM to the player with information about the items they carry.'
    )
    @cooldown(1, 5, BucketType.member)
    async def inventory(self, ctx: Context, filtr: str = None, gid: int = None):
        """
        Sends a DM to the player with information about the items they carry.

        (5-second cool-down)

        :param filtr: If provided, filter the items by name or quality containing the given string. If playing on more than one server and you wish to use this in DM to display all items, specify _ as the filter before specifying the game index.

        :param gid: If calling from a DM and playing on more than one server, provide the game's index for which you wish to view inventory. Use the 'games' command to determine the game index.
        """

        game, player = await RpgUtilities.get_game_and_player(ctx, gid)
        if game is None or player is None:
            return

        if ctx.guild is not None and not RpgUtilities.is_bot_player(player.member):
            await ctx.message.delete()

        dest = RpgUtilities.dm_target(player.member, ctx.channel)
        Dispatcher.add(dest, f'Inventory for {player.name} on {game.guild.name}')
        inv = Dispatcher.split_message(player.get_inventory(filtr), keep_sep=True)

        for msg in inv:
            Dispatcher.add(dest, f'```js\n{msg.strip()}```')

    @command(name='item', brief='Displays details about an item or placement.')
    @cooldown(1, 2, BucketType.member)
    async def item(self, ctx: Context, *, name: str = None):
        """
        Displays details about an inventory item OR the item
        currently equipped at a placement.

        Shares the query grammar with ``$equip`` / ``$stow`` /
        ``$sell``: ``<item-query>[@<placement-hint>]``. When the
        query doesn't match an inventory item, falls back to the
        placement lookup so ``$item head.worn`` or ``$item worn``
        shows the currently-worn helm's details.

        (2-second cool-down)
        """
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return

        if not name:
            Dispatcher.add(ctx, "Please specify an item or placement.")
            return

        channel = RpgUtilities.resolve_reply_channel(ctx, game)
        resolved = RpgUtilities.resolve_items_or_notify(
            channel, player, [name], mode="item",
        )
        if not resolved:
            return

        for item, _placement in resolved:
            embed, file = item.get_embed()
            Dispatcher.add(channel, embed=embed, file=file)

    @item.error
    async def item_err(self, ctx: Context, error):
        if isinstance(error, MissingRequiredArgument):
            embed = Embed(
                title=f'Item help',
                description=f"The item's index is required. To find the index, check `{ctx.prefix}inventory`",
                color=0xff0000
            )
            Dispatcher.add(ctx, embed=embed)

    @command(aliases=['spoils', 'pillage', 'plunder'], brief='Loots the remains of a recently-felled foe.')
    @guild_only()
    @cooldown(1, 10, BucketType.member)
    async def loot(self, ctx: Context):
        """
        Loots the remains of a recently-felled foe.

        (10-second cool-down)
        """

        game, player = await RpgUtilities.get_game_and_player(ctx)

        if game is None or player is None:
            return

        if game.monster is not None:
            Dispatcher.add(game.channel, "You should probably kill it before you try to loot it.")
            return

        if len(game.loot) == 0:
            Dispatcher.add(game.channel, "There is nothing to loot!")
            return

        if player.user_id not in game.loot.keys():
            Dispatcher.add(game.channel, f"{player.name} attempts to loot the corpse, but cannot interact with it.")
            return

        loot = game.loot[player.user_id]
        msg = item_list_to_string(loot)
        dropped: List[Item] = []
        if msg is not None and len(msg) > 0:
            msg = f"{player.name} found {msg}."
            for item in loot:
                if not player.give_item(item):
                    dropped.append(item)
            if len(dropped) > 0:
                txt = item_list_to_string(dropped)
                msg += f" It appears you may have a hoarding problem, though. The following item" \
                    f"{'s' if len(dropped) > 1 else ''} would overburden you: {txt}."
        else:
            msg = f"{player.name} pokes around the corpse, finding nothing useful."

        del game.loot[player.user_id]
        if len(dropped) > 0:
            game.loot[player.user_id] = dropped

        Dispatcher.add(game.channel, msg)

    @command(name='favorite', aliases=['fav', 'lock'], brief='Favorites items to protect them from bulk-sell.')
    @cooldown(1, 2, BucketType.member)
    async def favorite(self, ctx: Context, *, item: str = None):
        """
        Flags matching items as favorited. Favorited items get a ★ in
        ``$inventory`` and are skipped by ``$sell``. Fuzzy-matches the
        same way as every other item command, so ``$favorite sword``
        flags every sword in your bag.

        (2-second cool-down)

        :param item: An item name, item.n, item.quality, item.quality.n, or index.
        """
        await self._toggle_favorite(ctx, item, value=True)

    @command(name='unfavorite', aliases=['unfav', 'unlock'], brief='Unfavorites items so they can be sold again.')
    @cooldown(1, 2, BucketType.member)
    async def unfavorite(self, ctx: Context, *, item: str = None):
        """
        Clears the favorited flag on matching items. Use before
        selling an item you previously protected.

        (2-second cool-down)

        :param item: An item name, item.n, item.quality, item.quality.n, or index.
        """
        await self._toggle_favorite(ctx, item, value=False)

    async def _toggle_favorite(self, ctx: Context, item: Optional[str], value: bool):
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return

        channel = RpgUtilities.resolve_reply_channel(ctx, game)

        if not item:
            Dispatcher.add(channel, "You must specify an item.")
            return

        matches = [i for i in player.inventory.filter(item) if i is not None]
        if not matches:
            Dispatcher.add(channel, f"I'm afraid you don't have any {item}.")
            return

        changed = [i for i in matches if i.favorited != value]
        for i in changed:
            i.favorited = value

        if not changed:
            verb = "favorited" if value else "unfavorited"
            Dispatcher.add(channel, f"Already {verb}: {item_list_to_string(matches)}.")
            return

        player.is_dirty = True
        verb = "favorites" if value else "un-favorites"
        Dispatcher.add(channel, f"{player.name} {verb} {item_list_to_string(changed)}.")

    @cooldown(1, 2, BucketType.member)
    @guild_only()
    @command(name='sell', brief='Sells an item, range of items, unequipped items, or items having a given rarity.')
    async def sell(self, ctx: Context, *items: Union[int, str]):
        """
        Sells items by name, name.n, index, a range of indices, all items, or items having a given rarity.
        Items must be unequipped to be sold.

        (2-second cool-down)

        :param items: An item name, name.n, name.quality, name.quality.n, index, range of indices, quality,
        or 'all'. You may also specify multiple items with a space between them (i.e. 'stick rock spear.junk')
        """

        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return

        channel = RpgUtilities.resolve_reply_channel(ctx, game)

        if RpgUtilities.dead_invoker_guard(
            channel, player, _DEAD_INVOKER_INVENTORY_FLAVOR,
        ):
            return

        if items is None or len(items) == 0:
            Dispatcher.add(channel, "You must specify something to sell.")
            return

        msg = ''
        sell: List[Item] = []
        total = 0
        favorited_skipped = 0

        # Per-query resolve-then-sell so repeat queries see the
        # updated inventory. ``$sell wand.b wand.b`` now sells the
        # BEST and then the NEXT-BEST wand: the first sell removes
        # the superior wand from inventory, so the second
        # ``wand.b`` resolver call picks the fine wand instead of
        # the same superior again. Pre-fix, both queries resolved
        # to the same instance and the second sell hit "Item not
        # found" in the receipt.
        for _item in items:
            # Track equipped set fresh each iteration so an already-
            # sold item in a preceding iteration doesn't linger as
            # a stale reference.
            equipped = {i.id for i in player._iter_equipped_items()}
            candidates: List[Item] = []

            if (isinstance(_item, int) or _item.isnumeric()) and 1 <= int(_item) <= len(player.inventory):
                item, *_ = player.inventory.filter(_item)
                if item and item.id not in equipped:
                    candidates.append(item)
                elif item is not None:
                    msg += f'\nYou must un-equip {item.get_full_name()} before selling them.'
                else:
                    msg += f'\nNo such item: {_item}.'

            elif isinstance(_item, str):
                if _item.lower() == 'all':
                    candidates = [
                        i for i in list(player.inventory.all())
                        if i.id not in equipped
                    ]
                elif '-' in _item:
                    try:
                        low, high = map(int, _item.split('-'))
                        if low > high:
                            low, high = high, low
                        low -= 1
                        if 0 <= low <= high <= len(player.inventory):
                            candidates = [
                                i for i in player.inventory.all()[low:high]
                                if i.id not in equipped
                            ]
                        else:
                            msg += f"\nIndex range invalid."
                    except ValueError:
                        msg += f"\nUnable to determine lower and upper indices from {_item}."
                else:
                    # Fuzzy name / ``.best`` / quality-prefix —
                    # shared resolver. Sell mode returns every
                    # matching unequipped item.
                    resolved = RpgUtilities.resolve_items_or_notify(
                        channel, player, [_item], mode="sell",
                    )
                    candidates = [item for item, _slot in resolved]

            else:
                msg += f"\nI'm afraid you don't have any {_item}."

            # Apply favorites guard + equipped re-check per
            # candidate, then actually sell. Each successful sale
            # removes the item from inventory, which is what makes
            # the next query's resolver pick a different instance.
            for item in candidates:
                if item.favorited:
                    favorited_skipped += 1
                    continue
                if item.id in equipped:
                    continue
                m, v = player.sell(item, 1, True)
                if v or m.startswith("You sold"):
                    sell.append(item)
                    total += v
                    msg += f"\n{m}"

        if favorited_skipped:
            noun = "item" if favorited_skipped == 1 else "items"
            msg += f"\n{favorited_skipped} {noun} skipped (★ favorited)."

        # Nothing to sell AND no pre-sell context (favorited skips,
        # no-match / bad-range / equipped-guard messages) to report
        # back to the player. Short-circuit so we don't dispatch an
        # empty "sold the following items for a total of 0 clarks"
        # receipt that follows a resolver-emitted "no match"
        # message — that was the 2026-04-22 playtest bug.
        if not sell and not msg.strip():
            return

        msg = f'{player.name} sold the following items for a total of {total:,} clarks: ```\n{msg}```'
        msgs = Dispatcher.split_message(msg, 'clarks.', True)
        count = 0
        for m in msgs:
            Dispatcher.add(
                channel,
                ('```\n' if count > 0 else '') + m + ('```' if count > 0 and not m.endswith('```') else '')
            )
            count += 1

    @command(name='use', brief='Attempts to use an item.')
    @cooldown(1, 5, BucketType.member)
    async def use(self, ctx: Context, item: Union[int, str], gid: int = None):
        """
        Attempts to use an item.

        (5-second cool-down)

        :param item: An item name, item.n, item.quality, item.quality.n, or index to display. .n indicates to use the nth of item, for example 'candy.2' would grab the second candy in your inventory. 'sandwich.fine' or 'sandwich.fine.1' would grab the first fine sandwich in your inventory.

        :param gid: For use in DMs when playing on more than one server. Specify the game's index for which information is to be displayed. The game indices can be determined by using the `games` command.
        """

        game, player = await RpgUtilities.get_game_and_player(ctx, gid)
        if game is None or player is None:
            return

        channel = RpgUtilities.resolve_reply_channel(ctx, game)

        if RpgUtilities.dead_invoker_guard(
            channel, player, _DEAD_INVOKER_INVENTORY_FLAVOR,
        ):
            return

        _item, *_ = player.inventory.filter(item)

        if _item:
            Dispatcher.add(channel, player.use_item(_item))

        else:
            Dispatcher.add(channel, f"I'm afraid you don't have that, {player.name}")

    @use.error
    async def use_err(self, ctx: Context, error):
        if isinstance(error, MissingRequiredArgument):
            embed = Embed(
                title=f'Item help',
                description=f"The item's name or index is required. To find the index, check `{ctx.prefix}inventory`",
                color=0xff0000
            )
            Dispatcher.add(ctx, embed=embed)

    # -----------------------------------------------------------------
    # $loadout — save / load / clear named gear sets
    # -----------------------------------------------------------------
    #
    # QoL follow-up to stage 2a (destroyed-part drops gear). Players
    # can snapshot their current ``part_equipment`` under a label
    # ("combat", "travel", ...) and restore it with a single
    # ``$loadout load combat`` — no more re-equipping piece by piece
    # after a limb-destroy drop. Capped per player via
    # :data:`Player.MAX_LOADOUTS`; the cap is referenced via the
    # constant so a future bump only needs one edit.

    @group(
        name="loadout",
        aliases=["kit", "gearset", "outfit"],
        brief="Save / load named gear sets.",
        invoke_without_command=True,
        case_insensitive=True,
    )
    @cooldown(1, 2, BucketType.member)
    async def loadout(self, ctx: Context):
        """
        Save and restore named gear sets. Bare ``$loadout`` shows
        every slot you've saved. Subcommands:

        ``$loadout save <label>`` — snapshot your current gear
        under ``<label>`` (case-insensitive lookup, stored as
        entered). Overwrites an existing label with the same
        casefolded form.

        ``$loadout load <label>`` — stow current gear, then
        re-equip every piece in the saved set that's still in
        your inventory and lands on a usable body part.

        ``$loadout clear <label>`` — delete a saved slot.

        Capacity capped at 3 slots per player.
        """
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return
        channel = RpgUtilities.resolve_reply_channel(ctx, game)
        await self._render_loadout_list(channel, player)

    async def _render_loadout_list(self, channel, player):
        """Bare ``$loadout`` display: list the slots the player
        has saved, or a "no loadouts yet" prompt."""
        from caldanai.lib.rpg.creatures.player import MAX_LOADOUTS

        if not player.loadouts:
            Dispatcher.add(
                channel,
                f"{player.name} has no saved loadouts "
                f"(cap: {MAX_LOADOUTS}). "
                f"Try `$loadout save <label>` to snapshot current gear.",
            )
            return

        lines = [f"**Saved loadouts for {player.name}** "
                 f"({len(player.loadouts)}/{MAX_LOADOUTS})"]
        for label, payload in player.loadouts.items():
            # Count unique item ids referenced to give the player
            # a quick "how much is in this slot" sense without
            # dumping the full placement tree.
            unique_ids = set()
            for keys in payload.values():
                unique_ids.update(keys.values())
            lines.append(
                f"  `{label}` — {len(unique_ids)} item"
                f"{'s' if len(unique_ids) != 1 else ''}"
            )
        Dispatcher.add(channel, "\n".join(lines))

    @loadout.command(name="save", brief="Save current gear under a label.")
    async def loadout_save(self, ctx: Context, *, label: str = None):
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return
        channel = RpgUtilities.resolve_reply_channel(ctx, game)

        if not label or not label.strip():
            Dispatcher.add(
                channel,
                "Specify a label: `$loadout save <label>`.",
            )
            return

        ok, msg = player.save_loadout(label)
        if ok:
            Dispatcher.add(
                channel,
                f"{player.name} saved the `{msg}` loadout.",
            )
        else:
            Dispatcher.add(channel, msg)

    @loadout.command(name="load", brief="Restore a saved gear set.")
    async def loadout_load(self, ctx: Context, *, label: str = None):
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return
        channel = RpgUtilities.resolve_reply_channel(ctx, game)

        if RpgUtilities.dead_invoker_guard(
            channel, player, _DEAD_INVOKER_INVENTORY_FLAVOR,
        ):
            return

        if not label or not label.strip():
            Dispatcher.add(
                channel,
                "Specify a label: `$loadout load <label>`.",
            )
            return

        # Fuzzy prefix resolution before the actual load.
        # ``$loadout load dual`` finds ``dual-wand`` when that's
        # the only prefix match. Multiple prefix matches surface
        # as a "did you mean" list instead of silently picking.
        resolved, candidates = player.resolve_loadout_label(label)
        if resolved is None:
            if candidates:
                cand = ", ".join(f"`{c}`" for c in candidates)
                Dispatcher.add(
                    channel,
                    f"`{label}` matches multiple loadouts: {cand}. "
                    f"Specify the full label.",
                )
            else:
                Dispatcher.add(
                    channel,
                    f"No loadout matching `{label}`. "
                    f"Check `$loadout` for your saved labels.",
                )
            return

        ok, stored_label, restored, skipped = player.load_loadout(resolved)
        # ``ok`` should always be True here — we just resolved
        # the label against live loadouts — but guard defensively.
        if not ok:
            Dispatcher.add(
                channel,
                f"No loadout matching `{label}`. "
                f"Check `$loadout` for your saved labels.",
            )
            return

        parts = [f"{player.name} equipped the `{stored_label}` loadout."]
        if restored:
            parts.append(f"Restored: {item_list_to_string(restored)}.")
        if skipped:
            bullets = "\n".join(f"  • {s}" for s in skipped)
            parts.append(f"Skipped:\n{bullets}")
        Dispatcher.add(channel, "\n".join(parts))

    @loadout.command(name="clear", aliases=["delete", "remove"], brief="Delete a saved gear set.")
    async def loadout_clear(self, ctx: Context, *, label: str = None):
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return
        channel = RpgUtilities.resolve_reply_channel(ctx, game)

        if not label or not label.strip():
            Dispatcher.add(
                channel,
                "Specify a label: `$loadout clear <label>`.",
            )
            return

        # Same fuzzy-prefix resolution as ``load``. Ambiguity
        # surfaces candidates instead of silently clearing the
        # wrong slot — deletion should be unambiguous.
        resolved, candidates = player.resolve_loadout_label(label)
        if resolved is None:
            if candidates:
                cand = ", ".join(f"`{c}`" for c in candidates)
                Dispatcher.add(
                    channel,
                    f"`{label}` matches multiple loadouts: {cand}. "
                    f"Specify the full label.",
                )
            else:
                Dispatcher.add(
                    channel,
                    f"No loadout matching `{label}`.",
                )
            return

        ok, stored_label = player.clear_loadout(resolved)
        if ok:
            Dispatcher.add(
                channel,
                f"{player.name} cleared the `{stored_label}` loadout.",
            )
        else:
            # Defensive; ``resolved`` was just looked up.
            Dispatcher.add(channel, f"No loadout matching `{label}`.")

    @Cog.listener()
    async def on_ready(self):
        _log.info("RpgInventoryCommands ready.")


async def setup(bot):
    await bot.add_cog(RpgInventoryCommands(bot))
