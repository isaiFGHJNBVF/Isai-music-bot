import os
import sys
import re
import json
import base64
import asyncio
import random
from collections import deque
from typing import Optional, List, Dict

import aiohttp
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import yt_dlp

# ─────────────── Locate Pip-installed FFmpeg ─────────────── #

try:
    import imageio_ffmpeg
    FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
    print(f"╭ ⟢ Using pip FFmpeg binary: {FFMPEG_EXE}")
except Exception:
    FFMPEG_EXE = "ffmpeg"

# ─────────────── Configuration & Constants ─────────────── #

load_dotenv()
TOKEN = os.getenv("TOKEN")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
PREFIX = "i"
OWNER_IDS = [1377967442172579843, 774224543531270144]

PASTEL_PINK = 0xFAD2E1
PASTEL_LAVENDER = 0xDFCCF1

PLATFORM_PROPERTIES = {
    "normal": {
        "os": "Windows",
        "browser": "Discord Client",
        "device": "",
    },
    "mobile": {
        "os": "Android",
        "browser": "Discord Android",
        "device": "Pixel 8",
    },
    "vr": {
        "os": "Console",
        "browser": "Discord VR",
        "device": "VR-Headset",
    },
}

current_platform = "vr"

# ─────────────── Platform Spoofer Hook ─────────────── #

from discord.gateway import DiscordWebSocket

_orig_send_as_json = DiscordWebSocket.send_as_json

async def _patched_send_as_json(self, data):
    if isinstance(data, dict) and data.get("op") == 2:
        props = PLATFORM_PROPERTIES.get(current_platform, PLATFORM_PROPERTIES["normal"])
        if "d" in data and "properties" in data["d"]:
            data["d"]["properties"]["os"] = props["os"]
            data["d"]["properties"]["browser"] = props["browser"]
            data["d"]["properties"]["device"] = props["device"]
            data["d"]["properties"]["$os"] = props["os"]
            data["d"]["properties"]["$browser"] = props["browser"]
            data["d"]["properties"]["$device"] = props["device"]
    await _orig_send_as_json(self, data)

DiscordWebSocket.send_as_json = _patched_send_as_json

# ─────────────── Bot Initialization ─────────────── #

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or(PREFIX),
    intents=intents,
    help_command=None
)

# ─────────────── Audio & YTDL Setup ─────────────── #

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": False,
    "nocheckcertificate": True,
    "ignoreerrors": True,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

def get_ffmpeg_options(bass_boost: bool = False):
    before_opts = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
    if bass_boost:
        return {
            "before_options": before_opts,
            "options": '-vn -af "equalizer=f=60:width_type=h:width=50:g=14,equalizer=f=120:width_type=h:width=50:g=10"'
        }
    return {
        "before_options": before_opts,
        "options": "-vn"
    }

