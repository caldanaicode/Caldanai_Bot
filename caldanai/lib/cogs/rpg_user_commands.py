import math
from random import choice

from discord.ext.commands import Cog, command, cooldown, BucketType, guild_only, group, Context

from caldanai.dispatcher import Dispatcher
from caldanai.logger import get_logger
from caldanai.lib.rpg.helpers.utils import RpgUtilities, generate_report
from caldanai.lib.rpg import Game
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.dice import Dice
from caldanai.lib.rpg.helpers.parser import parse


_log = get_logger(__name__)


# Dead-invoker flavor pool for the attack / kill / slay family.
# Each line is a single-actor ``@1`` template applied to the invoker
# via ``RpgUtilities.dead_invoker_guard``.
_DEAD_INVOKER_ATTACK_FLAVOR = [
    "A ghostly moan escapes the corpse of @1.",
    "@1np spectral hand twitches toward a weapon that is no longer there.",
    "A sound like a distant war-drum rolls through the bones of @1 and fades.",
    "The corpse of @1 cannot strike, but the impulse lingers.",
    "@1np death-mask sets in grim determination at no one in particular.",
    "A cold draught hisses through the remains of @1 — perhaps a battle-cry, perhaps only the wind.",
    "@1np fingers curl around the memory of a hilt.",
]


