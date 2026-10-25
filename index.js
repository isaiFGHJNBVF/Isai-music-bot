require('dotenv').config();
const {
  Client,
  GatewayIntentBits,
  Partials,
  EmbedBuilder,
  ActionRowBuilder,
  ButtonBuilder,
  ButtonStyle,
  SlashCommandBuilder,
  ActivityType,
  Events,
  MessageFlags
} = require('discord.js');
const { Poru, Rest } = require('poru');

// Lavalink REST content-type patch:
// Some Lavalink nodes return 'application/json;charset=utf-8' which fails Poru's
// strict `=== "application/json"` check, causing Rest.get to return a raw string
// and throwing "Cannot create property 'loadType' on string".
if (Rest && Rest.prototype && Rest.prototype.get) {
  const origRestGet = Rest.prototype.get;
  Rest.prototype.get = async function (path) {
    const res = await origRestGet.call(this, path);
    if (typeof res === 'string') {
      try {
        return JSON.parse(res);
      } catch {
        // Upstream returned an HTML error page (e.g. Cloudflare 502/524)
        return { loadType: 'error', data: { message: 'Upstream server error' } };
      }
    }
    return res;
  };
}

// ==========================================
// 🛡️ ANTI-CRASH PROTECTION SYSTEM
// ==========================================
process.on('unhandledRejection', (reason) => {
  console.error('[Anti-Crash] Unhandled Rejection:', reason);
});
process.on('uncaughtException', (err) => {
  console.error('[Anti-Crash] Uncaught Exception:', err);
});

// ==========================================
// 🌸 BOT CONFIGURATION & SETTINGS
// ==========================================
const fs = require('fs');
const path = require('path');

const SETTINGS_FILE = path.join(__dirname, 'settings.json');

function loadSettings() {
  try {
    const data = JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf8'));
    return {
      prefix: typeof data.prefix === 'string' && data.prefix.trim() ? data.prefix : 'i',
      stay247: data.stay247 && typeof data.stay247 === 'object' ? data.stay247 : {}
    };
  } catch {
    return { prefix: 'i', stay247: {} };
  }
}

const settings = loadSettings();

function saveSettings() {
  try {
    fs.writeFileSync(SETTINGS_FILE, JSON.stringify(settings, null, 2));
  } catch (err) {
    console.log('[isai Settings Error]', err.message);
  }
}

let prefix = settings.prefix;
const THEME_COLOR = 0xf3c4db; // Aesthetic sakura blush

// Parse owner IDs from .env
const owner = process.env.OWNERS
  ? process.env.OWNERS.split(',').map((id) => id.trim())
  : ['1377967442172579843', '1247200258719617115'];

const isOwnerUser = (id) => owner.includes(id);

// Commands owners may use without the prefix (no-prefix is an owner privilege).
const NO_PREFIX_ALIASES = new Set([
  'play', 'p', 'connect', 'c', 'join', 'j', 'disconnect', 'dc', 'leave', 'l',
  'pause', 'resume', 'r', 'skip', 's', 'next', 'previous', 'prev', 'back', 'stop',
  'queue', 'q', 'clear', 'clr', 'clean', 'remove', 'rm', 'del', 'shuffle', 'sh',
  'bass', 'bb', 'loop', 'repeat', 'repeate', 'rep', 'lp', 'help', 'h',
  '247', '24/7', 'stay', 'prefix', 'setprefix',
  'say', 'dm', 'status', 'customstatus', 'cstatus', 'custom', 'dev'
]);

// Custom Emojis for Player Buttons
const EMOJIS = {
  PREVIOUS: '<:Previous:1562765089332011009>',
  PAUSE_PLAY: '<:pause_play:1562765087046115408>',
  STOP: '<:stop:1562765084592443462>',
  SKIP: '<:skip:1562765082050564146>',
  LOOP: '<:loop:1562765079470936064>',
  SHUFFLE: '<:shuffle:1562765076942032956>',
  BASS: '<:bass:1562765074458738758>',
  QUEUE: '<:queue:1562765071912804362>'
};

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.GuildVoiceStates,
    GatewayIntentBits.MessageContent,
    GatewayIntentBits.GuildMessageReactions
  ],
  partials: [Partials.Message, Partials.Channel, Partials.Reaction]
});

// Without these listeners a single gateway error would crash the whole process.
client.on(Events.Error, (err) => console.error('[isai Discord Error]', err?.message || err));
client.on(Events.Warn, (msg) => console.warn('[isai Discord Warn]', msg));

// Lavalink Node Setup (supports multiple fallback nodes)
// Option A: LAVALINK_NODES='[{"name":"A","host":"x.com","port":443,"password":"pw","secure":true}]'
// Option B: single node via LAVALINK_HOST / PORT / PASSWORD / SECURE
let nodes;
try {
  nodes = process.env.LAVALINK_NODES ? JSON.parse(process.env.LAVALINK_NODES) : null;
} catch (e) {
  console.log('[isai] LAVALINK_NODES is not valid JSON, falling back to single node.');
}
if (!Array.isArray(nodes) || !nodes.length) {
  nodes = [{
    name: 'isai-Core',
    host: process.env.LAVALINK_HOST,
    port: parseInt(process.env.LAVALINK_PORT || '2333', 10),
    password: process.env.LAVALINK_PASSWORD || 'youshallnotpass',
    secure: process.env.LAVALINK_SECURE === 'true'
  }];
}

console.log(`[isai Audio] Configured nodes: ${nodes.map((n) => `${n.name} (${n.host}:${n.port})`).join(', ')}`);

// Poru Audio Engine (Default: YouTube Music)
client.poru = new Poru(client, nodes, {
  library: 'discord.js',
  defaultPlatform: 'ytmsearch',
  reconnectTimeout: 10000,
  reconnectTries: 100
});

// True when at least one Lavalink node is connected
const hasNode = () => client.poru.leastUsedNodes.length > 0;
const NO_NODE_EMBED = () => new EmbedBuilder()
  .setColor(THEME_COLOR)
  .setDescription('⚠️ **The music server is offline right now. Please try again in a bit!**');

// ==========================================
// 🛰️ LAVALINK NODE SUPERVISION
// ==========================================
// Poru removes a node from its internal list the moment its socket closes, and
// its built-in reconnect gives up after `reconnectTries`. Free/public nodes drop
// sockets on purpose (idle timeout, restarts, session limits), which used to
// leave the bot with zero nodes forever -> every command answered
// "music server is offline". This re-creates the node whenever it disappears.
const nodeConfigs = nodes;
let nodeRecoveryInFlight = false;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForNode(timeoutMs = 0) {
  const deadline = Date.now() + timeoutMs;
  while (!hasNode()) {
    if (Date.now() >= deadline) return null;
    await sleep(250);
  }
  return client.poru.leastUsedNodes[0];
}

async function restoreNodes() {
  if (hasNode() || nodeRecoveryInFlight) return null;
  nodeRecoveryInFlight = true;
  try {
    for (const config of nodeConfigs) {
      const existing = client.poru.nodes.get(config.name);
      try {
        if (existing) {
          // Cancel Poru's pending reconnect so two sockets never open at once.
          if (existing.reconnectAttempt) {
            clearTimeout(existing.reconnectAttempt);
            existing.reconnectAttempt = null;
          }
          // Drop the dead socket first: its close handler would otherwise remove
          // the node we are about to re-add under the same name. Aborting a socket
          // that is still connecting emits "error"/"close" on it, so keep no-op
          // listeners attached or Node turns that into an uncaught exception.
          if (existing.ws) {
            const stale = existing.ws;
            existing.ws = null;
            stale.removeAllListeners();
            stale.on('error', () => {});
            stale.on('close', () => {});
            try { stale.terminate(); } catch { /* already closed */ }
          }
          existing.isConnected = false;
          existing.attempt = 0;
          await existing.connect();
        } else {
          await client.poru.addNode(config);
        }
      } catch (err) {
        console.log(`[isai Audio Error] Could not (re)connect ${config.name}:`, err.message);
        continue;
      }

      if (await waitForNode(5000)) {
        console.log(`[isai Audio] Node ${config.name} recovered ♡`);
        return client.poru.leastUsedNodes[0];
      }
    }
    console.log('[isai Audio] Still no Lavalink node available, retrying soon.');
    return null;
  } finally {
    nodeRecoveryInFlight = false;
  }
}

