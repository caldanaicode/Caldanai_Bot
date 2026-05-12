"""Old herbalist — a cryptic, mythic-voiced traveler who reads the
land more than the road. Carries a satchel of cuttings, knows the
plants that don't grow in straight lines, and references Mendholm
by name in the way someone names something they trust.

Voice register: fragments and aphorisms. "The dirt knows what it
knows" energy. Speaks like she's translating from a quieter
language. The world is hers in a way it isn't for the wagoneer or
the child — she names Mendholm, she names the seasons, she names
weather as a kind of person.

Per Caels: "the herbalist references it mystically — the dirt
knows what it knows" — the world-name lands explicitly with this
NPC. She's the rumor-bearer of V1 and one of the two NPCs who
say "Mendholm" aloud.

Parser tokens: ``@1`` = the actor (player) when used in social
reactions. Pools authored for acquainted state; the herbalist's
low NAMING_BIAS (0.15) means most renderings substitute the
StrangerActor's "traveler" surface — and when she does say a
name, it lands.
"""
from typing import Dict, List

from caldanai.lib.rpg.creatures.passersby import PasserbyPlugin
from caldanai.lib.rpg.helpers.enums import TimePartitions
from caldanai.lib.rpg.helpers.warmth import Warmth


class Herbalist(PasserbyPlugin):
    name = "herbalist"
    uses_article = True
    gender = "female"
    pronouns = "she,her,hers,her,herself"
    ALIASES = ["old herbalist", "wise woman", "herb-witch"]

    # The herbalist walks at the edges of the day — gathering in
    # good light, walking the verges at dusk for the herbs that
    # only show themselves then. DIURNAL covers dawn through
    # evening; CREPUSCULAR adds the dusk walk. Excludes deep
    # night (even mythic figures sleep eventually).
    time_partition = TimePartitions.DIURNAL | TimePartitions.CREPUSCULAR

    # Mostly "traveler" — names land as deliberate weight.
    # Occasional name-use is a *moment*, not a habit. 0.15 means
    # ~1 in 7 lines pulls the player's actual name through.
    NAMING_BIAS = 0.15

    ARRIVAL_POOL: List[str] = [
        "An old woman steps into the clearing the way roots find water — gradually, then unmistakably. @1S has a satchel slung diagonal across her back and stops a moment to greet a particular tuft of grass.",
        "An herbalist arrives at the verge unhurried, kneels to brush a hand across some bracken, and seems to listen for a long beat to nothing in particular.",
        "A grey-haired woman in earth-colored layers walks the clearing's perimeter once, slowly, then stops where the light falls right and begins to harvest something from the ground that you hadn't noticed was there.",
        "@1D arrives following a smell rather than a path, satchel already half-open. She finds what she came for between two stones and nods once, satisfied.",
        "@1D comes in from the southern path, leaning lightly on a stick worn smooth by decades. The clearing seems to settle around her; even the wind takes a slower turn.",
        "An old woman steps over the last root at the verge and stops, eyes closed, breathing the clearing the way you'd taste a wine. She opens her eyes. \"Aye,\" she says, mostly to herself. \"Aye.\"",
        "@1D arrives at the pace of a thing growing. She crouches beside the willow, runs a careful thumb along a leaf-edge, and lays her satchel down.",
        "Twigs and small bones tied to her belt clack quietly as @1d walks the verge, unhurried, her head turning just often enough to suggest she sees more than she's looking at.",
    ]

    AMBIENT_POOL: List[str] = [
        "@1D crouches and parts a tuft of grass with two fingers, examining what's there, naming it under her breath with a satisfaction that sounds private.",
        "@1D runs the edge of a leaf between thumb and finger, sniffs her thumb, nods once to herself.",
        "@1D closes her eyes and tilts her face to a wind only she seems to feel.",
        "@1D unties a small bundle of dried roots from her belt, sniffs it, considers, ties it back.",
        "@1D lays a flat hand on the ground for a moment, listens to whatever the dirt says, and seems to receive an answer she expected.",
        "@1D pulls a small earthen jar from her satchel, unstoppers it, smells it, smiles thinly, restoppers it.",
    ]

    DEPARTURE_POOL: List[str] = [
        "@1D gathers her satchel slowly, gives the clearing a long look, and walks off the way she came at the pace of weather.",
        "@1D straightens, knees creaking, and says \"Mendholm holds\" the way someone says good night to a house. She's gone before the words quite stop hanging.",
        "@1D ties one final bundle, slings it across her back, and nods to the clearing as if dismissing class.",
        "@1D walks the perimeter once more on her way out, touching nothing, naming nothing aloud — just the slow circuit of someone confirming the world is where she left it.",
        "@1D murmurs something to the willow on her way past — a thanks, perhaps, or an old promise — and is gone between two heartbeats of the wind.",
        "@1D leaves at the pace she arrived, which is the pace of root-water finding stone.",
    ]

    SILHOUETTE_POOL: List[str] = [
        "At the clearing's edge, an old woman with a satchel stops, watches the noise with the steady attention of a thing that has watched worse, and stays put.",
        "@1D appears at the verge, takes one look at the situation, and settles cross-legged in the moss to wait.",
        "Up the path, an old woman pauses with one hand on her walking-stick. @1S does not approach. @1S does not leave. @1S is, quietly, present.",
        "@1D comes to a stop at the treeline, lays her satchel down with care, and waits the way she'd wait for water to finish boiling.",
        "@1D halts at the verge, eyes the clearing, and folds her hands in front of her — patient as a hill.",
    ]

    # Reactive flavor for witnessing a passive-monster kill (sheep
    # today). Herbalist's voice is mythic-disapproval — the dirt
    # knows, Mendholm watches, the act stands. Authored as starting
    # voice; revise to taste.
    PASSIVE_KILL_REACTIONS: Dict[str, List[str]] = {
        "*": [
            "@1D looks at the body for a long beat, then at @2. \"The dirt takes everything,\" she says, slow. \"It does not always thank you for what you give it.\"",
            "@1D crosses to the body, kneels, and lays a hand briefly over its eye — closing it. She stands, dusts her palms on her satchel-strap, and walks away without looking at @2.",
            "@1D does not approach. From where she stands at the verge, she says, evenly: \"That was not a thing of the dirt's making, what you just did. The dirt knows.\"",
            "@1Np face does not move. \"Mendholm holds,\" she says, evenly, \"and Mendholm watches. There is no hiding what was done here.\"",
            "@1D plucks a single leaf from a low branch as she passes the body, tucks it into her satchel, and tells @2 quietly: \"Some weights you will carry yourself. The dirt will not take this one for you.\"",
        ],
    }

    COMBAT_WON_REACTIONS: List[str] = [
        "@1D comes in unhurried after the dust settles, looks the kill over with a clinical sympathy, and tells @2: \"The dirt knows what it knows. It will keep what's worth keeping.\"",
        "@1D crosses to where @2 is standing, lays a thumb against @2np pulse without asking, nods at what she finds, and says, \"Mendholm doesn't waste good blood. Yours is good.\"",
        "@1D walks the edge of the carcass slowly, gathering — a tooth here, a tuft of fur there — and looks up at @2 with eyes that have seen more of these moments than @2 has years. \"Walk careful, traveler. Worse waits.\"",
        "@1D approaches and stoops to pluck something small from beside the body — a single leaf, perhaps, or a stone — tucks it into her satchel without explanation, and tells @2: \"You'll need this less than I will. Trust me on that.\"",
        "@1D lays a hand on @2np shoulder for one short moment. \"The dirt mends, traveler. So do you. Mind the second part.\"",
    ]

    COMBAT_FLED_REACTIONS: List[str] = [
        "@1D arrives once the air's gone honest. She studies the empty space where the creature was. \"Some things,\" she says, \"are best let walk. The dirt knows.\"",
        "@1D crouches and presses a hand to the trampled grass, listening. \"It will come back,\" she says, conversational. \"Not soon. Not before the moon turns.\"",
        "@1D walks slowly into the clearing, examining the disturbed ground, and addresses @2: \"You held what couldn't be killed yet. It will hold longer next, or it won't. The dirt watches either way.\"",
        "@1D nods at the path the creature took. \"It will mend,\" she tells @2, with no judgment in either direction. \"As you mend. As we all do.\"",
        "@1D sniffs the air once, says \"It bleeds at the den, then,\" and leaves it at that — a fact returning to its shelf.",
    ]

    PARTY_DEATH_REACTIONS: List[str] = [
        "@1D comes in slowly, sees @2, and stops where she is. She closes her eyes. \"The dirt mends,\" she says quietly. \"Mendholm always does.\"",
        "@1D crouches at @2np side, lays her hand flat on the ground beside @2np shoulder, and stays that way a long moment. \"You'll be back,\" she tells @2 — or perhaps tells the dirt. \"You'll be back.\"",
        "@1D pulls a small stoppered jar from her satchel, unties it carefully, and lets a measure of dark water spill into the soil at @2np feet. \"For the road back,\" she says. \"Mendholm hears.\"",
        "@1D doesn't speak right away. She sits on her heels by @2 and breathes with the rhythm of an old prayer no one taught her. Then: \"You go where the dirt is warm. You come back when it remembers.\"",
        "@1D gathers a single sprig of yarrow from her satchel and lays it across @2np chest. \"Walk careful in the under-place, traveler. The world will keep your name until you come for it.\"",
    ]

    SOCIAL_REACTIONS: Dict[str, Dict[Warmth, List[str]]] = {
        "wave": {
            Warmth.HOT: [
                "@2Np whole face creases into a slow smile. She raises an open palm, holds it a beat, and says with quiet weight: \"There you are, @1. The dirt's been asking after you.\"",
                "@2D nods deeply at @1 and lifts a hand. \"Good. Good. The world is more correct with you in it today.\"",
                "@2D beams in her quiet way and presses her palm to her heart, briefly, before lifting it in greeting. \"Walk in light, @1.\"",
            ],
            Warmth.WARM: [
                "@2D returns the wave with a single slow lift of her hand, the way you'd raise a glass.",
                "@2D inclines her head and lifts a palm. \"Walk careful, traveler. The road is a long one.\"",
                "@2D smiles, slight but warm, and answers the wave with a small open hand.",
            ],
            Warmth.NEUTRAL: [
                "@2D raises her hand briefly in return — polite, unhurried, attention already half-elsewhere.",
                "@2D nods at the wave and acknowledges it with a single dipped finger. The clearing remains the world's main concern.",
                "@2D returns the gesture in a way that takes its full half-second and no more.",
            ],
            Warmth.COOL: [
                "@2Np eyes find @1d for a measured moment, and she does not raise her hand.",
                "@2D tilts her head a fraction in acknowledgement, and turns back to her satchel.",
                "@2D holds @1np gaze for one long beat, says nothing, looks back to the ground.",
            ],
            Warmth.COLD: [
                "@2D closes her eyes briefly, the way you'd shut a window against weather, and does not return the wave.",
                "@2D turns her head a careful, deliberate quarter-turn away, and the air around her cools.",
                "@2D lays her hand flat on the dirt as if she's borrowing the dirt's silence, and does not look up.",
            ],
        },
        "nod": {
            Warmth.HOT: [
                "@2D returns the nod slowly, holds @1np eyes, and says: \"You are seen, @1. Walk in light.\"",
                "@2D dips her head with grave warmth. \"Aye. The dirt remembers.\"",
                "@2D touches her brow briefly with two fingers, then nods deeply — an old benediction worn into a habit.",
            ],
            Warmth.WARM: [
                "@2D returns the nod, slow and weighted. \"Walk careful, traveler.\"",
                "@2D inclines her head with quiet recognition. \"Aye. Carry the day kindly.\"",
                "@2D dips her chin in answer and meets @1np eyes for a beat that says she'll remember.",
            ],
            Warmth.NEUTRAL: [
                "@2D returns the nod simply, unhurried.",
                "@2D inclines her head once and goes back to her satchel.",
                "@2D acknowledges with the smallest dip of her chin.",
            ],
            Warmth.COOL: [
                "@2Np eyes flick to @1d and away. She does not nod back.",
                "@2D marks the nod with a barely-there shift of her gaze, and nothing more.",
                "@2D regards @1d a moment, says nothing, looks down at the dirt.",
            ],
            Warmth.COLD: [
                "@2D closes her eyes briefly and does not return the nod.",
                "@2D turns her face deliberately away, and the gesture is the answer.",
                "@2D bends her attention back to her satchel like @1d isn't there.",
            ],
        },
        "greet": {
            Warmth.HOT: [
                "@2D looks up with her slow smile and says: \"@1d. You return when the dirt expects you. That's a kindness to it.\"",
                "@2D dips her head and answers softly: \"Walk in light, @1. The world's been less without you.\"",
                "\"Aye, traveler,\" @2d says — her voice on \"@1\" the way some say a prayer they haven't said in years.",
            ],
            Warmth.WARM: [
                "@2D meets @1np eyes and says, with that quiet weight: \"Walk careful, traveler. Mendholm holds.\"",
                "@2D inclines her head. \"Greetings, traveler. The dirt knows your weight on it.\"",
                "\"Aye,\" @2d says simply. \"Aye. The clearing is glad of you today.\"",
            ],
            Warmth.NEUTRAL: [
                "@2D nods. \"Traveler.\"",
                "@2D acknowledges the greeting briefly. \"Greetings. Walk careful.\"",
                "\"Aye,\" @2d says, and returns to her satchel.",
            ],
            Warmth.COOL: [
                "@2D gives @1d a long look, says nothing in return, and resumes her work.",
                "@2D inclines her head a fraction without speaking.",
                "@2D lets the silence answer for her, and the silence is polite enough.",
            ],
            Warmth.COLD: [
                "@2D regards @1d in silence for a long beat, then turns her face to the ground.",
                "@2D does not return the greeting. The clearing, around her, goes still.",
                "@2D lays her hand on the dirt and lets that be her response.",
            ],
        },
        "thank": {
            Warmth.HOT: [
                "@2D meets @1np eyes a long quiet beat, then dips her head. \"Thank the dirt, @1. The dirt is owed. I am only the thing it sent.\"",
                "@2D presses her palm briefly to @1np forearm. \"Mendholm hears. That is the only thanks worth keeping. It already has it.\"",
                "@2D smiles her slow smile. \"Aye, @1. I will carry your thanks down to the ground for you. The ground will know what to do with it.\"",
            ],
            Warmth.WARM: [
                "@2D inclines her head slowly. \"The dirt is owed, traveler — not me. But I will pass the word on.\"",
                "@2D nods, weighted. \"Walk careful. That is thanks enough returned.\"",
                "\"Aye,\" @2d says simply. \"The world was a little less without the asking. Now it is a little more.\"",
            ],
            Warmth.NEUTRAL: [
                "@2D dips her chin once. \"Mendholm holds.\"",
                "@2D acknowledges without claiming. \"The dirt did its part. I did mine.\"",
                "@2D nods. \"Aye, traveler.\"",
            ],
            Warmth.COOL: [
                "@2D regards @1d a long beat, then looks down at her satchel. \"Thank the dirt, traveler. Not me.\"",
                "@2D lays her hand flat on the ground. \"Tell it to this,\" she says quietly, and says no more.",
                "@2Np eyes flick to @1d and away. \"Some thanks finds the wrong door.\"",
            ],
            Warmth.COLD: [
                "@2D closes her eyes briefly, the way you'd shut a window against weather, and does not answer.",
                "@2D turns her face deliberately to the willow. The thanks, undelivered, settles on the dirt instead.",
                "@2D lays her palm on the ground and leaves it there. The ground takes the thanks. She does not.",
            ],
        },
        "rest": {
            Warmth.HOT: [
                "@2D folds herself down beside @1d at her unhurried pace and lays her satchel between them. \"Aye. Rest, @1. The dirt is glad of weight on it. So am I.\"",
                "@2D pats the moss beside her, slow and certain. \"Sit a while. The clearing holds longer when good people rest in it.\"",
                "@2D smiles her quiet smile and gestures to a flat place at her side. \"Mendholm mends faster when you stay still in it a beat. Stay.\"",
            ],
            Warmth.WARM: [
                "@2D nods slowly. \"Rest as long as you need, traveler. The dirt is patient. So am I.\"",
                "@2D lays her satchel aside and leaves a quiet space at her side. \"Aye. The ground holds.\"",
                "@2D dips her chin. \"Mendholm doesn't begrudge a rested body. Take what the clearing offers.\"",
            ],
            Warmth.NEUTRAL: [
                "@2D acknowledges without comment. The clearing makes room.",
                "@2D nods once and goes back to her satchel. The space is shared without being shared.",
                "@2D lets @1d rest where @1s is. The dirt, she would say, knows what to do.",
            ],
            Warmth.COOL: [
                "@2D shifts a careful half-pace, leaving a thin polite space that doesn't quite invite.",
                "@2D regards @1np resting form a moment, says nothing, and turns back to her satchel.",
                "@2Np gaze brushes @1d once. The space between them stays as it was.",
            ],
            Warmth.COLD: [
                "@2D stands and walks the perimeter slowly, putting weather between herself and @1d.",
                "@2D closes her eyes briefly and does not look @1np way again.",
                "@2D gathers her satchel without fuss and finds a different patch of dirt to attend to.",
            ],
        },
        "ponder": {
            Warmth.HOT: [
                "@2D settles cross-legged near @1d, satchel in lap, and breathes with @1np pace. \"Aye, @1. The dirt is thinking with you. Listen for it.\"",
                "@2D lays her hand flat on the ground and says, soft as a leaf turning: \"What you ask, the ground has been asking longer. Sit with it.\"",
                "@2D meets @1np eyes briefly, nods. \"Mendholm thinks slowly. So do good travelers. We are in good company, you and I.\"",
            ],
            Warmth.WARM: [
                "@2D nods, weighted, and says nothing else for a long moment. The silence between them is companionable.",
                "@2D murmurs, mostly to the dirt: \"Aye. Some questions root before they answer.\"",
                "@2D inclines her head once and lets @1d ponder. The clearing holds the quiet for both of them.",
            ],
            Warmth.NEUTRAL: [
                "@2D continues her slow attention to her satchel. The silence between them is silence; it is enough.",
                "@2D acknowledges with a barely-there shift of her gaze and lets @1d be.",
                "@2D works her cuttings unhurried, and the moment passes between them without weight.",
            ],
            Warmth.COOL: [
                "@2D turns her shoulder a careful fraction and bends to her satchel. The silence is not shared.",
                "@2Np eyes pass over @1d as if @1s were one more shape of bracken.",
                "@2D shifts her attention pointedly to a tuft of grass. The pondering is @1np alone.",
            ],
            Warmth.COLD: [
                "@2D closes her eyes and lets the air between them cool perceptibly.",
                "@2D walks a slow perimeter without looking back, satchel in hand. The pondering finds nowhere to settle.",
                "@2D lays her hand on the dirt and lets that be her answer to nothing in particular.",
            ],
        },
        "tend": {
            Warmth.HOT: [
                "@2D holds still while @1d works, eyes briefly closed. \"Aye, @1. The dirt tends through you today. I am glad of the hand.\"",
                "@2D catches @1np wrist when @1s is done, presses it once. \"Who tends whom, traveler. Mendholm passes the kindness through.\"",
                "@2D smiles slow and warm. \"Aye. The world tends itself in small hands, when it remembers to.\"",
            ],
            Warmth.WARM: [
                "@2D inclines her head and lets @1d adjust whatever needs adjusting. \"Aye. The dirt tends. So do you. Both work.\"",
                "@2D dips her chin in quiet thanks. \"Walk careful, traveler. You've a gentle hand. The world will use it.\"",
                "@2D pats the back of @1np hand briefly when @1s is done. \"Aye. That's done.\"",
            ],
            Warmth.NEUTRAL: [
                "@2D allows the gesture without remark, attention half-elsewhere.",
                "@2D dips her head once in unspoken acknowledgement.",
                "@2D lets the small care happen and goes back to her cuttings.",
            ],
            Warmth.COOL: [
                "@2D steps back a careful half-pace. \"The dirt tends, traveler. Not you. Not yet.\"",
                "@2D shakes her head slowly. \"Mind your own,\" she says, not unkindly. \"I am tended.\"",
                "@2D lays her hand on her own satchel — claim, gentle but firm — and the gesture finds nowhere to land.",
            ],
            Warmth.COLD: [
                "@2D closes her eyes and turns her shoulder. The reaching hand finds only the air she has left for it.",
                "@2D steps back without sound. The clearing between her and @1d widens by a slow careful pace.",
                "@2D lays her palm on the ground. \"The dirt holds,\" she says, and says no more. The hand of @1 has nothing to do.",
            ],
        },
        "lean": {
            Warmth.HOT: [
                "@2D smiles her slow smile. \"Aye, @1. The stones hold what's leaned on them. So does the world. Lean well.\"",
                "@2D nods, weighted. \"The ground beneath you, the stone behind you. That's all most days need, traveler.\"",
                "@2D watches @1d a long moment and says, quietly: \"You lean like someone who has finally given up the pretense of standing alone. Aye. Mendholm allows it.\"",
            ],
            Warmth.WARM: [
                "@2D inclines her head. \"The ground holds, traveler. Always has.\"",
                "@2D nods at the leaning. \"Aye. Borrow what the world offers.\"",
                "@2D murmurs, mostly to the willow: \"Stone is patient. So is the dirt.\"",
            ],
            Warmth.NEUTRAL: [
                "@2D acknowledges with a small dip of her chin. The clearing makes room.",
                "@2D returns her attention to her satchel. The lean is not remarked upon, and that is its own welcome.",
                "@2D nods once, unhurried, and goes back to her work.",
            ],
            Warmth.COOL: [
                "@2D regards @1d a beat, says nothing, looks back at the dirt.",
                "@2Np eyes flick to the leaning form and away. The silence is not warm.",
                "@2D adjusts her satchel a careful pace further from @1d's chosen spot.",
            ],
            Warmth.COLD: [
                "@2D closes her eyes briefly and does not acknowledge the leaning at all.",
                "@2D walks a slow circle to the far side of the clearing without comment.",
                "@2D lays her hand flat on the dirt and lets that be the only answer the moment receives.",
            ],
        },
    }

    # DEPART_WHEN_PUSHED — convention matches future on_pushed
    # wiring: ``@1`` = the actor (player), ``@2`` = the herbalist (NPC).
    DEPART_WHEN_PUSHED_POOL: List[str] = [
        "@2D holds up a calm hand. \"The dirt knows what it knows, traveler. I am not the asking-place. Walk well.\" She gathers her satchel and goes.",
        "\"Some things stay between the dirt and itself,\" @2d says, not unkindly, slinging her satchel. \"Find me again when the world has another question for you to bring.\"",
        "@2D nods once, decisively. \"You will know what you need to when you need to. Mendholm doesn't waste an answer.\" She walks out at the pace of weather.",
    ]

    # FLEE_FROM_ATTACK rendering: ``@1`` = the attacker (player),
    # ``@2`` = the herbalist (NPC).
    FLEE_FROM_ATTACK_POOL: List[str] = [
        "@2Np expression doesn't change, but her hand goes to a small pouch at her belt and the air around her shifts perceptibly. \"No,\" she says, calm as a hill. She walks out of the clearing and the path closes behind her like a door.",
        "@2D holds @1np eyes for one terrible moment, says only \"Mendholm sees,\" and is somehow already at the treeline by the time @1 takes a step. The bracken does not bend in her wake.",
        "@2D raises one hand, palm out — the dirt seems to hush — and she is gone before @1 quite knows in which direction she went. A single sprig of yarrow lies where she stood.",
        "@2D walks away unhurried, satchel in hand, and the ground between her and the clearing seems to forget @1 was ever a problem worth her time. She does not look back.",
    ]

    LOOK_LINE: str = (
        "An old herbalist works the clearing's edges with a satchel "
        "of cuttings, listening to things the rest of you can't "
        "quite hear."
    )

    # ACQUAINTANCE_CUE — fires when the herbalist learns @2's name
    # for the first time. Voice: weighted, ritual-soft. The old
    # woman has known many names. Adding one more is a small,
    # deliberate ceremony.
    ACQUAINTANCE_CUE_POOL: List[str] = [
        "*The herbalist looks up briefly. \"@2,\" she says, the way you'd seal a small jar.*",
        "*The old woman's eyes meet @2np for a long quiet moment. \"The dirt will know to expect you.\"*",
        "*@1d folds @2np name into something at the back of her mouth, and goes back to her satchel.*",
    ]
