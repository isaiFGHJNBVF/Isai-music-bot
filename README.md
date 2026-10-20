# 🌸 Isai Music Bot

> An aesthetic, lightweight Discord music bot powered by **Discord.js**, **Poru**, and **Lavalink**.

Isai (இசை) is a music bot with slash commands, prefix commands, an interactive music player panel, queue management, loop controls, and bass boost.

## ✨ Features

- 🎵 Play music using song searches and supported media URLs
- 🔎 YouTube search autocomplete for the `/play` command
- 🎛️ Interactive player panel with pause/resume, skip, previous, stop, loop, shuffle, bass, and queue buttons
- 📜 Queue viewing, shuffling, clearing, and track removal
- 🔁 Repeat the current track or the entire queue
- 🎧 Bass boost using Lavalink filters
- 🖼️ Track thumbnails and a live progress display
- ⚡ Slash commands and prefix commands
- 🌸 Soft sakura-pink embeds and an aesthetic help menu
- 🛡️ Basic process-level error logging

## 🧰 Requirements

- **Node.js 18 or newer**
- A Discord bot application and bot token
- A reachable **Lavalink v4-compatible server** with a source/plugin configuration that supports the media you want to play
- The packages listed in `package.json`

> **Note:** Poru connects to Lavalink for audio playback. Installing the npm packages alone does not provide a Lavalink server. Configure your own server or use a trusted provider. Media-source availability depends on the Lavalink plugins and server configuration.

## 📦 Installation

1. **Download or clone** this project and open a terminal in its folder.

2. **Install dependencies:**

   ```bash
   npm install
   ```

3. **Create a `.env` file** in the project root:

   ```env
   TOKEN=your_discord_bot_token

   LAVALINK_HOST=your_lavalink_host
   LAVALINK_PORT=2333
   LAVALINK_PASSWORD=your_lavalink_password
   LAVALINK_SECURE=false
   ```

   Replace the example values with your actual bot and Lavalink credentials. Use `LAVALINK_SECURE=true` when your Lavalink connection requires TLS.

   The code has fallback Lavalink connection values, but configuring your own valid server is recommended.

4. **Configure your Discord bot:**
   - In the Discord Developer Portal, create an application and add a bot.
   - Copy the bot token into `TOKEN` in `.env`. Never share or commit this token.
   - Enable **Message Content Intent** in the bot's privileged gateway intents if you want prefix commands to work.
   - Invite the bot to your server with the permissions it needs, including viewing channels, sending messages, embedding links, using application commands, and connecting to and speaking in voice channels.

5. **Start the bot:**

   ```bash
   npm start
   ```

   This runs `node index.js`.

## ⚙️ Environment variables

| Variable | Purpose |
| --- | --- |
| `TOKEN` | Discord bot token; required |
| `LAVALINK_HOST` | Lavalink server hostname |
| `LAVALINK_PORT` | Lavalink server port |
| `LAVALINK_PASSWORD` | Lavalink authentication password |
| `LAVALINK_SECURE` | Set to `true` to use a secure connection; otherwise use `false` |

## 🎮 Commands

The default prefix is **`i`**. For example, `iplay` or `i play` is not required—the command format is `iplay <song>`.

### Music and playback

| Slash command | Prefix command | Purpose |
| --- | --- | --- |
| `/play query:<song or URL>` | `iplay <song or URL>` or `ip <song or URL>` | Play a search result or URL |
| `/pause` | `ipause` | Pause playback |
| `/resume` | `iresume` or `ir` | Resume playback |
| `/skip` | `iskip`, `is`, or `inext` | Skip the current track |
| `/previous` | `iprevious`, `iprev`, or `iback` | Return to the previous track recorded in the session |
| `/stop` | `istop` | Stop playback and clear the queue |
| `/connect` | `iconnect`, `ic`, `ijoin`, or `ij` | Join your voice channel |
| `/disconnect` | `idisconnect`, `idc`, `ileave`, or `il` | Leave the voice channel |

### Queue and audio controls

