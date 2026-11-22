# The daily StoryBook TikTok

Instructions for the scheduled task in the Claude desktop app that runs on the owner's computer each
morning. It makes one new 30–48 second vertical video (1080×1920) from a StoryBook episode, then uses
Claude in Chrome to stage it on the StoryBook TikTok account. **It stops before pressing Post.** The owner
reviews it and posts it.

Never post, schedule or publish anything, and never change account settings. Don't commit or push to the
repository, and don't change the live site.

## 0. Setup (the first run does this; later runs just check it)

- Repository: `~/StoryBook`. If it's missing, run `git clone https://github.com/DenverDawgs18/StoryBook ~/StoryBook`.
  Each run, `git fetch` and check out the repository's default branch, then `git pull`.
- Python: `python3 -m venv ~/StoryBook/.venv && ~/StoryBook/.venv/bin/pip install -q numpy scipy pillow pyyaml soundfile`.
  Use `~/StoryBook/.venv/bin/python` for everything below.
- ffmpeg must be on PATH. On a Mac use `brew install ffmpeg`; on Windows use `winget install ffmpeg`.
- The video tools download the site's fonts into `.cache/fonts` the first time they run.
- The rendered episodes are already in the repo (`site/audio/<story>.mp3` plus a timings `.json`), so no
  text-to-speech is needed.

## 1. What has already been made: don't repeat these

The log `~/StoryBook/dist/tiktok_log.md` (not in git) lists every video this task has made. Read it first,
and append a line to it when you finish (step 5). Before the task existed, these videos were made:

| Date | Story | Hook / angle | Scene used |
| --- | --- | --- | --- |
| Nov 13 | The Three Little Pigs | "Bedtime stories, performed." | The wolf at the straw house: knock, "chinny chin chin", huffing, the house collapses |
| Nov 13 | Personal (Mia) | "POV: the bedtime story knows your kid's name" | Mia's preview: dedication, "Mia, Mia, let me come in", huffing at the brick house |
| Nov 14 | The Elves and the Shoemaker | "He went to bed with nothing." / "He woke up to finished shoes." | Shoes appear, "sit up and watch tonight", midnight, the dwarfs, tap tap tap, dancing away |
| Nov 14 | The Masque of the Red Death | "He locked the plague outside." / "At midnight, it joined the party." | Gates sealed, midnight chime, the masked figure, Prospero, closing boom |
| Nov 14 | The Masque of the Red Death | "A masked ball. An ebony clock." / "Every hour, the dancing stopped." | The ebony clock, the gaunt figure, "a thief in the night" |
| Nov 15 | Little Red-Cap | (details not recorded) | Probably the famous "what big ears…" scene |
| Nov 16 | The Frog-Prince | "She promised a frog anything." / "Then he knocked at her door." | The ball in the spring (splash), the bargain, the knock, "Open the door, my princess dear", the king |
| Nov 17 | Rumpelstiltskin | "Guess his name in 3 days." / "Or he takes her baby." | Three days' grace, the song by the fire, the guesses, "Some witch told you that!", the STAMP |

## 2. Pick today's story

Let `n` be the number of days from 2026-11-23 to today's date in America/New_York. Then
`slot = n mod 16` (floor modulo, always 0–15) and `cycle = n // 16` (floor division).
Today's story is `ROTATION[slot]`:

0. the_travelling_musicians
1. little_red_cap
2. the_frog_prince
3. personal (see below)
4. rumpelstiltskin
5. the_fisherman_and_his_wife
6. the_little_match_girl
7. the_emperors_new_clothes
8. siege_of_alesia
9. hansel_and_gretel
10. personal (see below)
11. the_real_princess
12. the_three_little_pigs
13. elves_and_the_shoemaker
14. tell_tale_heart
15. masque_of_the_red_death

**personal** is the $6 personalised-story offer, twice per rotation because it is what sells. Use
`site/audio/personal/the_three_little_pigs_for_mia_preview` on slot 3 and
`site/audio/personal/elves_and_the_shoemaker_for_leo_preview` on slot 10 (if a preview has no unused scene
left, use the other one). The end card is about putting your own child in the story, for example
"Put your child / in the story." with the sub-line "free preview · $6 · link in bio". From Nov 27 to Dec 24,
hooks may lean on the gift angle (a story with a dedication from Grandma), but must stay true to the preview.

Choose which part of the story to use: the first of these that the log and section 1 don't already show
for this story.
- **The most famous scene.**
- **The build-up and setup from the first half.**
- **The climax and ending.**

Never reuse a hook or scene listed in section 1 or in the log. If today's natural choice was already
used, pick another scene from the same story. The only exception is in section 6: if today's story truly
has no unused scene left, reuse its least-recently used scene with a new hook, and say so in the heads-up.

