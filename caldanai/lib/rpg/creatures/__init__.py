from collections import defaultdict
from random import choice, choices, random, sample
from typing import List, Tuple, Union, Optional, Dict, Set

from discord import Embed, File

from caldanai.lib.rpg import parse
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.combat.attack_result import AttackResult, AttackSequence
from caldanai.lib.rpg.combat.attack_source import (
    AttackSource,
    NaturalAttackSource,
)
from caldanai.lib.rpg.combat.block import Assignment, ReactionEntry
from caldanai.lib.rpg.combat.resolution import (
    MultiVictimResolutionResult,
    ResolutionResult,
    apply_sequence_to_target,
)
from caldanai.lib.rpg.helpers.dice import Dice
from caldanai.lib.rpg.helpers.enums import (
    INJURY_LEVEL_DISPLAY, Pronouns, DamageTypes, InjuryLevels, Reach, Size, Stat,
)
from caldanai.lib.rpg.helpers.roll_data import (
    AttackRoll, DamageRoll, CombinedRoll)
from caldanai.logger import get_logger


_log = get_logger(__name__)


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

    # Combat pipeline — per-attacker stage methods. Not yet wired into
    # ``Game.do_combat``; see ``combat-pipeline-refactor.md`` for stage
    # contracts and the migration phase that lights each one up.

    ACTION_BUDGET: int = 2

    def get_action_budget(self) -> int:
        """Number of action points this creature may spend this round.

        Base reads the declarative ``ACTION_BUDGET`` class attribute.
        Dynamic attackers (hydra, whose budget scales with live heads)
        override this method directly."""
        return self.ACTION_BUDGET

    def pick_actions(self) -> List[AttackSource]:
        """Stage 1 — walk living body parts, collect the merged
        ``DEFAULT_ACTIONS`` pool (part-default + creature override),
        then weighted-random select within :meth:`get_action_budget`.

        Callable fields on action entries are invoked at this stage:

        - ``is_available(actor, target) -> bool`` filters entries out
          of the selection pool when it returns falsy.
        - ``get_dice(actor, target) -> str`` overrides the static
          ``dice`` field when present (also consulted if ``dice`` is
          absent and no size-scaled tier entry exists).
        - ``get_narrative`` is deferred to :meth:`narrate_attempt`;
          ``pick_actions`` only needs ``is_available`` and ``get_dice``
          to build the source.

        Returns ``NaturalAttackSource`` objects built from each
        selected action entry. When no part declares any actions (the
        pre-Phase-3 default for every monster), falls back to the
        first entry from :meth:`get_attack_sources` so today's
        single-attack behavior is preserved."""
        part_pools = self._collect_part_action_pools()
        if not part_pools:
            sources = self.get_attack_sources()
            return [sources[0]] if sources else []

        selected = _select_actions_within_budget(
            part_pools, self.get_action_budget(),
        )
        if not selected:
            sources = self.get_attack_sources()
            return [sources[0]] if sources else []

        sources: List[AttackSource] = []
        for part, action_name, action in selected:
            reach = action.get("reach", Reach.MELEE)
            dmg_type = action.get("dmg_type")
            label = action.get("label", action_name)
            dice = _resolve_action_dice(action, action_name, self)
            source = NaturalAttackSource(
                atk=dice,
                dmg_type=dmg_type,
                label=label,
                skill=action.get("skill", "natural"),
                reach=reach,
            )
            # Stash origin so downstream stages (narrative, resolve,
            # reactions) can recover the part and template pool without
            # rethreading them through the pipeline signature. Not a
            # public field on AttackSource — phase-local bookkeeping.
            source._part = part
            source._action_name = action_name
            source._action = action
            sources.append(source)
        return sources

    def _collect_part_action_pools(
        self,
    ) -> List[Tuple[BodyPart, Dict[str, Dict]]]:
        """Walk living parts, return ``(part, merged_actions)`` pairs.

        Merged actions = part's ``DEFAULT_ACTIONS`` deep-merged with
        this creature's ``ACTION_REPERTOIRE[part_type]`` — matching
        entries override fields on the part default, non-matching
        entries add brand-new actions (minotaur's ``gore``, etc.).

        Entries carrying ``is_available(actor, target)`` that returns
        falsy drop out of the selectable pool at this stage (target
        is ``None`` at action-pick time; the callable may inspect
        actor state only). Parts whose final pool is empty drop out —
        partially populated anatomies (Phase 3 ships only six active
        plugins) need to be tolerated gracefully."""
        overrides = getattr(self, "ACTION_REPERTOIRE", {}) or {}
        pools: List[Tuple[BodyPart, Dict[str, Dict]]] = []
        for part in self.body_parts:
            if part.is_destroyed():
                continue
            defaults = getattr(part, "DEFAULT_ACTIONS", {}) or {}
            part_type = _part_base_name(part)
            part_overrides = overrides.get(part_type, {}) or {}
            merged: Dict[str, Dict] = {}
            for action_name, entry in defaults.items():
                merged[action_name] = dict(entry)
            for action_name, entry in part_overrides.items():
                if action_name in merged:
                    merged[action_name].update(entry)
                else:
                    merged[action_name] = dict(entry)
            # Drop entries whose ``is_available`` callable vetoes them.
            merged = {
                name: entry
                for name, entry in merged.items()
                if _action_is_available(entry, self, None)
            }
            if merged:
                pools.append((part, merged))
        return pools

    def pick_targets(
        self,
        actions: List[AttackSource],
        combatants: List["Creature"],
    ) -> List[Assignment]:
        """Stage 2 — pair each action with a target. Default is
        single-target: every action points at the first living
        combatant. Sources with a preset ``intended_target`` honor it.
        Multi-target attackers (Hydra) override to distribute actions
        across combatants via :func:`round_robin_assignment`."""
        if not actions:
            return []
        living = [c for c in combatants if not c.is_dead()]
        default_target = living[0] if living else (combatants[0] if combatants else None)
        out: List[Assignment] = []
        for source in actions:
            target = source.intended_target or default_target
            if target is None:
                continue
            out.append(Assignment(source=source, target=target))
        return out

    def resolve(
        self,
        assignments: List[Assignment],
    ) -> MultiVictimResolutionResult:
        """Stage 3 — pure part-routing + aggregation.

        Bucket assignments by victim, run each bucket through
        :func:`apply_sequence_to_target`, aggregate into a
        :class:`MultiVictimResolutionResult`. Each source's
        :meth:`make_attack_rolls` fires against this creature (the
        attacker); the victim's :meth:`resolve_attack` produces the
        per-hit :class:`AttackResult`. Target-part selection mirrors
        today's :meth:`do_attack` — honor a coupled ``(victim, part)``
        assignment when present, else exposure-weighted random via
        :func:`pick_random_part`.

        Body-HP application is the caller's responsibility.
        ``Game.do_combat``, ``MonsterPlugin.attack_random``, and
        ``Hydra.attack_random`` each own the post-resolve
        ``victim.apply_damage(max(num_hits, total - defense))`` math
        so this method stays a pure routing/aggregation step — which
        is what unblocks porting Player through the pipeline."""
        if not assignments:
            return MultiVictimResolutionResult()

        victims_order: List["Creature"] = []
        seen_ids: Set[int] = set()
        victim_buckets: Dict[int, List[AttackResult]] = defaultdict(list)
        all_results: List[AttackResult] = []

        for assignment in assignments:
            source = assignment.source
            target = assignment.target
            if isinstance(target, tuple):
                victim, coupled_part = target
            else:
                victim, coupled_part = target, None
            if victim is None:
                continue

            if id(victim) not in seen_ids:
                seen_ids.add(id(victim))
                victims_order.append(victim)

            target_part = coupled_part
            target_dodge = None
            if target_part is None and getattr(victim, "body_parts", None):
                target_part = pick_random_part(
                    victim.get_targetable_parts(), source.reach,
                )
            if target_part is not None:
                target_dodge = victim.get_targeted_dodge(self, target_part, source)

            atk_roll, dmg_roll = source.make_attack_rolls(self)
            result = victim.resolve_attack(
                self, source, atk_roll, dmg_roll,
                target_dodge=target_dodge, target_part=target_part,
            )
            result.target_part = target_part
            result.victim = victim
            self._on_attack_resolved(source, result)
            victim_buckets[id(victim)].append(result)
            all_results.append(result)

        per_victim: Dict["Creature", ResolutionResult] = {}
        any_crit = False
        for victim in victims_order:
            bucket = victim_buckets[id(victim)]
            part_routed = [
                r for r in bucket
                if r.damage > 0 and r.target_part is not None
            ]
            victim_seq = AttackSequence(
                attacker=self, target=victim, results=part_routed,
            )
            resolution = apply_sequence_to_target(
                victim_seq, victim, attacker=self,
            )
            # Recompute ``num_hits`` / ``body_damage_total`` across ALL
            # positive-damage results (not just part-routed) so the
            # downstream damage-summary floor matches today's behavior
            # for partless targets. Body-HP application itself is the
            # caller's job — see docstring.
            positive = [r for r in bucket if r.damage > 0]
            resolution.num_hits = len(positive)
            resolution.body_damage_total = sum(r.damage for r in positive)
            # Q.6: victim_results feeds the body-HP bleed formula in
            # ``compute_body_hp_damage``. Full positive-damage bucket
            # (not just part-routed) so partless hits still contribute
            # via the fallback 1.0 bleed rate.
            resolution.victim_results = positive
            per_victim[victim] = resolution
            if resolution.critical_part_kill:
                any_crit = True

        return MultiVictimResolutionResult(
            per_victim=per_victim,
            all_results=all_results,
            any_critical_part_kill=any_crit,
        )

    def narrate_attempt(
        self,
        assignments: List[Assignment],
    ) -> Optional[str]:
        """Stage 4 — per-assignment attempt flavor lifted from each
        source's action entry. Pulls a random template from the
        action's ``"narrative"`` pool (or invokes the entry's
        ``get_narrative`` callable when present) and runs each line
        through :func:`parse` with this creature as ``@1`` and the
        assignment's victim as ``@2``. A synthetic ``result`` bearing
        the part stashed on the source is passed via the ``result``
        kwarg so ``@2p_target`` resolves to the part display name
        even though real ``AttackResult`` objects aren't available
        until the resolve stage.

        Returns ``None`` when no assignment's source carries a
        narrative pool (also true of old-style ``{display}`` format
        strings once they're removed) — matches the pre-Phase-3
        default shape."""
        if not assignments:
            return None
        lines: List[str] = []
        for assignment in assignments:
            source = assignment.source
            action = getattr(source, "_action", None)
            if not action:
                continue
            target = assignment.target
            victim = target[0] if isinstance(target, tuple) else target
            templates = _resolve_action_narratives(action, self, victim)
            if not templates:
                continue
            template = choice(templates)
            # Synthesize a result-shaped object so ``@Np_target`` in
            # authored-ahead templates resolves to the targeted part's
            # display name. Real ``AttackResult`` objects only exist
            # after the resolve stage.
            part = getattr(source, "_part", None)
            synthetic = _TargetPartContext(target_part=part)
            lines.append(parse(template, self, victim, result=synthetic))
        if not lines:
            return None
        return "\n".join(lines)

    def render_table(
        self,
        results: MultiVictimResolutionResult,
    ) -> str:
        """Stage 5 — the compact diff-block attack table, composed
        over every :class:`AttackResult` across all victims. Defers to
        :meth:`AttackSequence.to_markdown` via a synthetic sequence
        over ``results.all_results``."""
        flat = list(results.all_results or [])
        if not flat:
            return ""
        first_victim = getattr(flat[0], "victim", None) or self
        sequence = AttackSequence(
            attacker=self,
            target=first_victim,
            results=flat,
            multi_target=len({id(getattr(r, "victim", None)) for r in flat}) > 1,
        )
        return sequence.to_markdown()

    def narrate_results(
        self,
        results: MultiVictimResolutionResult,
    ) -> List[str]:
        """Stage 6 — per-victim injury feedback lines. Concatenates
        every victim's :attr:`ResolutionResult.injury_feedback_lines`
        (already owner-prefixed by :func:`apply_sequence_to_target`)
        in first-encounter order."""
        lines: List[str] = []
        for _victim, resolution in (results.per_victim or {}).items():
            lines.extend(resolution.injury_feedback_lines)
        return lines

    def summarize_damage(
        self,
        results: MultiVictimResolutionResult,
        victims: List["Creature"],
        health_snapshots: Optional[Dict["Creature", int]] = None,
    ) -> Optional[str]:
        """Stage 7 — "Total damage done vs Health" summary, suppressed
        wholesale when any victim died to a critical-part kill (the
        "utterly destroyed" feedback + death beat already tell the
        story). One per-victim block using today's figure-space
        template; multi-victim loops the same shape, prefixed by the
        victim name so the reader can tell whose HP is whose.

        ``health_snapshots`` supplies pre-round HP per victim — Phase 5
        captures these before the round so the "vs" number matches
        today's ``Game.do_combat`` output exactly. If omitted, falls
        back to ``victim.get_health_max()`` (useful for isolated tests
        where no round composer is running)."""
        if results.any_critical_part_kill:
            return None
        per_victim = results.per_victim or {}
        if not per_victim:
            return None
        multi = len(per_victim) > 1
        out_lines: List[str] = []
        for victim in victims:
            resolution = per_victim.get(victim)
            if resolution is None or resolution.num_hits == 0:
                continue
            defense = victim.get_defense()
            final = max(
                resolution.num_hits,
                resolution.body_damage_total - defense,
            )
            if health_snapshots is not None and victim in health_snapshots:
                reference = health_snapshots[victim]
            else:
                reference = victim.get_health_max()
            current = getattr(victim, "health", 0)
            remaining = 0 if victim.is_dead() else max(current, 0)
            header = "Total damage done vs Health:"
            if multi:
                victim_name = getattr(victim, "name", "someone") or "someone"
                header = f"{victim_name} — Total damage done vs Health:"
            out_lines.append(
                f"{header}\n\u2800\u2800\u2800\u2800"
                f"{final:,} vs {reference:,} "
                f"= **{remaining} health remaining.**"
            )
        if not out_lines:
            return None
        return "\n".join(out_lines)

    def narrate_target_death(
        self,
        newly_dead: List["Creature"],
        results: Optional[MultiVictimResolutionResult] = None,
    ) -> Optional[str]:
        """Stage 8 — victim death flavor. Dispatch order per victim:
        part-driven-death hook (:meth:`check_part_driven_death`) →
        the already-computed ``result.death_msg`` from
        :func:`apply_sequence_to_target` (critical-part-kill flavor
        like "@1np head is utterly destroyed") → the victim's
        ``death`` attribute (monsters) → a generic "crumples
        lifelessly" line (players).

        Returns a single string joining every death beat with newlines,
        or ``None`` when nothing died."""
        if not newly_dead:
            return None
        per_victim = (results.per_victim if results is not None else {}) or {}
        beats: List[str] = []
        for victim in newly_dead:
            beat = None
            hook = getattr(victim, "check_part_driven_death", None)
            if callable(hook):
                try:
                    beat = hook()
                except TypeError:
                    beat = None
            if not beat:
                resolution = per_victim.get(victim)
                if resolution is not None and resolution.death_msg:
                    beat = parse(resolution.death_msg, victim)
            if not beat:
                death_attr = getattr(victim, "death", None)
                if death_attr:
                    beat = parse(death_attr, victim)
                else:
                    beat = parse(
                        "@1 crumples to the ground lifelessly!", victim,
                    )
            if beat:
                beats.append(beat)
        if not beats:
            return None
        return "\n".join(beats)

    def reactions(
        self,
        attacker: "Creature",
        victims: List["Creature"],
        results: MultiVictimResolutionResult,
    ) -> List[ReactionEntry]:
        """Stage 9 — out-of-turn effects (thorns, status ticks,
        explode-on-death). Default empty; monsters with retaliation /
        death-triggered effects override.

        TODO: phase 2 of reactions-stage work lands when the first
        reaction mechanic ships. Today no combat code emits reactions,
        so the default stays empty and downstream stages see no
        ``ReactionEntry`` inputs."""
        return []

    def narrate_attacker_death(
        self,
        attacker: "Creature",
        reactions_output: List[ReactionEntry],
    ) -> Optional[str]:
        """Stage 10 — single death beat when reactions kill the
        block's own attacker (thorns, death-curse). Default ``None``
        because no current reaction mechanic can kill the attacker.

        TODO: phase 2 of reactions-stage work — this stage only
        produces output once :meth:`reactions` can return a
        :class:`ReactionEntry` that killed ``attacker``."""
        if attacker is None or not reactions_output or not attacker.is_dead():
            return None
        death_attr = getattr(attacker, "death", None)
        if death_attr:
            return parse(death_attr, attacker)
        return parse("@1 crumples to the ground lifelessly!", attacker)

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
                self, source, atk_roll, dmg_roll,
                target_dodge=target_dodge, target_part=target_part,
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
        target_part: Optional[BodyPart] = None,
    ) -> AttackResult:
        """Pure calculation of a single attack against this creature.

        Computes hit/miss and applies trait multipliers.  Defense is NOT
        subtracted per-source — it is subtracted once from the per-player
        total in ``do_combat`` (variant B, restored pre-refactor balance).

        ``target_dodge`` lets the caller override the dodge check value
        (used by per-part dodge scaling when a player explicitly targets
        a low-exposure body part). When ``None``, the creature's base
        dodge is used.

        ``target_part`` lets the caller pass the aimed-at part so the
        per-part ``defense_mod`` scales effective defense for THIS
        hit. Q.6.2: defense applies per-hit at the part level (not
        once per round at body HP), so an armored torso actually
        gates part destruction. Body HP is then drained by the
        already-post-defense ``result.damage`` × ``bleed_rate``
        without further defense subtract.
        """
        dodge = target_dodge if target_dodge is not None else self.get_dodge()
        defense = self.get_defense()
        if target_part is not None:
            # Q.6.3: additive integer adjustment per part. Anatomy
            # adjusts base_def by a signed bonus — tank torso +3,
            # limb -1, eye clamps via SOFT_PART. Integer math avoids
            # the earlier ``int(base × mult)`` truncation drama, and
            # reads as "base_def plus/minus N" at the part declaration
            # site.
            defense = max(
                0, defense + getattr(target_part, "defense_bonus", 0),
            )

        # Apply attacker's HIT modifier (eye/head functionality)
        hit_mod = attacker.get_hit_modifier()
        if hit_mod != 0:
            atk_roll.skillBonus += hit_mod
            atk_roll.result += hit_mod

        combined = CombinedRoll(atk_roll, dmg_roll, dodge)
        multiplier = self.get_trait_multiplier(source.damage_type)
        sub_dmg = int(multiplier * combined.result)
        # Q.6.2: per-hit defense subtract, floor at 1 so "you
        # connected" still registers. ``defense_mod`` on the part
        # (set by content like tank torso + exposed eye) scales how
        # much of this hit the part absorbs before the HP pool
        # actually drops.
        if combined.isMiss or sub_dmg <= 0:
            damage = 0
        else:
            damage = max(1, sub_dmg - defense)
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
        """Q.6 body-HP-relative part HP scaling. Call after composing
        ``body_parts`` in subclass ``__init__``.

        Replaces the pre-Q.6 ``hp_scale``-multiplier path: critical
        parts scale as ``body_hp × size_scalar × def_scalar`` with a
        ``body_hp × 0.5`` floor (a critical part never has less than
        half the body's HP); non-critical parts scale as
        ``body_hp × part_fraction × size_scalar``. See the Q.6 design
        doc for the numbers.

        Symmetrization always runs (even at MEDIUM / def 10-20) so
        left/right HP matches after scaling. The Player path doesn't
        invoke this method — it calls ``_symmetrize_paired_parts``
        directly after anatomy setup.
        """
        defense = self.get_defense()
        for part in self.body_parts:
            part.health_max = _compute_scaled_part_hp(
                part, self.health_max, self.size, defense,
            )
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

    def check_part_driven_death(self) -> Optional[str]:
        """Hook for part-state-driven death detection, called by the
        combat loop **before** the HP-based :meth:`is_dead` branch.

        Subclasses override when the creature can die from body-part
        state alone — e.g. a hydra whose every non-critical head is
        destroyed, regardless of remaining body HP. The override is
        expected to set ``self.health = 0`` as a side effect so any
        subsequent :meth:`is_dead` calls agree, then return the death
        narration (parsed, ready for the death branch to consume).

        Returning ``None`` means no part-driven death this round — the
        combat loop then falls through to the normal HP-based flow.
        """
        return None


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