class Song:
    def __init__(self, data: dict, requester: discord.Member):
        self.title = data.get("title", "Unknown Track")
        self.url = data.get("url")
        self.webpage_url = data.get("webpage_url", "")
        self.duration = data.get("duration", 0)
        self.thumbnail = data.get("thumbnail", "")
        self.requester = requester

    @property
    def formatted_duration(self) -> str:
        if not self.duration:
            return "Live ☁️"
        m, s = divmod(int(self.duration), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

class GuildPlayer:
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.queue = deque()
        self.history = []
        self.current: Optional[Song] = None
        self.loop_mode: str = "off"
        self.bass_boost: bool = False
        self.panel_msg: Optional[discord.Message] = None
        self.bound_channel: Optional[discord.TextChannel] = None
        self.is_playing = False

guild_players = {}

def get_player(guild_id: int) -> GuildPlayer:
    if guild_id not in guild_players:
        guild_players[guild_id] = GuildPlayer(guild_id)
    return guild_players[guild_id]

# ─────────────── Multi-Layer Spotify Resolver (Windows SSL Bypass) ─────────────── #

async def fetch_spotify_tracks(item_type: str, item_id: str) -> List[Dict[str, str]]:
    tracks = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    # TCPConnector(ssl=False) prevents Windows SSLCertVerificationError
    connector = aiohttp.TCPConnector(ssl=False)

    # Layer 1: Official API (if credentials in .env)
    if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
        try:
            auth_str = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}"
            b64_auth = base64.b64encode(auth_str.encode()).decode()
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(
                    "https://accounts.spotify.com/api/token",
                    data={"grant_type": "client_credentials"},
                    headers={"Authorization": f"Basic {b64_auth}"}
                ) as resp:
                    if resp.status == 200:
                        token_info = await resp.json()
                        token = token_info.get("access_token")
                        auth_headers = {"Authorization": f"Bearer {token}"}
                        
                        if item_type == "track":
                            async with session.get(f"https://api.spotify.com/v1/tracks/{item_id}", headers=auth_headers) as r:
                                if r.status == 200:
                                    d = await r.json()
                                    artist = d["artists"][0]["name"] if d.get("artists") else ""
                                    return [{"title": f"{d.get('name', 'Track')} - {artist}", "query": f"{d.get('name', '')} {artist} audio"}]
                        elif item_type == "playlist":
                            async with session.get(f"https://api.spotify.com/v1/playlists/{item_id}/tracks?limit=100", headers=auth_headers) as r:
                                if r.status == 200:
                                    d = await r.json()
                                    for item in d.get("items", []):
                                        t = item.get("track")
                                        if t and t.get("name"):
                                            artist = t["artists"][0]["name"] if t.get("artists") else ""
                                            tracks.append({"title": f"{t['name']} - {artist}", "query": f"{t['name']} {artist} audio"})
                                    return tracks
                        elif item_type == "album":
                            async with session.get(f"https://api.spotify.com/v1/albums/{item_id}/tracks?limit=50", headers=auth_headers) as r:
                                if r.status == 200:
                                    d = await r.json()
                                    for t in d.get("items", []):
                                        if t and t.get("name"):
                                            artist = t["artists"][0]["name"] if t.get("artists") else ""
                                            tracks.append({"title": f"{t['name']} - {artist}", "query": f"{t['name']} {artist} audio"})
                                    return tracks
        except Exception as e:
            print(f"[Spotify API]: {e}")

    # Layer 2: Keyless Embed Scraper
    embed_url = f"https://open.spotify.com/embed/{item_type}/{item_id}"
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
            async with session.get(embed_url, headers=headers) as resp:
                if resp.status == 200:
                    html = await resp.text()

                    # 2A: Spotify initial-state Base64 JSON
                    state_match = re.search(r'<script id="initial-state" type="text/plain">([^<]+)</script>', html)
                    if state_match:
                        try:
                            raw_data = base64.b64decode(state_match.group(1).strip()).decode("utf-8")
                            data = json.loads(raw_data)
                            entity = data.get("data", {}).get("entity", {})
                            
                            track_list = entity.get("trackList", [])
                            for t in track_list:
                                title = t.get("title") or t.get("name")
                                artist = t.get("subtitle") or ""
                                if title:
                                    tracks.append({
                                        "title": f"{title} - {artist}".strip(" -"),
                                        "query": f"{title} {artist} audio"
                                    })
                            
                            if not tracks and entity.get("title"):
                                title = entity.get("title")
                                artist = entity.get("subtitle") or ""
                                tracks.append({
                                    "title": f"{title} - {artist}".strip(" -"),
                                    "query": f"{title} {artist} audio"
                                })
                        except Exception:
                            pass

                    # 2B: __NEXT_DATA__
                    if not tracks:
                        next_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">([^<]+)</script>', html)
                        if next_match:
                            try:
                                data = json.loads(next_match.group(1))
                                page_props = data.get("props", {}).get("pageProps", {})
                                entity = page_props.get("state", {}).get("data", {}).get("entity", {})
                                for t in entity.get("trackList", []):
                                    title = t.get("title") or t.get("name")
                                    artist = t.get("subtitle") or ""
                                    if title:
                                        tracks.append({
                                            "title": f"{title} - {artist}".strip(" -"),
                                            "query": f"{title} {artist} audio"
                                        })
                            except Exception:
                                pass

                    # 2C: Schema.org JSON-LD
                    if not tracks:
                        for ld_match in re.finditer(r'<script type="application/ld\+json">([^<]+)</script>', html):
                            try:
                                ld_data = json.loads(ld_match.group(1))
                                if ld_data.get("@type") == "MusicPlaylist" and "track" in ld_data:
                                    for item in ld_data["track"]:
                                        name = item.get("name")
                                        artists = [a.get("name") for a in item.get("byArtist", []) if a.get("name")]
                                        artist_str = ", ".join(artists)
                                        if name:
                                            tracks.append({
                                                "title": f"{name} - {artist_str}".strip(" -"),
                                                "query": f"{name} {artist_str} audio"
                                            })
                                elif ld_data.get("@type") == "MusicRecording":
                                    name = ld_data.get("name")
                                    artists = [a.get("name") for a in ld_data.get("byArtist", []) if a.get("name")]
                                    artist_str = ", ".join(artists)
                                    if name:
                                        tracks.append({
                                            "title": f"{name} - {artist_str}".strip(" -"),
                                            "query": f"{name} {artist_str} audio"
                                        })
                            except Exception:
                                pass
    except Exception as e:
        print(f"[Spotify Scraper]: {e}")

    return tracks

