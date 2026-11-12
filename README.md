# StoryBook

Full-cast audiobooks of public-domain classics. Each one has its own soundscape and score,
made in the spirit of *Fall of Civilizations*: a narrator who draws you in, a separate voice
for every character, and weather, rooms and music built for that story alone.

The website is laid out like an old illustrated book bound in green cloth. It has a title page
with a watercolour frontispiece, a table of contents, and a **featured tale** (Joseph Jacobs's
*The Three Little Pigs*) set as a two-page spread with its plate on the left and a
read-along transcript that follows the voice on the right. Then come two chapters of
**plates**, *The Fairy Tales* and *Tales for After Dark*, and a **Studio** where anyone can
paste or upload a manuscript and get a finished, mastered audiobook back.

```
python -m storybook serve      # → http://127.0.0.1:8000
```

## What's in the box

### The Fairy Tales

| Episode | Source | What to listen for |
| --- | --- | --- |
| **The Three Little Pigs** *(featured)* | Jacobs, 1890 | Three knocks, the wolf's huffing and puffing, straw and sticks collapsing, a butter-churn rolling downhill |
| **The Elves and the Shoemaker** | Grimm, 1812 | A fire, a clock striking midnight, a music box playing Brahms's lullaby, and tiny hammers |
| **Little Red-Cap** | Grimm, 1812 | Birdsong and a path through the wood. The music darkens when the wolf says good day |
| **Hansel and Gretel** | Grimm, 1812 | Crickets at night, a gingerbread house, the oven door, a river and a white duck |
| **Rumpelstiltskin** | Grimm, 1812 | The spinning wheel that turns straw into gold, a fire in the hills, the court jeering |
| **The Frog-Prince** | Grimm, 1812 | The golden ball dropping into the spring, a wet knock at the door, the spell breaking |
| **The Emperor's New Clothes** | Andersen, 1837 | Empty looms clattering, a procession with horns and drums, one small voice in the crowd |
| **The Real Princess** | Andersen, 1835 | Thunder and rain at the city gate, then twenty feather beds and a pea |
| **The Little Match Girl** | Andersen, 1845 | Snow wind, a match flaring, a carol on the music box, bells at New Year |

### Tales for After Dark

| Episode | Source | What to listen for |
| --- | --- | --- |
| **The Tell-Tale Heart** | Poe, 1843 | A heartbeat that gets faster and louder until it fills the mix; the narrator speeds up with it |
| **The Masque of the Red Death** | Poe, 1842 | A slightly detuned waltz behind iron gates, and an ebony clock that silences the revel |
| **The Sack of Rome** | Gibbon, *Decline and Fall*, ch. XXXI | A documentary-style frame, Gothic war horns, a burning city, Alaric's river grave |

The finished MP3s (with chapter markers) and the read-along timings are in `site/audio/`.

## How it works

```
scripts/*.story ──► storybook.script   parse the production script (cast, cues, text)
                ──► storybook.voices   Kokoro-82M neural TTS, run locally; voice blends,
                                       pitch, tone and room per character; phrase-level pacing
                ──► storybook.sounds   procedural ambience and effects (wind, rain, fire,
                                       clocks, bells, chains, heartbeats, horns, crowds…)
                ──► storybook.music    additive-synthesis score: choir/string pads, cello
                                       drones, music box, a ghostly waltz
                ──► storybook.render   timeline, side-chain ducking under speech, convolution
                                       reverb, two-pass EBU R128 mastering → MP3 + chapters
```

No sound is sampled. Everything is synthesised from noise and oscillators, so the project
has no licensing tangles and every render is reproducible.

### The `.story` format

```text
---
title: The Tell-Tale Heart
author: Edgar Allan Poe
cast:
  narrator: {voice: "bm_george*0.6+bm_fable*0.4", speed: 0.93, room: room, wet: 0.08}
  oldman:   {voice: bm_daniel, pitch: -1.5, tone: thin, room: chamber, wet: 0.25}
---
[bed amb roomtone creaks=0.6 vol=-2 fade=4]     # start/replace a layer (ducked under voices)
[bed heart heartbeat bpm=72:150 gain=0.35:1]    # parameters can ramp across the span
[sfx knock count=3 room=hall vol=-8 wait=1]      # one-shot; wait=1 lets it finish first
[voice narrator speed=1.08]                      # direct the performance as it goes
[stop heart fade=0.05]

Plain paragraphs are narration.
@oldman: “Quoted words” go to the old man; the rest stays with the narrator.
@@host: A whole paragraph in one voice.
```