// Used by music commands: wait a few seconds for the node to come back instead
// of instantly answering "offline" while it is reconnecting.
async function getMusicNode(waitMs = 8000) {
  if (hasNode()) return client.poru.leastUsedNodes[0];
  restoreNodes().catch((err) => console.log('[isai Audio Error] Node recovery failed:', err.message));
  return waitForNode(waitMs);
}

// ==========================================
// 🔁 24/7 VOICE MODE
// ==========================================
// Enabled guilds are stored in settings.json so the bot rejoins their voice
// channel after a restart or a kick, and never leaves when the queue ends.
async function setStay247(guild, voiceChannel, textChannel, enable) {
  if (!enable) {
    delete settings.stay247[guild.id];
    saveSettings();
    return { ok: true, enabled: false };
  }

  if (!voiceChannel) return { ok: false, reason: 'voice' };
  if (!(await getMusicNode())) return { ok: false, reason: 'node' };

  settings.stay247[guild.id] = { voiceChannel: voiceChannel.id, textChannel: textChannel.id };
  saveSettings();

  const player = client.poru.players.get(guild.id);
  if (player) {
    if (player.voiceChannel !== voiceChannel.id) {
      player.voiceChannel = voiceChannel.id;
      player.connect();
    }
  } else {
    client.poru.createConnection({
      guildId: guild.id,
      voiceChannel: voiceChannel.id,
      textChannel: textChannel.id,
      deaf: true
    });
  }

  return { ok: true, enabled: true };
}

async function rejoinStay(guildId) {
  const saved = settings.stay247[guildId];
  const guild = client.guilds.cache.get(guildId);
  if (!saved || !guild) return;
  if (!(await getMusicNode())) return;

  const player = client.poru.players.get(guildId);
  if (player) {
    player.voiceChannel = saved.voiceChannel;
    player.textChannel = saved.textChannel;
    player.connect();
    return;
  }

  client.poru.createConnection({
    guildId,
    voiceChannel: saved.voiceChannel,
    textChannel: saved.textChannel,
    deaf: true
  });
  console.log(`[isai 24/7] Rejoined ${guild.name}.`);
}

async function restoreStayGuilds() {
  const entries = Object.entries(settings.stay247);
  if (!entries.length) return;

  if (!(await waitForNode(30000))) {
    console.log('[isai 24/7] No Lavalink node yet, will rejoin on the next command.');
    return;
  }

  for (const [guildId, saved] of entries) {
    const guild = client.guilds.cache.get(guildId);
    if (!guild || !saved?.voiceChannel) continue;

    if (!guild.channels.cache.get(saved.voiceChannel)) {
      delete settings.stay247[guildId];
      saveSettings();
      continue;
    }

    try {
      const player = client.poru.players.get(guildId);
      if (player) {
        player.voiceChannel = saved.voiceChannel;
        player.textChannel = saved.textChannel;
        player.connect();
      } else {
        client.poru.createConnection({
          guildId,
          voiceChannel: saved.voiceChannel,
          textChannel: saved.textChannel,
          deaf: true
        });
      }
      console.log(`[isai 24/7] Rejoined ${guild.name}.`);
    } catch (err) {
      console.log('[isai 24/7 Error]', err?.message || err);
    }
  }
}

// State & Panel Management
const activePanels = new Map();
const guildState = new Map();

function getState(guildId) {
  if (!guildState.has(guildId)) {
    guildState.set(guildId, { bassboost: false, previousTrack: null });
  }
  return guildState.get(guildId);
}

// Cleanly delete old panel and clear ticker
async function cleanupOldPanel(guildId) {
  const existing = activePanels.get(guildId);
  if (existing) {
    if (existing.interval) clearInterval(existing.interval);
    if (existing.msg) {
      await existing.msg.delete().catch(() => {});
    }
    activePanels.delete(guildId);
  }
}

// Format Milliseconds to MM:SS
function formatTime(ms) {
  if (!ms || isNaN(ms)) return '00:00';
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
}

// Aesthetic Visual Slider
function renderProgressBar(current, total, length = 12) {
  if (total <= 0) return '━'.repeat(length);
  const ratio = Math.min(Math.max(current / total, 0), 1);
  const passed = Math.round(length * ratio);
  const remaining = length - passed;
  return '━'.repeat(passed) + '🔘' + '─'.repeat(Math.max(0, remaining - 1));
}

// Extract real song thumbnail
function getTrackThumbnail(track) {
  if (!track || !track.info) return null;
  const info = track.info;

  if (info.artworkUrl && typeof info.artworkUrl === 'string' && info.artworkUrl.startsWith('http')) {
    return info.artworkUrl;
  }
  if (info.image && typeof info.image === 'string' && info.image.startsWith('http')) {
    return info.image;
  }

  let ytId = null;
  if (info.identifier && info.identifier.length === 11) {
    ytId = info.identifier;
  } else if (info.uri) {
    const match = info.uri.match(/(?:youtu\.be\/|youtube\.com\/(?:watch\?v=|embed\/|shorts\/))([\w-]{11})/);
    if (match && match[1]) ytId = match[1];
  }

  if (ytId) {
    return `https://i.ytimg.com/vi/${ytId}/hqdefault.jpg`;
  }

  return null;
}

// Fire-and-forget wrapper for Poru calls that reject when a node drops.
const safe = (promise) => Promise.resolve(promise).catch((err) => {
  console.log('[isai Audio Error]', err?.message || err);
});

// Safe Stop Method for Poru
function stopMusic(player, guildId) {
  cleanupOldPanel(guildId);
  if (!player) return;
  player.queue.clear();
  try {
    if (typeof player.stop === 'function') {
      player.stop();
    } else {
      safe(player.skip());
    }
  } catch (err) {
    console.error('[isai Stop Error]:', err.message);
  }
}

// ==========================================
// 🧸 AESTHETIC PLAYER PANEL BUILDER
// ==========================================
function buildPanelEmbed(player, track) {
  const state = getState(player.guildId);
  const position = player.position || 0;
  const duration = track.info.length || 0;
  const isStream = track.info.isStream;
  const progressBar = isStream
    ? '🔴 ʟɪᴠᴇ sᴛʀᴇᴀᴍ'
    : `${formatTime(position)} ${renderProgressBar(position, duration, 10)} ${formatTime(duration)}`;

  const loopIcon = player.loop === 'TRACK' ? '🔂 Song' : player.loop === 'QUEUE' ? '🔁 Queue' : 'Off';
  const isBass = state.bassboost ? '🔊 Active' : '🔈 Standard';

  const embed = new EmbedBuilder()
    .setColor(THEME_COLOR)
    .setAuthor({ name: '⋆˚࿔ 𝐧𝐨𝐰 𝐩𝐥𝐚𝐲𝐢𝐧𝐠 𝜗𝜚˚⋆', iconURL: client.user.displayAvatarURL() })
    .setTitle(track.info.title.substring(0, 70))
    .setURL(track.info.uri)
    .setDescription(
      `**Author:** \`${track.info.author}\`\n` +
      `**Requested By:** <@${track.info.requester?.id || track.info.requester}>\n` +
      `**Duration:** \`${formatTime(duration)}\`\n\n` +
      `${progressBar}\n`
    )
    .addFields(
      { name: '୨ৎ Loop', value: `\`${loopIcon}\``, inline: true },
      { name: '୨ৎ Bass', value: `\`${isBass}\``, inline: true },
      { name: '୨ৎ In Queue', value: `\`${player.queue.length} track(s)\``, inline: true }
    )
    .setFooter({ text: 'isai • Pure aesthetic vibes ♡', iconURL: client.user.displayAvatarURL() });

  const songCover = getTrackThumbnail(track);
  if (songCover) {
    embed.setThumbnail(songCover);
  }

  return embed;
}