# ─────────────── Visual Helpers ─────────────── #

def make_slider(percent: float = 0.35) -> str:
    total_bars = 14
    filled = int(total_bars * percent)
    return "▰" * filled + "⟡" + "▱" * (total_bars - filled)

def create_panel_embed(song: Song, player: GuildPlayer) -> discord.Embed:
    loop_tag = "Disabled" if player.loop_mode == "off" else ("🔂 Track" if player.loop_mode == "track" else "🔁 Queue")
    bass_tag = "Boosted ✨" if player.bass_boost else "Flat 🍃"

    embed = discord.Embed(
        title="*listening to...*",
        description=f"### 𖦹 [{song.title}]({song.webpage_url})\n",
        color=PASTEL_PINK
    )
    embed.add_field(
        name="˚₊· progress ‧₊˚",
        value=f"`00:45` {make_slider(0.35)} `{song.formatted_duration}`",
        inline=False
    )
    embed.add_field(name="🎧 requester", value=f"`{song.requester.display_name}`", inline=True)
    embed.add_field(name="🔁 loop", value=f"`{loop_tag}`", inline=True)
    embed.add_field(name="🪄 bass", value=f"`{bass_tag}`", inline=True)

    if song.thumbnail:
        embed.set_thumbnail(url=song.thumbnail)
    embed.set_footer(text="isai • gentle beats & warm vibes ☁️")
    return embed

# ─────────────── Interactive Buttons Panel ─────────────── #

class PlayerControls(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, custom_id="btn_prev")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = get_player(self.guild_id)
        if not player.history:
            return await interaction.response.send_message("╭ ☁️ *no previous songs in memory...*", ephemeral=True)
        prev_song = player.history.pop()
        if player.current:
            player.queue.appendleft(player.current)
        player.queue.appendleft(prev_song)
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()
        await interaction.response.send_message("╭ ⟢ *rewinding to previous track...*", ephemeral=True)

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary, custom_id="btn_playpause")
    async def pause_resume_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("╭ ☁️ *not connected to any vc*", ephemeral=True)
        if vc.is_paused():
            vc.resume()
            await interaction.response.send_message("╭ ⟢ *resumed the melody*", ephemeral=True)
        else:
            vc.pause()
            await interaction.response.send_message("╭ ⟢ *paused the session*", ephemeral=True)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="btn_skip")
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await interaction.response.send_message("╭ ⟢ *skipped to next blossom*", ephemeral=True)
        else:
            await interaction.response.send_message("╭ ☁️ *nothing is playing right now*", ephemeral=True)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="btn_loop")
    async def loop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = get_player(self.guild_id)
        modes = ["off", "track", "queue"]
        player.loop_mode = modes[(modes.index(player.loop_mode) + 1) % len(modes)]
        await interaction.response.send_message(f"╭ ⟢ *loop mode set to: `{player.loop_mode}`*", ephemeral=True)
        if player.panel_msg and player.current:
            await player.panel_msg.edit(embed=create_panel_embed(player.current, player))

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="btn_stop")
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = get_player(self.guild_id)
        player.queue.clear()
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()
        await interaction.response.send_message("╭ ⟢ *cleared queue and resting now...*", ephemeral=True)

