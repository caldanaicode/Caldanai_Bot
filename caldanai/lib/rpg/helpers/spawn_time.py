"""Time-of-day spawn gating, composable across plugin types.

Why this exists
---------------

Monsters already gate their spawn window via a per-instance
``time_partition`` flag mask (``MonsterPlugin.__init__`` sets it
to ``TimePartitions.CATHEMERAL`` by default; subclasses override
for nocturnal / diurnal / dawn-only spawns). Passerby NPCs need
the same gate — Wren shouldn't run errands at 02:00, the
wagoneer doesn't roll a cart at midnight — and any future
spawnable plugin type (deity manifestations, ghost NPCs, etc.)
will too. This mixin extracts the concern so plugin classes
opt in by inheritance and pick up both the default and the
helper accessor.

Design
------

- **Class-level default.** Subclasses declare
  ``time_partition`` as a class attribute. Default is
  :data:`TimePartitions.CATHEMERAL` (any time of day) so
  composing the mixin doesn't change behavior unless explicitly
  narrowed.
- **Instance-level override.** :class:`MonsterPlugin` keeps its
  existing pattern of setting ``self.time_partition`` in
  ``__init__``; that overrides the class default at instance
  level. Both representations work with the helpers below.
- **Two accessors.** :meth:`is_active_at` works on instances or
  classes (Python attribute lookup); :classmethod:`filter_active`
  trims a candidate-class iterable down to those active at a
  given time without instantiating each one.

The ``filter_active`` class-level path is the win for spawn
pipelines: instead of instantiating every candidate to check
their time window (which builds body trees, runs spawn
loadouts, etc.), the filter operates on classes directly via
their class-level ``time_partition`` and only instantiates the
chosen one. For passersby this matches the
``PasserbyPlugin.find_plugin_classes`` pattern; for monsters
it's an optimization that future cleanup can pick up.
"""

from typing import Iterable, List, Type, TypeVar

from caldanai.lib.rpg.helpers.enums import TimePartitions, TimesOfDay


T = TypeVar("T", bound="SpawnTimeMixin")


class SpawnTimeMixin:
    """Time-of-day spawn gating. Composable into any plugin class
    that spawns at game-clock-driven intervals.

    Subclasses declare:

    .. code-block:: python

        class Wagoneer(PasserbyPlugin):  # PasserbyPlugin extends SpawnTimeMixin
            time_partition = TimePartitions.DIURNAL  # dawn through evening

    The default is :data:`TimePartitions.CATHEMERAL` (any time of
    day) so simply mixing in doesn't narrow spawn windows
    unintentionally.
    """

    time_partition: TimePartitions = TimePartitions.CATHEMERAL

    def is_active_at(self, time_of_day: TimesOfDay) -> bool:
        """True if this entity's ``time_partition`` overlaps the
        provided current time. Bitwise overlap matches the existing
        ``MonsterPlugin.get_random_monster`` filter so behavior
        stays consistent across plugin families."""
        return bool(time_of_day & self.time_partition)

    @classmethod
    def filter_active(
        cls: Type[T],
        candidates: Iterable[Type[T]],
        time_of_day: TimesOfDay,
    ) -> List[Type[T]]:
        """Trim a candidate iterable of plugin classes to those
        whose class-level ``time_partition`` is active at
        ``time_of_day``. Operates on classes, not instances —
        cheap, no body-tree materialization or spawn-loadout
        rolls. Use this in spawn pipelines to filter BEFORE
        instantiating the chosen plugin.

        Note for plugin classes that set ``time_partition`` at
        instance level (the historical :class:`MonsterPlugin`
        pattern): the class-level default still applies here, so
        ``MonsterPlugin.filter_active`` returns every monster
        class whose default is active. That's a false-positive
        risk if a subclass narrows the partition only at
        instance level — but for V1 ``MonsterPlugin``
        consumption goes through ``get_random_monster`` which
        instantiates and uses ``is_active_at`` on instances, so
        this method's class-level filter is a passerby-side
        feature for now.
        """
        return [
            c for c in candidates
            if bool(time_of_day & getattr(
                c, "time_partition", TimePartitions.CATHEMERAL,
            ))
        ]