// All Buttons Strictly Dark Grey
function buildPanelButtons() {
  const row1 = new ActionRowBuilder().addComponents(
    new ButtonBuilder()
      .setCustomId('btn_prev')
      .setEmoji(EMOJIS.PREVIOUS)
      .setStyle(ButtonStyle.Secondary),
    new ButtonBuilder()
      .setCustomId('btn_pause')
      .setEmoji(EMOJIS.PAUSE_PLAY)
      .setStyle(ButtonStyle.Secondary),
    new ButtonBuilder()
      .setCustomId('btn_skip')
      .setEmoji(EMOJIS.SKIP)
      .setStyle(ButtonStyle.Secondary),
    new ButtonBuilder()
      .setCustomId('btn_stop')
      .setEmoji(EMOJIS.STOP)
      .setStyle(ButtonStyle.Secondary)
  );

  const row2 = new ActionRowBuilder().addComponents(
    new ButtonBuilder()
      .setCustomId('btn_loop')
      .setEmoji(EMOJIS.LOOP)
      .setStyle(ButtonStyle.Secondary),
    new ButtonBuilder()
      .setCustomId('btn_shuffle')
      .setEmoji(EMOJIS.SHUFFLE)
      .setStyle(ButtonStyle.Secondary),
    new ButtonBuilder()
      .setCustomId('btn_bass')
      .setEmoji(EMOJIS.BASS)
      .setStyle(ButtonStyle.Secondary),
    new ButtonBuilder()
      .setCustomId('btn_queue')
      .setEmoji(EMOJIS.QUEUE)
      .setStyle(ButtonStyle.Secondary)
  );

  return [row1, row2];
}

// ==========================================
// 🎵 PORU (LAVALINK) EVENTS
// ==========================================
client.poru.on('nodeConnect', (node) => {
  node.attempt = 0;
  console.log(`[isai Audio] Connected to Lavalink Node: ${node.name} ✨`);

  // A reconnect starts a fresh Lavalink session: re-send voice state so that
  // players created before the drop can still play afterwards.
  for (const player of client.poru.players.values()) {
    if (player.node === node) player.connect();
  }
});

client.poru.on('nodeDisconnect', (node, code) => {
  if (!code) return; // Poru emits this twice per drop; only the one with a close code matters
  console.log(`[isai Audio] Lost connection to ${node.name} (code ${code}).`);
});

client.poru.on('nodeReconnect', (node) => {
  console.log(`[isai Audio] Reconnecting to ${node.name}...`);
});

client.poru.on('nodeError', (node, error) => {
  console.log(`[isai Audio Error] ${node.name}:`, error?.code || error?.message || error);
});

// Set LAVALINK_DEBUG=true in .env to see raw Poru websocket details.
client.poru.on('debug', (...args) => {
  if (process.env.LAVALINK_DEBUG === 'true') console.log('[Poru Debug]', ...args);
});

client.poru.on('trackStart', async (player, track) => {
  await cleanupOldPanel(player.guildId);

  const channel = client.channels.cache.get(player.textChannel);
  if (!channel) return;

  const panelMsg = await channel.send({
    embeds: [buildPanelEmbed(player, track)],
    components: buildPanelButtons()
  }).catch(() => null);

  if (!panelMsg) return;

  const interval = setInterval(async () => {
    if (!player.isPlaying || player.isPaused) return;
    try {
      await panelMsg.edit({
        embeds: [buildPanelEmbed(player, track)],
        components: buildPanelButtons()
      });
    } catch {
      clearInterval(interval);
    }
  }, 5000);

  activePanels.set(player.guildId, { msg: panelMsg, interval });
});

client.poru.on('trackEnd', async (player, track) => {
  const state = getState(player.guildId);
  state.previousTrack = track;
  await cleanupOldPanel(player.guildId);
});

client.poru.on('queueEnd', async (player) => {
  await cleanupOldPanel(player.guildId);
  const channel = client.channels.cache.get(player.textChannel);
  if (channel) {
    channel.send({
      embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('˗ˏˋ 𝜗𝜚 **Queue completed!** Hope you enjoyed the music. `ˎˊ˗')]
    }).catch(() => null);
  }
});

// ==========================================
// 🚀 SLASH COMMAND DEFINITIONS
// ==========================================
const slashCommands = [
  new SlashCommandBuilder()
    .setName('play')
    .setDescription('Play a song from YouTube Music, Spotify, or direct audio link')
    .addStringOption(opt =>
      opt.setName('query')
        .setDescription('Song title, YouTube Music URL, or Spotify link')
        .setRequired(true)
        .setAutocomplete(true)
    ),
  new SlashCommandBuilder().setName('pause').setDescription('Pause playback'),
  new SlashCommandBuilder().setName('resume').setDescription('Resume playback'),
  new SlashCommandBuilder().setName('skip').setDescription('Skip to the next song'),
  new SlashCommandBuilder().setName('previous').setDescription('Play previous song'),
  new SlashCommandBuilder().setName('stop').setDescription('Stop playback and clear queue'),
  new SlashCommandBuilder().setName('connect').setDescription('Join your voice channel'),
  new SlashCommandBuilder().setName('disconnect').setDescription('Leave voice channel'),
  new SlashCommandBuilder().setName('shuffle').setDescription('Shuffle queue order'),
  new SlashCommandBuilder().setName('queue').setDescription('View queued songs'),
  new SlashCommandBuilder().setName('clear').setDescription('Clear the queue'),
  new SlashCommandBuilder()
    .setName('remove')
    .setDescription('Remove a song by index or title')
    .addStringOption(opt => opt.setName('target').setDescription('Song number or title').setRequired(true)),
  new SlashCommandBuilder()
    .setName('bass')
    .setDescription('Toggle high-quality bass boost')
    .addBooleanOption(opt => opt.setName('enabled').setDescription('Enable or disable bass boost').setRequired(true)),
  new SlashCommandBuilder().setName('loop').setDescription('Change repeat/loop modes'),
  new SlashCommandBuilder().setName('help').setDescription('Aesthetic overview of all isai commands'),
  new SlashCommandBuilder().setName('ping').setDescription('Check bot latency and music server status'),
  new SlashCommandBuilder()
    .setName('24-7')
    .setDescription('Keep isai in your voice channel 24/7 (survives restarts)'),
  new SlashCommandBuilder()
    .setName('prefix')
    .setDescription('Change the command prefix (Owner Only)')
    .addStringOption(opt =>
      opt.setName('new_prefix')
        .setDescription('New prefix (1-5 characters, no spaces)')
        .setRequired(true)
    ),

  // Owner Only Slash Commands
  new SlashCommandBuilder()
    .setName('devhelp')
    .setDescription('Developer commands overview (Owner Only)'),
  new SlashCommandBuilder()
    .setName('say')
    .setDescription('Broadcast a message (Owner Only)')
    .addStringOption(opt => opt.setName('content').setDescription('Message content').setRequired(true)),
  new SlashCommandBuilder()
    .setName('dm')
    .setDescription('Send a direct message to a user (Owner Only)')
    .addUserOption(opt => opt.setName('target').setDescription('Target user').setRequired(true))
    .addStringOption(opt => opt.setName('content').setDescription('Message text').setRequired(true)),
  new SlashCommandBuilder()
    .setName('status')
    .setDescription('Update bot presence status (Owner Only)')
    .addStringOption(opt =>
      opt.setName('type')
        .setDescription('online, idle, or dnd')
        .setRequired(true)
        .addChoices(
          { name: 'Online', value: 'online' },
          { name: 'Idle', value: 'idle' },
          { name: 'Do Not Disturb', value: 'dnd' }
        )
    ),
  new SlashCommandBuilder()
    .setName('customstatus')
    .setDescription('Set custom bubble text status (Owner Only)')
    .addStringOption(opt => opt.setName('text').setDescription('Custom status text').setRequired(true))
];