class LoopSelector(discord.ui.View):
    def __init__(self, player: GuildPlayer):
        super().__init__(timeout=60)
        self.player = player

    @discord.ui.button(label="Single Track 🔂", style=discord.ButtonStyle.primary)
    async def loop_track(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player.loop_mode = "track"
        await interaction.response.send_message("╭ ⟢ *looping current melody continuously.*", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Entire Queue 🔁", style=discord.ButtonStyle.secondary)
    async def loop_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player.loop_mode = "queue"
        await interaction.response.send_message("╭ ⟢ *queue will now repeat seamlessly.*", ephemeral=True)
        self.stop()

    @discord.ui.button(label="Turn Off ☁️", style=discord.ButtonStyle.danger)
    async def loop_off(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player.loop_mode = "off"
        await interaction.response.send_message("╭ ⟢ *loop disabled.*", ephemeral=True)
        self.stop()

# ─────────────── Playback Engine ─────────────── #

async def play_next(guild: discord.Guild):
    player = get_player(guild.id)
    vc = guild.voice_client

    if not vc or not vc.is_connected():
        player.is_playing = False
        return

    next_song = None

    if player.loop_mode == "track" and player.current:
        next_song = player.current
    elif player.queue:
        if player.current:
            player.history.append(player.current)
            if player.loop_mode == "queue":
                player.queue.append(player.current)
        next_song = player.queue.popleft()
    else:
        player.current = None
        player.is_playing = False
        if player.bound_channel:
            embed = discord.Embed(
                description="╭── ⟢  *queue is all wrapped up... sleeping softly* ☁️",
                color=PASTEL_LAVENDER
            )
            await player.bound_channel.send(embed=embed)
        return

    player.current = next_song
    player.is_playing = True

    try:
        loop = asyncio.get_event_loop()
        
        if next_song.url.startswith("ytsearch:"):
            info = await loop.run_in_executor(None, lambda: ytdl.extract_info(next_song.url, download=False))
            if "entries" in info and info["entries"]:
                track_info = info["entries"][0]
                audio_url = track_info["url"]
                next_song.webpage_url = track_info.get("webpage_url", next_song.webpage_url)
                next_song.duration = track_info.get("duration", next_song.duration)
                next_song.thumbnail = track_info.get("thumbnail", next_song.thumbnail)
            else:
                raise Exception("Could not resolve song to audio stream.")
        else:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(next_song.url, download=False))
            audio_url = data["url"] if "url" in data else next_song.url

        source = discord.FFmpegPCMAudio(
            audio_url,
            executable=FFMPEG_EXE,
            **get_ffmpeg_options(player.bass_boost)
        )
        transformed_source = discord.PCMVolumeTransformer(source, volume=1.0)

        def after_playback(err):
            fut = asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop)
            try:
                fut.result()
            except Exception:
                pass

        vc.play(transformed_source, after=after_playback)

        if player.bound_channel:
            embed = create_panel_embed(next_song, player)
            view = PlayerControls(guild.id)
            if player.panel_msg:
                try:
                    await player.panel_msg.delete()
                except Exception:
                    pass
            player.panel_msg = await player.bound_channel.send(embed=embed, view=view)

    except Exception as e:
        if player.bound_channel:
            await player.bound_channel.send(f"╭ ⟢ *error during playback: `{e}`*")
        await play_next(guild)

# ─────────────── Music Hybrid Commands ─────────────── #

@bot.hybrid_command(name="join", aliases=["ijoin", "ij", "j", "connect", "ic"], description="Connect bot to your voice channel.")
async def join(ctx: commands.Context):
    if not ctx.author.voice:
        return await ctx.send("╭ ☁️ *join a voice channel first so i can find you.*")
    vc = ctx.guild.voice_client
    if not vc:
        await ctx.author.voice.channel.connect()
        await ctx.send(f"╭ ⟢ *joined* `{ctx.author.voice.channel.name}` *peacefully.* 🎧")
    else:
        await vc.move_to(ctx.author.voice.channel)
        await ctx.send(f"╭ ⟢ *moved to* `{ctx.author.voice.channel.name}`. 🌸")

@bot.hybrid_command(name="leave", aliases=["ileave", "idc", "dc", "disconnect"], description="Disconnect bot from voice.")
async def leave(ctx: commands.Context):
    vc = ctx.guild.voice_client
    if vc:
        player = get_player(ctx.guild.id)
        player.queue.clear()
        player.current = None
        await vc.disconnect()
        await ctx.send("╭ ⟢ *unplugged headphones and stepped away... bye for now.* ☁️")
    else:
        await ctx.send("╭ ☁️ *i'm not sitting in any voice channel.*")

@bot.hybrid_command(name="play", aliases=["p"], description="Play music via title, playlist, spotify or direct link.")
@app_commands.describe(query="Song title, YouTube link/playlist, or Spotify link")
async def play(ctx: commands.Context, *, query: str):
    await ctx.defer()

    if not ctx.author.voice:
        return await ctx.send("╭ ☁️ *you must be nestled inside a voice channel first.*")

    vc = ctx.guild.voice_client
    if not vc:
        vc = await ctx.author.voice.channel.connect()
    elif vc.channel != ctx.author.voice.channel:
        await vc.move_to(ctx.author.voice.channel)

    player = get_player(ctx.guild.id)
    player.bound_channel = ctx.channel

    spotify_match = re.search(r"open\.spotify\.com/(?:[a-zA-Z-]+/)?(track|playlist|album)/([a-zA-Z0-9]+)", query)
    if spotify_match:
        item_type = spotify_match.group(1)
        item_id = spotify_match.group(2)
        tracks = await fetch_spotify_tracks(item_type, item_id)
        
        if not tracks:
            return await ctx.send("╭ ☁️ *couldn't fetch tracks from that Spotify link.*")

        for t in tracks:
            s = Song({
                "title": t["title"],
                "url": f"ytsearch:{t['query']}",
                "webpage_url": query,
                "duration": 0,
                "thumbnail": "",
            }, ctx.author)
            player.queue.append(s)

        if len(tracks) > 1:
            embed = discord.Embed(
                title="˚₊· spotify collection loaded ‧₊˚",
                description=f"╭── ⟢ added **{len(tracks)}** tracks from Spotify\n╰── 𖦹 ready to serenade your vc.",
                color=PASTEL_LAVENDER
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title="˚₊· queued note ‧₊˚",
                description=f"╭── ⟢ [{tracks[0]['title']}]({query})\n╰── 🎧 requested by {ctx.author.mention}",
                color=PASTEL_PINK
            )
            await ctx.send(embed=embed)

    else:
        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False, process=False))
        except Exception as e:
            return await ctx.send(f"╭ ☁️ *couldn't fetch that track:* `{e}`")

        if not data:
            return await ctx.send("╭ ☁️ *no matching results found.*")

        if "entries" in data:
            entries = list(data["entries"])
            added_count = 0
            for item in entries:
                if not item:
                    continue
                entry_url = item.get("url") or item.get("webpage_url") or f"https://www.youtube.com/watch?v={item.get('id')}"
                s = Song({
                    "title": item.get("title", "Aesthetic Track"),
                    "url": entry_url,
                    "webpage_url": entry_url,
                    "duration": item.get("duration", 0),
                    "thumbnail": item.get("thumbnail", ""),
                }, ctx.author)
                player.queue.append(s)
                added_count += 1

            embed = discord.Embed(
                title="˚₊· playlist loaded ‧₊˚",
                description=f"╭── ⟢ added **{added_count}** tracks from [{data.get('title', 'Playlist')}]({query})\n╰── 𖦹 ready to serenade your vc.",
                color=PASTEL_LAVENDER
            )
            await ctx.send(embed=embed)
        else:
            info = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
            if "entries" in info:
                info = info["entries"][0]

            song = Song(info, ctx.author)
            player.queue.append(song)

            embed = discord.Embed(
                title="˚₊· queued note ‧₊˚",
                description=f"╭── ⟢ [{song.title}]({song.webpage_url})\n╰── ⏱️ duration: `{song.formatted_duration}` • requested by {ctx.author.mention}",
                color=PASTEL_PINK
            )
            if song.thumbnail:
                embed.set_thumbnail(url=song.thumbnail)
            await ctx.send(embed=embed)

    if not vc.is_playing() and not vc.is_paused():
        await play_next(ctx.guild)

