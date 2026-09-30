# Teleprompter

A free teleprompter for your iPhone. The script scrolls right under the front camera, you record one section at a time, and every take saves straight to your Mac, checked and ready to edit.

No app to install and no account. A small Python server on your Mac does the work, and the iPhone uses it through Safari over your home Wi-Fi. You write scripts and manage takes in the **Studio**, a page on your Mac.

## What it does

- **Reads under the lens.** The script scrolls past a reading line near the top of the screen, so your eyes stay close to the camera.
- **Records one section at a time.** Split your script into sections with `## Heading` lines. Press record and the take starts at the top of that section and stops when the next heading comes up.
- **Retake just the bit you fluffed.** After each take you can watch it back, then **Retake**, **Keep, next** or **Discard**. Earlier takes are never overwritten.
- **Saves to your Mac while you film.** Video goes to the Mac a second at a time, so a long take doesn't fill up the phone or run it out of memory.
- **Checks every take.** As soon as a take lands, the Mac opens the file and reports the length, resolution and whether there's sound, or tells you exactly what's wrong.
- **Save to Photos.** Send any take from the Mac to your iPhone's camera roll, ready to post.
- **Studio on the Mac.** Write and edit scripts with a live word count and read time. See every take by section, then play it, keep it, download it or show it in Finder.
- **Remembers your settings.** Speed, text size, column width and where the reading line sits.

Takes are organised by script and section:

```
~/Movies/Teleprompter/my-script/
  01-intro/take-01.mp4, take-02.mp4
  02-the-problem/take-01.mp4
  choices.json        which take you kept for each section
```

## What you need

- A Mac with Python 3.8 or newer. The one that comes with Xcode's command line tools works. No packages to install.
- `openssl`, which macOS already has.
- `ffmpeg` and `ffprobe` for the take checks. Optional: without them, takes still save but aren't checked.
- An iPhone on the same Wi-Fi as the Mac.

## Set it up

1. **Download it.** Click **Code → Download ZIP** above and unzip it, or run `git clone https://github.com/jameselle/teleprompter.git`.
2. **Double-click `Start Teleprompter.command`.** The first time, it makes the certificate your iPhone needs, then opens the **Studio** in your browser. Leave the Terminal window it opens running while you film.
   - If macOS says it can't be opened because it's from an unidentified developer, right-click the file, choose **Open**, then **Open** again. You only need to do this once.
3. **Connect your iPhone** from the Studio's **Connect iPhone** tab. It shows two QR codes.

**Step 1, once: let the iPhone trust your Mac.** iPhone Safari only allows the camera on a secure page, so the phone needs to trust your Mac's certificate.

1. Scan the first QR code with the iPhone camera and open it in **Safari** (Chrome can't install profiles). Tap **Allow**, then **Close**.
2. Settings → General → **VPN & Device Management** → **Teleprompter** → **Install**.
3. Settings → General → About → **Certificate Trust Settings** → turn on **Teleprompter Local CA**.

**Step 2: open the prompter.** Scan the second QR code, open it in Safari, and allow the camera and microphone. Then use Share → **Add to Home Screen** so it opens full screen like an app.

Next time, just double-click `Start Teleprompter.command` and open the prompter from your Home Screen.

<details>
<summary>Prefer the terminal?</summary>

```sh
./make-cert.sh     # once
python3 serve.py   # then open http://localhost:8792
```
</details>

## Your scripts

Write them in the Studio's **Scripts** tab. It shows the section count, word count, read time and any blanks you haven't filled in. Scripts are plain `.txt` files in `scripts/`, so you can use any editor, and there's an example in `scripts/example.txt`. To see a newly saved script on the phone, reload the prompter.

```
## Hook
Stop paying for a clipping app.
I built my own.

## The problem
Filming isn't the hard part. Everything after is.
```

- `## Name` starts a section. Each section is its own take.
- A blank line starts a new paragraph.
- Anything in `{{double braces}}` is highlighted, so you can spot the blanks you still need to fill in.

## Controls

| On the iPhone | On a Mac keyboard | What it does |
|---|---|---|
| ● Rec | `R` | 3‑2‑1, then record and scroll |
| Tap the text | `Space` | Pause or resume the scroll |
| Drag the text | Scroll wheel | Move the text by hand |
| − / + | `↑` / `↓` | Slower or faster, in words per minute |
| Section chips | `←` / `→` | Jump between sections |
| Takes | | See, play, keep, discard or save to Photos |
| ⚙ | | Script, camera, mic, text size, width, reading line, mirror, one section or whole script |

## Turn your takes into clips

[Clipper](https://github.com/jameselle/clipper), also free, joins your kept takes in script order and cuts them into short vertical clips with pop captions, hooks and QA:

```sh
npm run clip -- from-teleprompter ~/Movies/Teleprompter/<script-folder>
```

## Security

- **The phone trusts one certificate only.** `make-cert.sh` creates a fresh certificate authority, uses it to sign your Mac's one certificate, and then **deletes its private key**. The profile on your phone can't be used to vouch for any other site, because the key that could do it no longer exists. Run the script again and you'll need to install the new profile.
- **The app needs a key.** `serve.py` creates a random key in `certs/token`, and the prompter QR code in the Studio includes it. Other devices on your Wi-Fi can load the page but can't read your scripts, see your takes or save files.
- **The Studio only opens on the Mac.** Other devices get a refusal, and it also refuses requests that arrive under another site's address, so a web page can't reach it through your browser.
- **Everything stays local.** Nothing goes to the internet. The page does load a font from Google Fonts, and the Studio loads a QR code library from cdnjs.
- **Keep `certs/` private.** It's in `.gitignore`. Never commit it.

To remove the certificate from the phone: Settings → General → VPN & Device Management → Teleprompter → Remove Profile.

## Settings

| Environment variable | Default | What it sets |
|---|---|---|
| `TELEPROMPTER_PORT` | `8791` | The HTTPS port for the prompter. The Studio uses this port plus 1. |
| `TELEPROMPTER_OUT` | `~/Movies/Teleprompter` | Where takes are saved |

## Good to know

- The phone finds your Mac by its `.local` name, so a change of Wi-Fi address doesn't break it. If you rename the Mac, run `./make-cert.sh` again.
- iPhone Safari records H.264 MP4. The files carry a rotation flag, so they play upright everywhere, and most editors handle them fine.
- If the Mac loses the connection partway through a take, everything up to that point is kept and the app tells you where it stopped.
- It also runs in a desktop browser. On a Mac with Continuity Camera, pick your iPhone from the Camera menu and read from the Mac's screen.

## Licence

MIT. See [LICENSE](LICENSE).