| Slash command | Prefix command | Purpose |
| --- | --- | --- |
| `/queue` | `iqueue` or `iq` | View the current track and queued tracks |
| `/shuffle` | `ishuffle` or `ish` | Shuffle queued tracks |
| `/clear` | `iclear`, `iclr`, or `iclean` | Clear the queue |
| `/remove target:<number or title>` | `iremove <number or title>`, `irm`, or `idel` | Remove a queued track |
| `/loop` | `iloop`, `irepeat`, `irep`, or `ilp` | Choose loop mode |
| `/bass enabled:<true/false>` | `ibass <on/off>` or `ibb` | Toggle bass boost |

### Help and owner commands

| Slash command | Prefix command | Purpose |
| --- | --- | --- |
| `/help` | `ihelp` or `ih` | Show the help menu |
| `/say content:<message>` | `isay <message>` | Send a message as the bot (owner only) |
| `/dm target:<user> content:<message>` | `idm <user> <message>` | DM a user (owner only) |
| `/status type:<online/idle/dnd>` | `istatus <online/idle/dnd>` | Change the bot's presence status (owner only) |

Owner-only commands are restricted to the user IDs configured in `index.js`. Change the owner IDs in the source code if necessary.

> Prefix commands require the Message Content Intent. Slash commands are registered by the bot when it becomes ready. Registration and visibility can take time, and the bot needs the appropriate application-command permissions.

## 🎛️ Player panel

When a track starts, Isai posts a music panel with track details, artwork when available, duration, progress, loop mode, bass status, and queue count.

The panel buttons provide:

- Previous track
- Pause or resume
- Skip
- Stop and clear the queue
- Cycle through loop modes
- Shuffle the queue
- Toggle bass boost
- View upcoming tracks

The progress display refreshes periodically while playback is active.

## 📁 Project structure

```text
isai-music-bot/
├── index.js
├── package.json
├── package-lock.json
└── .env
```

- `index.js` — bot setup, commands, Lavalink/Poru events, and player controls
- `package.json` — project metadata, scripts, and dependencies
- `package-lock.json` — exact dependency versions installed by npm
- `.env` — private bot and Lavalink configuration; do not commit this file

## ☁️ Hosting

On a Node.js hosting platform:

1. Upload the project files.
2. Select **Node.js 18 or newer**.
3. Install dependencies using `npm install` (or the host's dependency installation step).
4. Add the environment variables from the table above in the host's environment-variable settings.
5. Ensure the Lavalink server is reachable from the bot host.
6. Set the startup command to:

   ```bash
   npm start
   ```

Keep the process running and check the logs for Discord login and Lavalink connection messages.

## 🛠️ Troubleshooting

- **Bot does not log in:** Check that `TOKEN` is correct and that the token has not been reset.
- **Prefix commands do not work:** Enable Message Content Intent in the Developer Portal and ensure `TOKEN` is set correctly.
- **Slash commands do not appear:** Check the bot's application-command permissions, invite scopes, and startup logs. Allow time for command registration to propagate.
- **Bot joins voice but music does not play:** Verify the Lavalink host, port, password, TLS setting, and server availability.
- **Search returns no tracks or loading fails:** Check Lavalink source/plugin configuration and server logs. Not every source or URL is supported by every Lavalink setup.
- **Bot cannot join or speak:** Check its channel permissions and confirm that the user issuing the command is in a voice channel.
- **Bass boost has no effect:** Confirm that the Lavalink server and audio filters support equalizer filters.

## 🔐 Security

- Never publish your Discord bot token or Lavalink password.
- Keep `.env` out of public repositories. Add it to `.gitignore`.
- If a token or password is exposed, rotate it immediately.
- Owner-only commands depend on the owner IDs configured in `index.js`.

Suggested `.gitignore`:

```gitignore
node_modules/
.env
```

## 📄 License

No license is specified in the provided project configuration. Add a `LICENSE` file if you intend to publish the project and want to define how others may use, modify, or redistribute it.

---

Made with ♡ by **Isai** 🌸