@bot.hybrid_command(name="pause", description="Pause current song playback.")
async def pause(ctx: commands.Context):
    vc = ctx.guild.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await ctx.send("╭ ⟢ *paused track. taking a quiet breath...* 🫧")
    else:
        await ctx.send("╭ ☁️ *nothing is actively singing right now.*")

@bot.hybrid_command(name="resume", description="Resume the paused melody.")
async def resume(ctx: commands.Context):
    vc = ctx.guild.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await ctx.send("╭ ⟢ *resumed our sweet melody.* ✨")
    else:
        await ctx.send("╭ ☁️ *the music isn't currently paused.*")

@bot.hybrid_command(name="skip", aliases=["s"], description="Skip onto the next song.")
async def skip(ctx: commands.Context):
    vc = ctx.guild.voice_client
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()
        await ctx.send("╭ ⟢ *skipping along to the next song...* 🍃")
    else:
        await ctx.send("╭ ☁️ *no songs available to skip.*")

@bot.hybrid_command(name="previous", aliases=["iprev", "prev", "back", "iback"], description="Return to previous song.")
async def previous(ctx: commands.Context):
    player = get_player(ctx.guild.id)
    if not player.history:
        return await ctx.send("╭ ☁️ *memory is clean; no previous track recorded.*")

    prev_song = player.history.pop()
    if player.current:
        player.queue.appendleft(player.current)
    player.queue.appendleft(prev_song)

    vc = ctx.guild.voice_client
    if vc:
        vc.stop()
    await ctx.send("╭ ⟢ *stepping back into the previous melody...* ⏪")

