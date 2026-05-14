"""Tests for ``$pray``'s d20 outcome branches.

Coverage focus:

- **Nat-20 full-party heal** — every injured player in the game gets
  the divine "made whole" treatment (was: single-target heal).
  Uninjured players are skipped (a "radiant column" line for someone
  at full HP would mean nothing).
- **Hidden 1d6 smite** — on a nat-20, a fresh 1d6 rolls under the
  hood. A 6 vaporizes every spawned monster via the canonical death
  pipeline. Any other result is silent: no narration, no ack, no
  log. Players discover the rate (1/120 prayers ≈ 0.83%) by
  observation. The mechanic is hidden by design — patch notes never
  mention it.
- **Regression pins** — the 17-19 single-target heal branch and the
  nat-1 sacrifice branch are unchanged.

Dice-mock pattern: ``Dice.d20()`` returns a real ``Dice`` instance
in production (the ``.value`` is read after ``__init__`` rolls).
We mock it with a stub object that exposes the same ``.value`` /
``.sides`` attributes so the call site reads back our chosen
roll. ``Dice.quick_roll`` is mocked separately for the d6 roll
so the d20 outcome and the d6 outcome can be controlled
independently.
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson.objectid import ObjectId

from caldanai.lib.cogs.rpg_user_commands import RpgUserCommands
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures.player import Player


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeDice:
    """Stub that mimics the read-back surface of a ``Dice`` roll
    without involving the RNG. Only ``.value`` and ``.sides`` are
    consumed by the pray callback."""

    def __init__(self, value: int, sides: int = 20):
        self.value = value
        self.sides = sides


def _make_player(
    name: str = "TestPlayer",
    health: int = 20,
    health_max: int = 20,
    uid: Optional[int] = None,
) -> Player:
    p = Player(
        pid=ObjectId(),
        gid=100,
        uid=uid if uid is not None else id(object()),
        health=health,
        health_max=health_max,
        defense=6,
        dodge=6,
        gender="male",
        pronouns="he,him,his,his,himself",
        weight_limit=100,
        clarks=50,
    )
    member = MagicMock()
    member.id = p.user_id
    member.display_name = name
    p.member = member
    p.name = name
    return p


def _make_monster(name: str = "goblin", health: int = 20) -> Creature:
    m = Creature(
        name=name,
        atk="1d4",
        defense=2,
        dodge=5,
        health_max=health,
        gender="female",
        pronouns="she,her,her,hers,herself",
    )
    m.health = health
    m.body_parts = [
        BodyPart(name="head", health_max=10),
        BodyPart(name="torso", health_max=20),
    ]
    # Provide stub death + flavor surface so on_monster_death / parse
    # don't blow up if the smite branch reaches them. Real plugins
    # populate these via class attributes; for the bare ``Creature``
    # used here we assign empty defaults.
    m.death = ""
    return m


def _make_game(
    monster: Optional[Creature],
    players: list[Player],
    combatants: Optional[list[Player]] = None,
):
    """Build a MagicMock ``Game`` with the surface ``pray`` reads:

    - ``game.monster`` (may be None)
    - ``game.player_manager.players`` — dict[user_id, Player]
    - ``game.combatants`` — list[Player]
    - ``game.channel`` — sink for ``Dispatcher.add``
    - ``game.on_monster_death`` — async, returns "" by default

    The smite branch calls ``await game.on_monster_death()``; we
    stub it as an ``AsyncMock`` so tests can both observe the call
    and avoid running the full death pipeline (corpse-scavenge,
    end_combat, set_spawn_timer) for unit-level coverage.
    """
    game = MagicMock()
    game.monster = monster
    game.combatants = list(combatants) if combatants else []
    game.channel = MagicMock()
    game.player_manager = MagicMock()
    game.player_manager.players = {p.user_id: p for p in players}
    game.on_monster_death = AsyncMock(return_value="")
    return game


def _make_ctx():
    ctx = MagicMock()
    ctx.guild = MagicMock()
    ctx.message = MagicMock()
    ctx.message.mentions = []
    return ctx


def _rpg_util_path():
    from caldanai.lib.rpg.helpers.utils import RpgUtilities
    return RpgUtilities


async def _invoke_pray(
    cog: RpgUserCommands,
    game,
    player: Player,
    d20_value: int,
    d6_value: int = 1,
):
    """Drive ``pray.callback`` under patched Dispatcher /
    RpgUtilities / Dice.

    ``d20_value`` controls the outer prayer roll. ``d6_value``
    controls the hidden smite roll on the nat-20 branch (ignored
    on other rolls — the production code only calls
    ``Dice.quick_roll('1d6')`` inside the d20==20 branch).
    """
    ctx = _make_ctx()

    # Track quick_roll calls so the test can assert d6 invocation
    # only fires on nat-20.
    quick_calls: list[str] = []

    def _quick_roll(spec: str, keep=None):
        quick_calls.append(spec)
        if spec == "1d6":
            return d6_value
        # 17-19 branch uses ``1d{quarter}`` / ``1d{missing}`` shapes;
        # return 1 deterministically so the heal-amount path is
        # reproducible without depending on a real RNG.
        return 1

    with (
        patch.object(
            _rpg_util_path(),
            "get_game_and_player",
            new=AsyncMock(return_value=(game, player)),
        ),
        patch("caldanai.lib.cogs.rpg_user_commands.Dispatcher") as dispatcher,
        patch(
            "caldanai.lib.cogs.rpg_user_commands.Dice.d20",
            return_value=_FakeDice(d20_value, sides=20),
        ),
        patch(
            "caldanai.lib.cogs.rpg_user_commands.Dice.quick_roll",
            side_effect=_quick_roll,
        ),
    ):
        await cog.pray.callback(cog, ctx)
        game._dispatcher = dispatcher
        game._quick_calls = quick_calls


def _dispatched_strings(dispatcher_mock) -> list[str]:
    sent = []
    for call in dispatcher_mock.add.call_args_list:
        for arg in call.args[1:]:
            if isinstance(arg, str):
                sent.append(arg)
        for value in call.kwargs.values():
            if isinstance(value, str):
                sent.append(value)
    return sent


def _cog() -> RpgUserCommands:
    return RpgUserCommands(bot=MagicMock())


# ---------------------------------------------------------------------------
# Nat-20 full-party heal
# ---------------------------------------------------------------------------


class TestNat20FullPartyHeal:
    """A nat-20 prayer heals EVERY injured player in the game, not
    just the most-injured. The closing "radiant column" beat
    consolidates onto ONE line listing the healed party — N=1 bare
    name, N=2 "X and Y", N>=3 "the whole party" (genericized;
    spelling out four-plus names would overstuff the line)."""

    @pytest.mark.asyncio
    async def test_all_injured_players_made_whole(self):
        cog = _cog()
        alice = _make_player("Alice", health=5, health_max=20, uid=1)
        bob = _make_player("Bob", health=8, health_max=20, uid=2)
        charlie = _make_player("Charlie", health=20, health_max=20, uid=3)
        game = _make_game(monster=None, players=[alice, bob, charlie])

        await _invoke_pray(cog, game, alice, d20_value=20, d6_value=1)

        # Each injured player is at full HP after the heal.
        assert alice.health == alice.get_health_max()
        assert bob.health == bob.get_health_max()
        # Charlie was already full HP — unchanged either way.
        assert charlie.health == charlie.get_health_max()

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        # ONE consolidated radiant-column line names Alice and Bob.
        assert sent.count("radiant column of light") == 1
        assert "engulfs Alice and Bob" in sent
        # Charlie was uninjured — must not appear in the heal line.
        assert "Charlie" not in sent.split("radiant column of light")[1]

    @pytest.mark.asyncio
    async def test_uninjured_players_skipped(self):
        """Players already at full HP and full parts should NOT
        receive a "made whole" line — meaningless for someone with
        no wounds."""
        cog = _cog()
        alice = _make_player("Alice", health=5, health_max=20, uid=1)
        bob = _make_player("Bob", health=20, health_max=20, uid=2)
        game = _make_game(monster=None, players=[alice, bob])

        await _invoke_pray(cog, game, alice, d20_value=20, d6_value=1)

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        # Exactly one heal line — Alice. Bob is uninjured, no line.
        assert sent.count("radiant column of light") == 1
        # Bob's name doesn't appear in the heal narration.
        assert "Bob" not in sent

    @pytest.mark.asyncio
    async def test_solo_praying_player_still_heals_self(self):
        """No other injured players? The praying player still gets
        their own injuries fixed if they have any."""
        cog = _cog()
        alice = _make_player("Alice", health=5, health_max=20, uid=1)
        game = _make_game(monster=None, players=[alice])

        await _invoke_pray(cog, game, alice, d20_value=20, d6_value=1)

        assert alice.health == alice.get_health_max()
        sent = "\n".join(_dispatched_strings(game._dispatcher))
        assert sent.count("radiant column of light") == 1

    @pytest.mark.asyncio
    async def test_single_healed_uses_bare_name(self):
        """N=1 form: 'engulfs <name>'; no 'and', no 'the whole
        party'."""
        cog = _cog()
        alice = _make_player("Alice", health=5, health_max=20, uid=1)
        game = _make_game(monster=None, players=[alice])

        await _invoke_pray(cog, game, alice, d20_value=20, d6_value=1)

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        assert "A radiant column of light engulfs Alice;" in sent
        assert " and " not in sent.split("radiant column of light")[1].split(";")[0]
        assert "the whole party" not in sent

    @pytest.mark.asyncio
    async def test_two_healed_uses_and(self):
        """N=2 form: 'engulfs X and Y'; no Oxford comma needed at
        this length."""
        cog = _cog()
        alice = _make_player("Alice", health=5, health_max=20, uid=1)
        bob = _make_player("Bob", health=8, health_max=20, uid=2)
        game = _make_game(monster=None, players=[alice, bob])

        await _invoke_pray(cog, game, alice, d20_value=20, d6_value=1)

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        assert "engulfs Alice and Bob;" in sent
        # No Oxford comma at N=2 — that form starts at N>=3, and the
        # fallback at N>=3 swaps in 'the whole party' anyway.
        assert ", and Bob" not in sent
        assert "the whole party" not in sent

    @pytest.mark.asyncio
    async def test_three_or_more_healed_genericizes_to_party(self):
        """N>=3 fallback: 'engulfs the whole party'. Listing four
        names spelled out would overstuff the line; the generic
        form keeps the beat short at scale."""
        cog = _cog()
        alice = _make_player("Alice", health=5, health_max=20, uid=1)
        bob = _make_player("Bob", health=8, health_max=20, uid=2)
        charlie = _make_player("Charlie", health=12, health_max=20, uid=3)
        game = _make_game(monster=None, players=[alice, bob, charlie])

        await _invoke_pray(cog, game, alice, d20_value=20, d6_value=1)

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        assert "engulfs the whole party;" in sent
        # Individual names must NOT appear in the consolidated line.
        heal_line = sent.split("radiant column of light")[1].split(";")[0]
        for needle in ("Alice", "Bob", "Charlie"):
            assert needle not in heal_line

    @pytest.mark.asyncio
    async def test_part_injuries_count_as_injured(self):
        """A player at full body HP with a destroyed part is still
        ``is_injured()`` and therefore eligible for the heal."""
        cog = _cog()
        alice = _make_player("Alice", health=20, health_max=20, uid=1)
        # Give Alice a body part and damage it.
        alice.body_parts = [BodyPart(name="arm.left", health_max=10)]
        alice.body_parts[0].health = 0
        game = _make_game(monster=None, players=[alice])

        await _invoke_pray(cog, game, alice, d20_value=20, d6_value=1)

        assert alice.body_parts[0].health == alice.body_parts[0].health_max