// ==========================================
// 💡 READY & CLEAN PURGE/REFRESH SYSTEM
// ==========================================
client.once(Events.ClientReady, async () => {
  client.poru.init(client);
  console.log(`[isai] Logged in as ${client.user.tag} ♡`);

  // Rejoin voice channels of guilds with 24/7 mode enabled.
  restoreStayGuilds().catch((err) => console.log('[isai 24/7 Error]', err?.message || err));

  // Self-healing watchdog: rebuild the Lavalink node if it ever drops out.
  setInterval(() => {
    if (hasNode()) return;
    console.log('[isai Audio] No Lavalink node connected, attempting recovery...');
    restoreNodes().catch((err) => console.log('[isai Audio Error] Node recovery failed:', err.message));
  }, 15000);

  try {
    console.log('[isai] 🧹 Purging old commands to prevent duplicates...');

    // 1. Delete all per-server slash commands from every guild
    for (const guild of client.guilds.cache.values()) {
      await guild.commands.set([]).catch(() => {});
    }

    // 2. Clear out any outdated global commands
    await client.application.commands.set([]).catch(() => {});

    // 3. Register the clean, fresh command set globally (Single source of truth)
    await client.application.commands.set(slashCommands);
    console.log('[isai] ✨ Fresh slash commands deployed with 0 duplicates!');
  } catch (err) {
    console.error('[isai Command Sync Error]:', err);
  }

  client.user.setPresence({
    status: 'idle',
    activities: [{ name: `${prefix}help | 𝜗𝜚 aesthetic tunes`, type: ActivityType.Listening }]
  });
});

// ==========================================
// 🔍 YOUTUBE MUSIC AUTOCOMPLETE
// ==========================================
client.on(Events.InteractionCreate, async (interaction) => {
  if (!interaction.isAutocomplete()) return;

  if (interaction.commandName === 'play') {
    const focusedValue = interaction.options.getFocused();
    if (!focusedValue || focusedValue.trim().length === 0 || !hasNode()) {
      return interaction.respond([]).catch(() => {});
    }

    try {
      const res = await client.poru.resolve({ query: focusedValue, source: 'ytmsearch' });
      if (!res || !res.tracks || res.tracks.length === 0) {
        return interaction.respond([]);
      }

      const choices = res.tracks.slice(0, 7).map(track => {
        const title = track.info.title.length > 70 ? track.info.title.substring(0, 67) + '...' : track.info.title;
        return {
          name: `🎵 ${title} (${track.info.author})`.substring(0, 100),
          value: track.info.uri || track.info.title
        };
      });

      await interaction.respond(choices);
    } catch {
      await interaction.respond([]).catch(() => {});
    }
  }
});

// ==========================================
// 🎛️ CORE MUSIC ENGINE EXECUTOR
// ==========================================
async function executePlay(guild, member, channel, query, sendReply) {
  const voiceChannel = member?.voice?.channel;
  if (!voiceChannel) {
    return sendReply({
      embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('🌸 **Please join a voice channel first!**')]
    });
  }

  const permissions = voiceChannel.permissionsFor(client.user);
  if (!permissions || !permissions.has('Connect') || !permissions.has('Speak')) {
    return sendReply({
      embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('⚠️ **I need connect and speak permissions in your voice channel!**')]
    });
  }

  if (!(await getMusicNode())) return sendReply({ embeds: [NO_NODE_EMBED()] });

  let player = client.poru.players.get(guild.id);
  // A player left over from a dead Lavalink session can never play again; rebuild it.
  if (player && (!player.node?.isConnected || client.poru.nodes.get(player.node.name) !== player.node)) {
    await player.destroy().catch(() => {});
    player = null;
  }
  if (!player) {
    try {
      player = client.poru.createConnection({
        guildId: guild.id,
        voiceChannel: voiceChannel.id,
        textChannel: channel.id,
        deaf: true
      });
    } catch (err) {
      console.log('[isai Audio Error] Could not create player:', err?.message || err);
      return sendReply({
        embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('⚠️ **I could not join your voice channel. Please try again in a moment!**')]
      });
    }
  }

  const isUrl = /^https?:\/\//i.test(query);
  let res = null;

  if (isUrl) {
    try {
      res = await client.poru.resolve({
        query: query,
        requester: member.user
      });
    } catch (err) {
      console.log('[isai Audio Error] URL resolve failed:', err.message);
    }
  } else {
    // Try multiple search sources in order: ytmsearch -> ytsearch -> scsearch
    const searchPlatforms = ['ytmsearch', 'ytsearch', 'scsearch'];
    for (const source of searchPlatforms) {
      try {
        const candidate = await client.poru.resolve({
          query: query,
          source: source,
          requester: member.user
        });
        if (candidate && candidate.tracks && candidate.tracks.length > 0 && candidate.loadType !== 'error' && candidate.loadType !== 'LOAD_FAILED') {
          res = candidate;
          break;
        }
      } catch (err) {
        console.log(`[isai Audio] ${source} search failed:`, err.message);
      }
    }
  }

  if (!res) {
    const existing = client.poru.players.get(guild.id);
    if (existing && !existing.currentTrack && existing.queue.length === 0) existing.destroy();
    return sendReply({
      embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('⚠️ **The music server is having trouble loading songs right now. Please try again shortly!**')]
    });
  }

  if (res.loadType === 'LOAD_FAILED' || res.loadType === 'error') {
    return sendReply({
      embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('❌ **Failed to load track or media.**')]
    });
  }

  if (res.loadType === 'NO_MATCHES' || res.loadType === 'empty') {
    return sendReply({
      embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('🔍 **No songs found for that search query.**')]
    });
  }

  if (res.loadType === 'PLAYLIST_LOADED' || res.loadType === 'playlist') {
    for (const track of res.tracks) {
      track.info.requester = member.user;
      player.queue.add(track);
    }

    sendReply({
      embeds: [
        new EmbedBuilder()
          .setColor(THEME_COLOR)
          .setDescription(`˚.⋆ 𝜗𝜚 **Added Playlist:** \`${res.playlistInfo.name}\` with **${res.tracks.length}** tracks!`)
      ]
    });
  } else {
    const track = res.tracks[0];
    track.info.requester = member.user;
    player.queue.add(track);

    if (player.isPlaying) {
      const cover = getTrackThumbnail(track);
      const queueEmbed = new EmbedBuilder()
        .setColor(THEME_COLOR)
        .setDescription(
          `˗ˏˋ ☕ **Queued:** [${track.info.title}](${track.info.uri})\n` +
          `**Position:** \`#${player.queue.length}\` ˎˊ˗\n\n` +
          `*React with ❌ below to cancel if you entered by mistake!*`
        );

      if (cover) queueEmbed.setThumbnail(cover);

      const queuedMsg = await sendReply({ embeds: [queueEmbed] });

      if (queuedMsg) {
        await queuedMsg.react('❌').catch(() => {});

        const filter = (reaction, user) =>
          reaction.emoji.name === '❌' && (user.id === member.id || isOwnerUser(user.id)) && !user.bot;

        const collector = queuedMsg.createReactionCollector({ filter, max: 1, time: 120000 });

        collector.on('collect', async () => {
          const index = player.queue.findIndex(
            (t) => (t.info.identifier && t.info.identifier === track.info.identifier) || t === track
          );

          if (index !== -1) {
            player.queue.remove(index);
            await queuedMsg.edit({
              embeds: [
                new EmbedBuilder()
                  .setColor(THEME_COLOR)
                  .setDescription(`˗ˏˋ 🗑️ **Cancelled:** Removed [${track.info.title}](${track.info.uri}) from the queue! ˎˊ˗`)
              ]
            }).catch(() => {});
          }
          await queuedMsg.reactions.removeAll().catch(() => {});
        });

        collector.on('end', async (collected) => {
          if (collected.size === 0) {
            await queuedMsg.reactions.removeAll().catch(() => {});
          }
        });
      }
    }
  }

  // Don't yank a paused track out from under the user when they queue a song.
  if (!player.isPlaying) {
    safe(player.play());
  }
}

