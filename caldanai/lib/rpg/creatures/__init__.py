from random import choice, choices, random
from typing import List, Union, Optional, Dict, Set

from discord import Embed, File

from caldanai.lib.rpg import parse
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.combat.attack_result import AttackResult, AttackSequence
from caldanai.lib.rpg.combat.attack_source import (
    AttackSource,
    NaturalAttackSource,
)
from caldanai.lib.rpg.helpers.dice import Dice
from caldanai.lib.rpg.helpers.enums import (
    INJURY_LEVEL_DISPLAY, Pronouns, DamageTypes, InjuryLevels, Reach, Size, Stat,
)
from caldanai.lib.rpg.helpers.roll_data import (
    AttackRoll, DamageRoll, CombinedRoll)


# Minimum effective exposure for per-part dodge calculations. Caps the
# maximum dodge multiplier at ``1 / EXPOSURE_FLOOR`` so aiming at a
# low-exposure part (eye 0.1, guarded dragon head 0.05) is harder but
# not "nat-20-only harder." At 0.3 the cap is ~3.33×. Below 0.3 feels
# punishing; above 0.5 makes targeting small parts trivial.
EXPOSURE_FLOOR = 0.3

# Attacker/target size-scale ratio is clamped to this range before
# entering the dodge calc. Prevents a TINY pixie from treating a
# COLOSSAL dragon as a stationary wall (32× ratio would collapse
# defense), while still letting cross-size mismatches matter.
SIZE_RATIO_MIN = 0.5
SIZE_RATIO_MAX = 2.0


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
        self.uses_article: bool = True  # "the dragon"; players override to False
        self.size: Size = Size.MEDIUM
        self.core_agility: int = 0
        self.core_toughness: int = 0
        # Owning game's primary channel id — the routing key for
        # subsystems that need time-of-day or other game-scoped state
        # via the ``caldanai.lib.rpg.time`` façade
        # (``get_time_components(self._channel_id)`` etc.). Populated
        # at spawn by ``Game.get_monster`` and when a Player is bound
        # to an active game. ``None`` in unit-test / pre-bind contexts
        # — façade functions return ``None`` gracefully so callers
        # don't need extra guards.
        self._channel_id: Optional[int] = None

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
    ) -> Optional[str]:
        """Applies damage (or healing if ``amount`` is negative) to this
        creature. Pure damage application — does not fire part hooks.

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

        **Hook firing is the caller's responsibility.** This method
        never calls ``on_injury_change`` / ``on_destroyed`` on the
        targeted part. The combat helper
        (:func:`apply_sequence_to_target`) owns hook firing — it
        coalesces transitions across a whole attack sequence so
        multi-source sequences don't double-fire side effects (wing
        grounding, doppelganger pain cries, etc.). Non-combat callers
        today never route ``target_part``; if that ever changes, the
        new caller should fire the relevant hooks itself.

        :param amount: Damage amount; negative heals.
        :param dmg_type: Optional damage type used to look up trait
            multipliers on both the creature and the targeted part.
        :param target_part: Optional body part to absorb the damage.
        :return: Empty string by default. Subclass overrides return a
            non-empty message for state transitions (Player death /
            resurrection, MonsterPlugin death).
        """

        if target_part is None or not self.body_parts:
            # Legacy path / no parts: preserves exact pre-refactor
            # behavior including healing.
            self.health -= amount
            self.health = max(0, self.health)
            self.health = min(self.health, self.get_health_max())
            return ""

        # Part-targeted routing (Model D — unified body HP).
        multiplier = (
            target_part.get_trait_multiplier(dmg_type)
        )
        final_dmg = int(amount * multiplier)

        # Part tracks damage for injury-level purposes.
        # Body HP is NOT reduced here — the caller (do_combat) applies
        # the post-defense total to body HP after all sources resolve.
        target_part.apply_damage(final_dmg, dmg_type)

        # Critical part destroyed → death (even before body HP is touched).
        if target_part.is_critical and target_part.is_destroyed():
            self.health = 0

        return ""

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
        - N names → source[i] targets name[i % N]; extra sources cycle
          through the list (so a 5-head hydra given two targets rips
          through both rather than dogpiling the second).
        - Each name is resolved via ``find_parts``: case-insensitive
          exact match wins, else case-insensitive segment-prefix match
          (``leg.r`` → ``leg.right``).

        When ``None`` or empty, each source independently picks a random
        target part weighted by reach.
        """

        def _resolve_name(name: str) -> Optional["BodyPart"]:
            """Resolve a part-name string to a BodyPart instance."""
            matches = target.find_parts(name)
            if matches:
                return choice(matches)
            return None

        # Pre-resolve explicit targets (one per source slot).
        explicit_parts: List[Optional["BodyPart"]] = []
        if explicit_part_names and target.body_parts:
            for name in explicit_part_names:
                explicit_parts.append(_resolve_name(name))

        results: List[AttackResult] = []
        sources = self.get_attack_sources()
        for i, source in enumerate(sources):
            # Choose the target part: explicit player choice > monster
            # preference > exposure-weighted random. All three paths
            # land at a concrete ``target_part`` (or ``None`` if the
            # target has no body parts).
            if explicit_parts:
                idx = i % len(explicit_parts)
                resolved = explicit_parts[idx]
                if resolved and not resolved.is_destroyed():
                    target_part = resolved
                else:
                    target_part = pick_random_part(target.get_targetable_parts(), source.reach)
            elif target.body_parts:
                target_part = None
                preference_name = self.get_target_part_preference(target, source)
                if preference_name:
                    resolved = _resolve_name(preference_name)
                    if resolved:
                        target_part = resolved
                if target_part is None:
                    target_part = pick_random_part(target.get_targetable_parts(), source.reach)
            else:
                target_part = None

            # Targeted-dodge math applies whenever a part is on the
            # receiving end, regardless of how it was chosen. The tax
            # lives with the *target* (small/hard-to-reach parts are
            # harder to hit), not with the *intent* — otherwise a
            # random swing that happens to land on an eye would hit it
            # easier than a deliberate eye-poke, which is the wrong
            # narrative. Shared with custom ``do_attack`` overrides
            # via ``Creature.get_targeted_dodge``.
            target_dodge: Optional[int] = None
            if target_part is not None:
                target_dodge = target.get_targeted_dodge(self, target_part, source)

            atk_roll, dmg_roll = source.make_attack_rolls(self)
            result = target.resolve_attack(
                self, source, atk_roll, dmg_roll, target_dodge=target_dodge
            )
            result.target_part = target_part  # store for damage application + display
            results.append(result)
            self._on_attack_resolved(source, result)
        return AttackSequence(attacker=self, target=target, results=results)

    def _on_attack_resolved(self, source: AttackSource, result: AttackResult) -> None:
        """Hook called after each attack source resolves.

        Default behavior: applies life-drain healing if ``source``
        carries a non-zero ``drain_ratio``. Spirit and future
        drain-attack monsters set this on their natural attack
        sources to heal a fraction of damage dealt.

        Subclasses that override should call ``super()`` to retain
        the drain behavior (Player does this — adds skill XP on top).
        """
        drain = getattr(source, "drain_ratio", 0.0)
        if drain > 0 and result.damage > 0:
            heal = int(result.damage * drain)
            if heal > 0:
                self.apply_damage(-heal)

    def _on_attacked(
        self,
        attacker: "Creature",
        source: AttackSource,
        result: AttackResult,
    ) -> None:
        """Hook called on the *target* after an attack resolves
        against it. Default no-op.

        Subclasses override for reactive damage / counter-effects:
        spirits deal cold counter-damage on melee, future "thorns"
        armor would damage the attacker, fire-aura monsters singe
        attackers who came in close. Fires regardless of hit/miss
        — the override decides what to do based on ``result.damage``
        and ``source.reach``.
        """
        pass

    # Class-level declaration of "I bias my AI targeting toward these
    # parts." Maps ``part_name -> probability``. Empty dict (the
    # default, inherited by every Creature subclass that doesn't opt
    # in) = no bias, fall through to exposure-weighted random
    # targeting. Monsters populate this; players inherit the empty
    # default and never touch it (their targeting is human-driven).
    #
    # Each entry is rolled once per attack in dict iteration order
    # (insertion-preserving on Py3.7+); the first entry whose roll
    # succeeds returns that part name and short-circuits. Per-entry
    # rolls are independent coin flips, NOT partitioned ranges — so
    # ``{"head": 0.3, "leg": 0.3}`` is "30% chance of head, plus if
    # head misses, 30% chance of leg," not "30/30/40 split."
    #
    # Subclasses with logic beyond "declarative dict of part
    # biases" (conditional on target state, weapon reach, feed
    # mechanics, etc.) override :meth:`get_target_part_preference`
    # directly instead of populating this dict.
    TARGET_PREFERENCES: Dict[str, float] = {}

    def get_target_part_preference(
        self,
        target: "Creature",
        source: AttackSource,
    ) -> Optional[str]:
        """Hook for predatory / tactical targeting. Walks
        :attr:`TARGET_PREFERENCES` in insertion order, rolling
        ``random()`` once per entry; returns the first part name whose
        roll succeeds, or ``None`` when the dict is empty or every
        entry's roll fails.

        Return value — a part name like ``"head"`` or a base like
        ``"leg"`` (the latter resolves to a random matching part on
        the target, e.g. ``leg.left`` or ``leg.right``). The framework
        resolves via the same matcher used by ``$target`` and falls
        back to exposure-weighted random targeting if no matching
        non-destroyed part exists.

        Returning ``None`` means "no preference" — the baseline
        "dumb" behavior that fits most creatures, which is exactly
        what an empty ``TARGET_PREFERENCES`` dict produces. Subclasses
        with logic beyond per-entry coin flips (conditional on target
        state, weapon reach, etc.) override this method directly.

        When a preference IS honored, the attack pays the exposure
        tax on dodge the same way a player's explicit target does:
        aiming at a low-exposure part makes the attack harder to land,
        which captures the tactical tradeoff of "smart but obvious."
        """
        for part_name, prob in self.TARGET_PREFERENCES.items():
            if random() < prob:
                return part_name
        return None

    # ------------------------------------------------------------------
    # Capability queries
    #
    # These are the canonical "what can this creature do?" predicates.
    # Tests filter over the monster registry using these methods so
    # adding a new flyer / predator / eyeless creature auto-joins the
    # relevant capability test groups without touching test files.
    # Combat code uses them too (e.g. ``get_dodge`` checks
    # ``is_flying``) so rewiring how a capability is stored is a
    # single-method change.
    # ------------------------------------------------------------------

    def can_fly(self) -> bool:
        """Does this creature have a functional flight capability right
        now? Default: at least one non-destroyed wing part. Override
        for magical flight that doesn't need wings (a djinn, say), or
        for conditional flight (only when a specific flag is set)."""
        wings = [p for p in self.body_parts if _part_base_name(p) == "wing"]
        if not wings:
            return False
        return any(not p.is_destroyed() for p in wings)

    def is_flying(self) -> bool:
        """Is this creature currently airborne? True when the
        ``"flying"`` state flag is set (the flag is the authoritative
        state — wing destruction discards it via
        ``WingPlugin.on_injury_change``, grounding the creature)."""
        return "flying" in self.flags

    def has_eyes(self) -> bool:
        """Does this creature have any eye parts? Distinguishes
        classical humanoids (eyeless by convention via
        ``BodyPart.humanoid``) from players / cyclopes / pixies who
        declare eye parts explicitly. Drives HIT emergence: if there
        are eyes, they're the HIT source; otherwise heads are."""
        return any(_part_base_name(p) == "eye" for p in self.body_parts)

    def has_body_parts(self) -> bool:
        """``True`` for any creature with a non-empty anatomy. The
        negative case (spirits, by design) routes combat through the
        legacy whole-body damage path."""
        return len(self.body_parts) > 0

    def has_target_preference(self) -> bool:
        """``True`` if this creature biases its AI targeting. Truthy
        when :attr:`TARGET_PREFERENCES` is non-empty (the declarative
        path — most creatures). Subclasses with custom targeting
        logic that bypasses the dict should override this method
        alongside :meth:`get_target_part_preference` to return
        ``True`` as well, so capability filters (tests, etc.) still
        classify them as preference-having."""
        return bool(self.TARGET_PREFERENCES)

    # ------------------------------------------------------------------
    # Per-hit narration
    #
    # Class-level dict mapping damage-type bits to flavor templates
    # ("@1d shrugs off the blow", etc.). The base ``get_hit_narration``
    # scans this dict and picks the first matching damage type, parsing
    # the template with the target as ``@1`` and attacker as ``@2``.
    #
    # Lets monsters with strong trait identities (skeleton vulnerable
    # to bludgeoning, golem shrugging off arrows) communicate the
    # interaction in narrative language without players needing to
    # read trait tables. Subclasses just declare ``HIT_NARRATIONS`` —
    # no method override needed for the static-string case.
    # ------------------------------------------------------------------

    HIT_NARRATIONS: Dict[DamageTypes, str] = {}

    @classmethod
    def _resolved_hit_narrations(cls) -> Dict[DamageTypes, str]:
        """Walk ``__mro__`` and merge every ``HIT_NARRATIONS`` dict
        encountered into a single resolved dict.

        Walks base → derived (via ``reversed(__mro__)``), so a
        subclass's entry for the same damage-type key overwrites the
        mixin's value. Lets classification mixins (Undead, future
        Construct/Fae/etc.) provide defaults that concrete monsters
        can selectively override without ``{**Parent.X, ...}``
        merge boilerplate at every declaration site.

        Cached implicitly via standard class introspection — cheap
        enough that we don't memoize.
        """
        merged: Dict[DamageTypes, str] = {}
        for klass in reversed(cls.__mro__):
            entries = klass.__dict__.get("HIT_NARRATIONS")
            if entries:
                merged.update(entries)
        return merged

    def get_hit_narration(
        self,
        attacker: "Creature",
        source: AttackSource,
        result: AttackResult,
    ) -> Optional[str]:
        """Return a short flavor line describing how this attack
        landed against this creature. Default: look up the
        MRO-merged ``HIT_NARRATIONS`` by damage type, return the
        first match (or None if no entry matches). Override for
        dynamic narration (varying by hit intensity, current
        state, etc.)."""
        if not result.hit() or source.damage_type is None:
            return None
        for dmg_type, template in self._resolved_hit_narrations().items():
            if source.damage_type & dmg_type:
                return parse(template, self, attacker)
        return None

    def resolve_attack(
        self,
        attacker: "Creature",
        source: AttackSource,
        atk_roll: AttackRoll,
        dmg_roll: DamageRoll,
        target_dodge: Optional[int] = None,
    ) -> AttackResult:
        """Pure calculation of a single attack against this creature.

        Computes hit/miss and applies trait multipliers.  Defense is NOT
        subtracted per-source — it is subtracted once from the per-player
        total in ``do_combat`` (variant B, restored pre-refactor balance).

        ``target_dodge`` lets the caller override the dodge check value
        (used by per-part dodge scaling when a player explicitly targets
        a low-exposure body part). When ``None``, the creature's base
        dodge is used.
        """
        dodge = target_dodge if target_dodge is not None else self.get_dodge()
        defense = self.get_defense()

        # Apply attacker's HIT modifier (eye/head functionality)
        hit_mod = attacker.get_hit_modifier()
        if hit_mod != 0:
            atk_roll.skillBonus += hit_mod
            atk_roll.result += hit_mod

        combined = CombinedRoll(atk_roll, dmg_roll, dodge)
        multiplier = self.get_trait_multiplier(source.damage_type)
        sub_dmg = int(multiplier * combined.result)
        damage = 0 if combined.isMiss else max(0, sub_dmg)
        result = AttackResult(
            source=source,
            combined=combined,
            damage=damage,
            multiplier=multiplier,
            defense=defense,
            dodge=dodge,
            dmg_type=source.damage_type,
        )
        # Per-hit narration: trait-aware flavor (e.g. "bones crack"
        # for bludgeoning vs skeleton). Surfaces in extra_text so it
        # renders below the attack row.
        narration = self.get_hit_narration(attacker, source, result)
        if narration:
            result.extra_text = narration
        # Reactive hook: gives the target a chance to retaliate
        # (spirit cold-touch, thorns armor, etc.) or surface flavor
        # of its own. Reactive overrides may append to extra_text.
        self._on_attacked(attacker, source, result)
        return result

    def render_body_part_status_table(self, show_hp: bool = True) -> str:
        """Render this creature's per-part status as an ansi-fenced
        table matching ``$health``'s format: dot gauge + part name +
        (optionally) HP + color-coded status word. Returns an empty
        string when the creature has no body parts.

        Used by both ``$health`` (for players) and ``$look`` (for
        monsters via ``get_embed``) so the single formatting source
        of truth is this method.

        :param show_hp: When ``True`` (default), include an ``HP``
            column with current/max values. When ``False``, collapse
            to dot + part name + status word — used by monster
            ``$look`` where per-part HP numbers invite confusing
            arithmetic against the creature's body HP (the two are
            parallel Model-D accounting, not a shared pool).
        """
        parts = self.body_parts or []
        if not parts:
            return ""

        rows = []
        for part in parts:
            level = part.get_injury_level()
            dot, word, color = INJURY_LEVEL_DISPLAY.get(level, ("🟢", "unharmed", "32"))
            hp_str = f"{part.health} / {part.health_max}"
            rows.append((dot, part.name, hp_str, word, color))

        part_w = max(len(r[1]) for r in rows + [("", "Part", "", "", "")])
        status_w = max(len(r[3]) for r in rows + [("", "", "", "Status", "")])

        lines = ["```ansi"]
        if show_hp:
            hp_w = max(len(r[2]) for r in rows + [("", "", "HP", "", "")])
            lines.append(
                f"   {'Part'.ljust(part_w)} | "
                f"{'HP'.ljust(hp_w)} | "
                f"{'Status'.ljust(status_w)}"
            )
            for dot, name, hp_str, word, color in rows:
                padded_word = word.ljust(status_w)
                colored_word = f"\x1b[2;{color}m{padded_word}\x1b[0m"
                lines.append(
                    f"{dot} {name.ljust(part_w)} | "
                    f"{hp_str.ljust(hp_w)} | "
                    f"{colored_word}"
                )
        else:
            lines.append(
                f"   {'Part'.ljust(part_w)} | "
                f"{'Status'.ljust(status_w)}"
            )
            for dot, name, _hp_str, word, color in rows:
                padded_word = word.ljust(status_w)
                colored_word = f"\x1b[2;{color}m{padded_word}\x1b[0m"
                lines.append(
                    f"{dot} {name.ljust(part_w)} | {colored_word}"
                )
        lines.append("```")
        return "\n".join(lines)

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
            ("Size", self.size.name.title(), True),
            ("Attack", self.attack, True),
            ("Defense", self.get_defense(), True),
            ("Dodge", self.get_dodge(), True),
            ("Health", f"{self.health} / {self.health_max}", True),
            ("\u200b", "\u200b", True),
        ]

        for f, v, i in fields:
            if isinstance(v, int):
                v = f"{v:,}"
            embed.add_field(name=f, value=v, inline=i)

        # Per-part injury table lives below the stat row. Non-inline so
        # the monospace table gets its full width. Embed field values
        # cap at 1024 chars — creatures with huge anatomy (hydras with
        # many heads, hypothetical centipedes) fall back to truncation
        # rather than crashing the embed.
        #
        # ``show_hp=False`` because body HP and per-part HP are parallel
        # accounting (Model D) — showing both numbers side-by-side in
        # one embed invites players to try math that has no answer.
        # The status words + dot gauge communicate relative injury
        # without baiting the comparison.
        parts_table = self.render_body_part_status_table(show_hp=False)
        if parts_table:
            if len(parts_table) > 1024:
                # Preserve the closing fence even after truncation so
                # the code block still renders correctly.
                parts_table = parts_table[:1000].rstrip() + "\n...\n```"
            embed.add_field(name="Body Parts", value=parts_table, inline=False)

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

        .. note:: DODGE and DEFENSE are now handled by emergence
           (``get_dodge`` / ``get_defense``) and the debuff table rows
           for those stats are deprecated. Phase B cleanup should remove
           them from the debuffs table.

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
        """Defense emerges from torso functionality scaled by size.

        Floored at 1 when any torso functionality remains — ``int()``
        truncation on a low rolled ``defense`` × a small ``defense_mod``
        (e.g. SMALL's 0.75) would otherwise collapse to 0 on a healthy
        creature, which reads as a bug at the combat surface.
        ``ratio == 0`` (all torsos destroyed) still yields 0.
        """
        if not self.body_parts:
            return max(0, self.defense)

        torsos = [p for p in self.body_parts if _part_base_name(p) == "torso"]
        if not torsos:
            return max(0, self.core_toughness)

        ratio = _functionality_ratio(torsos)
        size_mod = self.size.value["defense_mod"]
        emergent = int(self.defense * ratio * size_mod) + self.core_toughness
        floor = 1 if ratio > 0 else 0
        return max(floor, emergent)

    def get_dodge(self) -> int:
        """Dodge emerges from mobility sources (legs or wings) scaled by size.

        Floored at 1 when any mobility functionality remains — ``int()``
        truncation on a low rolled ``dodge`` × a small ``dodge_mod``
        (HUGE's 0.5, COLOSSAL's 0.25) would otherwise collapse to 0 on
        a healthy creature (a HUGE giant rolling 1 on ``1d4`` is the
        canonical case). ``ratio == 0`` (all mobility parts destroyed)
        still yields 0.
        """
        if not self.body_parts:
            # Legacy path: no body parts, use flat stat
            return max(0, self.dodge)

        # Determine mobility sources: wings if flying, else legs
        if self.is_flying():
            sources = [p for p in self.body_parts if _part_base_name(p) == "wing"]
        else:
            sources = [p for p in self.body_parts if _part_base_name(p) == "leg"]

        if not sources:
            # No relevant mobility parts (e.g., a snake or magical creature)
            return max(0, self.core_agility)

        ratio = _functionality_ratio(sources)
        size_mod = self.size.value["dodge_mod"]
        emergent = int(self.dodge * ratio * size_mod) + self.core_agility
        floor = 1 if ratio > 0 else 0
        return max(floor, emergent)

    def get_targeted_dodge(
        self,
        attacker: "Creature",
        target_part: BodyPart,
        source: AttackSource,
    ) -> int:
        """Effective dodge when ``attacker`` is deliberately aiming at
        ``target_part`` on this creature. Composes three factors on top
        of ``get_dodge()``:

        - **Exposure**: the part's ``exposure[source.reach]`` value.
          Lower exposure → the part is harder to pinpoint → effective
          dodge scales up. Bounded below by ``EXPOSURE_FLOOR`` to keep
          the math from exploding on near-zero exposures.
        - **Size ratio**: ``attacker.attack_scale / self.attack_scale``,
          clamped to ``[SIZE_RATIO_MIN, SIZE_RATIO_MAX]``. Captures the
          "nimble vs massive" asymmetry — a TINY attacker finds a
          MEDIUM target's parts easier, a HUGE attacker finds a TINY
          target's parts harder. Clamp prevents extreme mismatches
          (pixie vs colossal dragon) from trivializing combat.

        Called from the base :meth:`do_attack` when a preferred or
        explicit target is honored. Custom ``do_attack`` / ``attack_random``
        overrides (hydra, future multi-target monsters) can call this
        method directly instead of re-implementing the formula. Monsters
        with bespoke targeting rules may override this method; the base
        :meth:`do_attack` will still use the override via normal dispatch.
        """
        base = self.get_dodge()
        exp = target_part.exposure.get(source.reach, 1.0)
        attacker_scale = attacker.size.value.get("attack_scale", 1.0)
        target_scale = self.size.value.get("attack_scale", 1.0)
        size_ratio = max(
            SIZE_RATIO_MIN,
            min(SIZE_RATIO_MAX, attacker_scale / target_scale),
        )
        return int(base * size_ratio / max(EXPOSURE_FLOOR, exp))

    def get_health_max(self) -> int:
        return self.health_max

    def get_hit_modifier(self) -> int:
        """HIT modifier from eye/head functionality.

        0 at full health, negative when injured.  Eyes are the primary
        HIT source; heads are the fallback when no eyes are present.
        """
        if not self.body_parts:
            return 0

        eyes = [p for p in self.body_parts if _part_base_name(p) == "eye"]
        heads = [p for p in self.body_parts if _part_base_name(p) == "head"]

        # Eyes are primary HIT source; heads are fallback
        sources = eyes if eyes else heads
        if not sources:
            return 0

        ratio = _functionality_ratio(sources)
        # At full health: 0 penalty. At all destroyed: -5 penalty.
        # Scale: (ratio - 1.0) * 5 -> ranges from 0 to -5
        return int((ratio - 1.0) * 5)

    def _scale_part_hp(self) -> None:
        """Scale body part HP by creature size, then symmetrize paired
        parts. Call after composing ``body_parts`` in subclass
        ``__init__``.

        Symmetrization always runs (even at scale 1.0) so MEDIUM
        creatures also get left/right HP matching. The Player path
        doesn't invoke this method — it calls
        ``_symmetrize_paired_parts`` directly after anatomy setup.
        """
        scale = self.size.value["hp_scale"]
        if scale != 1.0:
            for part in self.body_parts:
                part.health_max = max(1, int(part.health_max * scale))
                part.health = part.health_max
        self._symmetrize_paired_parts()

    def _symmetrize_paired_parts(self) -> None:
        """Sync ``<base>.left`` / ``<base>.right`` pairs so both sides
        of an individual creature share one rolled ``health_max``.

        Independent rolls at construction produced jarring intra-body
        asymmetry (e.g. one bearowl hindleg at 12 HP, the other at
        44). We pick the *max* of the pair's rolled values — preserves
        any lucky roll without penalizing the unluckier side — and
        reset both sides' current health to that value since this is
        called at construction time.

        Unpaired parts (``head``, ``torso``, ``tail``, numbered heads
        like ``head.1``) are untouched. Creature-to-creature variance
        still comes from independent rolls across different
        individuals.
        """
        from collections import defaultdict
        groups: Dict[str, List[BodyPart]] = defaultdict(list)
        for part in self.body_parts:
            if "." not in part.name:
                continue
            base, side = part.name.rsplit(".", 1)
            if side in ("left", "right"):
                groups[base].append(part)
        for parts in groups.values():
            if len(parts) < 2:
                continue
            new_max = max(p.health_max for p in parts)
            for p in parts:
                p.health_max = new_max
                p.health = new_max

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

    def find_parts(self, name: str) -> List[BodyPart]:
        """Fuzzy, case-insensitive lookup over non-destroyed body parts.

        Matches per dotted segment: each ``.``-separated segment of
        ``name`` must be a prefix of the corresponding segment of the
        part name. So ``leg.r`` matches ``leg.right`` (and not
        ``leg.left``), ``leg`` matches both sided legs, and ``h`` on a
        monster with ``head``/``hand.left``/``hand.right`` matches all
        three but never stray parts whose later segments merely happen
        to contain ``h`` (e.g. ``arm.right``). Exact matches
        short-circuit so a bare ``leg`` part beats its dotted variants
        when the user types ``leg`` exactly.
        """
        q = name.lower().strip()
        if not q:
            return []
        candidates = self.get_targetable_parts()
        exact = [p for p in candidates if p.name.lower() == q]
        if exact:
            return exact
        query_segs = q.split(".")
        # A trailing or leading dot (e.g. ``"leg."`` or ``".r"``) leaves
        # an empty segment that would otherwise prefix-match anything;
        # treat such queries as non-matches rather than inventing weird
        # semantics around them.
        if any(seg == "" for seg in query_segs):
            return []

        def segment_match(part: BodyPart) -> bool:
            name_segs = part.name.lower().split(".")
            if len(query_segs) > len(name_segs):
                return False
            return all(ns.startswith(qs) for qs, ns in zip(query_segs, name_segs))

        return [p for p in candidates if segment_match(p)]

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

        Legacy per-command hook. New social commands go through
        :meth:`on_social` with a class-level ``SOCIAL_REACTIONS``
        dict; this method stays as the fallback for ``cmd == "hug"``
        so existing monster overrides (Dragon, Golem, etc.) keep
        working unchanged.

        :param actor: The Creature object initiating the hug.
        :param invocation: The calling command, such as 'hug', 'cuddle', or 'snuggle'.
        :return: A string representing the creature's reaction.
        """
        if self.is_dead():
            return parse("@1cnp corpse rolls lifelessly in @2np arms.", self, actor)
        return parse("@1dc glances at @2 and sidesteps @2a hug.", self, actor)

    def on_social(
        self,
        cmd: str,
        actor: "Creature",
        invocation: str,
    ) -> str:
        """Reaction narration when a social command targets this
        creature. Default: look up ``cmd`` in the class-level
        ``SOCIAL_REACTIONS`` dict (if defined). Empty return = the
        caller renders a bland "doesn't react" line.

        Subclasses can either declare a ``SOCIAL_REACTIONS`` dict
        (keyed by warmth-aware command name) for sparse per-command
        flavor, or override this method wholesale for dynamic
        reactions that depend on creature state.

        For backwards compatibility, ``cmd == "hug"`` with no
        matching dict entry delegates to :meth:`on_hugged` so
        existing monster plugins (Dragon, Golem, etc.) don't need
        to be touched — they gain the new hook "for free" on the
        hug path and opt into other commands at their own pace.

        :param cmd: The warmth-aware command name (``"hug"``,
            ``"salute"``, ``"glare"``, etc.). Lowercase.
        :param actor: The player (or creature) initiating the
            gesture. Passed through so narration parsers that
            reference ``@2`` get the right substitution.
        :param invocation: The literal command alias the actor
            typed (``"hug"`` / ``"snuggle"`` for hug;
            ``"salute"`` / ``"sal"`` for salute; etc.). Monsters
            rarely need this but some flavor lines use the verb.
        :return: A narration string (runs through ``parse`` by
            the caller), or ``""`` for no reaction.
        """
        reactions = getattr(self, "SOCIAL_REACTIONS", None) or {}
        if cmd in reactions:
            return parse(reactions[cmd], self, actor)
        if cmd == "hug":
            # Existing monster overrides of ``on_hugged`` are
            # inconsistent about parsing — Creature.on_hugged parses
            # before returning, but Bandit / Dragon return raw
            # templates. The prior cog-level call did
            # ``parse(on_hugged(...), self, actor)`` to normalize;
            # keep that normalization here so ``on_social`` always
            # returns rendered text regardless of the subclass's
            # parsing habits. Double-parsing already-rendered text
            # is a no-op (no tokens remain).
            return parse(self.on_hugged(actor, invocation), self, actor)
        return ""

    @property
    def plural_verbs(self) -> bool:
        """``True`` when the creature takes plural-verb agreement with
        a pronoun subject (they/them by default; extensible via
        ``PLURAL_VERB_SUBJECTIVES`` in the parser). Used by the verb-
        agreement token ``@<n>v(singular|plural)`` in narration.

        Best-effort detection from ``pronouns[Pronouns.SUBJECTIVE]``:
        known plural-agreeing values match, everything else falls back
        to singular — the conventional default for English neopronouns
        (xe/ze/etc., all singular-agreeing). Players with unusual
        pronoun choices may see imperfect verbs until/unless we add an
        explicit override knob."""
        # Local import to avoid circular dependency on parser module.
        from caldanai.lib.rpg.helpers.parser import PLURAL_VERB_SUBJECTIVES
        subj = self.pronouns.get(Pronouns.SUBJECTIVE, "").lower()
        return subj in PLURAL_VERB_SUBJECTIVES

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


def _part_base_name(part: BodyPart) -> str:
    """Get the plugin base name for a body part (e.g., 'leg', 'head').

    Reads the class-level ``name`` attribute set by each
    :class:`BodyPartPlugin` subclass.  Returns ``""`` for plain
    ``BodyPart`` instances that lack a class-level ``name``.
    """
    cls = type(part)
    # Only consider the *class*-level attribute — instance ``self.name``
    # is the dot-qualified instance name (e.g. "leg.left"), not the
    # plugin role identifier.
    if "name" in cls.__dict__:
        return cls.__dict__["name"]
    # Walk the MRO (excluding the instance) looking for a class-level
    # ``name`` that isn't the instance attribute.
    for klass in cls.__mro__:
        if "name" in klass.__dict__:
            return klass.__dict__["name"]
    return ""


_FUNCTIONALITY_WEIGHTS = {
    InjuryLevels.NONE:     1.0,
    InjuryLevels.MINOR:    0.8,
    InjuryLevels.MODERATE: 0.5,
    InjuryLevels.SEVERE:   0.25,
    InjuryLevels.USELESS:  0.0,
}


def _functionality_ratio(parts: list) -> float:
    """Compute the average functionality of a group of body parts.

    Returns 0.0–1.0 based on injury-level-weighted average.
    """
    if not parts:
        return 0.0
    total = sum(_FUNCTIONALITY_WEIGHTS.get(p.get_injury_level(), 1.0) for p in parts)
    return total / len(parts)


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
    return choices(parts, weights=weights, k=1)[0]
