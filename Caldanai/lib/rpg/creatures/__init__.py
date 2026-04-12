import random
from random import choice
from typing import List, Union, Optional, Dict, Set

from discord import Embed, File

from Caldanai.lib.rpg import parse
from Caldanai.lib.rpg.creatures.bodypart import BodyPart
from Caldanai.lib.rpg.combat.attack_result import AttackResult, AttackSequence
from Caldanai.lib.rpg.combat.attack_source import (
    AttackSource,
    NaturalAttackSource,
)
from Caldanai.lib.rpg.helpers.dice import Dice
from Caldanai.lib.rpg.helpers.enums import Pronouns, DamageTypes, Reach, Stat
from Caldanai.lib.rpg.helpers.rollData import (
    AttackRoll, DamageRoll, CombinedRoll)



class Creature:
    """
    An instance of a creature object.
    """

    def __init__(
        self,
        name: Optional[str],
        atk: Optional[str],
        defense: Optional[Union[str, int]],
        dodge: Optional[Union[str, int]],
        health_max: Optional[Union[str, int]],
        health: Optional[int] = None,
        gender: Optional[str] = None,
        pronouns: Optional[str] = None,
        traits: Optional[Dict[DamageTypes, float]] = (),
    ):
        """
        Creates a new instance of a creature object.

        :param name: The creature's name or noun. Defaults to ''.
        :param atk: The creature's attack strength as an ndn string. Defaults to '1d4'.
        :param defense: The creature's defense strength as an integer or ndn string. Defaults to 1.
        :param dodge: The creature's dodge ability as an integer or ndn string. Defaults to 1.
        :param health_max: The creature's max health as an integer or ndn string. Defaults to 1.
        :param health: The creature's current health as an integer. Defaults to health_max.
        :param gender: The creature's gender as a string. Will randomly choose between 'male' and 'female' for NPCs    if
            not provided. For players, the gender can be defined by the player.
        :param pronouns: The creature's pronouns as a comma-separated string in the format of 'subject, object,
            possessive'. For example, a female's pronouns will default to 'she, her, hers' if no pronouns are provided.
        :param traits: Damage types and effectiveness against this creature.
        """

        self.name = name or ""
        self.attack = atk or "1d4"
        self.defense = Dice.quick_roll(defense) if isinstance(defense, str) else defense if defense else 1
        self.dodge = Dice.quick_roll(dodge) if isinstance(dodge, str) else dodge if dodge else 1
        self.health_max = (
            Dice.quick_roll(health_max) if isinstance(health_max, str) else health_max if health_max else 1
        )
        self.health = health if health is not None else self.health_max
        self.flavor = ""
        self.image = None
        self.clarks = 0
        self.gender: Optional[str] = gender or choice(["male", "female"])
        self.is_dirty: bool = False
        self.pronouns: Dict[Pronouns, str] = {}
        self.traits: Dict[DamageTypes, float] = traits or {}
        # Per-instance composition: body parts and state flags must be
        # fresh mutable containers on every instance so that injuring one
        # goblin's leg doesn't injure every goblin's leg. Subclasses
        # populate ``body_parts`` in their own ``__init__`` after calling
        # ``super().__init__(...)``; ``flags`` is used for discrete state
        # like ``"flying"`` (see the dragon-toes design).
        self.body_parts: List[BodyPart] = []
        self.flags: Set[str] = set()

        if pronouns:
            s = pronouns.split(",")
            self.pronouns: Dict[Pronouns, str] = {
                Pronouns.SUBJECTIVE: s[0].strip(),
                Pronouns.OBJECTIVE: s[1].strip(),
                Pronouns.POSSESSIVE: s[2].strip(),
                Pronouns.ADJECTIVE: s[3].strip(),
                Pronouns.REFLEXIVE: s[1].strip() + "self",
            }
        else:
            self.update_pronouns()

        # if stats:
        #     for name, value in stats.items():
        #         n = name.upper()
        #         if n in Stats.__members__.keys():
        #             if Stats[n] == Stats.ATTACK:
        #                 self.stats[Stats.ATTACK] = value or Stats.ATTACK['default']
        #             else:
        #                 self.stats[Stats[n]] = value if isinstance(value, int) else Dice.quick_roll(value)
        #                 if Stats[n]['min']:
        #                     self.stats[Stats[n]] = max(self.stats[Stats[n]], Stats[n]['min'])
        #
        # for stat in Stats:
        #     if stat not in self.stats.keys():
        #
        #         self.stats[stat] = 1

    def get_trait_multiplier(self, dmg_type: DamageTypes) -> float:
        if not dmg_type:
            return 1.0

        if dmg_type in self.traits:
            return self.traits[dmg_type]

        highest = 0.0
        trait_matched = False
        for trait in self.traits:
            if trait & DamageTypes.COMBINED:
                if not dmg_type & DamageTypes.COMBINED:
                    continue
                if dmg_type & trait == trait:
                    highest = max(self.traits[trait], highest)
                    trait_matched = True

            elif dmg_type & trait:
                highest = max(self.traits[trait], highest)
                trait_matched = True

        if not trait_matched:
            highest = 1.0

        return highest

    def apply_damage(
        self,
        amount: int,
        dmg_type: Optional[DamageTypes] = None,
        target_part: Optional[BodyPart] = None,
    ) -> None:
        """Applies damage (or healing if ``amount`` is negative) to this
        creature.

        When ``target_part`` is ``None`` or this creature has no
        ``body_parts``, the legacy whole-body path is used: ``health``
        is decremented by ``amount`` and clamped to ``[0, health_max]``.
        This preserves the original healing semantics (negative
        ``amount`` heals, capped at max health).

        When ``target_part`` is provided and this creature has parts,
        damage routes per Phase 1 option C (hybrid): the part takes the
        full damage after the combined ``creature * part`` trait
        multiplier, and the body takes the same final damage (Model D
        unified HP). If the targeted part is critical and becomes
        destroyed, the creature is killed outright.

        Fires ``target_part.on_injury_change`` once per injury-level
        transition and ``target_part.on_destroyed`` exactly once on the
        hit that reduces the part to 0 HP (never re-firing on
        subsequent hits to an already-destroyed part).

        :param amount: Damage amount; negative heals.
        :param dmg_type: Optional damage type used to look up trait
            multipliers on both the creature and the targeted part.
        :param target_part: Optional body part to absorb the damage.
        """

        if target_part is None or not self.body_parts:
            # Legacy path / no parts: preserves exact pre-refactor
            # behavior including healing.
            self.health -= amount
            self.health = max(0, self.health)
            self.health = min(self.health, self.get_health_max())
            return

        # Part-targeted routing (Model D — unified body HP).
        multiplier = (
            target_part.get_trait_multiplier(dmg_type)
        )
        final_dmg = int(amount * multiplier)

        # Snapshot the part's state before damage so we can detect
        # injury-level transitions and first-time destruction.
        was_destroyed = target_part.is_destroyed()
        old_level = target_part.get_injury_level()

        # Part tracks damage for injury-level purposes.
        # Body HP is NOT reduced here — the caller (do_combat) applies
        # the post-defense total to body HP after all sources resolve.
        target_part.apply_damage(final_dmg, dmg_type)

        # Critical part destroyed → death (even before body HP is touched).
        if target_part.is_critical and target_part.is_destroyed():
            self.health = 0

        # Hooks: injury_change fires on any level transition;
        # on_destroyed fires exactly once (only when the part was NOT
        # already destroyed and now is). For this item, hook return
        # strings are intentionally discarded — items 1.10 and combat
        # rendering will wire the output.
        new_level = target_part.get_injury_level()
        if new_level != old_level:
            target_part.on_injury_change(self, old_level, new_level)
        if target_part.is_destroyed() and not was_destroyed:
            target_part.on_destroyed(self)

    def get_attack_sources(self) -> List[AttackSource]:
        """Returns the list of attack sources this creature uses when attacking.

        The base implementation returns a single NaturalAttackSource built
        from the creature's `attack` dice string. Subclasses override to
        provide weapon-based, body-part-based, or multi-attack patterns.
        """
        return [
            NaturalAttackSource(
                atk=self.attack,
                dmg_type=None,
                label=self.name.title() if self.name else "",
                skill="natural",
            )
        ]

    def do_attack(
        self,
        target: "Creature",
        explicit_part_names: Optional[List[str]] = None,
    ) -> AttackSequence:
        """Performs an attack against the target by iterating this creature's
        attack sources and delegating each to the target's `resolve_attack`.

        ``explicit_part_names`` is an optional list of part-name strings
        (from ``$kill arm.left leg.right`` or ``$target``).  When provided:

        - One name → ALL sources target that part.
        - N names → source[i] targets name[i]; extra sources use the last
          name; extra names are ignored.
        - Each name is resolved via exact match then prefix match.

        When ``None`` or empty, each source independently picks a random
        target part weighted by reach.
        """

        def _resolve_name(name: str) -> Optional["BodyPart"]:
            """Resolve a part-name string to a BodyPart instance."""
            part = target.get_part(name)
            if part and not part.is_destroyed():
                return part
            prefix_matches = [
                p for p in target.get_targetable_parts()
                if p.name.startswith(name + ".") or p.name == name
            ]
            if prefix_matches:
                return random.choice(prefix_matches)
            return None

        # Pre-resolve explicit targets (one per source slot).
        explicit_parts: List[Optional["BodyPart"]] = []
        if explicit_part_names and target.body_parts:
            for name in explicit_part_names:
                explicit_parts.append(_resolve_name(name))

        results: List[AttackResult] = []
        sources = self.get_attack_sources()
        for i, source in enumerate(sources):
            # Explicit target for this source (cycle: last target fills remaining).
            if explicit_parts:
                idx = min(i, len(explicit_parts) - 1)
                resolved = explicit_parts[idx]
                if resolved and not resolved.is_destroyed():
                    target_part = resolved
                else:
                    target_part = pick_random_part(target.get_targetable_parts(), source.reach)
            elif target.body_parts:
                target_part = pick_random_part(target.get_targetable_parts(), source.reach)
            else:
                target_part = None

            atk_roll, dmg_roll = source.make_attack_rolls(self)
            result = target.resolve_attack(self, source, atk_roll, dmg_roll)
            result.target_part = target_part  # store for damage application + display
            results.append(result)
            self._on_attack_resolved(source, result)
        return AttackSequence(attacker=self, target=target, results=results)

    def _on_attack_resolved(self, source: AttackSource, result: AttackResult) -> None:
        """Hook called after each attack source resolves.

        Subclasses override to react to individual results (e.g., grant
        skill XP on a hit). No-op by default.
        """
        pass

    def resolve_attack(
        self,
        attacker: "Creature",
        source: AttackSource,
        atk_roll: AttackRoll,
        dmg_roll: DamageRoll,
    ) -> AttackResult:
        """Pure calculation of a single attack against this creature.

        Computes hit/miss and applies trait multipliers.  Defense is NOT
        subtracted per-source — it is subtracted once from the per-player
        total in ``do_combat`` (variant B, restored pre-refactor balance).
        """
        dodge = self.get_dodge()
        defense = self.get_defense()
        combined = CombinedRoll(atk_roll, dmg_roll, dodge)
        multiplier = self.get_trait_multiplier(source.damage_type)
        sub_dmg = int(multiplier * combined.result)
        damage = 0 if combined.isMiss else max(0, sub_dmg)
        return AttackResult(
            source=source,
            combined=combined,
            damage=damage,
            multiplier=multiplier,
            defense=defense,
            dodge=dodge,
            dmg_type=source.damage_type,
        )

    def get_embed(self) -> tuple:
        """
        Generates a discord embed and image file for displaying information about this creature.

        :return: A tuple containing (Embed, File) for the creature's details
        """

        embed = Embed(title=f"{self.name.title()}", description=parse(self.flavor, self), color=0xFFCC00)
        file = None
        if self.image is not None:
            file = File(f"./site/static/images/{self.image}", filename=self.image)
            embed.set_thumbnail(url=f"attachment://{self.image}")

        fields = [
            ("Attack", self.attack, True),
            ("Defense", self.defense, True),
            ("Dodge", self.dodge, True),
            ("Health", f"{self.health} / {self.health_max}", True),
        ]

        for f, v, i in fields:
            if isinstance(v, int):
                v = f"{v:,}"
            embed.add_field(name=f, value=v, inline=i)
        return embed, file

    def get_stat_modifier_total(self, stat: Stat) -> int:
        """Sum of ``part.get_stat_modifier(stat, owner=self)`` across all
        body parts.

        Iterates **all** body parts — including destroyed ones at
        :attr:`InjuryLevels.USELESS` — not just the targetable pool. A
        destroyed part's USELESS debuff row is the most severe entry in
        the debuffs table and represents "the part is still attached but
        completely non-functional" (e.g. a severed arm still dangling
        from its shoulder socket, contributing its maximum attack
        penalty even though it can no longer hold a weapon). Filtering
        destroyed parts would erase the most severe debuffs at the exact
        moment they should matter most, which is the opposite of the
        design intent. ``get_targetable_parts()`` exists for the
        *targeting* code path (don't aim at a destroyed arm), not the
        stat-aggregation path.

        Works for any :class:`Stat`: the combat system will call
        ``creature.get_stat_modifier_total(Stat.ATTACK)`` when the attack
        roll is wired to respect injury debuffs in a future item.

        The ``owner=self`` argument is threaded through to every part so
        that state-dependent overrides (dragon toes that read
        ``owner.flags``, blocking arms that read round state, etc.) can
        inspect the owning creature.
        """
        total = 0
        for part in self.body_parts:
            total += part.get_stat_modifier(stat, owner=self)
        return total

    def get_defense(self) -> int:
        return max(0, self.defense + self.get_stat_modifier_total(Stat.DEFENSE))

    def get_dodge(self) -> int:
        return max(0, self.dodge + self.get_stat_modifier_total(Stat.DODGE))

    def get_health_max(self) -> int:
        return self.health_max

    def get_part(self, name: str) -> Optional[BodyPart]:
        """Look up a body part on this creature by name.

        Exact, case-sensitive match against ``part.name``. Returns the
        first match or ``None`` if no part matches (including when this
        creature has no body parts at all).
        """
        for part in self.body_parts:
            if part.name == name:
                return part
        return None

    def get_targetable_parts(self) -> List[BodyPart]:
        """Return the list of non-destroyed body parts.

        Destroyed parts drop out of the targeting pool entirely (see the
        Phase 1 design doc). Stat aggregation and random-target routing
        both consume this list.
        """
        return [p for p in self.body_parts if not p.is_destroyed()]

    def get_health_scale(self) -> float:
        return self.health / self.get_health_max()

    def give_clarks(self, amount: int) -> bool:
        """
        Gives (or removes, if negative amount is passed) clarks to the creature.

        :param amount: The amount to adjust clarks by.
        :return: True if the exchange succeeded, otherwise False.
        """
        if self.clarks + amount > 0:
            self.clarks += amount
            self.is_dirty = True
            return True
        return False

    # Returns a boolean indicating whether the creature's health is depleted.
    def is_dead(self) -> bool:
        """
        Returns a boolean indicating whether the creature's health is depleted.

        :return: True if health <= 0, otherwise False.
        """
        return self.health <= 0


    def on_hugged(self, actor: "Creature", invocation: str) -> str:
        """
        Gets a creature's reaction to being hugged.

        :param actor: The Creature object initiating the hug.
        :param invocation: The calling command, such as 'hug', 'cuddle', or 'snuggle'.
        :return: A string representing the creature's reaction.
        """
        if self.is_dead():
            return parse("@1c's corpse rolls lifelessly in @2's arms.", self, actor)
        return parse("The @1 glances at @2 and sidesteps @2a hug.", self, actor)

    def update_pronouns(self):
        """Auto-updates the creature's pronouns, if the gender matches a preset."""
        if self.gender.lower() == "male":
            self.pronouns[Pronouns.SUBJECTIVE] = "he"
            self.pronouns[Pronouns.OBJECTIVE] = "him"
            self.pronouns[Pronouns.POSSESSIVE] = "his"
            self.pronouns[Pronouns.ADJECTIVE] = "his"
            self.pronouns[Pronouns.REFLEXIVE] = "himself"

        elif self.gender.lower() == "female":
            self.pronouns[Pronouns.SUBJECTIVE] = "she"
            self.pronouns[Pronouns.OBJECTIVE] = "her"
            self.pronouns[Pronouns.POSSESSIVE] = "hers"
            self.pronouns[Pronouns.ADJECTIVE] = "her"
            self.pronouns[Pronouns.REFLEXIVE] = "herself"

        elif self.gender.lower() == "non-binary":
            self.pronouns[Pronouns.SUBJECTIVE] = "they"
            self.pronouns[Pronouns.OBJECTIVE] = "them"
            self.pronouns[Pronouns.POSSESSIVE] = "theirs"
            self.pronouns[Pronouns.ADJECTIVE] = "their"
            self.pronouns[Pronouns.REFLEXIVE] = "themself"


def pick_random_part(parts: List[BodyPart], reach: Reach) -> Optional[BodyPart]:
    """Pick a random body part weighted by exposure to the given reach.

    This is a module-level free function (not a ``Creature`` method)
    because damage routing and combat UX call it with an arbitrary
    pre-filtered list of parts and don't need a creature instance.

    Parts that don't declare an exposure for ``reach`` default to weight
    ``1.0`` (fully exposed by default) via ``exposure.get(reach, 1.0)``.

    :param parts: The candidate parts to pick from (typically the output
        of ``Creature.get_targetable_parts()``).
    :param reach: The reach class of the incoming attack.
    :return: A randomly-chosen part weighted by exposure, or ``None`` if
        ``parts`` is empty or every part has zero exposure for this
        reach (nothing is reachable — caller should fall back to body).
    """
    if not parts:
        return None
    weights = [p.exposure.get(reach, 1.0) for p in parts]
    if sum(weights) == 0:
        return None
    return random.choices(parts, weights=weights, k=1)[0]