async function setBassBoost(player, enable) {
  const state = getState(player.guildId);
  state.bassboost = enable;

  if (!player.filters) return;
  try {
    if (enable) {
      await player.filters.setEqualizer([
        { band: 0, gain: 0.25 },
        { band: 1, gain: 0.20 },
        { band: 2, gain: 0.15 },
        { band: 3, gain: 0.10 },
        { band: 4, gain: 0.05 }
      ]);
    } else {
      await player.filters.clearFilters();
    }
  } catch (err) {
    console.log('[isai Bass Error]', err?.message || err);
  }
}

// ==========================================
// 💬 SLASH COMMAND INTERACTION ROUTING
// ==========================================
client.on(Events.InteractionCreate, async (interaction) => {
  if (interaction.isButton()) {
    return handleButtonInteraction(interaction);
  }

  if (!interaction.isChatInputCommand()) return;

  // Slash commands need a guild: in DMs `guild` and `member.voice` are null.
  if (!interaction.guild || !interaction.member) {
    return interaction.reply({
      content: '🌸 I only work inside servers — invite me to a server to use my commands!',
      flags: MessageFlags.Ephemeral
    });
  }

  const { commandName, guild, member, channel, user } = interaction;
  const isOwner = isOwnerUser(user.id);

  if (['say', 'dm', 'status', 'customstatus', 'devhelp', 'prefix'].includes(commandName) && !isOwner) {
    return interaction.reply({ content: 'Nothing here.', flags: MessageFlags.Ephemeral });
  }

  // Owner Commands
  if (commandName === 'devhelp') {
    return interaction.reply({ embeds: [buildDevHelpEmbed()], flags: MessageFlags.Ephemeral });
  }

  if (commandName === 'say') {
    const text = interaction.options.getString('content');
    await channel.send(text);
    return interaction.reply({ content: 'Message sent ♡', flags: MessageFlags.Ephemeral });
  }

  if (commandName === 'dm') {
    const target = interaction.options.getUser('target');
    const text = interaction.options.getString('content');
    try {
      await target.send(text);
      return interaction.reply({ content: `Sent to ${target.tag} ✨`, flags: MessageFlags.Ephemeral });
    } catch {
      return interaction.reply({ content: `Could not DM ${target.tag}. DMs might be closed.`, flags: MessageFlags.Ephemeral });
    }
  }

  if (commandName === 'status') {
    const statusType = interaction.options.getString('type');
    client.user.setPresence({ status: statusType });
    return interaction.reply({ content: `Status set to \`${statusType}\` ✨`, flags: MessageFlags.Ephemeral });
  }

  if (commandName === 'customstatus') {
    const statusText = interaction.options.getString('text');
    client.user.setPresence({
      activities: [{ name: 'Custom Status', state: statusText, type: ActivityType.Custom }]
    });
    return interaction.reply({ content: `Bubble status updated to: "${statusText}" 🫧`, flags: MessageFlags.Ephemeral });
  }

  if (commandName === 'prefix') {
    const value = (interaction.options.getString('new_prefix') || '').trim();
    if (!value || value.length > 5 || /\s/.test(value)) {
      return interaction.reply({ content: '⚠️ Prefix must be 1-5 characters with no spaces.', flags: MessageFlags.Ephemeral });
    }
    prefix = value;
    settings.prefix = value;
    saveSettings();
    return interaction.reply({
      embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`✨ **Prefix updated to** \`${value}\``)]
    });
  }

  if (commandName === '24-7') {
    // Same reason as /connect: the node wait can outlive the reply window.
    await interaction.deferReply();
    const voice = member.voice?.channel;
    const enable = !settings.stay247[guild.id];
    const result = await setStay247(guild, voice, channel, enable);
    if (!result.ok) {
      return interaction.editReply(
        result.reason === 'voice'
          ? { content: 'Join a voice channel first!' }
          : { embeds: [NO_NODE_EMBED()] }
      );
    }
    return interaction.editReply({
      embeds: [
        new EmbedBuilder()
          .setColor(THEME_COLOR)
          .setDescription(
            result.enabled
              ? `🔁 **24/7 mode enabled** — I'll stay in **${voice.name}** even after the queue ends.`
              : '🔁 **24/7 mode disabled.**'
          )
      ]
    });
  }

  // Music Commands
  const player = client.poru.players.get(guild.id);

  if (commandName === 'play') {
    await interaction.deferReply();
    const query = interaction.options.getString('query');
    return executePlay(guild, member, channel, query, (opts) => interaction.editReply(opts)).catch((err) => {
      console.log('[isai Audio Error] Play failed:', err?.message || err);
    });
  }

  if (commandName === 'connect') {
    const voice = member.voice?.channel;
    if (!voice) {
      return interaction.reply({ content: 'Join a voice channel first!', flags: MessageFlags.Ephemeral });
    }
    // Defer first: waiting for a dropped node can take longer than the 3s reply window.
    await interaction.deferReply();
    if (!(await getMusicNode())) return interaction.editReply({ embeds: [NO_NODE_EMBED()] });
    client.poru.createConnection({
      guildId: guild.id,
      voiceChannel: voice.id,
      textChannel: channel.id,
      deaf: true
    });
    return interaction.editReply({
      embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`Joined **${voice.name}** ♡`)]
    });
  }

  if (commandName === 'disconnect') {
    if (!player) return interaction.reply({ content: 'Not connected to any voice channel.', flags: MessageFlags.Ephemeral });
    if (settings.stay247[guild.id]) {
      delete settings.stay247[guild.id];
      saveSettings();
    }
    await cleanupOldPanel(guild.id);
    safe(player.destroy());
    return interaction.reply({
      embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('Disconnected from the voice channel 🌸')]
    });
  }

  if (commandName === 'pause') {
    if (!player) return interaction.reply({ content: 'Nothing is playing.', flags: MessageFlags.Ephemeral });
    safe(player.pause(true));
    return interaction.reply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('⏸️ **Playback paused.**')] });
  }

  if (commandName === 'resume') {
    if (!player) return interaction.reply({ content: 'Nothing is playing.', flags: MessageFlags.Ephemeral });
    safe(player.pause(false));
    return interaction.reply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('▶️ **Playback resumed.**')] });
  }

  if (commandName === 'skip') {
    if (!player) return interaction.reply({ content: 'Nothing is playing.', flags: MessageFlags.Ephemeral });
    safe(player.skip());
    return interaction.reply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('⏭️ **Skipped track.**')] });
  }

  if (commandName === 'previous') {
    if (!player) return interaction.reply({ content: 'Nothing is playing.', flags: MessageFlags.Ephemeral });
    const state = getState(guild.id);
    if (!state.previousTrack) return interaction.reply({ content: 'No previous track recorded in this session.', flags: MessageFlags.Ephemeral });
    player.queue.unshift(state.previousTrack);
    safe(player.skip());
    return interaction.reply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`⏮️ Playing previous: **${state.previousTrack.info.title}**`)] });
  }

  if (commandName === 'stop') {
    if (!player) return interaction.reply({ content: 'Nothing is playing.', flags: MessageFlags.Ephemeral });
    stopMusic(player, guild.id);
    return interaction.reply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('⏹️ **Music stopped and queue cleared.**')] });
  }

  if (commandName === 'shuffle') {
    if (!player || player.queue.length === 0) return interaction.reply({ content: 'Not enough songs in queue to shuffle.', flags: MessageFlags.Ephemeral });
    player.queue.shuffle();
    return interaction.reply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`🔀 **Shuffled ${player.queue.length} track(s)!**`)] });
  }

  if (commandName === 'clear') {
    if (!player || player.queue.length === 0) return interaction.reply({ content: 'Queue is already empty.', flags: MessageFlags.Ephemeral });
    player.queue.clear();
    return interaction.reply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('🗑️ **Queue cleared completely.**')] });
  }

  if (commandName === 'remove') {
    if (!player || player.queue.length === 0) return interaction.reply({ content: 'The queue is empty.', flags: MessageFlags.Ephemeral });
    const target = interaction.options.getString('target');
    const index = parseInt(target, 10);

    if (!isNaN(index) && index > 0 && index <= player.queue.length) {
      const removed = player.queue.remove(index - 1);
      return interaction.reply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`Removed: **${removed?.info.title || target}**`)] });
    } else {
      const songIndex = player.queue.findIndex(t => t.info.title.toLowerCase().includes(target.toLowerCase()));
      if (songIndex !== -1) {
        const removed = player.queue.remove(songIndex);
        return interaction.reply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`Removed: **${removed?.info.title}**`)] });
      }
      return interaction.reply({ content: 'Could not find that track in the queue.', flags: MessageFlags.Ephemeral });
    }
  }

  if (commandName === 'bass') {
    if (!player) return interaction.reply({ content: 'Nothing is playing.', flags: MessageFlags.Ephemeral });
    const enable = interaction.options.getBoolean('enabled');
    await setBassBoost(player, enable);
    return interaction.reply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`🎧 **Bass boost set to:** \`${enable ? 'ON' : 'OFF'}\``)] });
  }

  if (commandName === 'loop') {
    const row = new ActionRowBuilder().addComponents(
      new ButtonBuilder().setCustomId('loop_off').setLabel('Off').setStyle(ButtonStyle.Secondary),
      new ButtonBuilder().setCustomId('loop_track').setLabel('Track').setStyle(ButtonStyle.Secondary),
      new ButtonBuilder().setCustomId('loop_queue').setLabel('Queue').setStyle(ButtonStyle.Secondary)
    );
    const embed = new EmbedBuilder().setColor(THEME_COLOR).setTitle('🔁 Loop Control').setDescription('Choose repeat mode:');
    return interaction.reply({ embeds: [embed], components: [row] });
  }

  if (commandName === 'queue') {
    if (!player || (!player.currentTrack && player.queue.length === 0)) {
      return interaction.reply({ content: 'Queue is currently empty.', flags: MessageFlags.Ephemeral });
    }
    const list = player.queue.slice(0, 10).map((t, i) => `**${i + 1}.** [${t.info.title}](${t.info.uri}) • \`${formatTime(t.info.length)}\``).join('\n');
    const embed = new EmbedBuilder()
      .setColor(THEME_COLOR)
      .setTitle('⋆˚࿔ Current Queue 𝜗𝜚˚⋆')
      .setDescription(`**Now Playing:** [${player.currentTrack?.info.title}](${player.currentTrack?.info.uri})\n\n` + (list || 'No upcoming songs.'));
    return interaction.reply({ embeds: [embed] });
  }

  if (commandName === 'help') {
    return interaction.reply({ embeds: [buildHelpEmbed()] });
  }

  if (commandName === 'ping') {
    const sent = await interaction.deferReply({ fetchReply: true });
    const roundtrip = sent.createdTimestamp - interaction.createdTimestamp;
    const wsPing = client.ws.ping;
    const node = client.poru.leastUsedNodes[0];
    const nodeStatus = node ? `🟢 Connected (\`${node.name}\`)` : '🔴 Offline';

    const embed = new EmbedBuilder()
      .setColor(THEME_COLOR)
      .setTitle('🏓 **Pong!**')
      .setDescription(
        `> ˚.⋆ **Gateway Ping:** \`${wsPing >= 0 ? wsPing : 0}ms\`\n` +
        `> ˚.⋆ **Roundtrip Latency:** \`${roundtrip}ms\`\n` +
        `> ˚.⋆ **Audio Engine:** ${nodeStatus}`
      )
      .setFooter({ text: 'isai Audio Latency ♡', iconURL: client.user.displayAvatarURL() })
      .setTimestamp();

    return interaction.editReply({ embeds: [embed] });
  }
});