# ---------------------------------------------------------------------------
# Hidden 1d6 smite
# ---------------------------------------------------------------------------


class TestNat20HiddenSmite:
    """A nat-20 rolls a hidden 1d6 — a 6 smites every spawned monster
    via the canonical damage path. Anything else is dead-silent."""

    @pytest.mark.asyncio
    async def test_d6_six_kills_monster(self):
        cog = _cog()
        alice = _make_player("Alice", health=5, health_max=20, uid=1)
        monster = _make_monster("goblin", health=20)
        game = _make_game(monster=monster, players=[alice])

        await _invoke_pray(cog, game, alice, d20_value=20, d6_value=6)

        assert monster.health == 0
        assert monster.is_dead()
        # Death pipeline fired.
        game.on_monster_death.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_d6_six_smite_narration_present(self):
        cog = _cog()
        alice = _make_player("Alice", health=5, health_max=20, uid=1)
        monster = _make_monster("goblin", health=20)
        game = _make_game(monster=monster, players=[alice])

        await _invoke_pray(cog, game, alice, d20_value=20, d6_value=6)

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        # Smite flavor pool's shared vocabulary: storm / lightning /
        # ash / cinders / ozone. At least one of these markers must
        # appear when the smite fires.
        markers = [
            "lightning",
            "ash drifts",
            "cinders",
            "ozone",
            "divine wrath",
            "Holy fire",
            "radiant lightning",
            "thunder",
        ]
        assert any(m in sent for m in markers), (
            f"Expected smite flavor marker in dispatch:\n{sent}"
        )

    @pytest.mark.asyncio
    async def test_d6_non_six_no_smite(self):
        """A d6 of 5 (or 1, 2, 3, 4) leaves the monster untouched
        and emits NO smite-related narration."""
        cog = _cog()
        alice = _make_player("Alice", health=5, health_max=20, uid=1)
        monster = _make_monster("goblin", health=20)
        game = _make_game(monster=monster, players=[alice])

        await _invoke_pray(cog, game, alice, d20_value=20, d6_value=5)

        assert monster.health == 20  # Untouched
        assert not monster.is_dead()
        game.on_monster_death.assert_not_awaited()

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        # No d6 reference, no smite flavor. The dispatch must read
        # exactly like a normal nat-20 heal — nothing telegraphs the
        # roll's existence.
        forbidden = [
            "lightning",
            "ash drifts",
            "cinders",
            "ozone",
            "divine wrath",
            "Holy fire",
            "radiant lightning",
            "thunder",
            "smite",
            "1d6",
        ]
        for needle in forbidden:
            assert needle not in sent, (
                f"Smite hint leaked on non-6 d6 roll: '{needle}' in:\n{sent}"
            )

    @pytest.mark.asyncio
    async def test_d6_six_no_monster_no_crash(self):
        """A nat-20 + d6=6 with no spawned monster must not crash and
        must not emit smite narration. The heal still runs."""
        cog = _cog()
        alice = _make_player("Alice", health=5, health_max=20, uid=1)
        game = _make_game(monster=None, players=[alice])

        await _invoke_pray(cog, game, alice, d20_value=20, d6_value=6)

        assert alice.health == alice.get_health_max()
        sent = "\n".join(_dispatched_strings(game._dispatcher))
        # Heal narration present.
        assert "radiant column of light" in sent
        # Smite flavor absent.
        for needle in ("lightning", "cinders", "ash drifts", "Holy fire"):
            assert needle not in sent

    @pytest.mark.asyncio
    async def test_d6_only_rolled_on_nat_20(self):
        """The hidden d6 is gated on d20==20. Other prayer outcomes
        (17-19, nat-1, mid-roll) must NOT roll a 1d6."""
        cog = _cog()
        alice = _make_player("Alice", health=5, health_max=20, uid=1)
        monster = _make_monster("goblin", health=20)

        # Nat-19 — uses 17-19 branch's 1d{quarter} quick_roll, NOT 1d6.
        game = _make_game(monster=monster, players=[alice])
        await _invoke_pray(cog, game, alice, d20_value=19, d6_value=6)
        assert "1d6" not in game._quick_calls
        assert monster.health == 20  # Smite did not fire

        # Nat-1 — sacrifice branch, no 1d6 roll.
        alice2 = _make_player("Alice", health=5, health_max=20, uid=1)
        monster2 = _make_monster("goblin", health=20)
        game2 = _make_game(monster=monster2, players=[alice2])
        await _invoke_pray(cog, game2, alice2, d20_value=1, d6_value=6)
        assert "1d6" not in game2._quick_calls
        assert monster2.health == 20

        # Mid-roll (e.g. 10) — no branch fires, no 1d6.
        alice3 = _make_player("Alice", health=5, health_max=20, uid=1)
        monster3 = _make_monster("goblin", health=20)
        game3 = _make_game(monster=monster3, players=[alice3])
        await _invoke_pray(cog, game3, alice3, d20_value=10, d6_value=6)
        assert "1d6" not in game3._quick_calls
        assert monster3.health == 20