# Q.6 body-HP-relative part HP scaling. See the Q.6 design doc for
# the rationale — fixed-dice part HP drifts out of tune with body HP
# as body HP varies wildly (bandit 9, hydra 203). These tables replace
# the old ``Size.hp_scale`` multiplier path.
_Q6_SIZE_SCALAR: Dict[Size, float] = {
    Size.TINY:     0.4,
    Size.SMALL:    0.6,
    Size.MEDIUM:   0.8,
    Size.LARGE:    1.0,
    Size.HUGE:     1.3,
    Size.COLOSSAL: 1.6,
}

# Keyed by the plugin's ``name`` (as returned by ``_part_base_name``).
# Non-critical parts only — critical parts use the critical formula.
_Q6_PART_FRACTIONS: Dict[str, float] = {
    "arm":  0.20,
    "leg":  0.25,   # legs carry body mass → more resilient
    "tail": 0.15,
    "wing": 0.15,
    "eye":  0.05,
    "toe":  0.03,
    # "head" as non-critical (e.g. hydra's multi-head repertoire):
    # sized like a torso-scale non-critical. Heads of non-critical
    # creatures are major structural parts, so we give them a
    # conservative share rather than rolling into the tiny-part
    # bucket. (Baseline 0.5 matches the classic "head = ~half body
    # HP" pattern hydra's pre-Q.6 variants relied on.)
    "head": 0.5,
}