// ==========================================
// 🖱️ INTERACTIVE PANEL BUTTON HANDLER
// ==========================================
async function handleButtonInteraction(interaction) {
  const { customId, guild, member } = interaction;
  if (!guild) return;
  const player = client.poru.players.get(guild.id);

  if (customId.startsWith('loop_')) {
    if (!player) return interaction.reply({ content: 'Player is no longer active.', flags: MessageFlags.Ephemeral });
    const mode = customId.split('_')[1];
    if (mode === 'off') player.setLoop('NONE');
    else if (mode === 'track') player.setLoop('TRACK');
    else if (mode === 'queue') player.setLoop('QUEUE');
    return interaction.reply({ content: `Loop set to \`${mode.toUpperCase()}\` 🔁`, flags: MessageFlags.Ephemeral });
  }

  if (!player) return interaction.reply({ content: 'No music is currently playing.', flags: MessageFlags.Ephemeral });
  if (!member?.voice?.channel || member.voice.channel.id !== player.voiceChannel) {
    return interaction.reply({ content: 'Please join my voice channel to use the controls!', flags: MessageFlags.Ephemeral });
  }

  // A second click on an expired panel would otherwise reject unhandled.
  try {
    await interaction.deferUpdate();
  } catch {
    return;
  }

  switch (customId) {
    case 'btn_pause':
      safe(player.pause(!player.isPaused));
      break;
    case 'btn_skip':
      safe(player.skip());
      break;
    case 'btn_stop':
      stopMusic(player, guild.id);
      break;
    case 'btn_prev':
      const state = getState(guild.id);
      if (state.previousTrack) {
        player.queue.unshift(state.previousTrack);
        safe(player.skip());
      }
      break;
    case 'btn_shuffle':
      if (player.queue.length > 1) player.queue.shuffle();
      break;
    case 'btn_loop':
      const nextLoop = player.loop === 'NONE' ? 'TRACK' : player.loop === 'TRACK' ? 'QUEUE' : 'NONE';
      player.setLoop(nextLoop);
      break;
    case 'btn_bass':
      const curState = getState(guild.id);
      await setBassBoost(player, !curState.bassboost);
      break;
    case 'btn_queue':
      const qList = player.queue.slice(0, 5).map((t, i) => `${i + 1}. ${t.info.title.substring(0, 30)}...`).join('\n');
      await interaction.followUp({
        embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`**Up Next:**\n${qList || 'No more songs in queue.'}`)],
        flags: MessageFlags.Ephemeral
      });
      break;
  }

  const panel = activePanels.get(guild.id);
  if (customId === 'btn_stop') {
    await cleanupOldPanel(guild.id);
  } else if (panel?.msg && player.currentTrack) {
    panel.msg.edit({
      embeds: [buildPanelEmbed(player, player.currentTrack)],
      components: buildPanelButtons()
    }).catch(() => {});
  }
}

