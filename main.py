"""Isai — a Discord music bot powered by a Lavalink node."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import aiohttp
import discord
import wavelink
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


load_dotenv()

TOKEN = os.getenv("TOKEN", "").strip()
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
PREFIX = os.getenv("PREFIX", "i").strip() or "i"

LAVALINK_HOST = os.getenv("LAVALINK_HOST", "ryzen.heavencloud.in").strip()
LAVALINK_PORT = os.getenv("LAVALINK_PORT", "2426").strip()
LAVALINK_SECURE = os.getenv("LAVALINK_SECURE", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}
LAVALINK_IDENTIFIER = os.getenv(
    "LAVALINK_IDENTIFIER", "LAVALINK-ZYNRAX DEV"
).strip()
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD", "").strip()

# These accounts can use the private owner commands.
owner = [1377967442172579843, 774224543531270144]
OWNER_IDS = set(owner)

EMBED_COLOR = discord.Color.from_rgb(244, 166, 193)
MAX_QUEUE_SIZE = 500
MAX_PLAYLIST_ITEMS = 100
MAX_SPOTIFY_ITEMS = 100

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("isai")


@dataclass(slots=True)
class Track:
    playable: wavelink.Playable
    requester: str

    @property
    def title(self) -> str:
        return self.playable.title or "Untitled track"

    @property
    def url(self) -> str:
        return self.playable.uri or ""

    @property
    def duration(self) -> int | None:
        if self.playable.is_stream or not self.playable.length:
            return None
        return round(self.playable.length / 1000)

    @property
    def thumbnail(self) -> str:
        return self.playable.artwork or ""


@dataclass
class GuildState:
    queue: deque[Track] = field(default_factory=deque)
    history: deque[Track] = field(default_factory=lambda: deque(maxlen=50))
    current: Track | None = None
    loop_mode: str = "off"
    bass: bool = False
    started_at: float | None = None
    elapsed_before_pause: float = 0.0
    paused_at: float | None = None
    suppress_after: bool = False
    panel_channel_id: int | None = None
    panel_message_id: int | None = None
    start_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


states: dict[int, GuildState] = {}


def state_for(guild_id: int) -> GuildState:
    return states.setdefault(guild_id, GuildState())


def format_time(seconds: int | float | None) -> str:
    if seconds is None or seconds < 0:
        return "LIVE"
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def elapsed_time(state: GuildState) -> float:
    if state.paused_at is not None:
        return state.elapsed_before_pause
    if state.started_at is None:
        return 0.0
    return state.elapsed_before_pause + max(0.0, time.monotonic() - state.started_at)


def make_progress_bar(state: GuildState, width: int = 16) -> str:
    track = state.current
    duration = track.duration if track else None
    if not duration:
        return "─" * width
    ratio = min(1.0, elapsed_time(state) / max(duration, 1))
    filled = round(ratio * width)
    return "▰" * filled + "▱" * (width - filled)


def make_player_embed(state: GuildState) -> discord.Embed:
    current = state.current
    if current:
        title = discord.utils.escape_markdown(current.title)
        linked_title = f"[{title}]({current.url})" if current.url else title
        status = "⏸️ Paused" if state.paused_at is not None else "🎶 Now playing"
        description = (
            f"{status}\n**{linked_title}**\n\n"
            f"`{format_time(elapsed_time(state))}` {make_progress_bar(state)} "
            f"`{format_time(current.duration)}`\n"
            "_Visual progress only; this bar does not seek._"
        )
        embed = discord.Embed(
            title="🌸 isai's little listening room",
            description=description,
            color=EMBED_COLOR,
        )
        if current.thumbnail:
            embed.set_thumbnail(url=current.thumbnail)
        embed.add_field(name="Requested by", value=current.requester, inline=True)
        embed.add_field(name="Up next", value=str(len(state.queue)), inline=True)
        embed.add_field(name="Repeat", value=state.loop_mode.title(), inline=True)
        embed.add_field(
            name="Bass boost",
            value="On for next song" if state.bass else "Off",
            inline=True,
        )
        return embed

    if state.queue:
        description = (
            f"✨ Up next: **{discord.utils.escape_markdown(state.queue[0].title)}**"
        )
    else:
        description = "The queue is empty. Add a song with `/play` or `iplay`."
    return discord.Embed(
        title="🌸 isai's little listening room",
        description=description,
        color=EMBED_COLOR,
    )


def queue_embed(state: GuildState) -> discord.Embed:
    embed = discord.Embed(title="📜 isai's queue", color=EMBED_COLOR)
    if state.current:
        embed.add_field(
            name="Now playing",
            value=f"**{discord.utils.escape_markdown(state.current.title)}**",
            inline=False,
        )
    if state.queue:
        rows = [
            f"`{index:02}` {discord.utils.escape_markdown(track.title)} "
            f"`{format_time(track.duration)}`"
            for index, track in enumerate(list(state.queue)[:20], start=1)
        ]
        if len(state.queue) > 20:
            rows.append(f"_and {len(state.queue) - 20} more…_")
        embed.add_field(name="Coming up", value="\n".join(rows), inline=False)
    else:
        embed.description = "Nothing queued yet. Add a song with `/play` or `iplay`."
    embed.set_footer(text=f"{len(state.queue)} waiting • repeat {state.loop_mode}")
    return embed


class SpotifyResolver:
    """Read Spotify metadata only; all audio playback is handled by Lavalink."""

    def __init__(self) -> None:
        self.session: aiohttp.ClientSession | None = None
        self.access_token: str | None = None
        self.token_expires_at = 0.0

    async def start(self) -> None:
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20)
        )

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    async def _get_token(self) -> str:
        if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
            raise ValueError(
                "Add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to your "
                "environment, or make sure Lavalink has a Spotify source plugin."
            )
        if not self.session:
            raise RuntimeError("Spotify lookup is not ready.")
        if self.access_token and time.time() < self.token_expires_at - 30:
            return self.access_token

        async with self.session.post(
            "https://accounts.spotify.com/api/token",
            auth=aiohttp.BasicAuth(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
        ) as response:
            if response.status >= 400:
                raise ValueError(
                    f"Spotify credentials were rejected (HTTP {response.status})."
                )
            data = await response.json()
        self.access_token = data["access_token"]
        self.token_expires_at = time.time() + int(data.get("expires_in", 3600))
        return self.access_token

    async def _get_json(self, url: str) -> dict[str, Any]:
        if not self.session:
            raise RuntimeError("Spotify lookup is not ready.")
        token = await self._get_token()
        async with self.session.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
        ) as response:
            if response.status >= 400:
                raise ValueError(
                    f"Spotify could not read that public link (HTTP {response.status})."
                )
            return await response.json()

    async def tracks_from_link(self, url: str) -> list[str]:
        parsed = urlparse(url)
        match = re.search(r"/(track|playlist|album)/([A-Za-z0-9]+)", parsed.path)
        if parsed.netloc.lower() not in {"open.spotify.com", "www.open.spotify.com"} or not match:
            raise ValueError("Use a Spotify track, album, or playlist link.")

        kind, spotify_id = match.groups()
        if kind == "track":
            data = await self._get_json(
                f"https://api.spotify.com/v1/tracks/{spotify_id}"
            )
            return [self._make_query(data)]

        if kind == "album":
            url = (
                f"https://api.spotify.com/v1/albums/{spotify_id}/tracks"
                f"?limit={MAX_SPOTIFY_ITEMS}"
            )
            data = await self._get_json(url)
            entries = data.get("items", [])
        else:
            url = (
                f"https://api.spotify.com/v1/playlists/{spotify_id}/tracks"
                f"?limit={MAX_SPOTIFY_ITEMS}"
            )
            data = await self._get_json(url)
            entries = [item.get("track") for item in data.get("items", [])]

        queries = [
            self._make_query(track)
            for track in entries
            if track and track.get("name")
        ][:MAX_SPOTIFY_ITEMS]
        if not queries:
            raise ValueError("No tracks were found in that Spotify collection.")
        return queries

    @staticmethod
    def _make_query(track: dict[str, Any]) -> str:
        title = str(track.get("name") or "Unknown track")
        artists = ", ".join(
            artist.get("name", "") for artist in track.get("artists", [])
        ).strip(", ")
        return f"{title} {artists}".strip()


spotify = SpotifyResolver()


def playable_list(result: wavelink.Search) -> list[wavelink.Playable]:
    if isinstance(result, wavelink.Playlist):
        return list(result)[:MAX_PLAYLIST_ITEMS]
    return list(result)[:MAX_PLAYLIST_ITEMS]


def wrap_playable(playable: wavelink.Playable, requester: str) -> Track:
    return Track(playable=playable, requester=requester)


async def search_one(query: str) -> wavelink.Playable | None:
    results = await wavelink.Playable.search(
        query,
        source=wavelink.TrackSource.YouTubeMusic,
    )
    tracks = playable_list(results)
    return tracks[0] if tracks else None


async def tracks_from_request(query: str, requester: str) -> list[Track]:
    if "open.spotify.com/" in query.lower():
        # Prefer LavaSrc/native source plugins when installed on the node.
        try:
            direct_results = await wavelink.Playable.search(query)
            direct_tracks = playable_list(direct_results)
            if direct_tracks:
                return [wrap_playable(track, requester) for track in direct_tracks]
        except (wavelink.LavalinkException, wavelink.LavalinkLoadException):
            pass

        queries = await spotify.tracks_from_link(query)
        semaphore = asyncio.Semaphore(4)

        async def resolve_spotify_query(text: str) -> wavelink.Playable | None:
            async with semaphore:
                try:
                    return await search_one(text)
                except (wavelink.LavalinkException, wavelink.LavalinkLoadException):
                    return None

        resolved = await asyncio.gather(*(resolve_spotify_query(text) for text in queries))
        tracks = [
            wrap_playable(track, requester)
            for track in resolved
            if track is not None
        ]
        if not tracks:
            raise ValueError(
                "I couldn’t find playable results for that Spotify link. "
                "Check the Lavalink source plugins and Spotify credentials."
            )
        return tracks

    try:
        results = await wavelink.Playable.search(query)
    except wavelink.LavalinkLoadException as error:
        raise ValueError(
            "Lavalink could not load that source. The server may need its "
            "YouTube/source plugin enabled."
        ) from error
    except wavelink.LavalinkException as error:
        raise ValueError("Could not search the Lavalink node. Try again shortly.") from error

    tracks = playable_list(results)
    if not tracks:
        raise ValueError("I couldn’t find a playable song for that title or link.")
    return [wrap_playable(track, requester) for track in tracks]


def make_filters(bass_enabled: bool) -> wavelink.Filters:
    filters = wavelink.Filters()
    if bass_enabled:
        filters.equalizer.set(
            bands=[
                {"band": 0, "gain": 0.10},
                {"band": 1, "gain": 0.16},
                {"band": 2, "gain": 0.22},
                {"band": 3, "gain": 0.18},
                {"band": 4, "gain": 0.10},
            ]
        )
    return filters


class IsaiBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix=commands.when_mentioned_or(PREFIX),
            intents=intents,
            help_command=None,
        )
        self.lavalink_session: aiohttp.ClientSession | None = None

    async def setup_hook(self) -> None:
        await spotify.start()
        try:
            synced = await self.tree.sync()
            log.info("Synced %d slash commands.", len(synced))
        except discord.HTTPException:
            log.exception("Could not sync slash commands.")

        scheme = "https" if LAVALINK_SECURE else "http"
        self.lavalink_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        )
        node = wavelink.Node(
            identifier=LAVALINK_IDENTIFIER,
            uri=f"{scheme}://{LAVALINK_HOST}:{LAVALINK_PORT}",
            password=LAVALINK_PASSWORD,
            client=self,
            session=self.lavalink_session,
        )
        try:
            connected = await wavelink.Pool.connect(nodes=[node], client=self)
            if LAVALINK_IDENTIFIER not in connected:
                raise RuntimeError(
                    "Lavalink node connection failed. Check the host, port, "
                    "password, server version, and secure setting."
                )
        except Exception:
            await self.lavalink_session.close()
            self.lavalink_session = None
            raise

    async def close(self) -> None:
        await spotify.close()
        await wavelink.Pool.close()
        if self.lavalink_session and not self.lavalink_session.closed:
            await self.lavalink_session.close()
        await super().close()


bot = IsaiBot()


def is_player(voice: discord.VoiceClient | None) -> bool:
    return isinstance(voice, wavelink.Player)


async def ensure_voice(
    guild: discord.Guild, member: discord.Member
) -> wavelink.Player:
    if not member.voice or not member.voice.channel:
        raise ValueError("Join a voice channel first, and I’ll meet you there.")

    voice = guild.voice_client
    if is_player(voice):
        assert isinstance(voice, wavelink.Player)
        if not voice.connected:
            await voice.connect(reconnect=True)
        if voice.channel != member.voice.channel:
            await voice.move_to(member.voice.channel)
        return voice

    connected = await member.voice.channel.connect(
        cls=wavelink.Player,
        self_deaf=True,
    )
    if not isinstance(connected, wavelink.Player):
        raise RuntimeError("Could not create the Lavalink voice player.")
    return connected


async def refresh_panel(
    state: GuildState,
    channel: discord.abc.Messageable | None = None,
) -> None:
    if channel is not None and hasattr(channel, "id"):
        state.panel_channel_id = channel.id  # type: ignore[attr-defined]

    target: Any = channel
    if target is None and state.panel_channel_id:
        target = bot.get_channel(state.panel_channel_id)
        if target is None:
            try:
                target = await bot.fetch_channel(state.panel_channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return
    if target is None:
        return

    paused = state.paused_at is not None
    embed = make_player_embed(state)
    view = PlayerPanelView(paused=paused)
    if state.panel_message_id:
        try:
            message = await target.fetch_message(state.panel_message_id)
            await message.edit(embed=embed, view=view)
            return
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            state.panel_message_id = None
    try:
        message = await target.send(embed=embed, view=view)
        state.panel_message_id = message.id
    except (discord.Forbidden, discord.HTTPException):
        log.info("Cannot post the player panel in channel %s.", target.id)


async def start_next(guild_id: int) -> None:
    guild = bot.get_guild(guild_id)
    state = state_for(guild_id)
    voice = guild.voice_client if guild else None
    if not is_player(voice) or not voice.connected:
        state.current = None
        return
    assert isinstance(voice, wavelink.Player)

    async with state.start_lock:
        if voice.playing or voice.paused:
            return
        while state.queue:
            track = state.queue.popleft()
            state.current = track
            try:
                await voice.play(
                    track.playable,
                    filters=make_filters(state.bass),
                    volume=100,
                )
                state.started_at = time.monotonic()
                state.elapsed_before_pause = 0.0
                state.paused_at = None
                await refresh_panel(state)
                return
            except (wavelink.LavalinkException, discord.HTTPException) as error:
                log.warning("Could not start %s: %s", track.title, error)
                state.current = None
                state.started_at = None
                if state.panel_channel_id:
                    await send_channel_message(
                        state.panel_channel_id,
                        f"Couldn’t play **{discord.utils.escape_markdown(track.title)}**; "
                        "I’ll try the next song.",
                    )

        state.current = None
        state.started_at = None
        state.elapsed_before_pause = 0.0
        state.paused_at = None
        await refresh_panel(state)


async def send_channel_message(channel_id: int, message: str) -> None:
    channel = bot.get_channel(channel_id)
    if channel:
        try:
            await channel.send(
                message,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.Forbidden, discord.HTTPException):
            pass


async def add_tracks(
    guild: discord.Guild,
    member: discord.Member,
    channel: discord.abc.Messageable,
    query: str,
) -> tuple[int, str]:
    voice = await ensure_voice(guild, member)
    found = await tracks_from_request(query, member.display_name)
    state = state_for(guild.id)
    if len(state.queue) + len(found) > MAX_QUEUE_SIZE:
        raise ValueError(
            f"The queue can hold up to {MAX_QUEUE_SIZE} waiting tracks. "
            "Remove a few before adding this request."
        )
    state.queue.extend(found)
    state.panel_channel_id = channel.id  # type: ignore[attr-defined]
    await start_next(guild.id)
    await refresh_panel(state, channel)
    return len(found), voice.channel.name


async def safe_respond(
    ctx: commands.Context,
    content: str | None = None,
    *,
    embed: discord.Embed | None = None,
    view: discord.ui.View | None = None,
    ephemeral: bool = False,
) -> discord.Message | discord.InteractionMessage | None:
    if ctx.interaction:
        if ctx.interaction.response.is_done():
            return await ctx.interaction.followup.send(
                content=content,
                embed=embed,
                view=view,
                ephemeral=ephemeral,
            )
        return await ctx.interaction.response.send_message(
            content=content,
            embed=embed,
            view=view,
            ephemeral=ephemeral,
        )
    return await ctx.send(content=content, embed=embed, view=view)


async def respond_interaction(
    interaction: discord.Interaction,
    content: str,
    *,
    ephemeral: bool = True,
) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(content, ephemeral=ephemeral)


async def player_for_interaction(
    interaction: discord.Interaction,
) -> tuple[wavelink.Player, GuildState] | None:
    if not interaction.guild:
        await respond_interaction(interaction, "This control works inside a server.")
        return None
    voice = interaction.guild.voice_client
    if not is_player(voice) or not voice.connected:
        await respond_interaction(interaction, "I’m not in a voice channel right now.")
        return None
    member = interaction.user
    if isinstance(member, discord.Member) and (
        not member.voice or member.voice.channel != voice.channel
    ):
        await respond_interaction(
            interaction,
            "Join my voice channel to use these player controls.",
        )
        return None
    assert isinstance(voice, wavelink.Player)
    return voice, state_for(interaction.guild.id)


class PlayerPanelView(discord.ui.View):
    def __init__(self, *, paused: bool = False) -> None:
        super().__init__(timeout=30 * 60)
        for item in self.children:
            if isinstance(item, discord.ui.Button) and str(item.emoji) == "⏯️":
                item.label = "Resume" if paused else "Pause"
                break

    async def _validate(
        self, interaction: discord.Interaction
    ) -> tuple[wavelink.Player, GuildState] | None:
        result = await player_for_interaction(interaction)
        if result is None:
            return None
        await interaction.response.defer(ephemeral=True)
        return result

    @discord.ui.button(label="Pause", emoji="⏯️", style=discord.ButtonStyle.secondary)
    async def pause_resume(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        result = await self._validate(interaction)
        if not result:
            return
        voice, state = result
        if voice.playing:
            state.elapsed_before_pause = elapsed_time(state)
            state.paused_at = time.monotonic()
            await voice.pause(True)
        elif voice.paused:
            state.started_at = time.monotonic()
            state.paused_at = None
            await voice.pause(False)
        await refresh_panel(state)
        await interaction.followup.send("Player updated.", ephemeral=True)

    @discord.ui.button(label="Previous", emoji="⏮️", style=discord.ButtonStyle.secondary)
    async def previous(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        result = await self._validate(interaction)
        if not result:
            return
        voice, state = result
        if not state.history:
            await interaction.followup.send(
                "There isn’t a previous song yet.",
                ephemeral=True,
            )
            return
        if state.current:
            state.queue.appendleft(state.current)
        state.queue.appendleft(state.history.pop())
        if voice.playing or voice.paused:
            state.suppress_after = True
            await voice.stop()
        else:
            await start_next(interaction.guild_id)  # type: ignore[arg-type]
        await interaction.followup.send("Playing the previous song.", ephemeral=True)

    @discord.ui.button(label="Skip", emoji="⏭️", style=discord.ButtonStyle.primary)
    async def skip(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        result = await self._validate(interaction)
        if not result:
            return
        voice, _ = result
        if voice.playing or voice.paused:
            await voice.stop()
            await interaction.followup.send("Skipped.", ephemeral=True)
        else:
            await interaction.followup.send("Nothing is playing.", ephemeral=True)

    @discord.ui.button(label="Shuffle", emoji="🔀", style=discord.ButtonStyle.secondary)
    async def shuffle(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        result = await self._validate(interaction)
        if not result:
            return
        _, state = result
        tracks = list(state.queue)
        random.shuffle(tracks)
        state.queue = deque(tracks)
        await refresh_panel(state)
        await interaction.followup.send("Queue shuffled.", ephemeral=True)

    @discord.ui.button(label="Queue", emoji="📜", style=discord.ButtonStyle.secondary)
    async def show_queue(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        result = await self._validate(interaction)
        if not result:
            return
        _, state = result
        await interaction.followup.send(
            embed=queue_embed(state),
            ephemeral=True,
        )

    @discord.ui.button(label="Stop", emoji="⏹️", style=discord.ButtonStyle.danger)
    async def stop(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        result = await self._validate(interaction)
        if not result:
            return
        voice, state = result
        state.queue.clear()
        if voice.playing or voice.paused:
            state.suppress_after = True
            await voice.stop()
        else:
            state.current = None
            state.suppress_after = False
        state.started_at = None
        state.elapsed_before_pause = 0.0
        state.paused_at = None
        await refresh_panel(state)
        await interaction.followup.send(
            "Playback stopped and the queue is clear.",
            ephemeral=True,
        )


def help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🌸 isai — little music commands",
        description=(
            f"Use `/command` or the **`{PREFIX}` prefix**, for example "
            f"`{PREFIX}play lofi`."
        ),
        color=EMBED_COLOR,
    )
    embed.add_field(
        name="Music",
        value=(
            "`play` — title, YouTube/media link, mix, or Spotify link\n"
            "`connect` (`c`) · `disconnect` (`dc`) · `stop`\n"
            "`pause` · `resume` · `skip` · `previous` (`prev`, `back`)\n"
            "`queue` (`q`) · `remove <position>` · `clear` · `shuffle`\n"
            "`loop <off|track|queue>` · `bass <true|false>`"
        ),
        inline=False,
    )
    embed.add_field(
        name="Player panel",
        value="Pause/resume, previous, skip, shuffle, queue, and stop buttons.",
        inline=False,
    )
    embed.add_field(
        name="Owner only",
        value=(
            "`say` · `dm` · `status <online|idle|dnd>` · `platform`\n"
            "The platform command explains a Discord bot API limitation."
        ),
        inline=False,
    )
    embed.set_footer(
        text="Lavalink plays audio; Spotify links are metadata/search only."
    )
    return embed


async def play_request(
    ctx: commands.Context,
    query: str,
) -> str:
    if not ctx.guild or not isinstance(ctx.author, discord.Member):
        raise ValueError("Use this command inside a server.")
    count, channel_name = await add_tracks(
        ctx.guild,
        ctx.author,
        ctx.channel,
        query,
    )
    if count == 1:
        return f"Added your song and joined **{channel_name}**."
    return f"Added **{count} tracks** to the queue and joined **{channel_name}**."


def user_is_owner(user: discord.abc.User) -> bool:
    return user.id in OWNER_IDS


async def handle_command_error(
    ctx: commands.Context,
    error: commands.CommandError,
) -> None:
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await safe_respond(ctx, f"Missing argument: `{error.param.name}`.")
        return
    if isinstance(error, commands.BadArgument):
        await safe_respond(ctx, "I couldn’t understand that argument. Check `/help`.")
        return
    log.error("Command error: %s", error)
    await safe_respond(ctx, "Something went wrong while running that command.")


# ----------------------- Hybrid prefix/slash commands -----------------------


@bot.hybrid_command(
    name="play",
    aliases=["p"],
    description="Play a song, playlist, mix, or supported media link.",
)
@app_commands.describe(query="Song title, YouTube/media link, or Spotify link")
async def play(ctx: commands.Context, *, query: str) -> None:
    if ctx.interaction:
        await ctx.defer(ephemeral=True, thinking=True)
    try:
        message = await play_request(ctx, query)
        await safe_respond(ctx, message, ephemeral=True)
    except (ValueError, wavelink.LavalinkException, discord.ClientException, discord.Forbidden) as error:
        await safe_respond(ctx, str(error), ephemeral=True)


@bot.hybrid_command(
    name="connect",
    aliases=["c", "join"],
    description="Join your voice channel.",
)
async def connect(ctx: commands.Context) -> None:
    if not ctx.guild or not isinstance(ctx.author, discord.Member):
        await safe_respond(ctx, "Use this command inside a server.")
        return
    try:
        voice = await ensure_voice(ctx.guild, ctx.author)
        await safe_respond(ctx, f"Joined **{voice.channel.name}**. Ready when you are.")
    except (ValueError, discord.ClientException, discord.Forbidden) as error:
        await safe_respond(ctx, str(error))


@bot.hybrid_command(
    name="disconnect",
    aliases=["dc", "leave"],
    description="Leave voice and clear the queue.",
)
async def disconnect(ctx: commands.Context) -> None:
    if not ctx.guild:
        await safe_respond(ctx, "Use this command inside a server.")
        return
    voice = ctx.guild.voice_client
    if not is_player(voice):
        await safe_respond(ctx, "I’m not in a voice channel.")
        return
    state = state_for(ctx.guild.id)
    state.queue.clear()
    if voice.playing or voice.paused:
        state.suppress_after = True
        await voice.stop()
    state.current = None
    await voice.disconnect()
    state.suppress_after = False
    await safe_respond(ctx, "Disconnected and cleared the queue.")


@bot.hybrid_command(name="pause", description="Pause the current song.")
async def pause(ctx: commands.Context) -> None:
    voice = ctx.guild.voice_client if ctx.guild else None
    if not is_player(voice) or not voice.playing:
        await safe_respond(ctx, "Nothing is playing right now.")
        return
    state = state_for(ctx.guild.id)  # type: ignore[union-attr]
    state.elapsed_before_pause = elapsed_time(state)
    state.paused_at = time.monotonic()
    await voice.pause(True)
    await refresh_panel(state, ctx.channel)
    await safe_respond(ctx, "Paused.")


@bot.hybrid_command(name="resume", description="Resume the paused song.")
async def resume(ctx: commands.Context) -> None:
    voice = ctx.guild.voice_client if ctx.guild else None
    if not is_player(voice) or not voice.paused:
        await safe_respond(ctx, "Nothing is paused right now.")
        return
    state = state_for(ctx.guild.id)  # type: ignore[union-attr]
    state.started_at = time.monotonic()
    state.paused_at = None
    await voice.pause(False)
    await refresh_panel(state, ctx.channel)
    await safe_respond(ctx, "Back to the music.")


@bot.hybrid_command(name="skip", description="Skip the current song.")
async def skip(ctx: commands.Context) -> None:
    voice = ctx.guild.voice_client if ctx.guild else None
    if not is_player(voice) or not (voice.playing or voice.paused):
        await safe_respond(ctx, "Nothing is playing right now.")
        return
    await voice.stop()
    await safe_respond(ctx, "Skipped.")


@bot.hybrid_command(name="stop", description="Stop playback and clear the queue.")
async def stop(ctx: commands.Context) -> None:
    if not ctx.guild:
        await safe_respond(ctx, "Use this command inside a server.")
        return
    state = state_for(ctx.guild.id)
    state.queue.clear()
    voice = ctx.guild.voice_client
    if is_player(voice) and (voice.playing or voice.paused):
        state.suppress_after = True
        await voice.stop()
    else:
        state.current = None
        state.suppress_after = False
    state.started_at = None
    state.elapsed_before_pause = 0.0
    state.paused_at = None
    await refresh_panel(state, ctx.channel)
    await safe_respond(ctx, "Stopped and cleared the queue.")


@bot.hybrid_command(name="shuffle", description="Shuffle the waiting songs.")
async def shuffle(ctx: commands.Context) -> None:
    if not ctx.guild:
        await safe_respond(ctx, "Use this command inside a server.")
        return
    state = state_for(ctx.guild.id)
    tracks = list(state.queue)
    random.shuffle(tracks)
    state.queue = deque(tracks)
    await refresh_panel(state, ctx.channel)
    await safe_respond(ctx, "Queue shuffled.")


@bot.hybrid_command(
    name="queue",
    aliases=["q"],
    description="Show the current song and waiting queue.",
)
async def queue(ctx: commands.Context) -> None:
    if not ctx.guild:
        await safe_respond(ctx, "Use this command inside a server.")
        return
    await safe_respond(ctx, embed=queue_embed(state_for(ctx.guild.id)))


@bot.hybrid_command(name="remove", aliases=["rm"], description="Remove a queued song by position.")
@app_commands.describe(position="The song's number in /queue, starting from 1")
async def remove(ctx: commands.Context, position: int) -> None:
    if not ctx.guild:
        await safe_respond(ctx, "Use this command inside a server.")
        return
    state = state_for(ctx.guild.id)
    if position < 1 or position > len(state.queue):
        await safe_respond(ctx, f"Choose a position from 1 to {len(state.queue)}.")
        return
    tracks = list(state.queue)
    removed = tracks.pop(position - 1)
    state.queue = deque(tracks)
    await refresh_panel(state, ctx.channel)
    await safe_respond(
        ctx,
        f"Removed **{discord.utils.escape_markdown(removed.title)}**.",
    )


@bot.hybrid_command(
    name="clear",
    aliases=["clr"],
    description="Clear waiting songs without stopping the current one.",
)
async def clear(ctx: commands.Context) -> None:
    if not ctx.guild:
        await safe_respond(ctx, "Use this command inside a server.")
        return
    state = state_for(ctx.guild.id)
    state.queue.clear()
    await refresh_panel(state, ctx.channel)
    await safe_respond(ctx, "Queue cleared. The current song will keep playing.")


@bot.hybrid_command(
    name="previous",
    aliases=["prev", "back"],
    description="Play the previous song again.",
)
async def previous(ctx: commands.Context) -> None:
    if not ctx.guild:
        await safe_respond(ctx, "Use this command inside a server.")
        return
    state = state_for(ctx.guild.id)
    voice = ctx.guild.voice_client
    if not state.history:
        await safe_respond(ctx, "There isn’t a previous song yet.")
        return
    if state.current:
        state.queue.appendleft(state.current)
    state.queue.appendleft(state.history.pop())
    if is_player(voice) and (voice.playing or voice.paused):
        state.suppress_after = True
        await voice.stop()
    else:
        await start_next(ctx.guild.id)
    await safe_respond(ctx, "Playing the previous song.")


@bot.hybrid_command(
    name="loop",
    aliases=["repeat", "rep"],
    description="Set repeat mode for the current server.",
)
@app_commands.choices(
    mode=[
        app_commands.Choice(name="Off", value="off"),
        app_commands.Choice(name="Current track", value="track"),
        app_commands.Choice(name="Queue", value="queue"),
    ]
)
async def loop(ctx: commands.Context, mode: str | None = None) -> None:
    if not ctx.guild:
        await safe_respond(ctx, "Use this command inside a server.")
        return
    state = state_for(ctx.guild.id)
    if mode is None:
        await safe_respond(
            ctx,
            f"Repeat is **{state.loop_mode}**. Choose `off`, `track`, or `queue`.",
        )
        return
    mode = mode.lower()
    if mode not in {"off", "track", "queue"}:
        await safe_respond(ctx, "Choose `off`, `track`, or `queue`.")
        return
    state.loop_mode = mode
    await refresh_panel(state, ctx.channel)
    await safe_respond(ctx, f"Repeat set to **{mode}**.")


@bot.hybrid_command(name="bass", description="Set bass boost for the next song.")
@app_commands.describe(enabled="True to boost bass, false to turn it off")
async def bass(ctx: commands.Context, enabled: bool) -> None:
    if not ctx.guild:
        await safe_respond(ctx, "Use this command inside a server.")
        return
    state = state_for(ctx.guild.id)
    state.bass = enabled
    await refresh_panel(state, ctx.channel)
    await safe_respond(
        ctx,
        f"Bass boost is {'on' if enabled else 'off'} for the next song.",
    )


@bot.hybrid_command(name="help", description="Show Isai's music commands.")
async def help_command(ctx: commands.Context) -> None:
    await safe_respond(ctx, embed=help_embed())


# ---------------------------- Owner commands ----------------------------


@bot.hybrid_command(name="say", description="Owner only: send a message in this channel.")
@app_commands.describe(message="Text for Isai to send")
async def say(ctx: commands.Context, *, message: str) -> None:
    if not user_is_owner(ctx.author):
        await safe_respond(ctx, "That command is only available to the bot owners.", ephemeral=True)
        return
    await safe_respond(
        ctx,
        message,
        ephemeral=False,
    )


@bot.hybrid_command(name="dm", description="Owner only: send a direct message.")
@app_commands.describe(user="The recipient", message="Text for Isai to send")
async def dm(ctx: commands.Context, user: discord.User, *, message: str) -> None:
    if not user_is_owner(ctx.author):
        await safe_respond(ctx, "That command is only available to the bot owners.", ephemeral=True)
        return
    if user.bot:
        await safe_respond(ctx, "I won’t send owner DMs to bot accounts.", ephemeral=True)
        return
    try:
        await user.send(
            message,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await safe_respond(
            ctx,
            f"Sent a DM to **{discord.utils.escape_markdown(user.name)}**.",
            ephemeral=True,
        )
    except discord.Forbidden:
        await safe_respond(ctx, "That user’s DMs are closed.", ephemeral=True)


@bot.hybrid_command(name="status", description="Owner only: set the bot's status.")
@app_commands.choices(
    status=[
        app_commands.Choice(name="Online", value="online"),
        app_commands.Choice(name="Idle", value="idle"),
        app_commands.Choice(name="Do Not Disturb", value="dnd"),
    ]
)
async def status(ctx: commands.Context, status: str) -> None:
    if not user_is_owner(ctx.author):
        await safe_respond(ctx, "That command is only available to the bot owners.", ephemeral=True)
        return
    status_value = {
        "online": discord.Status.online,
        "idle": discord.Status.idle,
        "dnd": discord.Status.dnd,
    }.get(status.lower())
    if status_value is None:
        await safe_respond(ctx, "Choose `online`, `idle`, or `dnd`.", ephemeral=True)
        return
    await bot.change_presence(status=status_value)
    await safe_respond(ctx, f"Bot status set to **{status.lower()}**.", ephemeral=True)


@bot.hybrid_command(name="platform", description="Owner only: explain Discord bot platform limits.")
async def platform(ctx: commands.Context) -> None:
    if not user_is_owner(ctx.author):
        await safe_respond(ctx, "That command is only available to the bot owners.", ephemeral=True)
        return
    await safe_respond(
        ctx,
        "Discord’s official bot API does not let a bot choose or spoof a VR, mobile, "
        "or desktop client platform. No platform setting was changed.",
        ephemeral=True,
    )


# ------------------------------ Bot events ------------------------------


@bot.event
async def on_wavelink_node_ready(payload: wavelink.NodeReadyEventPayload) -> None:
    log.info("Connected to Lavalink node %s.", payload.node.identifier)


@bot.event
async def on_wavelink_node_disconnected(
    payload: wavelink.NodeDisconnectedEventPayload,
) -> None:
    log.warning("Lavalink node %s disconnected; Wavelink will attempt to reconnect.", payload.node.identifier)


@bot.event
async def on_wavelink_track_end(payload: wavelink.TrackEndEventPayload) -> None:
    player = payload.player
    if not player:
        return
    state = state_for(player.guild.id)
    ended = state.current

    if state.suppress_after:
        state.suppress_after = False
    elif ended:
        if payload.reason == "finished" and state.loop_mode == "track":
            state.queue.appendleft(ended)
        elif payload.reason == "finished" and state.loop_mode == "queue":
            state.queue.append(ended)
        else:
            state.history.append(ended)

    state.current = None
    state.started_at = None
    state.elapsed_before_pause = 0.0
    state.paused_at = None
    await start_next(player.guild.id)
    await refresh_panel(state)


@bot.event
async def on_wavelink_track_exception(
    payload: wavelink.TrackExceptionEventPayload,
) -> None:
    log.warning(
        "Lavalink track exception for guild %s: %s",
        payload.player.guild.id if payload.player else "unknown",
        payload.exception,
    )


@bot.event
async def on_ready() -> None:
    log.info("Isai is ready as %s.", bot.user)
    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Activity(
            type=discord.ActivityType.listening,
            name=f"{PREFIX}help • /help",
        ),
    )


@bot.event
async def on_command_error(
    ctx: commands.Context,
    error: commands.CommandError,
) -> None:
    await handle_command_error(ctx, error)


@bot.event
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    log.error("Slash command error: %s", error)
    await respond_interaction(
        interaction,
        "Something went wrong while running that command.",
    )


async def main() -> None:
    missing = []
    if not TOKEN:
        missing.append("TOKEN")
    if not LAVALINK_PASSWORD:
        missing.append("LAVALINK_PASSWORD")
    if missing:
        raise SystemExit(
            "Add the required secret(s) before starting Isai: "
            + ", ".join(missing)
        )
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Isai stopped.")