# Fallback fraction for any part plugin whose name isn't in the
# per-part table above (e.g. custom per-monster parts). Conservative
# midpoint so unknown parts don't drift wildly in either direction.
_Q6_PART_FRACTION_DEFAULT: float = 0.20


def _q6_def_scalar(defense: int) -> float:
    """Defense-band scalar for the critical-part HP formula.

    Light-armor creatures (def<10) get +50% critical-part HP to
    compensate for taking full hits; heavy-armor (def 20+) get -30%
    because their defense is already doing the protection work.
    Medium-armor (10-20) is the neutral band.
    """
    if defense < 10:
        return 1.5
    if defense >= 20:
        return 0.7
    return 1.0


def _compute_scaled_part_hp(
    part: BodyPart, body_hp: int, size: Size, defense: int,
) -> int:
    """Return the Q.6 scaled ``health_max`` for ``part``.

    See ``_scale_part_hp`` for the formulas. Critical parts are keyed
    by ``part.is_critical`` (the instance flag, which may differ from
    the plugin default — hydra's multi-head variants flip head.1..N
    to non-critical so decapitation doesn't end the fight)."""
    size_scalar = _Q6_SIZE_SCALAR.get(size, 1.0)
    if part.is_critical:
        def_scalar = _q6_def_scalar(defense)
        raw = body_hp * size_scalar * def_scalar
        floor = body_hp * 0.5
        return max(1, int(max(raw, floor)))

    base_name = _part_base_name(part)
    fraction = _Q6_PART_FRACTIONS.get(base_name, _Q6_PART_FRACTION_DEFAULT)
    raw = body_hp * fraction * size_scalar
    return max(1, int(raw))


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