class RpgUserCommands(Cog):
    def __init__(self, bot):
        self.bot = bot

    @group(brief="Groups together various game commands for players.", case_insensitive=True)
    @guild_only()
    @cooldown(1, 10, BucketType.member)
    async def game(self, ctx: Context):
        """
        Requires a subcommand.

        (10-second cool-down)
        """

        if ctx.invoked_subcommand is None:
            Dispatcher.add(ctx, "This command cannot be used on its own.")
            return

    @guild_only()
    @game.command(brief="Adds a player to the RPG system.")
    async def join(self, ctx: Context):
        """
        Adds a member to the RPG system as a player if they do not already exist in the database. This can only be called by the member trying to participate.
        """

        game: Game = await RpgUtilities.get_game(ctx)
        if game is None:
            return

        if await game.player_manager.add_player(ctx):
            Dispatcher.add(game.channel, f"Welcome, {ctx.author.display_name}")

        else:
            Dispatcher.add(game.channel, f"You are already a player in this RPG, {ctx.author.display_name}!")

    @guild_only()
    @game.command(name="leave", brief="Removes the player from the RPG system.")
    async def leave(self, ctx: Context, gid: int = None):
        """
        Removes an existing player from the game. This can only be called by member withdrawing from participation.
        """

        game, player = await RpgUtilities.get_game_and_player(ctx, gid)

        if game is None or player is None:
            return

        await game.player_manager.remove_player(ctx.author.id, game.guild.id, game.channel.id)
        game.save()
        Dispatcher.add(game.channel, f"You have been removed from the game, {ctx.author.display_name}!")

    @command(
        name="attack",
        aliases=[
            "annihilate",
            "kill",
            "murder",
            "destroy",
            "obliterate",
            "slaughter",
            "slay",
            "rip&tear",
            "ripandtear",
            "ripampersandtear",
        ],
        brief="Attacks the critter currently daring to show it's face to intrepid adventurers!",
    )
    @guild_only()
    @cooldown(1, 10, BucketType.member)
    async def attack(self, ctx: Context, *, target: str = None):
        """
        Attacks the critter currently daring to show its face to intrepid adventurers!
        Optionally specify a body part to target, e.g. ``$kill arm.left``
        or ``$kill goblin arm.left``. If already in combat, re-calling
        ``$kill <part>`` updates the target without re-joining.

        (10-second cool-down)
        """

        game, player = await RpgUtilities.get_game_and_player(ctx)

        if game is None or player is None:
            return

        if game.monster is None:
            Dispatcher.add(game.channel, "You see nothing to attack!")
            return

        if RpgUtilities.dead_invoker_guard(
            game.channel, player, _DEAD_INVOKER_ATTACK_FLAVOR,
        ):
            return

        already_in_combat = player in game.combatants

        # Peel an optional leading monster-name token off ``target``
        # before part parsing. ``$kill werewolf`` should join combat
        # without the misleading "no targetable part matching
        # 'werewolf'" warning. ``$kill werewolf arm.left`` should
        # target the left arm. Monster-name detection is FIRST-TOKEN
        # ONLY — ``$kill arm.left werewolf`` keeps today's behavior
        # (werewolf becomes an unknown part token and silently drops).
        # Forward-compat for multi-monster swarms where the leading
        # token actively picks the enemy.
        part_input, monster_token_consumed = self._strip_leading_monster_token(
            target, game.monster,
        )

        # Parse explicit body-part targets from the command arguments.
        # Supports one target (all sources hit it) or multiple (one per source).
        part_targets = self._parse_part_targets(part_input, game.monster)

        # Warn if the player typed something but nothing resolved.
        # If we consumed the leading monster token, ``leftover`` is
        # the remainder; if it's empty (player typed *only* the
        # monster name) the warning is correctly suppressed by the
        # ``leftover`` truthiness check. If it's non-empty but has
        # no recognized parts (e.g. ``$kill werewolf typo``), we
        # still warn — the typo is a real problem worth surfacing.
        leftover = (part_input or "").strip()
        if leftover and not part_targets and game.monster.body_parts:
            Dispatcher.add(
                game.channel,
                f"No targetable part matching '{leftover}' found. Attacking randomly.",
            )

        if already_in_combat:
            game.combat_targets[player.user_id] = part_targets or None
            if part_targets:
                label = self._display_targets(part_targets, game.monster)
                Dispatcher.add(game.channel, f"{player.name} shifts focus to {label}!")
            else:
                Dispatcher.add(game.channel, f"{player.name} attacks wildly!")
            return

        game.combatants.append(player)
        game.combat_targets[player.user_id] = part_targets or None

        if part_targets:
            label = self._display_targets(part_targets, game.monster)
            Dispatcher.add(game.channel, f"{player.name} prepares to attack, targeting {label}!")
        else:
            Dispatcher.add(game.channel, f"{player.name} prepares to attack!")

    @staticmethod
    def _strip_leading_monster_token(target_str, monster):
        """Peel an optional leading monster-name token off ``$kill``'s
        argument string.

        Returns ``(remainder, consumed)``:

        - ``remainder`` is the argument string with the first token
          removed if (and only if) it resolved to ``monster``;
          otherwise it's the original ``target_str`` unchanged.
        - ``consumed`` is ``True`` when the first token was consumed.

        Match rule mirrors ``$look``'s
        :meth:`_monster_matches_look_target`: case-insensitive
        equality against ``monster.name`` OR equality against any
        whitespace-separated word token of that name (so ``"hydra"``
        catches a "hexed hydra"). Fuzzy / prefix matching is
        deliberately NOT applied here — ``find_plugin_classes`` /
        prefix lookup would consume single-letter or short tokens
        like ``"h"`` (against Hydra) or ``"t"`` (against Toad), which
        players actually type to target ``head`` / ``torso`` via
        ``find_parts``. Loose matching here would silently lose
        those part shortcuts. Multi-monster swarms will eventually
        need a tighter disambiguation rule; today's exact / word-
        token match is correct for the single-monster case.

        First-token only — ``$kill arm.left werewolf`` keeps today's
        behavior (the trailing ``werewolf`` becomes an unknown part
        token and silently drops out via ``_parse_part_targets``).
        """
        if not target_str or monster is None:
            return target_str, False
        # Whitespace-aware split so tabs / multiple spaces don't
        # leak into the remainder. Matches ``_parse_part_targets``'s
        # ``.split()`` convention below.
        parts = (target_str or "").split(None, 1)
        if not parts:
            return target_str, False
        first = parts[0]
        rest = parts[1] if len(parts) > 1 else ""

        first_lower = first.lower()
        name_lower = (monster.name or "").lower()

        is_match = (
            first_lower == name_lower
            or first_lower in name_lower.split()
        )

        if not is_match:
            return target_str, False

        return rest, True

    def _parse_part_targets(self, target_str, monster):
        """Parse body-part names from the player's command input.

        Returns a list of canonical part-name strings (may be empty).
        Accepts: ``"arm.left"``, ``"arm.left leg.right"``,
        ``"goblin arm.left"`` (unrecognized tokens like the monster
        name are silently skipped). Fuzzy-matches per dotted segment so
        ``"leg.r"`` resolves to ``"leg.right"``.

        Every match expands to the part's canonical ``name`` so that
        ``_display_targets`` always renders cleanly. A token that
        resolves to multiple parts (e.g. ``"leg"`` → both legs, or
        ``"h"`` → head plus hands) contributes one canonical entry per
        match; ``do_attack`` then distributes one name per source slot.
        """
        if not target_str or not monster.body_parts:
            return []

        seen = set()
        matched = []
        for token in target_str.strip().split():
            for p in monster.find_parts(token):
                if p.name in seen:
                    continue
                seen.add(p.name)
                matched.append(p.name)
        return matched

    # Flavor pools for `$target <@player>` — a goofy, non-mechanical
    # branch in the same spirit as ``$smite`` / ``$hug`` / ``$haunt``.
    # Self-targeting leans into "wait, am *I* the problem?" humor;
    # other-player targeting leans into "you aren't actually going to
    # do it and you know it."
    _TARGET_SELF_FLAVOR = [
        "@1 contemplates the precise angle for a proper seppuku, then thinks better of it.",
        "@1 draws a weapon, squints at @1a own navel, and quietly changes @1a mind.",
        "@1 takes aim at @1a own shadow. The shadow flinches first.",
        "@1 adopts a thousand-yard stare pointed inward.",
        "@1 squares up to the nearest mirror. The mirror squares back.",
        "@1 arrives at the uncomfortable suspicion that *@1s* has been the monster all along.",
        "@1 stares down at @1a boots with a long, introspective sigh.",
        "@1np hand drifts to @1a hilt; @1np other hand gently guides it away.",
    ]

    _TARGET_OTHER_FLAVOR = [
        "@1 takes aim at @2, who visibly decides to notice something more interesting.",
        "@1 lines up a heroic stance in @2np direction. @2 yawns.",
        "@1 contemplates @2, weighs the cost of friendship, and sheathes the impulse.",
        "@1 squints meaningfully at @2. @2 does not respond to the squint.",
        "@1 pretends to draw a bead on @2 for at least one dramatic beat.",
        "@1 considers whether @2 is, in fact, the real threat here. Verdict: pending.",
        "@1 levels a finger at @2 and mouths *bang*. @2 clutches at nothing in particular.",
    ]

    _TARGET_BOT_FLAVOR = [
        "You cannot target the narrator, mortal. The narrator targets you.",
        "@1 trains @1a weapon on a ghost in the machine. The machine does not flinch.",
        "@1 aims at the sky itself. Somewhere, a server shrugs.",
    ]

    # Pool fires whenever the *invoker* is dead, regardless of who
    # they targeted — the dead can't meaningfully line up a swing.
    # Kept target-agnostic (no @2) so one pool covers self-targeting,
    # other-player-targeting, and dead-player-targeting from beyond
    # the grave.
    _TARGET_DEAD_INVOKER_FLAVOR = [
        "The corpse of @1 stares skyward, undecided on any particular target.",
        "@1 is in no condition to aim at anything — the dead declare no targets.",
        "@1np spirit flickers at the idea, but the body stays put.",
        "A non-committal glare escapes @1np still form. Hard to say at what.",
        "@1 would very much like to pick a target, but the dead have no hands to point with.",
    ]

    # Pool fires when a live invoker targets a dead player — a dead
    # teammate isn't going to notice and the line leans into that.
    _TARGET_DEAD_TARGET_FLAVOR = [
        "@2 is in no condition to notice @1np attention. Best to let @2o rest.",
        "@1 levels a finger at the corpse of @2, who remains resolutely uninterested.",
        "The dead do not flinch. @2 is no exception.",
        "@1 squints meaningfully at @2. @2 does not squint back. @2 does not do much of anything, really.",
    ]

    @command(name="target", aliases=["aim", "focus"], brief="Changes your attack target to specific body parts.")
    @guild_only()
    async def target_part(self, ctx: Context, *, part: str = None):
        """
        Changes your attack focus mid-combat.
        Use ``$target arm.left`` to focus all weapons on one part,
        ``$target arm.left leg.right`` to split (one per weapon),
        ``$target`` alone to clear targeting and attack randomly, or
        ``$target @someone`` for a bit of fun.
        """
        game, player = await RpgUtilities.get_game_and_player(ctx)

        if game is None or player is None:
            return

        # Player-mention branch: `$target @someone` is a flavor-only,
        # non-mechanical response. Keep it above the combat-state
        # guards so targeting a friend doesn't have to wait for
        # combat to exist. The doppelganger case (monster whose
        # ``name`` matches a player's ``display_name``) routes to
        # the body-part flow — mirrors the ``$hug`` pattern.
        if ctx.message.mentions:
            mention = ctx.message.mentions[0]

            # Dead-invoker check runs FIRST, before bot / doppelganger
            # / target-player dispatch. A dead player can't
            # meaningfully aim at anything, so the dead pool always
            # wins regardless of who was mentioned — matches the
            # other-command convention (``$kill @something`` also
            # hits the dead-invoker pool, not the target-specific
            # response).
            if RpgUtilities.dead_invoker_guard(
                game.channel, player, self._TARGET_DEAD_INVOKER_FLAVOR,
            ):
                return

            if self.bot.user in ctx.message.mentions:
                Dispatcher.add(
                    game.channel, parse(choice(self._TARGET_BOT_FLAVOR), player),
                )
                return
            if (
                game.monster is not None
                and game.monster.name.lower() == mention.display_name.lower()
            ):
                Dispatcher.add(
                    game.channel,
                    f"Even in that shape, there's still a {game.monster.name} "
                    f"under it. Try $target <part>.",
                )
                return
            target_player = await RpgUtilities.get_player(
                mention, game=game, notify=False,
            )
            if target_player is None:
                return

            # Dead-target check: live invoker (we cleared the dead
            # branch above) is aiming at a dead teammate. Two-actor
            # pool doesn't fit the single-actor guard shape, stays
            # inline.
            if (
                target_player.is_dead()
                and target_player.member != player.member
            ):
                Dispatcher.add(
                    game.channel,
                    parse(
                        choice(self._TARGET_DEAD_TARGET_FLAVOR),
                        player, target_player,
                    ),
                )
                return

            if target_player.member == player.member:
                Dispatcher.add(
                    game.channel, parse(choice(self._TARGET_SELF_FLAVOR), player),
                )
            else:
                Dispatcher.add(
                    game.channel,
                    parse(choice(self._TARGET_OTHER_FLAVOR), player, target_player),
                )
            return

        # Order matters: "no monster" is the more fundamental state
        # than "not in combat" — if there's nothing to target, "use
        # $kill to join" is misleading (nothing to join).
        if game.monster is None:
            Dispatcher.add(game.channel, "There's nothing to target!")
            return

        if player not in game.combatants:
            Dispatcher.add(game.channel, f"{player.name} is not in combat. Use $kill to join!")
            return

        if not part or not part.strip():
            game.combat_targets[player.user_id] = None
            Dispatcher.add(game.channel, f"{player.name} clears targeting — attacking randomly.")
            return

        part_targets = self._parse_part_targets(part, game.monster)

        if not part_targets:
            Dispatcher.add(
                game.channel,
                f"No targetable part matching '{part.strip()}' found on the {game.monster.name}.",
            )
            return

        game.combat_targets[player.user_id] = part_targets
        label = self._display_targets(part_targets, game.monster)
        Dispatcher.add(game.channel, f"{player.name} shifts focus to {label}!")

    @staticmethod
    def _display_targets(part_targets: list, monster) -> str:
        """Join a list of codified part names into a readable label
        with appropriate articles.

        ``["arm.left", "leg.right"]`` → ``"the left arm and the right leg"``
        ``["head.2", "torso"]`` → ``"head 2 and the torso"``

        Each codified name is resolved to the owning ``BodyPart`` on
        ``monster`` so the rendering uses the canonical
        ``BodyPart._display_with_article`` logic. If a name fails to
        resolve (e.g. the part was destroyed between target-parse and
        display), we degrade to a plain string-based rendering rather
        than crashing.
        """
        def render(codified: str) -> str:
            matches = monster.find_parts(codified) if monster is not None else []
            for part in matches:
                if part.name == codified:
                    return part._display_with_article()
            # Fallback: no resolving part (destroyed, missing, or no
            # monster). Reproduce the legacy string-only logic so the
            # label still renders something sensible.
            if "." not in codified:
                return f"the {codified}"
            base, qualifier = codified.rsplit(".", 1)
            if qualifier.isnumeric():
                return f"{base} {qualifier}"
            return f"the {qualifier} {base}"

        return " and ".join(render(t) for t in part_targets)

    @cooldown(1, 60, BucketType.member)
    @command(name="pray", aliases=["meditate", "reflect"], brief="Beseeches heavenly blessings.")
    async def pray(self, ctx: Context):
        """
        Beseeches heavenly blessings. Occasionally, prayers may be answered...

        (60-second cool-down)
        """

        if ctx.guild is None:
            Dispatcher.add(ctx, f"I see you're interested in a little private reflection...")
            return

        game, player = await RpgUtilities.get_game_and_player(ctx)

        if game is None or player is None:
            return

        if player.is_dead():
            msg = choice(
                [
                    "Posthumous piety profits particularly poorly, @1.",
                    "Your prayers can no longer pierce the planes of piety, @1.",
                    "It seems, @1, that if anyone is listening, they no longer care...",
                    "The power of prayer eludes the dead, @1.",
                    "Hideous cackling erupts from unseen places as the spirit of @1 seeks salvation.",
                    "A sense of dread settles over @1np shade, and @1s @1v(cries|cry) out forlornly.",
                ]
            )
            Dispatcher.add(game.channel, parse(msg, player))
            return

        msgs = [
            "@1 offers a solemn prayer, seeking forgiveness and humility.",
            "@1 seeks the guidance of the Divine.",
            "@1 falls to @1a knees in reverence, face lifted to the sky as @1s @1v(basks|bask) in a divine embrace.",
            "@1np eyes turn skyward as @1s @1v(entreats|entreat) the Divine for benevolence.",
            "@1 proffers words of hope, attempting to sooth the splintered souls of comrades.",
        ]

        msg = choice(msgs)
        d20 = Dice.d20()
        msg += f" (1d{d20.sides} = {d20.value})"
        player.update_roll_count(d20.sides, d20.value)
        heal_amount = 0
        actors = [
            player,
        ]
        if d20.value == 1:
            msg += (
                "\nSacrifice is demanded for your insolence, @1!\n\nA sudden storm explodes into the area, "
                "as a blinding bolt of lightning envelopes @1. When the light fades, nothing remains but a charred husk."
            )

            msg += f"\n\n{player.apply_damage(player.health)}\n\nThe storm calms to a gentle rain..."

            index = 2
            for p in game.player_manager.players.values():
                if p == player:
                    continue
                # "Needs healing" includes part injuries — a player
                # with a destroyed arm but full body HP should still
                # be caught in the rain.
                if not p.is_injured():
                    continue
                msg += f"\n@{index}'s skin glows softly under the touch of the rain. "
                # apply_damage before heal_fully so the resurrection
                # narration (only fired when the player was at 0 HP)
                # still gets appended before heal_fully tops everything
                # off. heal_fully handles parts, regen, and is_dirty.
                if p.health < p.get_health_max():
                    heal_msg = p.apply_damage(p.health - p.get_health_max())
                    if heal_msg:
                        msg += f"{heal_msg} "
                p.heal_fully()
                msg += f"@{index} is made whole!"
                actors.append(p)
                index += 1

            if player in game.combatants:
                game.combatants.remove(player)

        elif d20.value > 16:
            # Candidate filter includes part-injured players, not
            # just body-HP-injured ones.
            candidates = [
                p for p in game.player_manager.players.values()
                if p.is_injured()
            ] or [player]
            # Pick the most-injured by body-HP ratio; if everyone has
            # full body HP but some have part injuries, pick by
            # part-injury count as a tiebreaker.
            heal_target: Player = min(
                candidates,
                key=lambda p: (
                    p.get_health_scale(),
                    -sum(
                        1 for part in (p.body_parts or [])
                        if part.health < part.health_max
                    ),
                ),
            )
            actors.append(heal_target)
            index = len(actors)

            if d20.value == 20:
                # Divine miracle: full body + full parts restore.
                # apply_damage first for the resurrection narration
                # side effect (only emitted when healing from 0 HP);
                # heal_fully then tops body HP off and restores parts,
                # regen, and is_dirty.
                body_heal_msg = ""
                if heal_target.health < heal_target.get_health_max():
                    body_heal_msg = heal_target.apply_damage(
                        -heal_target.get_health_max()
                    )
                heal_target.heal_fully()
                if body_heal_msg:
                    msg += f"\n{body_heal_msg}"
                msg += (
                    f"\nA radiant column of light engulfs @{index}; "
                    f"wounds seal and broken flesh knits whole in moments."
                )
            else:
                # 17–19: computed body heal + fully restore ONE most-
                # injured part (triage). Keeps nat 20 distinct as the
                # "everything fixed" outcome.
                missing_health = heal_target.get_health_max() - heal_target.health
                quarter = math.ceil(missing_health / 4) if missing_health else 0

                if quarter > 1:
                    heal_amount = Dice.quick_roll(f"1d{quarter}") + quarter * (d20.value % 17)
                elif missing_health == 1:
                    heal_amount = 1
                elif missing_health > 0:
                    heal_amount = Dice.quick_roll(f"1d{missing_health}")
                else:
                    heal_amount = 0

                heal_amount = heal_amount or 0

                # Pick the worst-injured part BEFORE applying heals so
                # we can fold its missing-HP contribution into the
                # single "points of health" total. Prior implementation
                # reported only the body-HP delta, which read as "1
                # point of health" even when an arm missing 8 HP was
                # being restored to full in the same beat.
                injured_parts = [
                    part for part in (heal_target.body_parts or [])
                    if part.health < part.health_max
                ]
                worst = (
                    min(injured_parts, key=lambda p: p.health / p.health_max)
                    if injured_parts else None
                )
                part_heal_amount = (
                    worst.health_max - worst.health if worst else 0
                )
                total_heal = heal_amount + part_heal_amount

                body_heal_msg = heal_target.apply_damage(-heal_amount) if heal_amount else ""

                if body_heal_msg:
                    msg += f"\n{body_heal_msg}"

                msg += f"\nA warm light suffuses @{index}, "

                if total_heal > 0:
                    noun = "point" if total_heal == 1 else "points"
                    msg += f"imbuing @{index}o with {total_heal} {noun} of health!"
                else:
                    msg += f"and a pleasant tingle envelops @{index}o without noticeable effect."

                if worst is not None:
                    worst.health = worst.health_max
                    heal_target.is_dirty = True
                    msg += (
                        f"\n@{index}'s {worst.display_name} knits itself whole."
                    )

        Dispatcher.add(game.channel, parse(msg, *actors))

    @cooldown(1, 60, BucketType.user)
    @command(aliases=["report"], brief="Reports an error or issue to the logs and developer.")
    async def report_problem(self, ctx: Context, *, msg: str):
        """
        Reports an error or issue to the logs and developer. 1-minute cooldown.

        :param msg: A description of the problem with as much detail as possible.
        :return:
        """
        game, player = await RpgUtilities.get_game_and_player(ctx, notify=False)

        result = generate_report(
            ctx.author.id,
            ctx.author.display_name,
            msg,
            player.name if player else "None",
            ctx.guild.id if ctx.guild else "None",
            ctx.channel.id if ctx.channel else "None",
        )

        m = f"{ctx.author.display_name}, "
        if result:
            m += "your message has been logged and relayed. Thank you for helping improve me!"
        else:
            m += "there was an unexpected error while delivering your report. Please ping the developer!"

        Dispatcher.add(ctx, m)

    @Cog.listener()
    async def on_ready(self):
        _log.info("RpgUserCommands ready.")

    @Cog.listener()
    async def on_member_update(self, before, after):
        """Keep per-game player names in sync with the member's
        ``display_name``. Without this, a nickname / global-name
        change only takes effect on the next bot restart (when
        ``load_players`` repopulates from Mongo). ``PlayerManager``
        owns the actual sync; this listener just fans the event
        out across every game on the affected guild."""
        if before.display_name == after.display_name:
            return
        for game in self.bot.games.values():
            if game.guild is None or game.guild.id != after.guild.id:
                continue
            game.player_manager.maybe_update_member_name(after)


async def setup(bot):
    await bot.add_cog(RpgUserCommands(bot))
