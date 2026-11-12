"""Personalised tales: the listener's child becomes the hero of a StoryBook episode.

Each tale has a direction sheet: which character the child plays, the exact passages that
are rewritten around them (with their name and pronouns), a spoken dedication, a goodnight,
and which stretch of the tale makes the short free preview.

    from storybook.personalize import personalize
    src = personalize("the_three_little_pigs", name="Mia", pronouns="she", gift_from="Grandma")
    src = personalize(..., preview=True)   # about a minute: dedication, title, the child's big scene

Rewrites are applied as exact-text substitutions and each one must match, so if a script is
edited later this fails loudly instead of quietly producing a story without the child in it.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

PRONOUNS = {
    "she": {"he": "she", "him": "her", "his": "her", "He": "She", "His": "Her", "was": "was"},
    "he": {"he": "he", "him": "him", "his": "his", "He": "He", "His": "His", "was": "was"},
    "they": {"he": "they", "him": "them", "his": "their", "He": "They", "His": "Their", "was": "were"},
}
# the child's voice: Kokoro's two most natural young-sounding voices
VOICES = {"lighter": "af_heart", "deeper": "am_puck"}
DEFAULT_VOICE = {"she": "lighter", "he": "deeper", "they": "lighter"}

TALES = {
    "the_three_little_pigs": {
        "title": "The Three Little Pigs",
        "role": "the clever third little pig, who builds with bricks and outwits the wolf",
        "hero": "pig3",
        # the hero's scenes start here; rewrites only apply from this point on
        "from": "The third little pig met a man",
        "heading": ("# The Three Little Pigs.", "# The Three Little Pigs. A story for {name}."),
        "cast_fix": {"deeper": {"pig1": "bm_fable"}},  # keep the first pig distinct from the hero
        "rewrites": [
            ("The third little pig met a man with a load of bricks, and said:",
             "The third little pig was called {name}, and {name} was the cleverest of the three. "
             "{He} met a man with a load of bricks, and said:"),
            ("So the man gave him the bricks, and he built his house with them.",
             "So the man gave {him} the bricks, and {name} built {his} house with them, brick by brick."),
            ("@wolf: “Little pig, little pig, let me come in.”", "@wolf: “{name}, {name}, let me come in.”"),
            ("@pig3: “Where?” said the little pig.", "@pig3: “Where?” said {name}."),
            ("“Very well,” said the little pig,", "“Very well,” said {name},"),
            ("Well, the little pig got up at five,", "Well, {name} got up at five,"),
            ("@wolf: “Little Pig, are you ready?”", "@wolf: “{name}, are you ready?”"),
            ("@pig3: The little pig said: “Ready!", "@pig3: {name} said: “Ready!"),
            ("he would be up to the little pig somehow", "he would be up to {name} somehow"),
            ("@pig3: “Where?” said the pig.", "@pig3: “Where?” said {name}."),
            ("Well, the little pig bustled up the next morning at four o'clock, and went off for the apples, "
             "hoping to get back before the wolf came; but he had further to go, and had to climb the tree, "
             "so that just as he was coming down from it, he saw the wolf coming, which, as you may suppose, "
             "frightened him very much.",
             "Well, {name} bustled up the next morning at four o'clock, and went off for the apples, "
             "hoping to get back before the wolf came; but {he} had further to go, and had to climb the tree, "
             "so that just as {he} {was} coming down from it, {he} saw the wolf coming, which, as you may suppose, "
             "frightened {him} very much."),
            ("@wolf: “Little pig, what! are you here before me?", "@wolf: “{name}, what! are you here before me?"),
            ("“Yes, very,” said the little pig.", "“Yes, very,” said {name}."),
            ("And he threw it so far, that, while the wolf was gone to pick it up, the little pig jumped down and "
             "ran home. The next day the wolf came again, and said to the little pig:",
             "And {he} threw it so far, that, while the wolf was gone to pick it up, {name} jumped down and "
             "ran home. The next day the wolf came again, and said to {name}:"),
            ("@wolf: “Little pig, there is a fair", "@wolf: “{name}, there is a fair"),
            ("“Oh yes,” said the pig,", "“Oh yes,” said {name},"),
            ("So the little pig went off before the time as usual, and got to the fair, and bought a butter-churn, "
             "which he was going home with, when he saw the wolf coming. Then he could not tell what to do. So he "
             "got into the churn to hide, and by so doing turned it round, and it rolled down the hill with the pig "
             "in it,",
             "So {name} went off before the time as usual, and got to the fair, and bought a butter-churn, "
             "which {he} {was} going home with, when {he} saw the wolf coming. Then {he} could not tell what to do. "
             "So {he} got into the churn to hide, and by so doing turned it round, and it rolled down the hill with "
             "{name} in it,"),
            ("He went to the little pig's house, and told him how frightened",
             "He went to {name}'s house, and told {him} how frightened"),
            ("Then the little pig said:", "Then {name} said:"),
            ("declared he would eat up the little pig, and that he would get down the chimney after him. When the "
             "little pig saw what he was about, he hung on the pot",
             "declared he would eat up {name}, and that he would get down the chimney after {him}. When "
             "{name} saw what he was about, {he} hung on the pot"),
            # a gentler ending for a bedtime story with your own child in it
            ("so the little pig put on the cover again in an instant, boiled him up, and ate him for supper, and "
             "lived happy ever afterwards.",
             "so {name} put on the cover again in an instant, and that was the very last of the wolf. And {name} "
             "lived happy ever afterwards, in the little brick house, with a nice potful of turnips for dinner."
             "\n\n[pause 1.5]\n\n@@narrator: Goodnight, {name}. Sleep tight."),
        ],
        "preview": [("The third little pig was called", "blow the house down, he said:")],
    },
    "elves_and_the_shoemaker": {
        "title": "The Elves and the Shoemaker",
        "role": "the shoemaker's child, who stays up to see the elves and thinks of a way to thank them",
        "hero": "child",
        "from": "There was once a shoemaker",
        "heading": ("# The Elves and the Shoemaker.", "# The Elves and the Shoemaker. A story for {name}."),
        "cast_fix": {},
        "rewrites": [
            ("save just leather enough to make one pair of shoes.",
             "save just leather enough to make one pair of shoes.\n\nThe shoemaker and his wife had one child, "
             "whose name was {name}. {name} swept the shop, and sorted the nails, and loved to sit by the bench "
             "and watch the leather being cut."),
            ("The wife liked the thought; so they left a light burning, and hid themselves in a corner",
             "The wife liked the thought, and {name} begged to stay up too; so they left a light burning, and all "
             "three of them hid themselves in a corner"),
            ("and could not take his eyes off them.",
             "and could not take his eyes off them; and {name} had to hold {his} breath so as not to laugh out loud."),
            ("@wife: The next day the wife said to the shoemaker. “These little wights have made us rich, and we "
             "ought to be thankful to them, and do them a good turn if we can. I am quite sorry to see them run "
             "about as they do; and indeed it is not very decent, for they have nothing upon their backs to keep "
             "off the cold. I’ll tell you what, I will make each of them a shirt, and a coat and waistcoat, and a "
             "pair of pantaloons into the bargain; and do you make each of them a little pair of shoes.”",
             "@child: The next day {name} said to {his} mother and father: “These little elves have made us rich, "
             "and we ought to be thankful to them, and do them a good turn if we can. They have nothing upon their "
             "backs to keep off the cold! Mother, you could make each of them a shirt, and a coat and waistcoat; "
             "and Father, you could make each of them a little pair of shoes.”"),
            ("The thought pleased the good cobbler very much;", "The thought pleased the good cobbler and his wife very much;"),
            ("The good couple saw them no more; but everything went well with them from that time forward, as "
             "long as they lived.",
             "The good couple saw them no more; but everything went well with them from that time forward, as "
             "long as they lived. And every Christmas Eve after that, {name} left a pair of tiny shoes by the fire, "
             "just in case.\n\n[pause 1.5]\n\n@@narrator: Goodnight, {name}. Sleep tight."),
        ],
        "preview": [("The shoemaker and his wife had one child", "The shoemaker and his wife had one child"),
                    ("One evening, about Christmas-time", "One evening, about Christmas-time"),
                    ("As soon as it was midnight", "so as not to laugh out loud.")],
    },
}

NAME_RX = re.compile(r"^[^\W\d_]+(?:[ '’\-][^\W\d_]+)*$")


def clean_name(raw: str, max_len: int = 24) -> str:
    """A child's first name (or two): letters with single spaces, hyphens or apostrophes."""
    s = unicodedata.normalize("NFC", " ".join((raw or "").split()))[:max_len].strip(" -'’")
    if not s or not NAME_RX.match(s):
        raise ValueError("Please use letters only for the name (hyphens and apostrophes are fine).")
    return s if any(c.isupper() for c in s) else s.title()