def _select_actions_within_budget(
    part_pools: List[Tuple[BodyPart, Dict[str, Dict]]],
    budget: int,
) -> List[Tuple[BodyPart, str, Dict]]:
    """Weighted-random action selection capped by ``budget``.

    Walks the parts in the caller's order, picking one action per
    part by ``weight`` and subtracting its ``cost`` from the remaining
    budget. When the cheapest action for the current part is too
    expensive, skip the part rather than pick nothing. Returns
    ``(part, action_name, action_dict)`` triples for the selected
    actions.

    Shape lifted directly from hydra's ``_select_round_actions`` for
    parity — see the design doc's "Action budget" section for the
    behavioral contract."""
    if budget <= 0 or not part_pools:
        return []
    selected: List[Tuple[BodyPart, str, Dict]] = []
    remaining = budget
    for part, repertoire in part_pools:
        if remaining <= 0:
            break
        if not repertoire:
            continue
        affordable = {
            name: action for name, action in repertoire.items()
            if action.get("cost", 1) <= remaining
        }
        if not affordable:
            continue
        names = list(affordable.keys())
        weights = [affordable[n].get("weight", 1.0) for n in names]
        picked_name = choices(names, weights=weights, k=1)[0]
        picked_action = affordable[picked_name]
        selected.append((part, picked_name, picked_action))
        remaining -= picked_action.get("cost", 1)
    return selected