# ---------------------------------------------------------------------------
# 17-19 regression pin
# ---------------------------------------------------------------------------


class TestNat17To19SingleTargetUnchanged:
    """The 17-19 branch is unchanged: pick the most-injured player,
    apply a partial body heal + restore one worst-injured part."""

    @pytest.mark.asyncio
    async def test_only_most_injured_player_healed(self):
        """With Alice at 5/20 and Bob at 10/20, only Alice should
        be healed on a 17-19 roll. Bob stays untouched — this is
        the single-target triage branch."""
        cog = _cog()
        alice = _make_player("Alice", health=5, health_max=20, uid=1)
        bob = _make_player("Bob", health=10, health_max=20, uid=2)
        game = _make_game(monster=None, players=[alice, bob])

        await _invoke_pray(cog, game, alice, d20_value=18, d6_value=1)

        # Alice (more injured) gets the heal — partial, not full.
        # Exact heal amount depends on the dice formula; assert
        # health > 5 (some heal happened) and Bob is untouched.
        assert alice.health > 5
        assert bob.health == 10

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        # 17-19 narration: "warm light suffuses" — distinct from
        # the nat-20 "radiant column".
        assert "warm light suffuses" in sent
        assert "radiant column of light" not in sent


class TestNat17To19RescueAndDistribute:
    """Pins the 2026-05-01 rewrite: free critical-part rescue + body
    spark, then a rolled buffer distributed 2:1 part:body, with
    honest reporting of HP that actually landed (not the intent).

    Locks in the contract behind the doppy-cyclops live-playtest bug
    chain: ``is_dead`` was a mutator that nuked mid-heal HP deltas;
    pray d20=17-19 was reporting a heal that didn't fully revive
    despite narrating "imbuing them with N points of health."
    """

    @pytest.mark.asyncio
    async def test_destroyed_critical_part_revives_with_gasping_tail(self):
        """Caels prays for fallen Alice — she's dead from critical-
        part destruction (head at 0/15, body HP at 0). Pray d20=17+
        should rescue the head to 1 HP, spark the body to 1 HP, and
        fire the resurrection narration tail through ``apply_damage``
        so Alice visibly comes back. Without the rescue-then-spark
        order the tail is suppressed because ``is_dead`` returns
        True throughout the body-heal call."""
        cog = _cog()
        caels = _make_player("Caels", health=20, health_max=20, uid=1)
        alice = _make_player("Alice", health=0, health_max=20, uid=2)
        # Critical-destroyed head, otherwise is_dead won't detect
        # critical-part death.
        head = BodyPart(name="head", health_max=15)
        head.is_critical = True
        head.health = 0
        torso = BodyPart(name="torso", health_max=30)
        torso.is_critical = True
        alice.body_parts = [head, torso]
        game = _make_game(monster=None, players=[caels, alice])

        await _invoke_pray(cog, game, caels, d20_value=17, d6_value=1)

        # Rescue: head off zero, body off zero, alive.
        assert head.health >= 1
        assert alice.health >= 1
        assert not alice.is_dead()

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        assert "gasps raggedly" in sent
        assert "warm light suffuses" in sent

    @pytest.mark.asyncio
    async def test_body_full_but_part_injured_reports_honest_amount(self):
        """Caels prays for Alice. Alice's body HP is at max but a
        part is injured. The 2:1 distribute directs body_budget at
        a full body — ``apply_damage`` clamps to max and the body-
        side absorbs nothing. The narration must reflect what
        actually landed (parts only), not the intended budget.
        Pre-fix, ``body_to_apply`` was reported as ``body_applied``
        and the message over-stated the heal magnitude."""
        cog = _cog()
        caels = _make_player("Caels", health=20, health_max=20, uid=1)
        alice = _make_player("Alice", health=20, health_max=20, uid=2)
        # One injured non-critical part with enough missing HP to
        # produce a meaningful budget at d20=19 (quarter ramp +
        # 2*quarter bonus).
        leg = BodyPart(name="left leg", health_max=20)
        leg.health = 4  # 16 HP missing
        alice.body_parts = [leg]
        game = _make_game(monster=None, players=[caels, alice])

        await _invoke_pray(cog, game, caels, d20_value=19, d6_value=1)

        # Body HP must remain at max (clamped). Leg gets some heal.
        assert alice.health == 20
        assert leg.health > 4

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        # Pull the "imbuing them with N points" line and parse N.
        # The reported number must equal the actual leg-HP delta —
        # not body+parts intent.
        import re
        match = re.search(r"imbuing .+? with (\d+) points? of health", sent)
        assert match, f"Expected imbuing-N narration, got: {sent}"
        reported = int(match.group(1))
        actual_leg_delta = leg.health - 4
        # Reported should be exactly the leg delta (body absorbed
        # zero, no rescue happened, no spark since alive).
        assert reported == actual_leg_delta, (
            f"Reported {reported} HP but only {actual_leg_delta} landed"
        )

    @pytest.mark.asyncio
    async def test_rescue_lifts_non_critical_ancestor_without_overwriting_critical(self):
        """Caels-2026-05-01 incident: neck (non-critical) is destroyed,
        cascade-destroying head (critical, but own HP intact). Pre-fix
        ``divine_rescue`` walked critical-AND-is-destroyed parts and
        OVERWROTE head's intact HP to 1 because ``is_destroyed`` cascades
        through ancestors. Post-fix: own-zero check skips intact head,
        ancestor-of-critical walk catches neck for rescue."""
        cog = _cog()
        caels = _make_player("Caels", health=20, health_max=20, uid=1)
        alice = _make_player("Alice", health=5, health_max=20, uid=2)

        # Real BodyPart objects with parent/child wiring so ``ancestors()``
        # walks correctly. MagicMocks don't expose the tree topology.
        torso = BodyPart(name="torso", health_max=30)
        torso.is_critical = True
        torso.health = 5  # alive but injured
        neck = BodyPart(name="neck", health_max=8)
        neck.is_critical = False  # matches production neck.py
        neck.health = 0  # destroyed
        torso.add_child(neck)
        head = BodyPart(name="head", health_max=15)
        head.is_critical = True
        head.health = 15  # FULL HP — must not be overwritten
        neck.add_child(head)
        alice.body_parts = [torso, neck, head]

        game = _make_game(monster=None, players=[caels, alice])

        await _invoke_pray(cog, game, caels, d20_value=17, d6_value=1)

        # Head's intact HP must NOT be overwritten by the rescue.
        assert head.health == 15
        # Neck (non-critical, ancestor of critical head) must be rescued.
        assert neck.health >= 1
        # Alice should now read alive — body still > 0 (wasn't 0),
        # head intact, neck rescued, no cascade-destroyed criticals.
        assert not alice.is_dead()

    @pytest.mark.asyncio
    async def test_uninjured_target_fires_tingle_branch(self):
        """Edge case: ``is_injured`` filter lands on the praying
        player as fallback (`or [player]` in the candidate list)
        when no one is actually injured. With ``total_missing == 0``,
        the rolled budget is zero and the narration falls through
        to the "pleasant tingle" branch instead of "imbuing"."""
        cog = _cog()
        alice = _make_player("Alice", health=20, health_max=20, uid=1)
        # All parts at full HP. ``is_injured`` returns False, so the
        # candidates list is empty and falls back to ``[alice]``.
        leg = BodyPart(name="left leg", health_max=12)
        leg.health = 12
        alice.body_parts = [leg]
        game = _make_game(monster=None, players=[alice])

        await _invoke_pray(cog, game, alice, d20_value=18, d6_value=1)

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        assert "warm light suffuses" in sent
        assert "pleasant tingle" in sent
        assert "imbuing" not in sent


