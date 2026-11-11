# StoryBook

Full-cast audiobooks of public-domain classics. Each one has its own soundscape and score,
made in the spirit of *Fall of Civilizations*: a narrator who draws you in, a separate voice
for every character, and weather, rooms and music built for that story alone.

The website is painted in watercolour, in greens. It has a **featured story**
(Poe's *The Tell-Tale Heart*) with a read-along transcript that follows the voice, a
**library** of further episodes, and a **Studio** where anyone can paste or upload a
manuscript and get a finished, mastered audiobook back.

```
python -m storybook serve      # → http://127.0.0.1:8000
```

## What's in the box

| Episode | Source | What to listen for |
| --- | --- | --- |
| **The Tell-Tale Heart** *(featured)* | Poe, 1843 | A heartbeat that gets faster and louder until it fills the mix; the narrator speeds up with it |
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

Beds: `wind rain fire clock watch heartbeat roomtone crowd river crickets battle tinnitus`
plus music `dread elegy hearth waltz music_box carol_voice title_theme`.
Effects: `knock door creak footsteps bell chime house_bells chains wail boom swell sting
thunder horn war_drums clash bolt quill lantern heartbeat_once`.

### The Studio's auto-director

`storybook/director.py` turns an arbitrary manuscript into a `.story` script with no
network access and no language model. It strips Project Gutenberg boilerplate and finds
chapter headings. It attributes dialogue (`said Scrooge`, `Scrooge said`, turn-taking,
he/she), casts distinct voices and guesses a mood from the vocabulary. It also cues
effects where the prose names a sound. In the browser you can recast any part, preview
voices, choose the weather and pace, and download the generated script to fine-tune it.

## Running it

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m storybook render scripts/tell_tale_heart.story   # models download on first use (~350 MB)
python tools/build_catalog.py                               # refresh the website's library
python -m storybook serve
```

`python tools/paint.py` regenerates the watercolour textures: layered glazes, pigment pooling
at the edges, granulation and back-run blooms, all from numpy.

The site in `site/` also works as plain static files (for example on GitHub Pages) for listening.
The Studio needs the Python server.

## Credits

Texts: [Project Gutenberg](https://www.gutenberg.org) (public domain). Voices:
[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (Apache-2.0) via
[kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx). Fonts: IM Fell (Igino Marini),
Spectral, Caveat (SIL OFL).
