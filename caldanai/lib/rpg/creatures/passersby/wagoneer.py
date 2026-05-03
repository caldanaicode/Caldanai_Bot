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
        "Cart-wheels announce themselves long before the wagoneer does. He pulls up at the verge, leans on his pole, and looks around like he's counting.",
        "The wagoneer's cart trundles into view, axle protesting. He hops down stiffly, knuckles the small of his back, and surveys the clearing.",
        "A horse plods into the clearing first; the cart follows; the wagoneer comes last, on foot, talking to the horse about a hill they've just survived.",
        "A weather-darkened wagoneer rolls in from the south road, a tarp lashed over barrels and a face like he's seen worse weather coming.",
        "The wagoneer pulls up his team beside a likely patch of grass, sets the brake, and rolls his shoulders one at a time. The horse takes the hint and crops.",
        "Cartwheels grind to a halt at the clearing's verge. The wagoneer doesn't unhitch — just stands beside his lead barrel and listens for a long moment.",
        "An older wagoneer arrives at a careful walking pace, his cart loaded heavy with rope-tied bundles. He nods to the clearing as if it owed him the courtesy.",
        "The track delivers a wagoneer the way it always does — slow, dusty, inevitable. He settles in like he's done this a thousand times.",
    ]

    # AMBIENT — fires periodically while the wagoneer is present.
    # Atmospheric beats; the NPC noticed in the corner of the eye.
    AMBIENT_POOL: List[str] = [
        "The wagoneer fusses with a strap on the lead barrel, frowning at a knot only he can see.",
        "He scratches his horse's ear, murmurs something the horse seems to agree with.",
        "The wagoneer pulls a heel of dark bread from his coat, chews it slowly, watching the treeline.",
        "He squats to inspect a wagon-wheel, runs a calloused thumb along the rim, decides it'll hold another mile.",
        "The wagoneer rolls a cigarette one-handed, lights it off a flint-strike, exhales toward the sky like he's reporting in.",
        "He thumps the side of a barrel, listens to the sound it makes, nods once like he's confirmed something.",
    ]

    # DEPARTURE — wagoneer leaves of his own accord, cart back on
    # the road.
    DEPARTURE_POOL: List[str] = [
        "The wagoneer clucks to his horse, gives the clearing one last unhurried look, and starts the cart back down the track.",
        "He shoulders his pole, gathers the reins, and rolls on. The cart-song fades into the trees.",
        "The wagoneer pulls up his collar, nods to no one in particular, and is gone before the stones stop singing under his wheels.",
        "Cart, horse, and man assemble themselves with practiced unhurriedness, and the road takes them back the way they came.",
        "The wagoneer flicks his pole loose, calls something soft to the horse, and the cart eases forward into a slow plod.",
        "He swings up onto the buckboard with a creak — the cart's, not his — and the road resumes around him.",
    ]

    # SILHOUETTE — fires when arrival timer hits during active
    # combat. The wagoneer doesn't approach; he watches from
    # distance until the fight resolves.
    SILHOUETTE_POOL: List[str] = [
        "On the far ridge, a wagoneer pulls his cart to the verge, sets the brake, and watches with a steady, weighed-out patience.",
        "A wagoneer's silhouette crests the rise. He doesn't come closer. He has work; he can wait.",
        "Cart-wheels stop somewhere up the track. A figure leans on a pole, distant, watching.",
        "Up at the clearing's edge, a wagoneer reins in his team and steadies them with a hand. He's content to wait the noise out.",
        "A wagoneer eyes the commotion from the ridgeline, makes the practical choice, and parks his cart out of arrow-range.",
    ]

    # COMBAT_WON — the wagoneer approaches after the party kills
    # the monster. ``@1`` = wagoneer; ``@2`` = a representative
    # party member (the killing-blow dealer or random survivor).
    COMBAT_WON_REACTIONS: List[str] = [
        "The wagoneer ambles down the track when the dust settles. He gives @2 a look that says good work, then asks if anyone needs water from the barrel.",
        "He waits until the last echo's gone before unbraking. \"Wasn't sure for a moment there,\" he says, settling his cart at the verge. \"Glad I waited to roll on through.\"",
        "The wagoneer rolls in unhurried, surveys the carcass, lets out a low whistle. \"Bigger than I'd've guessed from up the road. You earned the road being a little quieter tonight.\"",
        "He pulls his team up beside @2, claps a hand on @2np shoulder once, says, \"That's a debt the road owes you,\" and means it the way wagoneers mean it — flat and complete.",
        "The wagoneer steps down, walks a slow circle around the kill, kicks one boot against a stone, and looks back up at @2. \"Hells of a thing. Glad you held the line.\"",
        "He sets the brake, pulls a corked bottle from a saddlebag, and offers it to whoever looks worst. \"For the shake,\" he says. \"It'll come; might as well meet it ready.\"",
    ]

    # COMBAT_FLED — monster escaped before dying. Wagoneer
    # approaches to acknowledge the close call.
    COMBAT_FLED_REACTIONS: List[str] = [
        "The wagoneer rolls in once the air's clear. \"That was close,\" he says, eyeing the trampled grass. \"Glad I held the team back. Glad you held your ground.\"",
        "He nods toward the path the creature took. \"I'll keep an ear out for that one. Pass the warning along the road.\"",
        "The wagoneer arrives at his unhurried pace, takes in the wreck of churned earth, and lets out a slow breath. \"Stayed standing. That counts.\"",
        "\"Sometimes they walk off,\" the wagoneer says, more to himself than anyone, settling his cart. \"And sometimes you let them. No shame in either.\"",
        "He surveys the damage, gives @2 a long look, and says, \"You held what could be held. Anyone tells you different's never had to.\"",
    ]

    # PARTY_DEATH — at least one party member died in the fight.
    # Wagoneer arrives quieter than usual, hat off, words careful.
    # ``@2`` = the fallen.
    PARTY_DEATH_REACTIONS: List[str] = [
        "The wagoneer arrives without his usual rumble, having heard the silence too long. He removes his hat, holds it at his side. \"The dirt mends,\" he says quiet. \"I'll be down this road again. Maybe by then.\"",
        "He kneels by @2, hat in hand. \"Long road behind, longer ahead. You'll see them again.\"",
        "The wagoneer ties his team off and walks the last stretch on foot, like the cart owes the moment that respect. He stands a while at @2's side without speaking.",
        "He pulls a small flask from inside his coat, uncorks it, lets a careful pour soak into the dirt by @2. \"Road tax,\" he says. \"For safe passage.\"",
        "The wagoneer settles his hat back on slowly. \"I'll remember the face,\" he tells the rest of the party. \"Next time I roll through, I'll ask after them.\" He means it.",
    ]

    # SOCIAL_REACTIONS — warmth-keyed responses to player verbs.
    # ``@1`` = the actor (player); ``@2`` = the wagoneer. Reactions
    # describe the wagoneer's response to the actor's gesture.
    # Acceptance is NPC-toward-actor warmth, looked up from
    # MongoDB before the spawn-pipeline picks the pool.
    SOCIAL_REACTIONS: Dict[str, Dict[Warmth, List[str]]] = {
        "wave": {
            Warmth.HOT: [
                "The wagoneer breaks into a grin and waves both arms back, hat held high. \"@1! Long ride to find this corner today.\"",
                "The wagoneer's whole face crinkles into a laugh. \"@1d!\" he calls, sweeping his hat in a broad arc. \"Tell me you've got a story for me.\"",
                "He drops the reins entirely, waves both hands like he's flagging a ship in. \"There you are! Road's been dull without you on it.\"",
            ],
            Warmth.WARM: [
                "The wagoneer waves back with a knowing smile, the way old friends do.",
                "He tips his hat and grins. \"@1d. Knew you'd be around here somewhere.\"",
                "The wagoneer raises a calloused hand, smile lined deep. \"Well met, @1.\"",
            ],
            Warmth.NEUTRAL: [
                "The wagoneer raises a hand in return, polite but unhurried.",
                "He nods his head and lifts a finger off the wagon-pole — half wave, half acknowledgement.",
                "The wagoneer returns a brief wave, eyes already drifting back to his cart.",
            ],
            Warmth.COOL: [
                "The wagoneer nods minimally, hands staying on his cart.",
                "He glances over, gives the smallest possible inclination of his head, and goes back to his work.",
                "The wagoneer's eyes meet @1np for a beat. He doesn't wave back.",
            ],
            Warmth.COLD: [
                "The wagoneer's eyes flick to @1np hands, then away. He doesn't return the wave.",
                "He turns deliberately, makes a show of busying himself with a barrel-strap, doesn't look up.",
                "The wagoneer tightens his grip on the wagon-pole and pretends he didn't see.",
            ],
        },
        "nod": {
            Warmth.HOT: [
                "The wagoneer nods back twice, deliberate and warm, then taps his hat brim with two fingers — kin's salute on the road.",
                "He returns the nod and adds a small smile that crinkles old laugh-lines into place.",
                "The wagoneer dips his hat in return, like saluting a passing king he likes.",
            ],
            Warmth.WARM: [
                "The wagoneer returns the nod, slow and considered, the way wagoneers do when they mean it.",
                "He nods back, holds the look a beat longer than he needs to. Friendship's been declared without a word.",
                "The wagoneer dips his head once. \"Aye,\" he says, like it's a whole sentence.",
            ],
            Warmth.NEUTRAL: [
                "The wagoneer returns the nod — short, road-polite, no more.",
                "He nods, neither warm nor cool, and turns back to his horse.",
                "The wagoneer's chin dips once in acknowledgement.",
            ],
            Warmth.COOL: [
                "The wagoneer barely moves — perhaps a nod, perhaps just adjusting his hat.",
                "He glances over without quite nodding, then back at his cart.",
                "The wagoneer tips his head a fraction. It might be a nod. It might be the wind.",
            ],
            Warmth.COLD: [
                "The wagoneer doesn't nod back. He looks past @1np like @1s isn't there.",
                "He fixes his eyes on the horizon and stays still.",
                "The wagoneer's jaw sets. He doesn't acknowledge the gesture at all.",
            ],
        },
        "greet": {
            Warmth.HOT: [
                "\"@1d!\" the wagoneer calls, beaming. \"Pull up a stone, you're staying — I'll get the kettle going.\"",
                "The wagoneer laughs, claps his hands once. \"Now THIS is a clearing worth stopping at. @1d, sit. Sit.\"",
                "\"Hells, @1!\" he says, throwing his hat onto the buckboard. \"Tell me you've got an hour. I've got bread.\"",
            ],
            Warmth.WARM: [
                "The wagoneer nods deeply. \"Hello, @1. Glad to see you on this road.\"",
                "\"@1d. Been a while.\" The wagoneer smiles, settles back against his cart, ready to hear how it's been.",
                "He extends a calloused hand. \"@1. Well met. Anything I can spare from the cart, you ask.\"",
            ],
            Warmth.NEUTRAL: [
                "The wagoneer touches the brim of his hat. \"Traveler.\"",
                "\"Evening,\" the wagoneer says, with the polite economy of someone who's said it a thousand times.",
                "He nods. \"Hello to you. Road's clear north, far as I came.\"",
            ],
            Warmth.COOL: [
                "The wagoneer grunts something that might have been hello.",
                "\"Hm,\" the wagoneer says, without looking up from his strap.",
                "He acknowledges @1np with the smallest possible word: \"Aye.\"",
            ],
            Warmth.COLD: [
                "The wagoneer doesn't return the greeting. He turns his back and busies himself with the cart.",
                "He lets the silence answer for him. The barrel he's checking suddenly needs a great deal of attention.",
                "\"I'm working,\" the wagoneer says flatly, and leaves it there.",
            ],
        },
    }

    # DEPART_WHEN_PUSHED — fires when a player tries to engage the
    # NPC in conversation past their pre-programmed surface (e.g.
    # repeated $say attempts, or a $-style command not in the
    # social repertoire). The wagoneer exits politely.
    DEPART_WHEN_PUSHED_POOL: List[str] = [
        "The wagoneer raises a placating hand. \"Long road ahead, @1. Be well.\" He clucks to his horse and the cart eases back onto the track.",
        "\"I've a schedule,\" the wagoneer says, not unkindly, and shoulders his pole. \"Mind the road. Mind yourself.\" The cart rolls on.",
        "The wagoneer dips his hat briefly. \"Stories are for inns, traveler. Cart's expected.\" He's gone before the next question can land.",
    ]

    # FLEE_FROM_ATTACK — fires when a player runs $kill <wagoneer>.
    # The NPC scrambles away; warmth toward attacker drops.
    # ``@1`` = the wagoneer; ``@2`` = the attacker.
    FLEE_FROM_ATTACK_POOL: List[str] = [
        "The wagoneer scrambles backward, one hand raised, the other clutching at his horse's traces. \"@2 — no — easy now —\" The cart bolts before he's fully aboard. A barrel rolls free, forgotten.",
        "@2np blade flashes and the wagoneer reacts before the thought lands — pole down, brake off, shouting at his horse. The cart careens out of the clearing, lurching wildly, and is gone before @2 can take a second step.",
        "The wagoneer goes pale, drops his pole, and turns his cart so hard the wheels skid. \"I've nothing worth this,\" he calls back over his shoulder, eyes white-rimmed. \"NOTHING.\" The cart-song that follows is the panicked kind.",
        "He doesn't say anything. He just runs — abandoning cart, horse, and dignity in a desperate scramble for the treeline. The horse bolts on its own a moment later, and what's left in the clearing is a broken silence and one tipped-over barrel.",
    ]

    # LOOK_LINE — inserted into $look output when the wagoneer is
    # present (post-arrival, pre-departure). Atmospheric, not
    # actionable.
    LOOK_LINE: str = (
        "A wagoneer's cart is parked at the clearing's verge, the horse "
        "cropping grass while the man busies himself with cargo straps."
    )
