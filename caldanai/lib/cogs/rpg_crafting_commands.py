"""Crafting cog — `$craft` and `$learn`.

`$craft <item>` consumes materials, rolls success against the
player's skill, and (on success) generates the output item with
quality emergent from input qualities + skill margin. `$craft
list` enumerates currently-craftable recipes; `$craft info <item>`
shows a single recipe's details and predicted outcome.

`$learn` consumes a recipe scroll from inventory and adds the
embedded recipe to the player's known set. Already-known scrolls
grant a small skill XP refund instead of being wasted.
"""
from typing import Dict, List, Optional, Tuple

from discord.ext.commands import (
    BucketType,
    Cog,
    Context,
    command,
    cooldown,
    group,
)

from caldanai.dispatcher import Dispatcher
from caldanai.logger import get_logger
from caldanai.lib.rpg.crafting import (
    RecipePlugin,
    discover_recipes,
    get_recipe,
    list_recipes,
    success_chance,
    roll_success,
    roll_quality,
)
from caldanai.lib.rpg.helpers.enums import Qualities
from caldanai.lib.rpg.helpers.utils import RpgUtilities
from caldanai.lib.rpg.inventory import Inventory
from caldanai.lib.rpg.inventory.stackables import Stackable


_log = get_logger(__name__)


_DEAD_INVOKER_CRAFT_FLAVOR = [
    "@1np tools sit cold and untouched. The corpse will not work them.",
    "A dry rattle escapes @1 — perhaps a curse against the unfinished work.",
    "@1 cannot craft. @1 is presently dead.",
]


def _normalize(name: str) -> str:
    """Map a user-typed item name to a recipe-output stem."""
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def _find_materials(
    player, materials: Dict[str, int],
) -> Tuple[bool, Dict[str, List[Stackable]], List[str]]:
    """Locate the requested materials in the player's inventory.

    Returns ``(ok, found_by_name, missing)``:

    - ``ok``: True iff every material has enough total count
      across all matching stacks.
    - ``found_by_name``: maps material plugin stem → list of
      matching ``Stackable`` instances in the inventory, sorted
      by quality (lowest first) so consumption defaults to using
      junk before fine.
    - ``missing``: human-readable list of "leather x 3 (have 1)"
      strings for the user-facing failure message.
    """
    found: Dict[str, List[Stackable]] = {}
    missing: List[str] = []
    for stem, need in materials.items():
        stacks = [
            it for it in player.inventory.all()
            if isinstance(it, Stackable) and it.plugin == stem
        ]
        # Lowest quality first — consume junk before fine.
        stacks.sort(
            key=lambda s: 0 if s.quality is None else list(Qualities).index(s.quality),
        )
        found[stem] = stacks
        have = sum(s.count for s in stacks)
        if have < need:
            missing.append(f"{stem.replace('_', ' ')} x {need} (have {have})")
    return (not missing), found, missing


def _consume_materials(
    player,
    materials: Dict[str, int],
    found_by_name: Dict[str, List[Stackable]],
    fraction: float = 1.0,
) -> List[Qualities]:
    """Remove ``materials`` from the player's inventory, scaled by
    ``fraction`` (0.5 on a failed craft → consumes half, rounded
    up). Returns the per-unit qualities consumed so the caller can
    feed them to the quality roll.
    """
    consumed: List[Qualities] = []
    for stem, need in materials.items():
        scaled = max(1, round(need * fraction)) if fraction > 0 else 0
        if scaled == 0:
            continue
        for stack in found_by_name.get(stem, []):
            if scaled == 0:
                break
            take = min(stack.count, scaled)
            consumed.extend([stack.quality or Qualities.ORDINARY] * take)
            player.inventory.remove(stack, take)
            scaled -= take
    return consumed


