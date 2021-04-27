from discord.errors import HTTPException
from discord.ext.commands import Bot
from discord.ext import tasks
from discord import Guild, TextChannel, Embed, File
from typing import Dict, List

from .creatures.player import Player
from .creatures.monster import Monster
from random import choice, randint
from asyncio import sleep
from ...db.db import MongoDB
from pymongo.errors import DuplicateKeyError
from datetime import datetime


class Game:
    def __init__(self,
                 bot: Bot = None,
                 game_id: str = None,
                 guild: Guild = None,
                 channel: TextChannel = None,
                 use_spawn_timer: bool = True,
                 spawn_max: int = 60,
                 spawn_min: int = 10,
                 spawn_duration: int = 10,
                 loot_duration: int = 5,
                 prefix: str = None
                 ):
        self.bot = bot
        self.id = game_id
        self.guild = guild
        self.channel = channel
        self.players: Dict[int, Player] = {}
        self.monster: Monster = None
        self.combatants: List[int] = []
        self.loot: Dict[int, list] = {}
        self.use_spawn_timer = use_spawn_timer
        self.spawn_duration = spawn_duration
        self.loot_duration = loot_duration
        self.trigger = randint(0, spawn_max)
        self.minutes_max = spawn_max
        self.minutes_min = spawn_min
        self.prefix = prefix

        if use_spawn_timer:
            self.spawn_check.start()

    def cancel_combat(self):
        self.monster = None
        self.combatants.clear()
        self.loot.clear()

    # Sends a message and/or embed to the game's channel, returning a boolean indicating success or failure.
    async def send(self, message: str = None, embed: Embed = None, file: File = None) -> bool:
        """Sends a message and/or embed to the game's channel, returning a boolean indicating success or failure."""
        try:
            await self.channel.send(content=message, embed=embed, file=file)
        except HTTPException as e:
            msg = f'{datetime.now().strftime("%m-%d-%Y %H:%M:%S")}: HTTPException {e.code}'
            if e.code == 429:
                msg += 'Message blocked due to rate limiting.'
                if 'Retry-After' in e.response.headers.keys():
                    msg += f" Retry After {e.response.headers['Retry-After']} seconds."
            elif e.code == 400:
                msg += 'Message returned a bad format error.'

            print(msg)
            return False
        return True

    # Cleans up any loot that wasn't picked up
    async def loot_expires(self):
        await sleep(self.loot_duration * 60)
        if len(self.loot) > 0:
            await self.send(
                "A swarm of tiny, shadow-clad creatures floods in and makes off with the items on the ground.")

        self.loot.clear()

    # Builds a combat message for a player, and returns the message and the damage as a tuple
    def get_combat_message(self, player: Player) -> (str, int):
        l_atk, l_dmg, r_atk, r_dmg = player.get_attack_rolls()
        l_crit = l_atk == 20
        r_crit = r_atk == 20
        l_fumble = l_atk == 1
        r_fumble = r_atk == 1
        l_miss = not l_crit and (l_atk < self.monster.dodge or l_fumble)
        r_miss = not r_crit and (r_atk < self.monster.dodge or r_fumble)
        two_handed = r_atk == 0
        msg = f"{player.member.mention}'s attack:"

        if l_miss:
            l_dmg = 0
        if r_miss:
            r_dmg = 0

        if l_crit:
            l_dmg *= 2
        if r_crit:
            r_dmg *= 2

        t_dmg = l_dmg + r_dmg - self.monster.defense

        if t_dmg <= 0 and not (l_miss and r_miss):
            t_dmg = 1
        elif t_dmg < 0 and l_miss and r_miss:
            t_dmg = 0

        if two_handed:
            msg += f"```\nAtk: {l_atk} vs Dodge: {self.monster.dodge} --> " \
                   f"{'FUMBLE' if l_fumble else 'MISS' if l_miss else 'CRIT' if l_crit else 'HIT'}"
            if not l_miss:
                msg += f"\nDamage: {l_dmg} vs Defense: {self.monster.defense} --> {t_dmg}"
        else:
            msg += f"```\nAtk: {l_atk}|{r_atk} vs Dodge: {self.monster.dodge} --> " \
                   f"{'FUMBLE' if l_fumble else 'MISS' if l_miss else 'CRIT' if l_crit else 'HIT'}|" \
                   f"{'FUMBLE' if r_fumble else 'MISS' if r_miss else 'CRIT' if r_crit else 'HIT'}"
            if not l_miss or not r_miss:
                msg += f"\nDamage: {l_dmg} + {r_dmg} vs Defense: {self.monster.defense} --> {t_dmg}"

        msg += "```\n"
        return msg, t_dmg

    async def on_monster_death(self):
        if not await self.send(f"{self.monster.death}"):
            self.cancel_combat()

        for pid in self.combatants:
            loot = self.monster.getLoot()
            self.loot[pid] = loot

        self.monster = None
        self.combatants.clear()
        if len(self.loot) == 0:
            await self.send("There does not appear to be anything to loot, this time.")
        else:
            await self.send(f"There might be something to `{self.prefix}loot`...")
            await self.loot_expires()

    # Performs combat sequence
    @tasks.loop(count=1)
    async def do_combat(self):
        self.spawn_check.cancel()
        await sleep(self.spawn_duration * 60)

        msg = ""
        damage = 0
        for pid in self.combatants:
            m, d = self.get_combat_message(self.players[pid])
            if len(msg) + len(m) > 2000:
                if await self.send(msg):
                    msg = ""
                else:
                    self.cancel_combat()
                    return
            msg += m
            damage += d

        msg += f"Total damage done: {damage:,} vs Health: {self.monster.health:,}\n"

        self.monster.health -= damage
        if self.monster.health <= 0:
            if await self.send(msg):
                await self.on_monster_death()
            else:
                self.cancel_combat()
                self.spawn_check.start()
                return

        else:
            if not await self.send(f"{msg}\n{self.monster.escape}"):
                self.cancel_combat()
                self.spawn_check.start()
                return

            self.cancel_combat()

        await sleep(self.minutes_min * 60)
        self.spawn_check.start()

    # Spawns a monster
    async def spawn(self):
        """Spawns a monster, and starts the combat sequence."""
        self.trigger = 0
        self.monster = Monster(choice(list(MongoDB.templates_monsters.find())))
        embed, file = self.monster.get_embed()
        if await self.send(self.monster.arrival, embed=embed, file=file):
            self.do_combat.start()
        else:
            self.cancel_combat()

    # Attempts to spawn a monster
    @tasks.loop(minutes=1)
    async def spawn_check(self):
        if not self.use_spawn_timer:
            print("Spawn loop ending...")
            self.spawn_check.cancel()
            return

        if self.bot.is_ws_ratelimited():
            print("Spawning blocked due to rate limit.")
            return

        self.trigger = min(self.trigger, self.minutes_max)
        r = randint(self.trigger, self.minutes_max)
        if r == self.minutes_max:
            await self.spawn()
            return

        self.trigger += 1
        return

    async def kill_monster(self):
        self.do_combat.cancel()
        await self.on_monster_death()

    # Gets a dictionary representation of the game.
    def to_dict(self):
        d = {
            'guildId': self.guild.id,
            'channelId': self.channel.id,
            'use_spawn_timer': self.use_spawn_timer,
            'spawn_duration': self.spawn_duration,
            'loot_duration': self.loot_duration,
            'minutes_max': self.minutes_max,
            'minutes_min': self.minutes_min,
            'prefix': self.prefix
        }

        if self.id is not None:
            d['_id'] = self.id

        return d

    # Adds or updates a game object in the database.
    def save(self) -> None:
        """Adds or updates a game object in the database."""
        try:
            self.id = MongoDB.games.insert_one(self.to_dict()).inserted_id
        except DuplicateKeyError:
            MongoDB.games.update_one({'_id': self.id}, {'$set': self.to_dict()})

    @classmethod
    async def load(cls, guild_id: int, bot: Bot):
        if guild_id is None:
            return None

        g = MongoDB.games.find_one({'guildId': guild_id})
        if g is None or bot is None:
            return None

        return await Game.from_dict(g, bot)

    @classmethod
    async def from_dict(cls, d: dict, bot: Bot):
        """Returns a dictionary representation of the game."""
        if d is None or bot is None:
            return None

        game = cls(
            bot=bot,
            game_id=d['_id'],
            use_spawn_timer=d['use_spawn_timer'],
            spawn_max=int(d['minutes_max']),
            spawn_min=int(d['minutes_min']),
            spawn_duration=int(d['spawn_duration']),
            loot_duration=int(d['loot_duration']),
            prefix=d['prefix']
        )

        game.guild = bot.get_guild(d['guildId'])
        game.channel = bot.get_channel(d['channelId'])

        for p in MongoDB.players.find({'guildId': game.guild.id}):
            uid = p['userId']
            player = Player.from_dict(p)
            player.member = game.guild.get_member(uid) or await game.guild.fetch_member(uid)
            player.name = player.member.display_name
            game.players[uid] = player

        return game