@bot.hybrid_command(name="stop", description="Stop the player and flush the queue.")
async def stop(ctx: commands.Context):
    player = get_player(ctx.guild.id)
    player.queue.clear()
    vc = ctx.guild.voice_client
    if vc:
        vc.stop()
    await ctx.send("╭ ⟢ *stopped music and washed the queue clean.* 🫧")

@bot.hybrid_command(name="shuffle", description="Shuffle songs inside the queue randomly.")
async def shuffle(ctx: commands.Context):
    player = get_player(ctx.guild.id)
    if len(player.queue) < 2:
        return await ctx.send("╭ ☁️ *need at least two songs in queue to shuffle.*")
    random.shuffle(player.queue)
    await ctx.send("╭ ⟢ *shuffled queue with a touch of magic.* 🪄")

@bot.hybrid_command(name="queue", aliases=["iq", "q"], description="View the current aesthetic song queue.")
async def queue(ctx: commands.Context):
    player = get_player(ctx.guild.id)
    if not player.current and not player.queue:
        return await ctx.send("╭ ☁️ *queue is light as air... nothing here yet.*")

    desc = []
    if player.current:
        desc.append(f"**Now Playing:**\n╰ 𖦹 [{player.current.title}]({player.current.webpage_url}) (`{player.current.formatted_duration}`)\n")

    if player.queue:
        desc.append("**Up Next:**")
        for i, track in enumerate(list(player.queue)[:10], 1):
            desc.append(f"`{i:02d}.` [{track.title[:45]}]({track.webpage_url}) • `{track.formatted_duration}`")
        if len(player.queue) > 10:
            desc.append(f"\n*...and {len(player.queue) - 10} more melodies waiting.*")

    embed = discord.Embed(
        title="˚₊· gentle queue line ‧₊˚",
        description="\n".join(desc),
        color=PASTEL_LAVENDER
    )
    embed.set_footer(text=f"Loop: {player.loop_mode.capitalize()} • Bass Boost: {'Active' if player.bass_boost else 'Off'}")
    await ctx.send(embed=embed)