def _action_is_available(
    action: Dict, actor: "Creature", target: Optional["Creature"],
) -> bool:
    """Evaluate an entry's ``is_available(actor, target)`` callable.

    Phase 3+ action entries may carry conditional selectability; the
    callable returns truthy to include the entry in the pool. Entries
    without the callable are unconditionally available."""
    checker = action.get("is_available")
    if not callable(checker):
        return True
    try:
        return bool(checker(actor, target))
    except Exception:
        _log.warning(
            "is_available callable raised for %s on %s; skipping entry.",
            action.get("label") or "<unnamed>", type(actor).__name__,
            exc_info=True,
        )
        return False


def _resolve_action_dice(
    action: Dict, action_name: str, actor: "Creature",
) -> str:
    """Return the dice string for an action entry.

    Precedence: ``get_dice(actor, target=None)`` callable → explicit
    static ``dice`` field → size-scaled default per :mod:`body_parts.
    action_dice`. The size-scaled fallback keeps naked creatures
    working without a creature-level override for every action."""
    getter = action.get("get_dice")
    if callable(getter):
        try:
            dice = getter(actor, None)
            if dice:
                return dice
        except Exception:
            _log.warning(
                "get_dice callable raised for %s on %s; falling through.",
                action_name, type(actor).__name__,
                exc_info=True,
            )
    static = action.get("dice")
    if static:
        return static
    from caldanai.lib.rpg.creatures.body_parts.action_dice import (
        size_scaled_dice,
    )
    return size_scaled_dice(action_name, getattr(actor, "size", Size.MEDIUM))