// ==========================================
// ⌨️ UNIVERSAL PREFIX & ALIAS COMMAND ROUTER
// ==========================================
client.on(Events.MessageCreate, async (message) => {
  if (message.author.bot || !message.guild) return;
  // `message.member` can be missing for uncached members; every command needs it.
  if (!message.member) return;

  const isOwner = isOwnerUser(message.author.id);
  let isPrefixed = message.content.toLowerCase().startsWith(prefix.toLowerCase());
  let rawContent = (isPrefixed ? message.content.slice(prefix.length) : message.content).trim();
  let args = rawContent.split(/ +/);
  let cmd = args.shift()?.toLowerCase();

  // If the prefix itself is a letter that starts a command (e.g. prefix "p" and
  // owner types "play x" without it), retry the message as a no-prefix command.
  if (isPrefixed && isOwner && (!cmd || !NO_PREFIX_ALIASES.has(cmd))) {
    const altContent = message.content.trim();
    const altArgs = altContent.split(/ +/);
    const altCmd = altArgs.shift()?.toLowerCase();
    if (altCmd && NO_PREFIX_ALIASES.has(altCmd)) {
      isPrefixed = false;
      rawContent = altContent;
      args = altArgs;
      cmd = altCmd;
    }
  }

  if (!cmd) return;

  // No-prefix usage is an owner-only privilege, and only for real commands.
  if (!isPrefixed && (!isOwner || !NO_PREFIX_ALIASES.has(cmd))) return;

  const isMatch = (aliases) => aliases.includes(cmd);

  // --- DEVELOPER HELP COMMAND ---
  if (cmd === 'dev' && args[0]?.toLowerCase() === 'help') {
    if (!isOwner) return;
    await message.delete().catch(() => {});
    return message.channel.send({ embeds: [buildDevHelpEmbed()] });
  }

  // --- OWNER PREFIX COMMANDS (Auto-Delete Trigger) ---
  if (isMatch(['say', 'dm', 'status', 'customstatus', 'cstatus'])) {
    if (!isOwner) return;

    await message.delete().catch(() => {});

    if (cmd === 'say') {
      const content = args.join(' ');
      if (!content) return;
      return message.channel.send(content).catch(() => null);
    }

    if (cmd === 'dm') {
      const targetUser = message.mentions.users.first() || await client.users.fetch(args[0]).catch(() => null);
      const text = message.mentions.users.first() ? args.slice(1).join(' ') : args.slice(1).join(' ');
      if (!targetUser || !text) return;
      return targetUser.send(text).catch(() => {});
    }

    if (cmd === 'status') {
      const statusType = args[0]?.toLowerCase();
      if (['online', 'idle', 'dnd'].includes(statusType)) {
        client.user.setPresence({ status: statusType });
      }
      return;
    }

    if (cmd === 'customstatus' || cmd === 'cstatus') {
      const statusText = args.join(' ');
      if (!statusText) return;
      client.user.setPresence({
        activities: [{ name: 'Custom Status', state: statusText, type: ActivityType.Custom }]
      });
      return;
    }
  }

  // Handle "icustom status <content>" format
  if (cmd === 'custom' && args[0]?.toLowerCase() === 'status') {
    if (!isOwner) return;
    await message.delete().catch(() => {});
    const statusText = args.slice(1).join(' ');
    if (!statusText) return;
    client.user.setPresence({
      activities: [{ name: 'Custom Status', state: statusText, type: ActivityType.Custom }]
    });
    return;
  }

  // --- MUSIC PREFIX & SHORT ALIAS COMMANDS ---
  // Never let a missing-permission send turn into an unhandled rejection.
  const sendReply = (opts) => message.channel.send(opts).catch(() => null);
  let player = client.poru.players.get(message.guild.id);

  // Prefix: iprefix <new> / isetprefix <new> (Owner only)
  if (isMatch(['prefix', 'setprefix'])) {
    if (!isOwner) return;
    const value = args.join(' ').trim();
    if (!value || value.length > 5 || /\s/.test(value)) {
      return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('⚠️ Prefix must be 1-5 characters with no spaces.')] });
    }
    prefix = value;
    settings.prefix = value;
    saveSettings();
    return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`✨ **Prefix updated to** \`${value}\``)] });
  }

  // 24/7: i247 / i24/7 / istay
  if (isMatch(['247', '24/7', 'stay'])) {
    const voice = message.member.voice?.channel;
    const enable = !settings.stay247[message.guild.id];
    const result = await setStay247(message.guild, voice, message.channel, enable);
    if (!result.ok) {
      if (result.reason === 'voice') {
        return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('🌸 Please join a voice channel first!')] });
      }
      return sendReply({ embeds: [NO_NODE_EMBED()] });
    }
    return sendReply({
      embeds: [
        new EmbedBuilder()
          .setColor(THEME_COLOR)
          .setDescription(
            result.enabled
              ? `🔁 **24/7 mode enabled** — I'll stay in **${voice.name}** even after the queue ends.`
              : '🔁 **24/7 mode disabled.**'
          )
      ]
    });
  }

  // Play: iplay / ip
  if (isMatch(['play', 'p'])) {
    const query = args.join(' ');
    if (!query) {
      return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`🌸 Usage: \`${prefix}play <song title / url>\``)] });
    }
    return executePlay(message.guild, message.member, message.channel, query, sendReply).catch((err) => {
      console.log('[isai Audio Error] Play failed:', err?.message || err);
    });
  }

  // Connect: iconnect / ic / ijoin / ij
  if (isMatch(['connect', 'c', 'join', 'j'])) {
    const voice = message.member.voice?.channel;
    if (!voice) {
      return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('🌸 Please join a voice channel first!')] });
    }
    if (!(await getMusicNode())) return sendReply({ embeds: [NO_NODE_EMBED()] });
    client.poru.createConnection({
      guildId: message.guild.id,
      voiceChannel: voice.id,
      textChannel: message.channel.id,
      deaf: true
    });
    return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`Joined **${voice.name}** ♡`)] });
  }

  // Disconnect: idisconnect / idc / ileave / il
  if (isMatch(['disconnect', 'dc', 'leave', 'l'])) {
    if (!player) return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('🌸 I am not in any voice channel!')] });
    if (settings.stay247[message.guild.id]) {
      delete settings.stay247[message.guild.id];
      saveSettings();
    }
    await cleanupOldPanel(message.guild.id);
    safe(player.destroy());
    return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('Disconnected from voice channel 🌸')] });
  }

  // Pause: ipause
  if (isMatch(['pause'])) {
    if (!player) return;
    safe(player.pause(true));
    return message.react('⏸️');
  }

  // Resume: iresume / ir
  if (isMatch(['resume', 'r'])) {
    if (!player) return;
    safe(player.pause(false));
    return message.react('▶️');
  }

  // Skip: iskip / is / next
  if (isMatch(['skip', 's', 'next'])) {
    if (!player) return;
    safe(player.skip());
    return message.react('⏭️');
  }

  // Previous: iprevious / iprev / iback
  if (isMatch(['previous', 'prev', 'back'])) {
    if (!player) return;
    const state = getState(message.guild.id);
    if (!state.previousTrack) return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('No previous track found.')] });
    player.queue.unshift(state.previousTrack);
    safe(player.skip());
    return message.react('⏮️');
  }

  // Stop: istop
  if (isMatch(['stop'])) {
    if (!player) return;
    stopMusic(player, message.guild.id);
    return message.react('⏹️');
  }

  // Queue: iqueue / iq
  if (isMatch(['queue', 'q'])) {
    if (!player || (!player.currentTrack && player.queue.length === 0)) {
      return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('Queue is empty.')] });
    }
    const list = player.queue.slice(0, 10).map((t, i) => `**${i + 1}.** [${t.info.title}](${t.info.uri}) • \`${formatTime(t.info.length)}\``).join('\n');
    const embed = new EmbedBuilder()
      .setColor(THEME_COLOR)
      .setTitle('⋆˚࿔ Current Queue 𝜗𝜚˚⋆')
      .setDescription(
        `**Now Playing:** [${player.currentTrack?.info.title}](${player.currentTrack?.info.uri})\n\n` +
        (list || 'No upcoming songs.') +
        (player.queue.length > 10 ? `\n\n*...and ${player.queue.length - 10} more tracks*` : '')
      );
    return sendReply({ embeds: [embed] });
  }

  // Clear: iclear / iclr / clean
  if (isMatch(['clear', 'clr', 'clean'])) {
    if (!player || player.queue.length === 0) return;
    player.queue.clear();
    return message.react('🗑️');
  }

  // Remove: iremove / irm / del
  if (isMatch(['remove', 'rm', 'del'])) {
    if (!player || player.queue.length === 0) return;
    const target = args.join(' ');
    const index = parseInt(target, 10);
    if (!isNaN(index) && index > 0 && index <= player.queue.length) {
      const removed = player.queue.remove(index - 1);
      return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`Removed: **${removed?.info.title}**`)] });
    } else {
      const songIndex = player.queue.findIndex(t => t.info.title.toLowerCase().includes(target.toLowerCase()));
      if (songIndex !== -1) {
        const removed = player.queue.remove(songIndex);
        return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`Removed: **${removed?.info.title}**`)] });
      }
    }
    return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('Track not found in queue.')] });
  }

  // Shuffle: ishuffle / ish
  if (isMatch(['shuffle', 'sh'])) {
    if (!player || player.queue.length === 0) return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('Queue has no songs to shuffle.')] });
    player.queue.shuffle();
    return message.react('🔀');
  }

  // Bass: ibass / ibb
  if (isMatch(['bass', 'bb'])) {
    if (!player) return;
    const arg = args[0]?.toLowerCase();
    const enable = arg === 'true' || arg === 'on' || arg === '1';
    await setBassBoost(player, enable);
    return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`🎧 **Bass Boost:** \`${enable ? 'ON' : 'OFF'}\``)] });
  }

  // Loop: iloop / irepeat / rep / lp
  if (isMatch(['loop', 'repeat', 'repeate', 'rep', 'lp'])) {
    const row = new ActionRowBuilder().addComponents(
      new ButtonBuilder().setCustomId('loop_off').setLabel('Off').setStyle(ButtonStyle.Secondary),
      new ButtonBuilder().setCustomId('loop_track').setLabel('Track').setStyle(ButtonStyle.Secondary),
      new ButtonBuilder().setCustomId('loop_queue').setLabel('Queue').setStyle(ButtonStyle.Secondary)
    );
    const embed = new EmbedBuilder().setColor(THEME_COLOR).setTitle('🔁 Loop Control').setDescription('Choose repeat mode:');
    return sendReply({ embeds: [embed], components: [row] });
  }

  // Ping: iping / ping / latency / pong
  if (isMatch(['ping', 'latency', 'pong'])) {
    const start = Date.now();
    const wsPing = client.ws.ping >= 0 ? client.ws.ping : 0;
    const node = client.poru.leastUsedNodes[0];
    const nodeStatus = node ? `🟢 Connected (\`${node.name}\`)` : '🔴 Offline';

    const initial = await sendReply({
      embeds: [
        new EmbedBuilder()
          .setColor(THEME_COLOR)
          .setDescription('🏓 *Pinging...*')
      ]
    });

    const roundtrip = Date.now() - start;

    const embed = new EmbedBuilder()
      .setColor(THEME_COLOR)
      .setTitle('🏓 **Pong!**')
      .setDescription(
        `> ˚.⋆ **Gateway Ping:** \`${wsPing}ms\`\n` +
        `> ˚.⋆ **Roundtrip Latency:** \`${roundtrip}ms\`\n` +
        `> ˚.⋆ **Audio Engine:** ${nodeStatus}`
      )
      .setFooter({ text: 'isai Audio Latency ♡', iconURL: client.user.displayAvatarURL() })
      .setTimestamp();

    if (initial && typeof initial.edit === 'function') {
      return initial.edit({ embeds: [embed] });
    }
    return sendReply({ embeds: [embed] });
  }

  // Help: ihelp / ih (Public Help - Dev commands excluded)
  if (isMatch(['help', 'h'])) {
    return sendReply({ embeds: [buildHelpEmbed()] });
  }
});