# ---------------------------------------------------------------------------
# Nat-1 regression pin
# ---------------------------------------------------------------------------


class TestNat1SacrificeSingleTargetRain:
    """Nat-1 sacrifices the praying player and rains a full heal on
    the SINGLE most-injured ally (not the praying player). The pre-
    smite-era full-party rain was retired when nat-20 took over the
    party-wide sweep — nat-1's rain is back to single-target so the
    "I died for you, comrade" narrative beat stays singular."""

    @pytest.mark.asyncio
    async def test_praying_player_dies_one_ally_healed(self):
        cog = _cog()
        alice = _make_player("Alice", health=20, health_max=20, uid=1)
        bob = _make_player("Bob", health=5, health_max=20, uid=2)
        game = _make_game(monster=None, players=[alice, bob])

        await _invoke_pray(cog, game, alice, d20_value=1, d6_value=6)

        # Alice was struck down by lightning.
        assert alice.health == 0
        # Bob (only injured ally) was healed by the rain.
        assert bob.health == bob.get_health_max()

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        assert "Sacrifice is demanded" in sent
        # Charred-husk flavor — distinct from the smite branch's
        # "ash drifts" / "cinders" lines, but uses some shared
        # storm vocabulary. The presence of "Sacrifice is demanded"
        # is the unambiguous tell that this is the nat-1 branch.

    @pytest.mark.asyncio
    async def test_only_weakest_ally_healed_when_multiple_injured(self):
        """With Bob at 5/20 and Carol at 10/20 (both injured non-
        praying allies), only Bob (weakest) should be healed. Carol
        stays at her current HP — single-target rain, not a sweep."""
        cog = _cog()
        alice = _make_player("Alice", health=20, health_max=20, uid=1)
        bob = _make_player("Bob", health=5, health_max=20, uid=2)
        carol = _make_player("Carol", health=10, health_max=20, uid=3)
        game = _make_game(monster=None, players=[alice, bob, carol])

        await _invoke_pray(cog, game, alice, d20_value=1, d6_value=6)

        assert alice.health == 0
        # Bob is the weakest non-praying ally — fully healed.
        assert bob.health == bob.get_health_max()
        # Carol stays at her pre-rain HP — not the weakest, no heal.
        assert carol.health == 10

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        # Exactly ONE "made whole" line — Bob's. Carol gets nothing.
        assert sent.count("is made whole!") == 1

    @pytest.mark.asyncio
    async def test_no_injured_allies_storm_fires_but_no_rain_heal(self):
        """When the praying player is the only injured one (or only
        player), the storm still kills them but no rain heal
        narration appears — there's no candidate."""
        cog = _cog()
        alice = _make_player("Alice", health=20, health_max=20, uid=1)
        bob = _make_player("Bob", health=20, health_max=20, uid=2)
        game = _make_game(monster=None, players=[alice, bob])

        await _invoke_pray(cog, game, alice, d20_value=1, d6_value=6)

        assert alice.health == 0
        # Bob untouched — already at full HP, not a candidate.
        assert bob.health == bob.get_health_max()

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        # Storm sacrifice + rain calm narration — no "made whole"
        # line because no one was eligible.
        assert "Sacrifice is demanded" in sent
        assert "is made whole!" not in sent


