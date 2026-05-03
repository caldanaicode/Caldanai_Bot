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
        "An old woman steps into the clearing the way roots find water — gradually, then unmistakably. She has a satchel slung diagonal across her back and stops a moment to greet a particular tuft of grass.",
        "An herbalist arrives at the verge unhurried, kneels to brush a hand across some bracken, and seems to listen for a long beat to nothing in particular.",
        "A grey-haired woman in earth-colored layers walks the clearing's perimeter once, slowly, then stops where the light falls right and begins to harvest something from the ground that you hadn't noticed was there.",
        "The herbalist arrives following a smell rather than a path, satchel already half-open. She finds what she came for between two stones and nods once, satisfied.",
        "She comes in from the southern path, leaning lightly on a stick worn smooth by decades. The clearing seems to settle around her; even the wind takes a slower turn.",
        "An old woman steps over the last root at the verge and stops, eyes closed, breathing the clearing the way you'd taste a wine. She opens her eyes. \"Aye,\" she says, mostly to herself. \"Aye.\"",
        "The herbalist arrives at the pace of a thing growing. She crouches beside the willow, runs a careful thumb along a leaf-edge, and lays her satchel down.",
        "Twigs and small bones tied to her belt clack quietly as the herbalist walks the verge, unhurried, her head turning just often enough to suggest she sees more than she's looking at.",
    ]

    AMBIENT_POOL: List[str] = [
        "The herbalist crouches and parts a tuft of grass with two fingers, examining what's there, naming it under her breath with a satisfaction that sounds private.",
        "She runs the edge of a leaf between thumb and finger, sniffs her thumb, nods once to herself.",
        "The old woman closes her eyes and tilts her face to a wind only she seems to feel.",
        "She unties a small bundle of dried roots from her belt, sniffs it, considers, ties it back.",
        "The herbalist lays a flat hand on the ground for a moment, listens to whatever the dirt says, and seems to receive an answer she expected.",
        "She pulls a small earthen jar from her satchel, unstoppers it, smells it, smiles thinly, restoppers it.",
    ]

    DEPARTURE_POOL: List[str] = [
        "The herbalist gathers her satchel slowly, gives the clearing a long look, and walks off the way she came at the pace of weather.",
        "She straightens, knees creaking, and says \"Mendholm holds\" the way someone says good night to a house. She's gone before the words quite stop hanging.",
        "The old woman ties one final bundle, slings it across her back, and nods to the clearing as if dismissing class.",
        "She walks the perimeter once more on her way out, touching nothing, naming nothing aloud — just the slow circuit of someone confirming the world is where she left it.",
        "The herbalist murmurs something to the willow on her way past — a thanks, perhaps, or an old promise — and is gone between two heartbeats of the wind.",
        "She leaves at the pace she arrived, which is the pace of root-water finding stone.",
    ]

    SILHOUETTE_POOL: List[str] = [
        "At the clearing's edge, an old woman with a satchel stops, watches the noise with the steady attention of a thing that has watched worse, and stays put.",
        "The herbalist appears at the verge, takes one look at the situation, and settles cross-legged in the moss to wait.",
        "Up the path, an old woman pauses with one hand on her walking-stick. She does not approach. She does not leave. She is, quietly, present.",
        "The herbalist comes to a stop at the treeline, lays her satchel down with care, and waits the way she'd wait for water to finish boiling.",
        "She halts at the verge, eyes the clearing, and folds her hands in front of her — patient as a hill.",
    ]

    COMBAT_WON_REACTIONS: List[str] = [
        "The herbalist comes in unhurried after the dust settles, looks the kill over with a clinical sympathy, and tells @2: \"The dirt knows what it knows. It will keep what's worth keeping.\"",
        "She crosses to where @2 is standing, lays a thumb against @2np pulse without asking, nods at what she finds, and says, \"Mendholm doesn't waste good blood. Yours is good.\"",
        "The old woman walks the edge of the carcass slowly, gathering — a tooth here, a tuft of fur there — and looks up at @2 with eyes that have seen more of these moments than @2 has years. \"Walk careful, traveler. Worse waits.\"",
        "She approaches and stoops to pluck something small from beside the body — a single leaf, perhaps, or a stone — tucks it into her satchel without explanation, and tells @2: \"You'll need this less than I will. Trust me on that.\"",
        "The herbalist lays a hand on @2np shoulder for one short moment. \"The dirt mends, traveler. So do you. Mind the second part.\"",
    ]

    COMBAT_FLED_REACTIONS: List[str] = [
        "The herbalist arrives once the air's gone honest. She studies the empty space where the creature was. \"Some things,\" she says, \"are best let walk. The dirt knows.\"",
        "She crouches and presses a hand to the trampled grass, listening. \"It will come back,\" she says, conversational. \"Not soon. Not before the moon turns.\"",
        "The old woman walks slowly into the clearing, examining the disturbed ground, and addresses @2: \"You held what couldn't be killed yet. That counts in Mendholm. Hold it again next time.\"",
        "She nods at the path the creature took. \"It will mend,\" she tells @2, with no judgment in either direction. \"As you mend. As we all do.\"",
        "The herbalist sniffs the air once, says \"It bleeds at the den, then,\" and leaves it at that — a fact returning to its shelf.",
    ]

    PARTY_DEATH_REACTIONS: List[str] = [
        "The herbalist comes in slowly, sees @2, and stops where she is. She closes her eyes. \"The dirt mends,\" she says quietly. \"Mendholm always does.\"",
        "She crouches at @2's side, lays her hand flat on the ground beside @2np shoulder, and stays that way a long moment. \"You'll be back,\" she tells @2 — or perhaps tells the dirt. \"You'll be back.\"",
        "The old woman pulls a small stoppered jar from her satchel, unties it carefully, and lets a measure of dark water spill into the soil at @2np feet. \"For the road back,\" she says. \"Mendholm hears.\"",
        "She doesn't speak right away. She sits on her heels by @2 and breathes with the rhythm of an old prayer no one taught her. Then: \"You go where the dirt is warm. You come back when it remembers.\"",
        "The herbalist gathers a single sprig of yarrow from her satchel and lays it across @2np chest. \"Walk careful in the under-place, traveler. The world will keep your name until you come for it.\"",
    ]

    SOCIAL_REACTIONS: Dict[str, Dict[Warmth, List[str]]] = {
        "wave": {
            Warmth.HOT: [
                "The herbalist's whole face creases into a slow smile. She raises an open palm, holds it a beat, and says with quiet weight: \"There you are, @1. The dirt's been asking after you.\"",
                "She nods deeply at @1 and lifts a hand. \"Good. Good. The world is more correct with you in it today.\"",
                "The herbalist beams in her quiet way and presses her palm to her heart, briefly, before lifting it in greeting. \"Walk in light, @1.\"",
            ],
            Warmth.WARM: [
                "The herbalist returns the wave with a single slow lift of her hand, the way you'd raise a glass.",
                "She inclines her head and lifts a palm. \"Walk careful, traveler. The road is a long one.\"",
                "The old woman smiles, slight but warm, and answers the wave with a small open hand.",
            ],
            Warmth.NEUTRAL: [
                "The herbalist raises her hand briefly in return — polite, unhurried, attention already half-elsewhere.",
                "She nods at the wave and acknowledges it with a single dipped finger. The clearing remains the world's main concern.",
                "The old woman returns the gesture in a way that takes its full half-second and no more.",
            ],
            Warmth.COOL: [
                "The herbalist's eyes find @1np for a measured moment, and she does not raise her hand.",
                "She tilts her head a fraction in acknowledgement, and turns back to her satchel.",
                "The old woman holds @1np gaze for one long beat, says nothing, looks back to the ground.",
            ],
            Warmth.COLD: [
                "The herbalist closes her eyes briefly, the way you'd shut a window against weather, and does not return the wave.",
                "She turns her head a careful, deliberate quarter-turn away, and the air around her cools.",
                "The old woman lays her hand flat on the dirt as if she's borrowing the dirt's silence, and does not look up.",
            ],
        },
        "nod": {
            Warmth.HOT: [
                "The herbalist returns the nod slowly, holds @1np eyes, and says: \"You are seen, @1. Walk in light.\"",
                "She dips her head with grave warmth. \"Aye. The dirt remembers.\"",
                "The old woman touches her brow briefly with two fingers, then nods deeply — an old benediction worn into a habit.",
            ],
            Warmth.WARM: [
                "The herbalist returns the nod, slow and weighted. \"Walk careful, traveler.\"",
                "She inclines her head with quiet recognition. \"Aye. Carry the day kindly.\"",
                "The old woman dips her chin in answer and meets @1np eyes for a beat that says she'll remember.",
            ],
            Warmth.NEUTRAL: [
                "The herbalist returns the nod simply, unhurried.",
                "She inclines her head once and goes back to her satchel.",
                "The old woman acknowledges with the smallest dip of her chin.",
            ],
            Warmth.COOL: [
                "The herbalist's eyes flick to @1np and away. She does not nod back.",
                "She marks the nod with a barely-there shift of her gaze, and nothing more.",
                "The old woman regards @1np a moment, says nothing, looks down at the dirt.",
            ],
            Warmth.COLD: [
                "The herbalist closes her eyes briefly and does not return the nod.",
                "She turns her face deliberately away, and the gesture is the answer.",
                "The old woman bends her attention back to her satchel like @1np isn't there.",
            ],
        },
        "greet": {
            Warmth.HOT: [
                "The herbalist looks up with her slow smile and says: \"@1d. You return when the dirt expects you. That's a kindness to it.\"",
                "She dips her head and answers softly: \"Walk in light, @1. The world's been less without you.\"",
                "\"Aye, traveler,\" the herbalist says — her voice on \"@1\" the way some say a prayer they haven't said in years.",
            ],
            Warmth.WARM: [
                "The herbalist meets @1np eyes and says, with that quiet weight: \"Walk careful, traveler. Mendholm holds.\"",
                "She inclines her head. \"Greetings, traveler. The dirt knows your weight on it.\"",
                "\"Aye,\" the old woman says simply. \"Aye. The clearing is glad of you today.\"",
            ],
            Warmth.NEUTRAL: [
                "The herbalist nods. \"Traveler.\"",
                "She acknowledges the greeting briefly. \"Greetings. Walk careful.\"",
                "\"Aye,\" the old woman says, and returns to her satchel.",
            ],
            Warmth.COOL: [
                "The herbalist gives @1np a long look, says nothing in return, and resumes her work.",
                "She inclines her head a fraction without speaking.",
                "The old woman lets the silence answer for her, and the silence is polite enough.",
            ],
            Warmth.COLD: [
                "The herbalist regards @1np in silence for a long beat, then turns her face to the ground.",
                "She does not return the greeting. The clearing, around her, goes still.",
                "The old woman lays her hand on the dirt and lets that be her response.",
            ],
        },
    }

    DEPART_WHEN_PUSHED_POOL: List[str] = [
        "The herbalist holds up a calm hand. \"The dirt knows what it knows, traveler. I am not the asking-place. Walk well.\" She gathers her satchel and goes.",
        "\"Some things stay between the dirt and itself,\" the old woman says, not unkindly, slinging her satchel. \"Find me again when the world has another question for you to bring.\"",
        "The herbalist nods once, decisively. \"You will know what you need to when you need to. Mendholm doesn't waste an answer.\" She walks out at the pace of weather.",
    ]

    FLEE_FROM_ATTACK_POOL: List[str] = [
        "The herbalist's expression doesn't change, but her hand goes to a small pouch at her belt and the air around her shifts perceptibly. \"No,\" she says, calm as a hill. She walks out of the clearing and the path closes behind her like a door.",
        "She holds @2np eyes for one terrible moment, says only \"Mendholm sees,\" and is somehow already at the treeline by the time @2 takes a step. The bracken does not bend in her wake.",
        "The old woman raises one hand, palm out — the dirt seems to hush — and she is gone before @2 quite knows in which direction she went. A single sprig of yarrow lies where she stood.",
        "The herbalist walks away unhurried, satchel in hand, and the ground between her and the clearing seems to forget @2 was ever a problem worth her time. She does not look back.",
    ]

    LOOK_LINE: str = (
        "An old herbalist works the clearing's edges with a satchel "
        "of cuttings, listening to things the rest of you can't "
        "quite hear."
    )
