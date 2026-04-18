from abc import ABC
from typing import TYPE_CHECKING, Dict, Optional, Union

from caldanai.lib.rpg.helpers.dice import Dice
from caldanai.lib.rpg.helpers.enums import (
    DamageTypes,
    InjuryLevels,
    Reach,
    Stat,
)

if TYPE_CHECKING:
    from caldanai.lib.rpg.creatures import Creature


class BodyPart(ABC):
    def __init__(
        self,
        name: str,
        health_max: Union[int, str],
        is_critical: bool = False,
        traits: Optional[Dict[DamageTypes, float]] = None,
        exposure: Optional[Dict[Reach, float]] = None,
        debuffs: Optional[Dict[InjuryLevels, Dict[Stat, int]]] = None,
    ):
        self.name = name
        # Accept ndn dice-notation strings (e.g. "1d10") and resolve them
        # at construction time, matching the Creature base class. Plugins
        # declare ``health_max = "1d8"`` at class level; the factory/
        # constructor is the right place to convert to an int once.
        self.health_max = (
            Dice.quick_roll(health_max) if isinstance(health_max, str) else health_max
        )
        self.health = self.health_max
        self.is_critical = is_critical
        self.traits = traits if traits is not None else {}
        self.exposure: Dict[Reach, float] = (
            exposure
            if exposure is not None
            else {
                Reach.MELEE: 1.0,
                Reach.REACH: 1.0,
                Reach.THROWN: 1.0,
                Reach.RANGED: 1.0,
            }
        )
        self.debuffs: Dict[InjuryLevels, Dict[Stat, int]] = (
            debuffs if debuffs is not None else {}
        )

    def get_injury_level(self):
        health_percent = self.health / self.health_max
        if 0.60 <= health_percent < 1.0:
            return InjuryLevels.MINOR

        if 0.30 <= health_percent < 0.60:
            return InjuryLevels.MODERATE

        if 0 < health_percent < 0.30:
            return InjuryLevels.SEVERE

        if health_percent <= 0:
            return InjuryLevels.USELESS

        return InjuryLevels.NONE

    def get_injury_string(self):
        level = self.get_injury_level()
        label = self._display_with_article()

        if level == InjuryLevels.MINOR:
            return f"{label} seems lightly battered."

        if level == InjuryLevels.MODERATE:
            return f"{label} shows signs of moderate damage."

        if level == InjuryLevels.SEVERE:
            return f"{label} appears severely wounded."

        if level == InjuryLevels.USELESS:
            return f"{label} is utterly destroyed."

        return f"{label} is completely unscathed."

    def get_recovery_string(self):
        """Returns a narration template for a part that has just
        *improved* to this injury level (i.e. healed up from something
        worse). Template uses ``@1`` / ``@1a`` tokens resolved via the
        parser, so the caller should pass the owning creature through
        :func:`parse` to render it.

        Level-appropriate flavor ramps from "just starting to recover"
        (SEVERE) to "completely fine" (NONE). Returns empty string if
        the part is still at USELESS — we don't narrate a non-heal.
        """
        level = self.get_injury_level()
        display = self.display_name  # "left arm", "right foreleg", "head"

        if level == InjuryLevels.MINOR:
            return f"@1np {display} is nearly back to full strength."

        if level == InjuryLevels.MODERATE:
            return f"@1np {display} is starting to mend."

        if level == InjuryLevels.SEVERE:
            # Name subject ("Caels winces") takes singular verb regardless
            # of the player's pronouns — no verb-agreement token needed.
            return f"@1 winces as feeling returns to @1a {display}."

        if level == InjuryLevels.NONE:
            return f"@1np {display} feels as good as new."

        # USELESS is not a "recovery" destination — if we healed
        # INTO it, something's gone very wrong.
        return ""

    def _display_with_article(self) -> str:
        """Display name with 'the' for directional/simple names, bare for numbered.

        ``"arm.left"`` → ``"the left arm"``, ``"head.2"`` → ``"head 2"``.
        Returned lowercase — the caller capitalizes if needed.
        """
        name = self.display_name
        if "." in self.name:
            _, qualifier = self.name.rsplit(".", 1)
            if qualifier.isnumeric():
                return name
        return f"the {name}"

    @property
    def display_name(self) -> str:
        """Human-readable name from the codified dot-notation.

        ``"arm.left"`` → ``"left arm"``, ``"head.2"`` → ``"head 2"``,
        ``"head"`` → ``"head"``, ``"foreleg.right"`` → ``"right foreleg"``.
        """
        if "." not in self.name:
            return self.name
        base, qualifier = self.name.rsplit(".", 1)
        if qualifier.isnumeric():
            return f"{base} {qualifier}"
        return f"{qualifier} {base}"

    def get_trait_multiplier(self, dmg_type: Optional[DamageTypes]) -> float:
        """Returns the part's damage multiplier for the given damage
        type. Defaults to ``1.0`` when ``dmg_type`` is falsy or no
        matching trait is declared. Combined with the creature's own
        ``get_trait_multiplier`` (multiplicatively) by
        :meth:`Creature.apply_damage`.
        """
        if not dmg_type:
            return 1.0
        if dmg_type in self.traits:
            return self.traits[dmg_type]
        return 1.0

    def apply_damage(self, amount: int, dmg_type: Optional[DamageTypes] = None) -> None:
        """Subtracts ``amount`` from this part's current health and
        clamps to ``[0, health_max]``. Negative amounts heal; the
        upper clamp prevents healing past full.

        The part's own trait multiplier is **not** applied here — the
        caller (:meth:`Creature.apply_damage`) applies the combined
        creature-and-part trait multiplier before calling this method.
        Applying it again here would double-count the part's resistance.
        ``dmg_type`` is accepted for signature compatibility and for
        future subclasses that want to react to specific damage types.
        """
        self.health = max(0, min(self.health_max, self.health - amount))

    def is_destroyed(self) -> bool:
        """Returns True iff this part's health has been depleted."""
        return self.health <= 0

    def get_stat_modifier(self, stat: Stat, owner: "Creature") -> int:
        """Canonical stat-modifier interface.

        Default implementation reads the static ``debuffs`` table keyed by
        the part's current injury level. Subclasses override for
        state-dependent behavior (e.g. dragon toes that only contribute
        while grounded, or arms that only contribute defense on rounds
        they block).
        """
        return self.debuffs.get(self.get_injury_level(), {}).get(stat, 0)

    def on_injury_change(
        self,
        creature: "Creature",
        old_level: InjuryLevels,
        new_level: InjuryLevels,
    ) -> str:
        """Hook for discrete state changes driven by injury level changes
        (e.g. a wing reaching USELESS removes the ``flying`` flag).
        Override in subclasses; empty string by default."""
        return ""

    def on_destroyed(self, creature: "Creature") -> str:
        """Hook for special destruction behavior (e.g. hydra head
        regrowth). Override in subclasses; empty string by default."""
        return ""

    @classmethod
    def make(cls, plugin_name: str, **overrides) -> "BodyPart":
        """Factory that constructs a :class:`BodyPart` from a registered
        ``BodyPartPlugin`` by name, applying any per-instance kwarg
        overrides.

        The plugin registry is populated lazily: if it is empty when
        ``make`` is called, :meth:`BodyPartPlugin.load_plugins` is invoked
        once and the lookup is retried. Callers therefore never need to
        remember to trigger plugin discovery explicitly.

        :param plugin_name: The declared registry key of a loaded
            body-part plugin (e.g. ``"head"``, ``"leg"``,
            ``"head"``, ``"torso"``). Named ``plugin_name`` rather than ``name``
            so callers can still pass ``name="..."`` as an instance-level
            override without a parameter collision.
        :param overrides: Optional per-instance kwargs forwarded to the
            plugin's ``__init__`` (e.g. ``name="head"``,
            ``is_critical=True``, ``exposure={Reach.MELEE: 0.05}``).
            Names now follow the codified dot-notation convention
            (e.g. ``name="head"``, ``name="arm.left"``).
        :raises ValueError: If no plugin is registered under
            ``plugin_name``.
        """
        # Imported lazily to avoid the ``bodypart`` <-> ``body_parts``
        # circular import at module load.
        from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin

        plugin_class = BodyPartPlugin.get_plugin_class(plugin_name)
        if plugin_class is None and not BodyPartPlugin._PLUGIN_REGISTRY:
            BodyPartPlugin.load_plugins()
            plugin_class = BodyPartPlugin.get_plugin_class(plugin_name)

        if plugin_class is None:
            known = sorted(BodyPartPlugin._PLUGIN_REGISTRY.keys())
            raise ValueError(
                f"No body part plugin registered as '{plugin_name}'. "
                f"Known plugins: {known}"
            )

        return plugin_class(**overrides)

    @classmethod
    def humanoid(cls):
        """Standard 6-part humanoid: head, torso, 2 arms, 2 legs."""
        return [
            cls.make("head", name="head"),
            cls.make("torso", name="torso"),
            cls.make("arm", name="arm.left"),
            cls.make("arm", name="arm.right"),
            cls.make("leg", name="leg.left"),
            cls.make("leg", name="leg.right"),
        ]

    @classmethod
    def quadruped(cls):
        """Standard 7-part quadruped: head, torso, 4 legs (fore/hind), tail."""
        return [
            cls.make("head", name="head"),
            cls.make("torso", name="torso"),
            cls.make("leg", name="foreleg.left"),
            cls.make("leg", name="foreleg.right"),
            cls.make("leg", name="hindleg.left"),
            cls.make("leg", name="hindleg.right"),
            cls.make("tail", name="tail"),
        ]

    @classmethod
    def quadruped_winged(cls):
        """9-part winged quadruped: quadruped + 2 wings."""
        parts = cls.quadruped()
        parts.extend([
            cls.make("wing", name="wing.left"),
            cls.make("wing", name="wing.right"),
        ])
        return parts