def clean_from(raw: str, max_len: int = 40) -> str:
    s = unicodedata.normalize("NFC", " ".join((raw or "").split()))[:max_len].strip()
    if s and not re.fullmatch(r"[^\W_][\w '’\-.,&]*", s):
        raise ValueError("Please keep the dedication to letters and simple punctuation.")
    return s


def _blocks(src: str):
    return re.split(r"\n\s*\n", src.strip())


def personalize(tale: str, name: str, pronouns: str = "she", voice: str | None = None,
                gift_from: str = "", say_as: str = "", preview: bool = False) -> str:
    """Return a ready-to-render .story script with the child written in as the hero."""
    if tale not in TALES:
        raise ValueError("Unknown tale.")
    if pronouns not in PRONOUNS:
        raise ValueError("Pronouns must be she, he or they.")
    spec = TALES[tale]
    display = clean_name(name)
    spoken = clean_name(say_as) if say_as else display  # "say it like" spelling for the voice
    gift_from = clean_from(gift_from)
    voice = voice if voice in VOICES else DEFAULT_VOICE[pronouns]
    fill = {"name": spoken, **PRONOUNS[pronouns]}

    src = (SCRIPTS / f"{tale}.story").read_text()
    _, front, body = src.split("---", 2)
    meta = yaml.safe_load(front)

    # --- the story: rewrites apply only from the hero's first scene onward
    i = body.index(spec["from"])
    head, tail = body[:i], body[i:]
    for old, new in spec["rewrites"]:
        n = tail.count(old)
        if n != 1:
            raise RuntimeError(f"{tale}: rewrite anchor found {n} times: {old[:60]!r}")
        tail = tail.replace(old, new.format(**fill))
    old_h, new_h = spec["heading"]
    if head.count(old_h) != 1:
        raise RuntimeError(f"{tale}: heading not found")
    head = head.replace(old_h, new_h.format(**fill))
    # the host's history lesson becomes a dedication
    dedication = f"@@host: This story is for {spoken}." + (f"\n\n@@host: With love, from {gift_from}." if gift_from else "")
    host_blocks = [b for b in _blocks(head) if b.startswith("@@host:")]
    if host_blocks:
        head = head.replace(host_blocks[0], dedication, 1)
        for b in host_blocks[1:]:
            head = head.replace(b + "\n", "", 1)
    body = head + tail

    # --- cast: the child gets a natural young voice and their own name in the read-along
    cast = meta["cast"]
    cast[spec["hero"]] = {"voice": VOICES[voice], "speed": 1.0, "room": "booth", "wet": 0.1}
    for k, v in spec["cast_fix"].get(voice, {}).items():
        cast[k]["voice"] = v
    meta.setdefault("labels", {})[spec["hero"]] = display
    meta["title"] = f"{spec['title']}, for {display}"
    meta["featured"] = False
    for k in ("blurb", "caption", "order", "shelf"):
        meta.pop(k, None)

    if preview:
        body = _preview(body, spec["preview"], spoken)
    return "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, width=200) + "---\n" + body


