"""Wagoneer passerby — a working traveler who passes through the
clearing on the rutted track.

Voice register: grounded, working-class, specific physical detail.
Carries cargo. Knows the road. Doesn't make a fuss but notices
things. Leans on a wagon-pole when stopped. Doesn't reference
Mendholm by name (Caels' direction: not every passerby names the
world; the wagoneer reads it functionally).

Parser tokens: ``@1`` = the wagoneer (uses_article=True so
``@1d`` → "the wagoneer"); ``@2`` = a referenced party member
where applicable (combat-witness reactions, social reactions
where ``@1`` swaps to the player). Per the existing convention,
``@1`` is the actor and ``@2`` is the target — so social-reaction
pools (``$wave``, ``$nod``, ``$greet``) use ``@1`` = the
player who initiated, and the wagoneer is referenced inline as
"the wagoneer" by name rather than tokenized.
"""
from typing import Dict, List

from caldanai.lib.rpg.creatures.passersby import PasserbyPlugin
from caldanai.lib.rpg.helpers.enums import TimePartitions
from caldanai.lib.rpg.helpers.warmth import Warmth


class Wagoneer(PasserbyPlugin):
    name = "wagoneer"
    uses_article = True
    gender = "male"
    pronouns = "he,him,his,his,himself"
    ALIASES = ["wagon driver", "wagoner", "carter"]

    # Wagoneers travel on the road — daylight hours plus a sliver
    # of evening for "rolling through before sundown." Doesn't
    # cart at night.
    time_partition = TimePartitions.DIURNAL

    # Functional, road-friendly. Wagoneers acknowledge people by
    # name — it's good business and good road manners. When he
    # doesn't, he's busy; the bias is high but not absolute.
    NAMING_BIAS = 0.85

    # ARRIVAL — quiet window, no combat. The wagoneer rolls up the
    # track with cargo and decides he can spare a moment.
    ARRIVAL_POOL: List[str] = [
        "A wagoneer rolls his cart up the rutted track, wheels singing on stones the rain has bared.",
        "An old wagoneer leads a tired horse into the clearing's edge, eyes the sky, and decides he can spare a moment.",
        "Cart-wheels announce themselves long before @1d does. @1S pulls up at the verge, leans on his pole, and looks around like he's counting.",
        "@1Np cart trundles into view, axle protesting. He hops down stiffly, knuckles the small of his back, and surveys the clearing.",
        "A horse plods into the clearing first; the cart follows; the wagoneer comes last, on foot, talking to the horse about a hill they've just survived.",
        "A weather-darkened wagoneer rolls in from the south road, a tarp lashed over barrels and a face like he's seen worse weather coming.",
        "@1D pulls up his team beside a likely patch of grass, sets the brake, and rolls his shoulders one at a time. The horse takes the hint and crops.",
        "Cartwheels grind to a halt at the clearing's verge. @1D doesn't unhitch — just stands beside his lead barrel and listens for a long moment.",
        "An older wagoneer arrives at a careful walking pace, his cart loaded heavy with rope-tied bundles. @1S nods to the clearing as if it owed him the courtesy.",
        "The track delivers a wagoneer the way it always does — slow, dusty, inevitable. @1S settles in like he's done this a thousand times.",
    ]

    # AMBIENT — fires periodically while the wagoneer is present.
    # Atmospheric beats; the NPC noticed in the corner of the eye.
    AMBIENT_POOL: List[str] = [
        "@1D fusses with a strap on the lead barrel, frowning at a knot only he can see.",
        "@1D scratches his horse's ear, murmurs something the horse seems to agree with.",
        "@1D pulls a heel of dark bread from his coat, chews it slowly, watching the treeline.",
        "@1D squats to inspect a wagon-wheel, runs a calloused thumb along the rim, decides it'll hold another mile.",
        "@1D rolls a cigarette one-handed, lights it off a flint-strike, exhales toward the sky like he's reporting in.",
        "@1D thumps the side of a barrel, listens to the sound it makes, nods once like he's confirmed something.",
    ]

    # DEPARTURE — wagoneer leaves of his own accord, cart back on
    # the road.
    DEPARTURE_POOL: List[str] = [
        "@1D clucks to his horse, gives the clearing one last unhurried look, and starts the cart back down the track.",
        "@1D shoulders his pole, gathers the reins, and rolls on. The cart-song fades into the trees.",
        "@1D pulls up his collar, nods to no one in particular, and is gone before the stones stop singing under his wheels.",
        "Cart, horse, and man assemble themselves with practiced unhurriedness, and the road takes @1d back the way he came.",
        "@1D flicks his pole loose, calls something soft to the horse, and the cart eases forward into a slow plod.",
        "@1D swings up onto the buckboard with a creak — the cart's, not his — and the road resumes around him.",
    ]

    # SILHOUETTE — fires when arrival timer hits during active
    # combat. The wagoneer doesn't approach; he watches from
    # distance until the fight resolves.
    SILHOUETTE_POOL: List[str] = [
        "On the far ridge, a wagoneer pulls his cart to the verge, sets the brake, and watches with a steady, weighed-out patience.",
        "A wagoneer's silhouette crests the rise. @1S doesn't come closer. @1S has work; he can wait.",
        "Cart-wheels stop somewhere up the track. A figure leans on a pole, distant, watching.",
        "Up at the clearing's edge, a wagoneer reins in his team and steadies them with a hand. @1S is content to wait the noise out.",
        "A wagoneer eyes the commotion from the ridgeline, makes the practical choice, and parks his cart out of arrow-range.",
    ]

    # COMBAT_WON — the wagoneer approaches after the party kills
    # the monster. ``@1`` = wagoneer; ``@2`` = a representative
    # party member (the killing-blow dealer or random survivor).
    COMBAT_WON_REACTIONS: List[str] = [
        "@1D ambles down the track when the dust settles. He gives @2 a look that says good work, then asks if anyone needs water from the barrel.",
        "@1D waits until the last echo's gone before unbraking. \"Wasn't sure for a moment there,\" he says, settling his cart at the verge. \"Glad I waited to roll on through.\"",
        "@1D rolls in unhurried, surveys the carcass, lets out a low whistle. \"Bigger than I'd've guessed from up the road. You earned the road being a little quieter tonight.\"",
        "@1D pulls his team up beside @2, claps a hand on @2np shoulder once, says, \"That's a debt the road owes you,\" and means it the way wagoneers mean it — flat and complete.",
        "@1D steps down, walks a slow circle around the kill, kicks one boot against a stone, and looks back up at @2. \"Hells of a thing. Glad you held the line.\"",
        "@1D sets the brake, pulls a corked bottle from a saddlebag, and offers it to whoever looks worst. \"For the shake,\" he says. \"It'll come; might as well meet it ready.\"",
    ]

    # COMBAT_FLED — monster escaped before dying. Wagoneer
    # approaches to acknowledge the close call.
    COMBAT_FLED_REACTIONS: List[str] = [
        "@1D rolls in once the air's clear. \"That was close,\" he says, eyeing the trampled grass. \"Glad I held the team back. Glad you held your ground.\"",
        "@1D nods toward the path the creature took. \"I'll keep an ear out for that one. Pass the warning along the road.\"",
        "@1D arrives at his unhurried pace, takes in the wreck of churned earth, and lets out a slow breath. \"Stayed standing. That counts.\"",
        "\"Sometimes they walk off,\" @1d says, more to himself than anyone, settling his cart. \"And sometimes you let them. No shame in either.\"",
        "@1D surveys the damage, gives @2 a long look, and says, \"You held what could be held. Anyone tells you different's never had to.\"",
    ]

    # PARTY_DEATH — at least one party member died in the fight.
    # Wagoneer arrives quieter than usual, hat off, words careful.
    # ``@2`` = the fallen.
    PARTY_DEATH_REACTIONS: List[str] = [
        "@1D arrives without his usual rumble, having heard the silence too long. He removes his hat, holds it at his side. \"The dirt mends,\" he says quiet. \"I'll be down this road again. Maybe by then.\"",
        "@1D kneels by @2, hat in hand. \"Long road behind, longer ahead. You'll see them again.\"",
        "@1D ties his team off and walks the last stretch on foot, like the cart owes the moment that respect. He stands a while at @2np side without speaking.",
        "@1D pulls a small flask from inside his coat, uncorks it, lets a careful pour soak into the dirt by @2. \"Road tax,\" he says. \"For safe passage.\"",
        "@1D settles his hat back on slowly. \"I'll remember the face,\" he tells the rest of the party. \"Next time I roll through, I'll ask after them.\" He means it.",
    ]

    # SOCIAL_REACTIONS — warmth-keyed responses to player verbs.
    # ``@1`` = the actor (player); ``@2`` = the wagoneer. Reactions
    # describe the wagoneer's response to the actor's gesture.
    # Acceptance is NPC-toward-actor warmth, looked up from
    # MongoDB before the spawn-pipeline picks the pool.
    SOCIAL_REACTIONS: Dict[str, Dict[Warmth, List[str]]] = {
        "wave": {
            Warmth.HOT: [
                "@2D breaks into a grin and waves both arms back, hat held high. \"@1! Long ride to find this corner today.\"",
                "@2Np whole face crinkles into a laugh. \"@1d!\" he calls, sweeping his hat in a broad arc. \"Tell me you've got a story for me.\"",
                "@2D drops the reins entirely, waves both hands like he's flagging a ship in. \"There you are! Road's been dull without you on it.\"",
            ],
            Warmth.WARM: [
                "@2D waves back with a knowing smile, the way old friends do.",
                "@2D tips his hat and grins. \"@1d. Knew you'd be around here somewhere.\"",
                "@2D raises a calloused hand, smile lined deep. \"Well met, @1.\"",
            ],
            Warmth.NEUTRAL: [
                "@2D raises a hand in return, polite but unhurried.",
                "@2D nods his head and lifts a finger off the wagon-pole — half wave, half acknowledgement.",
                "@2D returns a brief wave, eyes already drifting back to his cart.",
            ],
            Warmth.COOL: [
                "@2D nods minimally, hands staying on his cart.",
                "@2D glances over, gives the smallest possible inclination of his head, and goes back to his work.",
                "@2Np eyes meet @1d for a beat. He doesn't wave back.",
            ],
            Warmth.COLD: [
                "@2Np eyes flick to @1np hands, then away. He doesn't return the wave.",
                "@2D turns deliberately, makes a show of busying himself with a barrel-strap, doesn't look up.",
                "@2D tightens his grip on the wagon-pole and pretends he didn't see.",
            ],
        },
        "nod": {
            Warmth.HOT: [
                "@2D nods back twice, deliberate and warm, then taps his hat brim with two fingers — kin's salute on the road.",
                "@2D returns the nod and adds a small smile that crinkles old laugh-lines into place.",
                "@2D dips his hat in return, like saluting a passing king he likes.",
            ],
            Warmth.WARM: [
                "@2D returns the nod, slow and considered, the way wagoneers do when they mean it.",
                "@2D nods back, holds the look a beat longer than he needs to. Friendship's been declared without a word.",
                "@2D dips his head once. \"Aye,\" he says, like it's a whole sentence.",
            ],
            Warmth.NEUTRAL: [
                "@2D returns the nod — short, road-polite, no more.",
                "@2D nods, neither warm nor cool, and turns back to his horse.",
                "@2Np chin dips once in acknowledgement.",
            ],
            Warmth.COOL: [
                "@2D barely moves — perhaps a nod, perhaps just adjusting his hat.",
                "@2D glances over without quite nodding, then back at his cart.",
                "@2D tips his head a fraction. It might be a nod. It might be the wind.",
            ],
            Warmth.COLD: [
                "@2D doesn't nod back. He looks past @1d like @1s isn't there.",
                "@2D fixes his eyes on the horizon and stays still.",
                "@2Np jaw sets. He doesn't acknowledge the gesture at all.",
            ],
        },
        "greet": {
            Warmth.HOT: [
                "\"@1d!\" @2d calls, beaming. \"Pull up a stone, you're staying — I'll get the kettle going.\"",
                "@2D laughs, claps his hands once. \"Now THIS is a clearing worth stopping at. @1d, sit. Sit.\"",
                "\"Hells, @1!\" @2d says, throwing his hat onto the buckboard. \"Tell me you've got an hour. I've got bread.\"",
            ],
            Warmth.WARM: [
                "@2D nods deeply. \"Hello, @1. Glad to see you on this road.\"",
                "\"@1d. Been a while.\" @2D smiles, settles back against his cart, ready to hear how it's been.",
                "@2D extends a calloused hand. \"@1. Well met. Anything I can spare from the cart, you ask.\"",
            ],
            Warmth.NEUTRAL: [
                "@2D touches the brim of his hat. \"Traveler.\"",
                "\"Evening,\" @2d says, with the polite economy of someone who's said it a thousand times.",
                "@2D nods. \"Hello to you. Road's clear north, far as I came.\"",
            ],
            Warmth.COOL: [
                "@2D grunts something that might have been hello.",
                "\"Hm,\" @2d says, without looking up from his strap.",
                "@2D acknowledges @1d with the smallest possible word: \"Aye.\"",
            ],
            Warmth.COLD: [
                "@2D doesn't return the greeting. He turns his back and busies himself with the cart.",
                "@2D lets the silence answer for him. The barrel he's checking suddenly needs a great deal of attention.",
                "\"I'm working,\" @2d says flatly, and leaves it there.",
            ],
        },
        "thank": {
            Warmth.HOT: [
                "@2D laughs and waves both hands. \"Hells, @1, sit down. Sit. You thank me by sharing a heel of bread and telling me what's south of here. That's the trade.\"",
                "@2D claps @1d on the shoulder hard enough to rattle a barrel-strap. \"That'll buy you a ride next time we cross paths. The road keeps that ledger, not me.\"",
                "@2D grins broad, tips his hat back. \"Aye, well. Don't make me a hero of it, @1. Tell me about the south road and we'll call it square.\"",
            ],
            Warmth.WARM: [
                "@2D nods slow, satisfied. \"Aye, friend. Glad to. The road's a long one — you do what you can for who's on it with you.\"",
                "@2D claps a calloused hand on @1np shoulder once. \"Don't mention it,\" he says. \"Or do, next inn we both end up at. Either way.\"",
                "@2D dips his hat brim. \"Aye. Take care on the road. That's all the thanks I want — knowing you're still on it next time.\"",
            ],
            Warmth.NEUTRAL: [
                "@2D nods once, all business. \"Aye. Mind the road.\"",
                "@2D touches his hat brim briefly. \"Right enough.\"",
                "@2D grunts a short \"Aye\" and goes back to his strap.",
            ],
            Warmth.COOL: [
                "@2D shrugs without quite looking up. \"Don't make it a thing.\"",
                "@2D waves a flat hand without turning. \"Aye, aye. We're square.\"",
                "@2D grunts something that might be acknowledgement and tightens a knot.",
            ],
            Warmth.COLD: [
                "@2D doesn't answer. He keeps his eyes on the wagon-pole and his hands on the strap.",
                "@2D snorts once and turns @1np way deliberately to check the horse's traces. The thanks lands nowhere.",
                "@2Np jaw tightens. \"Cart's expected,\" he says flat, and that's all he says.",
            ],
        },
    }

    # DEPART_WHEN_PUSHED — fires when a player tries to engage the
    # NPC in conversation past their pre-programmed surface (e.g.
    # repeated $say attempts, or a $-style command not in the
    # social repertoire). The wagoneer exits politely.
    # Convention (matches future on_pushed wiring): ``@1`` = the
    # actor (player), ``@2`` = the wagoneer (NPC).
    DEPART_WHEN_PUSHED_POOL: List[str] = [
        "@2D raises a placating hand. \"Long road ahead, @1. Be well.\" He clucks to his horse and the cart eases back onto the track.",
        "\"I've a schedule,\" @2d says, not unkindly, and shoulders his pole. \"Mind the road. Mind yourself.\" The cart rolls on.",
        "@2D dips his hat briefly. \"Stories are for inns, traveler. Cart's expected.\" He's gone before the next question can land.",
    ]

    # FLEE_FROM_ATTACK — fires when a player runs $kill <wagoneer>.
    # The NPC scrambles away; warmth toward attacker drops.
    # Convention (matches ``spawn.flee_from_attack`` rendering):
    # ``@1`` = the attacker (player), ``@2`` = the wagoneer (NPC).
    FLEE_FROM_ATTACK_POOL: List[str] = [
        "@2D scrambles backward, one hand raised, the other clutching at his horse's traces. \"@1 — no — easy now —\" The cart bolts before he's fully aboard. A barrel rolls free, forgotten.",
        "@1Np blade flashes and @2d reacts before the thought lands — pole down, brake off, shouting at his horse. The cart careens out of the clearing, lurching wildly, and is gone before @1 can take a second step.",
        "@2D goes pale, drops his pole, and turns his cart so hard the wheels skid. \"I've nothing worth this,\" he calls back over his shoulder, eyes white-rimmed. \"NOTHING.\" The cart-song that follows is the panicked kind.",
        "@2D doesn't say anything. He just runs — abandoning cart, horse, and dignity in a desperate scramble for the treeline. The horse bolts on its own a moment later, and what's left in the clearing is a broken silence and one tipped-over barrel.",
    ]

    # LOOK_LINE — inserted into $look output when the wagoneer is
    # present (post-arrival, pre-departure). Atmospheric, not
    # actionable.
    LOOK_LINE: str = (
        "A wagoneer's cart is parked at the clearing's verge, the horse "
        "cropping grass while the man busies himself with cargo straps."
    )

    # ACQUAINTANCE_CUE — fires when the wagoneer learns @2's name
    # for the first time. Voice: working-class observation, the
    # kind of moment a wagoneer would file away mid-task.
    ACQUAINTANCE_CUE_POOL: List[str] = [
        "*The wagoneer pauses at his strap, gives @2 a longer look. \"@2.\" Like he's filing it.*",
        "*The wagoneer's mouth shapes @2np name once, soundless, and he goes back to the barrel.*",
        "*@1d nods once at @2 — a small, deliberate acknowledgement. The face has a name now.*",
    ]