class TestNat17To19SmallInjuryQuarterOne:
    """Regression: 2026-05-02 live crash. Caels at 19/21 with a few
    bruised parts, $pray rolled into the 17-19 branch, the heal
    target's injury surface was small enough that
    ``ceil(surface/4) == 1``, and ``Dice.quick_roll('1d1')`` returned
    ``None`` (``Dice.from_ndn`` rejects ``sides < 2``). The
    subsequent ``None + int`` arithmetic crashed the entire prayer
    with a ``TypeError`` and no narration reached the channel.

    The heal-amount path now shortcuts ``quarter <= 1`` to ``1``
    (the only value a 1d1 could roll), matching the same defense
    used by ``_q7_absorbed_dn`` in ``creatures/__init__.py``."""

    @pytest.mark.asyncio
    async def test_small_injury_completes_without_crash(self):
        # Light injury: 1 HP body gap (under the surface/4 ≤ 1
        # threshold once part gaps are zero). Should not crash.
        cog = _cog()
        alice = _make_player("Alice", health=20, health_max=21, uid=1)
        game = _make_game(monster=None, players=[alice])

        # Patch only Dice.d20 (to control the branch); leave
        # quick_roll UNPATCHED so the real ``1d1`` → None path
        # is exercised. If the shortcut isn't in place, this test
        # crashes with the original TypeError.
        with (
            patch.object(
                _rpg_util_path(),
                "get_game_and_player",
                new=AsyncMock(return_value=(game, alice)),
            ),
            patch("caldanai.lib.cogs.rpg_user_commands.Dispatcher"),
            patch(
                "caldanai.lib.cogs.rpg_user_commands.Dice.d20",
                return_value=_FakeDice(18, sides=20),
            ),
        ):
            ctx = _make_ctx()
            # Should complete without raising.
            await cog.pray.callback(cog, ctx)

        # Heal landed (some HP recovered).
        assert alice.health > 20