// Keep 24/7 guilds in their voice channel even if the bot gets disconnected.
client.on(Events.VoiceStateUpdate, (oldState, newState) => {
  if (!client.user || newState.id !== client.user.id) return;

  const saved = settings.stay247[newState.guild.id];
  if (!saved) return;

  if (newState.channelId === saved.voiceChannel) return;

  // The bot was moved to another channel: remember where it is.
  if (newState.channelId) {
    saved.voiceChannel = newState.channelId;
    saveSettings();
    return;
  }

  // Kicked or disconnected: rejoin shortly after.
  setTimeout(() => {
    rejoinStay(newState.guild.id).catch((err) => console.log('[isai 24/7 Error]', err?.message || err));
  }, 2000);
});

// ==========================================
// 📖 AESTHETIC PUBLIC HELP MENU
// ==========================================
function buildHelpEmbed() {
  return new EmbedBuilder()
    .setColor(THEME_COLOR)
    .setAuthor({ name: 'isai • Music Commands', iconURL: client.user.displayAvatarURL() })
    .setDescription(
      `Welcome to **isai** — aesthetic music companion. 𝜗𝜚\n` +
      `Current Prefix: \`${prefix}\` | All commands work with **Slash (/)** & **Short Aliases**!\n`
    )
    .addFields(
      {
        name: '🎧 Playback Commands',
        value:
          `\`${prefix}play\` • \`${prefix}p\` • \`/play\` ➔ Play YouTube Music, Spotify & URL\n` +
          `\`${prefix}pause\` • \`/pause\` ➔ Pause song\n` +
          `\`${prefix}resume\` • \`${prefix}r\` • \`/resume\` ➔ Resume song\n` +
          `\`${prefix}skip\` • \`${prefix}s\` • \`/skip\` ➔ Skip track\n` +
          `\`${prefix}previous\` • \`${prefix}prev\` • \`/previous\` ➔ Previous song\n` +
          `\`${prefix}stop\` • \`/stop\` ➔ Stop and clear queue`
      },
      {
        name: '📜 Queue & Audio Controls',
        value:
          `\`${prefix}queue\` • \`${prefix}q\` • \`/queue\` ➔ View queued tracks\n` +
          `\`${prefix}shuffle\` • \`${prefix}sh\` • \`/shuffle\` ➔ Shuffle playlist\n` +
          `\`${prefix}clear\` • \`${prefix}clr\` • \`/clear\` ➔ Clear full queue\n` +
          `\`${prefix}remove\` • \`${prefix}rm\` • \`/remove\` ➔ Remove song\n` +
          `\`${prefix}loop\` • \`${prefix}rep\` • \`/loop\` ➔ Repeat options\n` +
          `\`${prefix}bass\` • \`${prefix}bb\` • \`/bass\` ➔ Boost bass (true/false)`
      },
      {
        name: '🌸 Voice Connections',
        value:
          `\`${prefix}connect\` • \`${prefix}join\` • \`${prefix}c\` • \`${prefix}j\` ➔ Join VC\n` +
          `\`${prefix}disconnect\` • \`${prefix}leave\` • \`${prefix}dc\` ➔ Leave VC\n` +
          `\`${prefix}247\` • \`/24-7\` ➔ Stay in VC 24/7 (survives restarts)`
      },
      {
        name: '⚙️ Utilities & Settings',
        value:
          `\`${prefix}ping\` • \`/ping\` ➔ Check bot latency & music node status\n` +
          `\`${prefix}prefix <new>\` • \`/prefix\` ➔ Change prefix (Owner Only)\n` +
          `Owners can also use any command **without** a prefix, e.g. \`play believer\``
      }
    )
    .setFooter({ text: 'Handcrafted with warmth & aesthetic care ♡', iconURL: client.user.displayAvatarURL() });
}

// ==========================================
// 🔒 DEVELOPER / OWNER HELP MENU (idev help)
// ==========================================
function buildDevHelpEmbed() {
  return new EmbedBuilder()
    .setColor(0x2b2d31)
    .setAuthor({ name: 'isai • Developer & Owner Controls', iconURL: client.user.displayAvatarURL() })
    .setDescription('Exclusive controls strictly accessible by verified bot owners. Messages automatically delete upon execution.')
    .addFields(
      {
        name: '💬 Messaging Controls',
        value:
          `\`${prefix}say <content>\` | \`/say <content>\`\n↳ Broadcasts a message in the current channel.\n\n` +
          `\`${prefix}dm <@user/id> <content>\` | \`/dm <user> <content>\`\n↳ Sends a direct message to a target user.`
      },
      {
        name: '🫧 Presence & Status Controls',
        value:
          `\`${prefix}status <online/idle/dnd>\` | \`/status <type>\`\n↳ Sets Discord online availability.\n\n` +
          `\`${prefix}custom status <text>\` | \`/customstatus <text>\`\n↳ Updates the bot's custom bubble status message.`
      },
      {
        name: '⚙️ Settings & Privileges',
        value:
          `\`${prefix}prefix <new>\` | \`/prefix <new_prefix>\`\n↳ Changes the prefix for everyone (Owner Only).\n\n` +
          `\`No-prefix commands\`\n↳ Owner IDs can type any command without the prefix, e.g. \`play believer\`.`
      }
    )
    .setFooter({ text: 'Confidential Developer Hub 🔐', iconURL: client.user.displayAvatarURL() });
}

// Log in
if (!process.env.TOKEN) {
  console.error('[isai] TOKEN is missing from .env — add your Discord bot token.');
  process.exit(1);
}

client.login(process.env.TOKEN).catch((err) => {
  console.error('[isai Login Error]', err?.message || err);
  process.exit(1);
});