## 3. Write the clip sheet

The format is documented at the top of `tools/tiktok_story.py`, and
`tools/clips/elves_and_the_shoemaker.json` is the worked example. Read the episode's timings JSON
(paragraphs → segments (speaker) → phrases `[text, start, end]`, in seconds of the source audio). Write
`dist/clip_<story>_<YYYY-MM-DD>.json` with `"name": "<story>_<YYYY-MM-DD>"`.

- **Hook (shown for the first 2 s):** two short lines, under about 28 characters each. The second line is a
  twist or a promise. It must be true to the story.
- **Excerpt:** 3–7 cuts that skip linking narration but keep the story easy to follow.
  - Cut at phrase boundaries: start about 0.2 s before a phrase and end about 0.2 s after it.
  - Prefer phrases shorter than about 8 s. Longer ones overflow the caption area.
- **Ending:** a last cut of the episode's closing music, so the final line isn't covered by the end card.
  The end card takes the last 3.5–4.5 s and ends with "free · link in bio".
- **Picture:** the plate is the story's `art` from `scripts/<story>.story` (a file in `site/assets/land/`).
  For the personal slot use `land_pigs` or `land_cottage`. The camera pushes in on the action and eases
  back out at the end.
- **Moments and effects:**
  - "moments": 1–3 handwritten words at the big sound beats.
  - "shake": for impacts only.
  - "highlight": 1–3 words to ink in green.
  - "labels": names the speakers in plain words.
- **Sound beats:** find them from the measured loudness, not from the `[sfx …]` cues in the script
  (some effects are too quiet to use). Run `ffmpeg -i <mp3> -ac 1 -ar 16000 -f f32le -`, take the RMS in
  0.1 s windows and look for the clear jumps.

## 4. Render and check

1. Render about six stills with `python tools/tiktok_story.py dist/clip_….json 1.5 8 15 …` and look at
   them. Fix overlapping text, bad crops, or captions that overflow or cover the end card.
2. Render the video with `python tools/tiktok_story.py dist/clip_….json`. It writes `dist/tiktok_<name>.mp4`.
3. Verify:
   - the duration is 30–48 s and the size is 1080×1920 (use ffprobe);
   - every shake or moment is within 0.3 s of its sound onset in the finished file;
   - the decoded peak is below 0 dBFS.

   Fix and re-render if anything fails. If a render fails twice, stop and tell the owner what failed.

## 5. Stage it on TikTok, but don't post it

1. Append to `dist/tiktok_log.md`: the date, story, hook, the scene used, and the file name.
2. Write the post caption: 1–2 short lines plus 4–6 relevant hashtags (for example #bedtimestories
   #fairytales #storytime #audiobook, plus one for the tale).
3. In Chrome (Claude in Chrome), open https://www.tiktok.com/tiktokstudio/upload.
   - **Check you're signed in to the StoryBook account.** If it's a different account, or you're signed out, stop
     and tell the owner. Don't sign in or switch accounts yourself.
   - Attach `~/StoryBook/dist/tiktok_<name>.mp4` with the page's file picker. If you can't attach a file
     from disk, stop and tell the owner where the file is.
   - Wait for the upload to finish, then paste the caption into the description box. Leave every other setting
     as it is.
   - **Do not click Post, Schedule, or anything that publishes.** Leave the tab open on the finished draft.
4. Tell the owner the video is ready to review and post. Include the story, the hook, the caption, and a
   suggested bio link:
   `https://storybook-audio.fly.dev/tales/<story>.html?utm_source=tiktok&utm_content=<YYYY-MM-DD>`. For the
   personal slot, use `/personal.html?utm_source=tiktok&utm_content=personal-<YYYY-MM-DD>` instead.

## 6. Look ahead: warn before the stories run out

Every run, after staging the video, check the next 3 days of the rotation (slots `n+1`, `n+2`, `n+3`).

1. For each of those stories, read its timings JSON. List the scenes that would make a good 30–48 s
   video: dialogue plus a sound moment, at least 3 phrases, and not the same scene as anything in
   section 1 or in `dist/tiktok_log.md`.

Flag a story as **running low** if it has no unused good scene left, or only one. Then end your message
with a clearly marked heads-up, for example:

> **Heads-up: running low on stories.** In 2 days (Nov 21) Hansel and Gretel has no unused scene left, and
> The Real Princess (Nov 22) has one. Ask Claude to make more episodes before then.

Name each story, the date it comes up, and how many unused scenes it has left. If nothing is running low,
say so in one short line ("Stories are fine for the next 3 days."). Don't skip a day or reuse a scene to
get around running out. If today's own story has no unused scene left, still make today's video from the
least-recently used scene, and say so in the heads-up.
