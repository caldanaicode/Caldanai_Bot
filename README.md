# Caldanai Bot

A Discord bot featuring dice rolling, a text-based RPG system, and general server utilities. Built with Python and [discord.py](https://discordpy.readthedocs.io/).

## Features

### Dice Rolling
- `$roll NdN` — Roll dice in standard NdN notation (e.g., `$roll 3d6`)
- `$roll NdN hi/lo K` — Keep the K highest or lowest results (e.g., `$roll 4d6 hi 3`)
- `$roll NdN verbose` — Show a breakdown of all individual rolls

### Text RPG
- Monsters spawn periodically in a designated channel
- Players can fight monsters using combat commands
- **Body parts system** — every monster has targetable body parts (head, torso, arms, legs, wings, tail) with injury tracking and debuffs
- **Explicit targeting** — `$kill arm.left`, `$kill head torso` for dual-wield split targeting, `$target` for mid-combat changes
- **Injury feedback** — parts degrade through injury levels (minor → moderate → severe → destroyed), debuffing monster stats as they take damage
- **Critical parts** — destroying a head or torso kills the monster outright
- Loot drops after defeating monsters, with a timed pickup window
- Creatures include goblins, bandits, dragons, hydras, bears, vampires, and more
- **Hydra** — regenerating heads, multi-head attacks, head cap, turn-based regrowth
- **Dragon** — VARIANTS system with the 62-toe flavor variant (grounded dragons can't dodge)
- Equipment system with weapons (swords, maces, bows, wands, etc.) and armor
- Inventory management with stackable items, consumables, and equipment
- Day/night cycle and weather with ambient flavor text
- Per-server game instances with configurable spawn timers

### Server Management
- `$prefix <new>` — Change the bot's command prefix per server
- `$ask` — Get a Magic 8-Ball style prediction
- `$reminder <time> [message]` — Set a personal DM reminder
- `$shutdown` — Graceful shutdown with optional announcement (admin only)
- Hot-reloadable cogs (`$reload_cog`)

### Infrastructure
- MongoDB backend for persistent storage (players, games, servers, logs)
- Batched database writes via a double-buffer queue
- Plugin architecture for dynamically loading cogs, console commands, monster definitions, and body parts
- Body composition templates (`BodyPart.humanoid()`, `quadruped()`, `quadruped_winged()`) for one-liner monster setup
- Console command interface for server-side management
- 1000+ automated tests (unit + integration)

## Requirements

- Python 3.10+
- MongoDB instance
- A Discord bot token

## Setup

1. **Clone the repo**
   ```bash
   git clone https://github.com/caldanaicode/Caldanai_Bot.git
   cd Caldanai_Bot
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```
   Or with [Poetry](https://python-poetry.org/):
   ```bash
   poetry install
   ```

3. **Configure environment variables**

   Create a `.env` file in the project root:
   ```env
   DB_CONNECTION=mongodb://localhost:27017
   LOG_LEVEL=INFO
   STAGE=TEST          # or omit for production
   ```

4. **Set up the database**

   The bot expects an `auth` document in MongoDB with your Discord bot token and owner IDs:
   ```json
   {
     "TOKEN": "your-discord-bot-token",
     "OWNER_IDS": [123456789012345678]
   }
   ```
   Insert this into the `caldanaiDB.auth` collection (or `caldanaiTest.auth` if `STAGE=TEST`).

5. **Run the bot**
   ```bash
   python main.py
   ```

## Project Structure

```
Caldanai_Bot/
├── main.py                  # Entry point — starts bot, console, and input loops
├── startup.py               # Git sync and process launcher
├── CHANGELOG.md             # Version history
├── caldanai/
│   ├── __init__.py          # Event/Observer pattern, PluginManager
│   ├── dispatcher.py        # Batched message queue for Discord API
│   ├── double_buffer.py     # Thread-safe double-buffer queue
│   ├── logger.py            # Colored stdout + MongoDB log handler
│   ├── environment.py       # .env loader
│   ├── db/                  # MongoDB wrapper (batch writes, connection mgmt)
│   ├── consolecommands/     # Server-side CLI plugins (echo, help, shutdown, etc.)
│   └── lib/
│       ├── bot/             # Bot class, state management, Discord events
│       ├── cogs/            # Discord command groups (general, RPG, admin)
│       └── rpg/             # RPG game engine
│           ├── areas/       # Game areas / zones
│           ├── combat/      # Attack sources, results, sequences, rendering
│           ├── creatures/   # Creature base class, targeting helpers
│           │   ├── bodypart.py      # BodyPart class, factory, templates
│           │   ├── body_parts/      # Body part plugins (head, arm, leg, etc.)
│           │   ├── monsters/        # Monster plugins (goblin, dragon, hydra, etc.)
│           │   └── player.py        # Player class
│           ├── PlayerManager/       # Player lifecycle management
│           ├── inventory/   # Items, equipment, weapons, armor, consumables
│           ├── abilities/   # Ability system
│           ├── ambience/    # Weather and flavor text
│           ├── helpers/     # Dice, enums (Stat, Reach, DamageTypes), parser, utilities
│           └── time/        # In-game clock and scheduled routines
├── tests/                   # Unit tests (~1000+)
│   ├── integration/         # Integration tests (combat damage pipeline)
│   └── conftest.py          # Shared fixtures
└── site/
    └── static/images/       # RPG asset images (used in Discord embeds)
```

## License

[MIT](LICENSE)