class RpgCraftingCommands(Cog):
    def __init__(self, bot):
        self.bot = bot

    @group(
        name="craft",
        invoke_without_command=True,
        brief="Craft an item from materials.",
    )
    @cooldown(1, 2, BucketType.member)
    async def craft(self, ctx: Context, *args: str):
        """
        Craft an item:

        ``$craft <item>``         — attempt to craft.
        ``$craft list``           — recipes you know AND can craft right now.
        ``$craft info <item>``    — recipe details + current success chance.

        Material costs scale with item size (a jerkin needs more
        leather than a cap). Output quality emerges from the
        average input quality plus a skill bonus, with some
        variance — combining lower-quality materials with high
        skill can produce something better than either alone.

        (2-second cool-down)
        """
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return
        channel = RpgUtilities.resolve_reply_channel(ctx, game)
        if RpgUtilities.dead_invoker_guard(
            channel, player, _DEAD_INVOKER_CRAFT_FLAVOR,
        ):
            return

        if not args:
            await self._send_list(channel, player)
            return

        await self._do_craft(channel, player, " ".join(args))

    @craft.command(name="list", brief="List craftable recipes you know.")
    async def craft_list(self, ctx: Context):
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return
        channel = RpgUtilities.resolve_reply_channel(ctx, game)
        await self._send_list(channel, player)

    @craft.command(name="info", brief="Show details for a recipe.")
    async def craft_info(self, ctx: Context, *args: str):
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return
        channel = RpgUtilities.resolve_reply_channel(ctx, game)
        if not args:
            Dispatcher.add(channel, "Usage: ``$craft info <item>``.")
            return
        await self._send_info(channel, player, " ".join(args))

    @command(
        name="learn",
        brief="Learn a recipe from a scroll in your inventory.",
    )
    @cooldown(1, 2, BucketType.member)
    async def learn(self, ctx: Context, *args: str):
        """Consume a recipe scroll from inventory and add the
        embedded recipe to your known set. If you already knew
        the recipe, the scroll grants a small skill-XP refund
        instead of being wasted.

        ``$learn``                — learn the first scroll in inventory.
        ``$learn <recipe name>``  — learn a specific recipe (matched
                                    against scroll's recipe name).

        (2-second cool-down)
        """
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return
        channel = RpgUtilities.resolve_reply_channel(ctx, game)
        if RpgUtilities.dead_invoker_guard(
            channel, player, _DEAD_INVOKER_CRAFT_FLAVOR,
        ):
            return

        scrolls = [
            it for it in player.inventory.all()
            if isinstance(it, Stackable)
            and it.plugin == "recipe_scroll"
        ]
        if args:
            wanted = _normalize(" ".join(args))
            scrolls = [
                s for s in scrolls
                if getattr(s, "recipe_name", "") == wanted
            ]
        if not scrolls:
            Dispatcher.add(
                channel,
                "You don't have a recipe scroll to learn from.",
            )
            return

        scroll = scrolls[0]
        recipe_name = getattr(scroll, "recipe_name", "")
        recipe = get_recipe(recipe_name)
        if recipe is None:
            label = f"`{recipe_name}`" if recipe_name else "(blank scroll)"
            Dispatcher.add(
                channel,
                f"The scroll's writing is illegible — no such recipe "
                f"as {label} exists.",
            )
            return

        already_known = recipe_name in player.known_recipes
        # Consume one scroll either way.
        player.inventory.remove(scroll, 1)
        player.is_dirty = True

        if already_known:
            # Refund: ~10% of min_skill, floor 1, plus a baseline so
            # learning a min_skill=0 recipe still pays a token amount.
            refund = max(1, recipe.min_skill // 10)
            if recipe.skill:
                player.skills.setdefault(recipe.skill, 0)
                player.skills[recipe.skill] += refund
                xp_str = f"+{refund} {recipe.skill}"
            else:
                xp_str = "no skill XP — this recipe is unskilled"
            Dispatcher.add(
                channel,
                f"{player.name} already knows `{recipe.display_name()}` — "
                f"the scroll's review reinforces the muscle memory "
                f"({xp_str}).",
            )
        else:
            player.known_recipes.add(recipe_name)
            Dispatcher.add(
                channel,
                f"{player.name} learns the recipe for "
                f"**{recipe.display_name()}**.",
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _do_craft(self, channel, player, raw_name: str) -> None:
        # Lazy ensure recipes are discovered (test fixtures sometimes
        # bypass the bot startup hook that does it eagerly).
        stem = _normalize(raw_name)
        recipe = get_recipe(stem)
        if recipe is None:
            Dispatcher.add(
                channel,
                f"No recipe matches `{raw_name}`. Try `$craft list`.",
            )
            return

        # Gate: known?
        if recipe.requires_known and stem not in player.known_recipes:
            Dispatcher.add(
                channel,
                f"You don't know how to craft "
                f"**{recipe.display_name()}** yet — find a scroll and "
                f"`$learn` it.",
            )
            return

        # Gate: skill min?
        skill_xp = (
            player.skills.get(recipe.skill, 0)
            if recipe.skill
            else 0
        )
        if recipe.skill and skill_xp < recipe.min_skill:
            Dispatcher.add(
                channel,
                f"You need at least {recipe.min_skill} XP in "
                f"`{recipe.skill}` to attempt **{recipe.display_name()}** "
                f"(you have {skill_xp}).",
            )
            return

        # Gate: materials?
        ok, found, missing = _find_materials(player, recipe.materials)
        if not ok:
            Dispatcher.add(
                channel,
                f"Not enough materials for **{recipe.display_name()}**: "
                f"missing {', '.join(missing)}.",
            )
            return

        # Roll success.
        succeeded = roll_success(skill_xp, recipe.min_skill)
        if succeeded:
            consumed = _consume_materials(player, recipe.materials, found, 1.0)
            quality = roll_quality(consumed, skill_xp, recipe.min_skill)
            output = Inventory.load_item(
                name=recipe.output, data={"quality": quality.name},
            )
            if output is None:
                # Defensive — should never happen in practice; recipe
                # output stems are validated at discovery.
                Dispatcher.add(
                    channel,
                    f"Crafted **{recipe.display_name()}** but couldn't "
                    f"materialize the item — flag this as a bug.",
                )
                return
            player.inventory.add(output)
            if recipe.skill:
                player.skills.setdefault(recipe.skill, 0)
                player.skills[recipe.skill] += recipe.xp_reward_success
            player.is_dirty = True
            Dispatcher.add(
                channel,
                f"{player.name} crafts {output.get_full_name()}. "
                f"(+{recipe.xp_reward_success} {recipe.skill or 'XP'})",
            )
        else:
            # Failure: half the materials are wasted, small XP grant
            # so the player isn't grinding-blocked by bad luck.
            _consume_materials(player, recipe.materials, found, 0.5)
            if recipe.skill:
                player.skills.setdefault(recipe.skill, 0)
                player.skills[recipe.skill] += recipe.xp_reward_failure
            player.is_dirty = True
            Dispatcher.add(
                channel,
                f"{player.name} botches **{recipe.display_name()}** — "
                f"half the materials are spoiled. "
                f"(+{recipe.xp_reward_failure} {recipe.skill or 'XP'})",
            )

    async def _send_list(self, channel, player) -> None:
        if not list_recipes():
            discover_recipes()
        rows: List[str] = []
        for cls in list_recipes():
            # Hide locked recipes the player can't see at all.
            if cls.requires_known and cls.output not in player.known_recipes:
                continue
            ok, _, _ = _find_materials(player, cls.materials)
            if not ok:
                continue
            skill_xp = (
                player.skills.get(cls.skill, 0)
                if cls.skill
                else 0
            )
            if cls.skill and skill_xp < cls.min_skill:
                continue
            chance = success_chance(skill_xp, cls.min_skill)
            rows.append(
                f"• **{cls.display_name()}** "
                f"({int(chance * 100)}% success)"
            )

        if not rows:
            Dispatcher.add(
                channel,
                "Nothing craftable right now — gather more materials "
                "or learn more recipes.",
            )
            return

        Dispatcher.add(
            channel,
            f"{player.name} can craft:\n" + "\n".join(rows),
        )

    async def _send_info(self, channel, player, raw_name: str) -> None:
        stem = _normalize(raw_name)
        recipe = get_recipe(stem)
        if recipe is None:
            Dispatcher.add(
                channel,
                f"No recipe matches `{raw_name}`. Try `$craft list`.",
            )
            return

        skill_xp = (
            player.skills.get(recipe.skill, 0)
            if recipe.skill
            else 0
        )
        chance = success_chance(skill_xp, recipe.min_skill)
        material_str = ", ".join(
            f"{stem.replace('_', ' ')} × {n}"
            for stem, n in recipe.materials.items()
        )
        known_marker = ""
        if recipe.requires_known:
            known_marker = (
                " (learned)"
                if recipe.output in player.known_recipes
                else " (not yet learned)"
            )
        skill_str = (
            f"{recipe.skill} (you: {skill_xp}, min: {recipe.min_skill})"
            if recipe.skill
            else "no skill required"
        )
        Dispatcher.add(
            channel,
            (
                f"**{recipe.display_name()}**{known_marker}\n"
                f"  Materials: {material_str}\n"
                f"  Skill: {skill_str}\n"
                f"  Success chance: {int(chance * 100)}%"
            ),
        )

    @Cog.listener()
    async def on_ready(self):
        # Eager discovery on bot ready so the first $craft doesn't
        # pay the import cost.
        discover_recipes()
        _log.info(
            f"RpgCraftingCommands ready. {len(list_recipes())} recipes loaded."
        )


async def setup(bot):
    await bot.add_cog(RpgCraftingCommands(bot))