def _preview(body: str, spans, spoken: str) -> str:
    """Dedication and title, then the child's key passages (each with the cues that set it up),
    then a teaser for the full story."""
    blocks = _blocks(body)
    is_cue = lambda b: all(l.strip().startswith(("[", "//")) for l in b.splitlines() if l.strip())
    h = next(i for i, b in enumerate(blocks) if b.startswith("# "))
    while h + 1 < len(blocks) and is_cue(blocks[h + 1]):
        h += 1
    keep = list(range(h + 1))
    for first, last in spans:
        a = next(i for i, b in enumerate(blocks) if first in b)
        while a - 1 > h and is_cue(blocks[a - 1]):  # keep the beds and music that set up the scene
            a -= 1
        z = next(i for i, b in enumerate(blocks) if last in b)
        keep += [i for i in range(a, z + 1) if i not in keep]
    teaser = ["[pause 1.2]", f"@@host: And what happens next? That's in {spoken}'s story.",
              "[sfx sparkle length=2.5 vol=-15]", "[pause 3]",
              "[stop amb fade=4]\n[stop music fade=5]\n[stop clock fade=3]\n[stop fire fade=3]"]
    return "\n\n".join([blocks[i] for i in keep] + teaser) + "\n"


def tales_for_web():
    return [{"slug": k, "title": v["title"], "role": v["role"]} for k, v in TALES.items()]
