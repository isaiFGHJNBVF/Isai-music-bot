# ˗ˏˋ isai • aesthetic music companion ˎˊ˗ ☁️

A Discord music bot featuring both slash commands (`/`) and prefix commands (`i`), live aesthetic interactive control panels, playlist resolution, and built-in client platform spoofing.

---

## 🎧 Features

* **Dual Command System**: Every single command works both as a prefix command (`iplay`, `ipause`, etc.) and a slash command (`/play`, `/pause`, etc.).
* **Aesthetic Panel**: An interactive control deck with visual progress sliders and tactile buttons (`⏮️`, `⏯️`, `⏭️`, `🔁`, `⏹️`).
* **High Quality Playback**: Powered by `yt-dlp` audio extractors and Opus FFmpeg streaming.
* **Playlists & Mixes**: Pass any YouTube playlist or mix link; **isai** queues up the entire album effortlessly.
* **Bass Boost Filter**: Toggle frequency-adjusted warm bass directly with `/bass True`.
* **Platform Spoofing**: Built-in Discord Gateway spoofer configured for `vr`, `mobile`, and `normal` badges.
* **Owner Suite**: Hidden and restricted administrative tools (`say`, `dm`, `status`, `platform`).

---

## ✦ Commands Overview

| Prefix | Slash | Description |
| :--- | :--- | :--- |
| `iplay <query/url>` | `/play <query>` | Play audio from title search, YouTube, direct audio, or Spotify/playlist |
| `ipause` | `/pause` | Pause currently playing track |
| `iresume` | `/resume` | Resume the paused track |
| `iskip` | `/skip` | Skip over to the next song |
| `iprevious` / `iprev` | `/previous` | Play the previously played song from memory |
| `iconnect` / `ic` | `/connect` | Summons the bot into your current voice channel |
| `idisconnect` / `idc` | `/disconnect` | Disconnects the bot from voice |
| `istop` | `/stop` | Stops current playback and clears queue |
| `ishuffle` | `/shuffle` | Shuffles all songs in the waiting queue |
| `iqueue` / `iq` | `/queue` | Displays the queue with aesthetic formatting |
| `iremove <target>` | `/remove <target>` | Removes a track by queue number or title |
| `iclear` | `/clear` | Flushes all songs from the queue |
| `ibass <True/False>` | `/bass <enabled>` | Toggles bass booster equalizer on next track |
| `iloop` / `rep` | `/loop` | Opens loop menu (Track / Queue / Off) |
| `ihelp` | `/help` | Explains all available commands |

### 🔒 Owner Only Commands (`OWNER_IDS`)
* `isay <content>` / `/say` — Echoes text cleanly.
* `idm <user> <content>` / `/dm` — Direct messages a user on behalf of the bot.
* `istatus <online/idle/dnd>` / `/status` — Changes bot presence.
* `iplatform <vr/mobile/normal>` / `/platform` — Dynamically spoofs Discord client platform and reconnects socket.

---

## ⚙️ Prerequisites & Setup

1. **Install FFmpeg**:
   * **Ubuntu/Debian**: `sudo apt update && sudo apt install -y ffmpeg`
   * **macOS (Homebrew)**: `brew install ffmpeg`
   * **Windows**: Download executable from `gyan.dev` and add `ffmpeg/bin` to your System `PATH`.

2. **Clone & Install Dependencies**:
   ```bash
   pip install -r requirements.txt