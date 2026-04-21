"""Every ``@group`` in the cog layer must set ``case_insensitive=True``.

Top-level ``Bot`` is case-insensitive (``caldanai/lib/bot/__init__.py``
— ``case_insensitive=True``), but ``discord.ext.commands`` groups
*don't* inherit that flag. A group registered without it dispatches
subcommands case-sensitively: ``$ambience Celestial on`` fails to
resolve even though ``$ambience celestial on`` works.

This test walks every cog's ``__cog_commands__`` and asserts that
every :class:`discord.ext.commands.Group` (and nested subgroup) has
``case_insensitive=True``. New groups that forget the flag regress
immediately.
"""

from discord.ext.commands import Group

from caldanai.lib.cogs.bot_admin_commands import BotAdminCommands
from caldanai.lib.cogs.rpg_admin_commands import RpgAdminCommands
from caldanai.lib.cogs.rpg_info_commands import RpgInfoCommands
from caldanai.lib.cogs.rpg_social_commands import RpgSocialCommands
from caldanai.lib.cogs.rpg_user_commands import RpgUserCommands


COGS = [
    BotAdminCommands,
    RpgAdminCommands,
    RpgInfoCommands,
    RpgSocialCommands,
    RpgUserCommands,
]


def _iter_groups(cog_cls):
    """Yield every ``Group`` reachable from a cog's command registry,
    including nested subgroups."""
    stack = list(cog_cls.__cog_commands__)
    while stack:
        cmd = stack.pop()
        if isinstance(cmd, Group):
            yield cmd
            stack.extend(cmd.commands)


def test_every_cog_group_is_case_insensitive():
    """Regression guard: every group (and subgroup) across every cog
    must be case-insensitive. Adding a new ``@group(...)`` without
    ``case_insensitive=True`` fails this test."""
    offenders = []
    for cog_cls in COGS:
        for group in _iter_groups(cog_cls):
            if not group.case_insensitive:
                offenders.append(f"{cog_cls.__name__}.{group.qualified_name}")
    assert not offenders, (
        "Found group(s) without case_insensitive=True: "
        f"{offenders}. Add ``case_insensitive=True`` to the "
        "``@group(...)`` decorator so subcommand dispatch matches "
        "the top-level Bot's case-insensitive behavior."
    )