Beds: `wind rain fire clock watch heartbeat roomtone crowd river crickets battle tinnitus
birds spinning` plus music `dread elegy hearth waltz music_box carol_voice title_theme fairytale`
(`music_box tune=lullaby` plays Brahms's *Wiegenlied*; `fairytale key=F|G|D|Am` is harp over strings).
Effects: `knock door creak footsteps bell chime house_bells chains wail boom swell sting
thunder horn war_drums clash bolt quill lantern heartbeat_once tapping sparkle splash
huff collapse roll`.

Front matter can also set `shelf: fairy` (which chapter of the library the tale goes in), `art`
(a plate: `land_*` for a landscape, otherwise a wash from `assets/paint`) and `featured: true`.

### The Studio's auto-director

`storybook/director.py` turns an arbitrary manuscript into a `.story` script with no
network access and no language model. It strips Project Gutenberg boilerplate and finds
chapter headings. It attributes dialogue (`said Scrooge`, `Scrooge said`, turn-taking,
he/she), casts distinct voices and guesses a mood from the vocabulary. It also cues
effects where the prose names a sound. In the browser you can recast any part, preview
voices, choose the weather and pace, and download the generated script to fine-tune it.

### Casting

Character voices sound most like actors when they are left alone. Kokoro grades its own voices
(see its `VOICES.md`): `af_heart` A, `af_bella` A-, `bf_emma` and `af_nicole` B-, then `am_fenrir`,
`am_michael`, `am_puck`, `af_kore`, `af_sarah` at C+. The episodes cast characters from those at their
natural pitch, and tell them apart by voice and pace. Formant-preserving `pitch:` shifts, `tone: thin`
and `a*0.6+b*0.4` blends still work, but they make speech sound processed, so the scripts no longer
use them on characters. The Studio's auto-director casts from the same pools, best voices first.

## Running it

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m storybook render scripts/tell_tale_heart.story   # models download on first use (~350 MB)
python tools/build_catalog.py                               # refresh the website's library
python -m storybook serve
```

`python tools/paint.py` regenerates the watercolour textures: layered glazes, pigment pooling
at the edges, granulation and back-run blooms, all from numpy. `python tools/landscape.py`
paints the landscape plates in `site/assets/land/` with the same glazes, back to front: a
wet-in-wet sky, ridges of hills that get greener as they come nearer, fir and beech tree lines,
cottages, castles and towns, with lit windows, moons and snow lifted out to the white of the paper.

The site in `site/` also works as plain static files (for example on GitHub Pages) for listening.
The Studio needs the Python server.


### A promo video

`python tools/tiktok.py` cuts a 38-second vertical video (1080×1920, for TikTok, Reels or Shorts) into
`dist/`. It plays the wolf at the straw house with a word-by-word read-along caption, swaps in a
second painting of the blown-down house (`python tools/landscape.py pigs_fallen`) as it collapses,
then shows a montage of the plates and a title-page end card. The fonts download into `.cache/` on first run.

`python tools/avatar.py` paints a matching 1080×1080 profile picture into `dist/`: a watercolour
landscape rising out of an open book, in a cream roundel on green cloth, kept inside the circle that
the apps crop avatars to. It also writes a preview sheet at 200, 110 and 56 px.

## Credits

Texts: [Project Gutenberg](https://www.gutenberg.org) (public domain). Voices:
[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (Apache-2.0) via
[kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx). Fonts: IM Fell (Igino Marini),
Spectral, Caveat (SIL OFL).

## Deploying to Fly.io

The repo ships a `Dockerfile` (voice model baked in, so cold starts are quick) and a `fly.toml`.

```bash
fly apps create storybook-audio      # or any free name; match `app` in fly.toml
fly deploy --ha=false                # keep to ONE machine: Studio jobs live in its memory
```

The VM is `shared-cpu-4x` with 4 GB, which renders Studio audio at roughly real time.
It stops when idle and wakes on the next request. A finished Studio recording lives on the
machine's disk until the machine is replaced. For permanent storage, mount a volume at `/data`.