@bot.hybrid_command(name="clear", aliases=["iclr"], description="Totally clear the current queue.")
async def clear(ctx: commands.Context):
    player = get_player(ctx.guild.id)
    player.queue.clear()
    await ctx.send("╭ ⟢ *queue wiped clean like freshly fallen snow.* ❄️")

@bot.hybrid_command(name="remove", description="Remove a specific song by index or name.")
@app_commands.describe(target="Song number or matching title")
async def remove(ctx: commands.Context, *, target: str):
    player = get_player(ctx.guild.id)
    if not player.queue:
        return await ctx.send("╭ ☁️ *queue is already empty.*")

    removed_song = None
    if target.isdigit():
        idx = int(target) - 1
        if 0 <= idx < len(player.queue):
            removed_song = player.queue[idx]
            del player.queue[idx]
    else:
        for song in list(player.queue):
            if target.lower() in song.title.lower():
                removed_song = song
                player.queue.remove(song)
                break

    if removed_song:
        await ctx.send(f"╭ ⟢ *removed* `[{removed_song.title}]` *from the queue.* 🍃")
    else:
        await ctx.send(f"╭ ☁️ *couldn't find any track matching `{target}`.*")

@bot.hybrid_command(name="bass", description="Boost or soften the low-end bass frequencies.")
@app_commands.describe(enabled="True to boost bass, False to disable")
async def bass(ctx: commands.Context, enabled: bool):
    player = get_player(ctx.guild.id)
    player.bass_boost = enabled
    state_str = "boosted into warmth ✨" if enabled else "returned to natural acoustic 🍃"
    await ctx.send(f"╭ ⟢ *bass frequencies are now {state_str}. (Applies to next song)*")

@bot.hybrid_command(name="loop", aliases=["irepeate", "rep"], description="Set loop mode with interactive buttons.")
async def loop(ctx: commands.Context):
    player = get_player(ctx.guild.id)
    embed = discord.Embed(
        title="˚₊· loop configuration ‧₊˚",
        description=f"╭── ⟢ current mode: **`{player.loop_mode}`**\n╰── 𖦹 select your desired vibe below:",
        color=PASTEL_PINK
    )
    view = LoopSelector(player)
    await ctx.send(embed=embed, view=view)

@bot.hybrid_command(name="help", description="Aesthetic guide to all isai music commands.")
async def help_cmd(ctx: commands.Context):
    embed = discord.Embed(
        title="˗ˏˋ isai • music & comfort guide ˎˊ˗",
        description="soft, clean, and high-fidelity audio companionship.\nboth slash (`/`) and prefix (`i`) work everywhere.\n",
        color=PASTEL_PINK
    )
    music_cmds = (
        "`join` / `ijoin` / `ij` ⟢ *summon bot into voice channel*\n"
        "`leave` / `ileave` / `idc` ⟢ *release bot from voice channel*\n"
        "`play` / `p` ⟢ *play audio from title, url, playlist or spotify*\n"
        "`pause` / `resume` ⟢ *pause or unpause soundscape*\n"
        "`skip` ⟢ *jump to the next song*\n"
        "`previous` / `prev` ⟢ *revisit previously played song*\n"
        "`loop` / `rep` ⟢ *toggle loop track / queue / off*\n"
        "`queue` / `q` ⟢ *display upcoming playlist entries*\n"
        "`shuffle` ⟢ *mix the queue randomly*\n"
        "`remove` ⟢ *remove a song by number or title*\n"
        "`clear` ⟢ *clear the entire waiting list*\n"
        "`bass` ⟢ *turn on / off deep bass equalizers*\n"
        "`stop` ⟢ *halt session completely*"
    )
    embed.add_field(name="₊˚🎧 music controls", value=music_cmds, inline=False)
    embed.set_footer(text="craft with love • prefix: i • isai bot")
    await ctx.send(embed=embed)