def _resolve_action_narratives(
    action: Dict, actor: "Creature", target: Optional["Creature"],
) -> List[str]:
    """Return the narrative template list for an action entry.

    Precedence: ``get_narrative(actor, target)`` callable → static
    ``narrative`` list. Empty/missing in both yields an empty list —
    ``narrate_attempt`` then skips the assignment rather than
    emitting a silent blank line."""
    getter = action.get("get_narrative")
    if callable(getter):
        try:
            pool = getter(actor, target)
            if pool:
                return list(pool)
        except Exception:
            _log.warning(
                "get_narrative callable raised for %s on %s; skipping pool.",
                action.get("label") or "<unnamed>", type(actor).__name__,
                exc_info=True,
            )
            return []
    pool = action.get("narrative") or []
    return list(pool)


class _TargetPartContext:
    """Minimal ``result``-shaped carrier for :func:`parse`'s
    ``@Np_target`` token. Used by :meth:`Creature.narrate_attempt` to
    resolve the target-part display name without needing a real
    :class:`AttackResult` at the attempt-narrative stage."""

    __slots__ = ("target_part",)

    def __init__(self, target_part):
        self.target_part = target_part


def round_robin_assignment(
    actions: List[AttackSource],
    combatants: List["Creature"],
) -> List[Assignment]:
    """Distribute ``actions`` round-robin across ``combatants``.

    Exposed as a free helper so multi-target creatures (hydra today,
    future swarms / AoE magic) can call it from their own
    ``pick_targets`` override without re-implementing the loop.
    Shuffles the actions so which specific head acts on which victim
    is random, and wraps via modulo so N actions > M combatants
    spreads evenly instead of dogpiling the last slot."""
    if not actions or not combatants:
        return []
    shuffled = sample(list(actions), len(actions))
    out: List[Assignment] = []
    for i, source in enumerate(shuffled):
        victim = combatants[i % len(combatants)]
        out.append(Assignment(source=source, target=victim))
    return out