# ─────────────── Owner Only Module ─────────────── #

def is_owner_check(ctx: commands.Context) -> bool:
    return ctx.author.id in OWNER_IDS

@bot.hybrid_command(name="say", description="Owner: repeat text through the bot.")
@app_commands.describe(content="Message to echo")
async def say(ctx: commands.Context, *, content: str):
    if not is_owner_check(ctx):
        return
    try:
        if ctx.interaction:
            await ctx.interaction.response.send_message("╭ ⟢ *sent.*", ephemeral=True)
        else:
            await ctx.message.delete()
        await ctx.channel.send(content)
    except Exception:
        pass

@bot.hybrid_command(name="dm", description="Owner: direct message a target user.")
@app_commands.describe(user="The user to message", content="Text to send")
async def dm(ctx: commands.Context, user: discord.User, *, content: str):
    if not is_owner_check(ctx):
        return
    try:
        await user.send(content)
        await ctx.send(f"╭ ⟢ *delivered message to `{user}` safely.*", ephemeral=True)
    except Exception as e:
        await ctx.send(f"╭ ☁️ *failed to send dm:* `{e}`", ephemeral=True)

@bot.hybrid_command(name="status", description="Owner: set the bot presence status.")
@app_commands.describe(state="Status mode: online, idle, or dnd")
async def status(ctx: commands.Context, state: str):
    if not is_owner_check(ctx):
        return
    status_map = {
        "online": discord.Status.online,
        "idle": discord.Status.idle,
        "dnd": discord.Status.dnd,
    }
    chosen = status_map.get(state.lower())
    if not chosen:
        return await ctx.send("╭ ☁️ *pick from:* `online`, `idle`, or `dnd`", ephemeral=True)

    await bot.change_presence(status=chosen, activity=discord.Activity(type=discord.ActivityType.listening, name="aesthetic tunes | iplay"))
    await ctx.send(f"╭ ⟢ *presence status shifted to `{state}`.*", ephemeral=True)

@bot.hybrid_command(name="platform", description="Owner: change platform spoofing (vr, mobile, normal).")
@app_commands.describe(mode="Spoof mode: vr, mobile, normal")
async def platform(ctx: commands.Context, mode: str):
    global current_platform
    if not is_owner_check(ctx):
        return
    mode_clean = mode.lower()
    if mode_clean not in ["vr", "mobile", "normal"]:
        return await ctx.send("╭ ☁️ *modes allowed: `vr`, `mobile`, `normal`*", ephemeral=True)

    current_platform = mode_clean
    await ctx.send(f"╭ ⟢ *platform updated to `{mode_clean}`. Reconnecting session...*", ephemeral=True)

    ws = bot.ws
    if ws:
        await ws.close(4000)

# ─────────────── Events & Startup ─────────────── #

@bot.event
async def on_ready():
    print(f"╭────────────────────────────────────────╮")
    print(f"│  Logged in as: {bot.user.name} ({bot.user.id})")
    print(f"│  Platform spoofed as: {current_platform.upper()}")
    print(f"│  Prefix: {PREFIX}")
    print(f"╰────────────────────────────────────────╯")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} application slash commands.")
    except Exception as e:
        print(f"Error syncing commands: {e}")

    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Activity(type=discord.ActivityType.listening, name="ihelp | soft lofi ☁️")
    )

if __name__ == "__main__":
    if not TOKEN:
        print("Error: No TOKEN found inside .env file.")
        sys.exit(1)
    bot.run(TOKEN)