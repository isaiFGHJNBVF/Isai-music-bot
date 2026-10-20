require('dotenv').config();
const {
  Client,
  GatewayIntentBits,
  EmbedBuilder,
  ActionRowBuilder,
  ButtonBuilder,
  ButtonStyle,
  SlashCommandBuilder,
  ActivityType,
  Events
} = require('discord.js');
const { Poru } = require('poru');

// ==========================================
// 🛡️ ANTI-CRASH PROTECTION SYSTEM
// ==========================================
process.on('unhandledRejection', (reason, promise) => {
  console.error('[Anti-Crash] Unhandled Rejection:', reason);
});
process.on('uncaughtException', (err, origin) => {
  console.error('[Anti-Crash] Uncaught Exception:', err);
});

// ==========================================
// 🌸 BOT CONFIGURATION & SETTINGS
// ==========================================
let prefix = 'i';
const owner = ['1377967442172579843', '774224543531270144'];
const THEME_COLOR = 0xf3c4db; // Aesthetic sakura blush

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.GuildVoiceStates,
    GatewayIntentBits.MessageContent
  ]
});

// Lavalink Node Setup
const nodes = [
  {
    name: 'Isai-Core',
    host: process.env.LAVALINK_HOST || 'lavalink.jirayu.net',
    port: parseInt(process.env.LAVALINK_PORT || '13592', 10),
    password: process.env.LAVALINK_PASSWORD || 'youshallnotpass',
    secure: process.env.LAVALINK_SECURE === 'true'
  }
];

// Poru Audio Engine (Default: YouTube)
client.poru = new Poru(client, nodes, {
  library: 'discord.js',
  defaultPlatform: 'ytsearch'
});

// Safe guild-level storage
const activePanels = new Map();
const guildState = new Map();

function getState(guildId) {
  if (!guildState.has(guildId)) {
    guildState.set(guildId, { bassboost: false, previousTrack: null });
  }
  return guildState.get(guildId);
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

// ==========================================
// 🖼️ REAL SONG THUMBNAIL RESOLVER
// ==========================================
function getTrackThumbnail(track) {
  if (!track || !track.info) return null;
  const info = track.info;

  // 1. Lavalink v4 artworkUrl (Spotify / SoundCloud / YouTube)
  if (info.artworkUrl && typeof info.artworkUrl === 'string' && info.artworkUrl.startsWith('http')) {
    return info.artworkUrl;
  }

  // 2. Poru image field
  if (info.image && typeof info.image === 'string' && info.image.startsWith('http')) {
    return info.image;
  }

  // 3. Extract YouTube Video ID from identifier or URL
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

// Safe Stop Method for Poru
function stopMusic(player, guildId) {
  clearTicker(guildId);
  if (!player) return;
  player.queue.clear();
  try {
    if (typeof player.stop === 'function') {
      player.stop();
    } else {
      player.skip(); // Safely skips the track with an empty queue, ending playback cleanly
    }
  } catch (err) {
    console.error('[Isai Stop Error]:', err.message);
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
      `💽 **Title:** [${track.info.title}](${track.info.uri})\n` +
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
    .setFooter({ text: 'Isai • Pure aesthetic vibes ♡', iconURL: client.user.displayAvatarURL() });

  const songCover = getTrackThumbnail(track);
  if (songCover) {
    embed.setThumbnail(songCover);
  }

  return embed;
}

function buildPanelButtons(player) {
  const state = getState(player.guildId);
  const row1 = new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId('btn_prev').setEmoji('⏮️').setStyle(ButtonStyle.Secondary),
    new ButtonBuilder()
      .setCustomId('btn_pause')
      .setEmoji(player.isPaused ? '▶️' : '⏸️')
      .setStyle(player.isPaused ? ButtonStyle.Success : ButtonStyle.Primary),
    new ButtonBuilder().setCustomId('btn_skip').setEmoji('⏭️').setStyle(ButtonStyle.Secondary),
    new ButtonBuilder().setCustomId('btn_stop').setEmoji('⏹️').setStyle(ButtonStyle.Danger)
  );

  const row2 = new ActionRowBuilder().addComponents(
    new ButtonBuilder()
      .setCustomId('btn_loop')
      .setLabel('Loop')
      .setEmoji('🔁')
      .setStyle(player.loop !== 'NONE' ? ButtonStyle.Primary : ButtonStyle.Secondary),
    new ButtonBuilder().setCustomId('btn_shuffle').setLabel('Shuffle').setEmoji('🔀').setStyle(ButtonStyle.Secondary),
    new ButtonBuilder()
      .setCustomId('btn_bass')
      .setLabel('Bass')
      .setEmoji('🎧')
      .setStyle(state.bassboost ? ButtonStyle.Success : ButtonStyle.Secondary),
    new ButtonBuilder().setCustomId('btn_queue').setLabel('Queue').setEmoji('📜').setStyle(ButtonStyle.Secondary)
  );

  return [row1, row2];
}

function clearTicker(guildId) {
  const existing = activePanels.get(guildId);
  if (existing?.interval) {
    clearInterval(existing.interval);
    activePanels.delete(guildId);
  }
}

// ==========================================
// 🎵 PORU (LAVALINK) EVENTS
// ==========================================
client.poru.on('nodeConnect', (node) => {
  console.log(`[Isai Audio] Connected to Lavalink Node: ${node.name} ✨`);
});

client.poru.on('nodeError', (node, error) => {
  console.log(`[Isai Audio Error] ${node.name}:`, error.message);
});

client.poru.on('trackStart', async (player, track) => {
  clearTicker(player.guildId);

  const channel = client.channels.cache.get(player.textChannel);
  if (!channel) return;

  const panelMsg = await channel.send({
    embeds: [buildPanelEmbed(player, track)],
    components: buildPanelButtons(player)
  }).catch(() => null);

  if (!panelMsg) return;

  // Real-time slider bar ticker (every 5 seconds)
  const interval = setInterval(async () => {
    if (!player.isPlaying || player.isPaused) return;
    try {
      await panelMsg.edit({
        embeds: [buildPanelEmbed(player, track)],
        components: buildPanelButtons(player)
      });
    } catch {
      clearTicker(player.guildId);
    }
  }, 5000);

  activePanels.set(player.guildId, { msg: panelMsg, interval });
});

client.poru.on('trackEnd', (player, track) => {
  const state = getState(player.guildId);
  state.previousTrack = track;
  clearTicker(player.guildId);
});

client.poru.on('queueEnd', (player) => {
  clearTicker(player.guildId);
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
    .setDescription('Play a song from YouTube, Spotify, or direct audio link')
    .addStringOption(opt =>
      opt.setName('query')
        .setDescription('Song title, YouTube URL, or Spotify link')
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
  new SlashCommandBuilder().setName('help').setDescription('Aesthetic overview of all Isai commands'),

  // Owner Only Slash Commands
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
    .setDescription('Update bot presence (Owner Only)')
    .addStringOption(opt =>
      opt.setName('type')
        .setDescription('online, idle, or dnd')
        .setRequired(true)
        .addChoices(
          { name: 'Online', value: 'online' },
          { name: 'Idle', value: 'idle' },
          { name: 'Do Not Disturb', value: 'dnd' }
        )
    )
];

// ==========================================
// 💡 READY & INSTANT SLASH COMMAND SYNC
// ==========================================
client.once(Events.ClientReady, async () => {
  client.poru.init(client);
  console.log(`[Isai] Logged in as ${client.user.tag} ♡`);

  try {
    for (const guild of client.guilds.cache.values()) {
      await guild.commands.set(slashCommands).catch(() => {});
    }
    await client.application.commands.set(slashCommands).catch(() => {});
    console.log('[Isai] Slash commands synced instantly to all connected guilds! 🌸');
  } catch (err) {
    console.error('[Isai Command Sync Error]:', err);
  }

  client.user.setPresence({
    status: 'idle',
    activities: [{ name: `${prefix}help | 𝜗𝜚 aesthetic tunes`, type: ActivityType.Listening }]
  });
});

client.on(Events.GuildCreate, async (guild) => {
  await guild.commands.set(slashCommands).catch(() => {});
});

// ==========================================
// 🔍 YOUTUBE AUTOCOMPLETE
// ==========================================
client.on(Events.InteractionCreate, async (interaction) => {
  if (!interaction.isAutocomplete()) return;

  if (interaction.commandName === 'play') {
    const focusedValue = interaction.options.getFocused();
    if (!focusedValue || focusedValue.trim().length === 0) {
      return interaction.respond([]);
    }

    try {
      const res = await client.poru.resolve({ query: focusedValue, source: 'ytsearch' });
      if (!res || !res.tracks || res.tracks.length === 0) {
        return interaction.respond([]);
      }

      const choices = res.tracks.slice(0, 7).map(track => {
        const title = track.info.title.length > 70 ? track.info.title.substring(0, 67) + '...' : track.info.title;
        return {
          name: `▶ ${title} (${track.info.author})`.substring(0, 100),
          value: track.info.uri
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
  const voiceChannel = member.voice.channel;
  if (!voiceChannel) {
    return sendReply({
      embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('🌸 **Please join a voice channel first!**')]
    });
  }

  const permissions = voiceChannel.permissionsFor(client.user);
  if (!permissions.has('Connect') || !permissions.has('Speak')) {
    return sendReply({
      embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('⚠️ **I need connect and speak permissions in your voice channel!**')]
    });
  }

  let player = client.poru.players.get(guild.id);
  if (!player) {
    player = client.poru.createConnection({
      guildId: guild.id,
      voiceChannel: voiceChannel.id,
      textChannel: channel.id,
      deaf: true
    });
  }

  const isUrl = /^https?:\/\//i.test(query);
  const res = await client.poru.resolve({
    query: query,
    source: isUrl ? undefined : 'ytsearch',
    requester: member.user
  });

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
        .setDescription(`˗ˏˋ ☕ **Queued:** [${track.info.title}](${track.info.uri})\nPosition: **#${player.queue.length}** ˎˊ˗`);

      if (cover) queueEmbed.setThumbnail(cover);

      sendReply({ embeds: [queueEmbed] });
    }
  }

  if (!player.isPlaying && player.isConnected) {
    player.play();
  }
}

function setBassBoost(player, enable) {
  const state = getState(player.guildId);
  state.bassboost = enable;

  if (!player.filters) return;
  if (enable) {
    player.filters.setEqualizer([
      { band: 0, gain: 0.25 },
      { band: 1, gain: 0.20 },
      { band: 2, gain: 0.15 },
      { band: 3, gain: 0.10 },
      { band: 4, gain: 0.05 }
    ]);
  } else {
    player.filters.clearFilters();
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

  const { commandName, guild, member, channel, user } = interaction;
  const isOwner = owner.includes(user.id);

  if (['say', 'dm', 'status'].includes(commandName) && !isOwner) {
    return interaction.reply({ content: 'Nothing here.', ephemeral: true });
  }

  // Owner Commands
  if (commandName === 'say') {
    const text = interaction.options.getString('content');
    await channel.send(text);
    return interaction.reply({ content: 'Message sent ♡', ephemeral: true });
  }

  if (commandName === 'dm') {
    const target = interaction.options.getUser('target');
    const text = interaction.options.getString('content');
    try {
      await target.send(text);
      return interaction.reply({ content: `Sent to ${target.tag} ✨`, ephemeral: true });
    } catch {
      return interaction.reply({ content: `Could not DM ${target.tag}. DMs might be closed.`, ephemeral: true });
    }
  }

  if (commandName === 'status') {
    const statusType = interaction.options.getString('type');
    client.user.setPresence({ status: statusType });
    return interaction.reply({ content: `Status set to \`${statusType}\` ✨`, ephemeral: true });
  }

  // Music Commands
  const player = client.poru.players.get(guild.id);

  if (commandName === 'play') {
    await interaction.deferReply();
    const query = interaction.options.getString('query');
    return executePlay(guild, member, channel, query, (opts) => interaction.editReply(opts));
  }

  if (commandName === 'connect') {
    if (!member.voice.channel) {
      return interaction.reply({ content: 'Join a voice channel first!', ephemeral: true });
    }
    client.poru.createConnection({
      guildId: guild.id,
      voiceChannel: member.voice.channel.id,
      textChannel: channel.id,
      deaf: true
    });
    return interaction.reply({
      embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`Joined **${member.voice.channel.name}** ♡`)]
    });
  }

  if (commandName === 'disconnect') {
    if (!player) return interaction.reply({ content: 'Not connected to any voice channel.', ephemeral: true });
    clearTicker(guild.id);
    player.destroy();
    return interaction.reply({
      embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('Disconnected from the voice channel 🌸')]
    });
  }

  if (commandName === 'pause') {
    if (!player) return interaction.reply({ content: 'Nothing is playing.', ephemeral: true });
    player.pause(true);
    return interaction.reply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('⏸️ **Playback paused.**')] });
  }

  if (commandName === 'resume') {
    if (!player) return interaction.reply({ content: 'Nothing is playing.', ephemeral: true });
    player.pause(false);
    return interaction.reply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('▶️ **Playback resumed.**')] });
  }

  if (commandName === 'skip') {
    if (!player) return interaction.reply({ content: 'Nothing is playing.', ephemeral: true });
    player.skip();
    return interaction.reply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('⏭️ **Skipped track.**')] });
  }

  if (commandName === 'previous') {
    if (!player) return interaction.reply({ content: 'Nothing is playing.', ephemeral: true });
    const state = getState(guild.id);
    if (!state.previousTrack) return interaction.reply({ content: 'No previous track recorded in this session.', ephemeral: true });
    player.queue.unshift(state.previousTrack);
    player.skip();
    return interaction.reply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`⏮️ Playing previous: **${state.previousTrack.info.title}**`)] });
  }

  if (commandName === 'stop') {
    if (!player) return interaction.reply({ content: 'Nothing is playing.', ephemeral: true });
    stopMusic(player, guild.id);
    return interaction.reply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('⏹️ **Music stopped and queue cleared.**')] });
  }

  if (commandName === 'shuffle') {
    if (!player || player.queue.length === 0) return interaction.reply({ content: 'Not enough songs in queue to shuffle.', ephemeral: true });
    player.queue.shuffle();
    return interaction.reply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`🔀 **Shuffled ${player.queue.length} track(s)!**`)] });
  }

  if (commandName === 'clear') {
    if (!player || player.queue.length === 0) return interaction.reply({ content: 'Queue is already empty.', ephemeral: true });
    player.queue.clear();
    return interaction.reply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('🗑️ **Queue cleared completely.**')] });
  }

  if (commandName === 'remove') {
    if (!player || player.queue.length === 0) return interaction.reply({ content: 'The queue is empty.', ephemeral: true });
    const target = interaction.options.getString('target');
    const index = parseInt(target, 10);

    if (!isNaN(index) && index > 0 && index <= player.queue.length) {
      const removed = player.queue.remove(index - 1);
      return interaction.reply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`Removed: **${removed[0]?.info.title || target}**`)] });
    } else {
      const songIndex = player.queue.findIndex(t => t.info.title.toLowerCase().includes(target.toLowerCase()));
      if (songIndex !== -1) {
        const removed = player.queue.remove(songIndex);
        return interaction.reply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`Removed: **${removed[0]?.info.title}**`)] });
      }
      return interaction.reply({ content: 'Could not find that track in the queue.', ephemeral: true });
    }
  }

  if (commandName === 'bass') {
    if (!player) return interaction.reply({ content: 'Nothing is playing.', ephemeral: true });
    const enable = interaction.options.getBoolean('enabled');
    setBassBoost(player, enable);
    return interaction.reply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`🎧 **Bass boost set to:** \`${enable ? 'ON' : 'OFF'}\``)] });
  }

  if (commandName === 'loop') {
    const row = new ActionRowBuilder().addComponents(
      new ButtonBuilder().setCustomId('loop_off').setLabel('Off').setStyle(ButtonStyle.Secondary),
      new ButtonBuilder().setCustomId('loop_track').setLabel('Track').setStyle(ButtonStyle.Primary),
      new ButtonBuilder().setCustomId('loop_queue').setLabel('Queue').setStyle(ButtonStyle.Success)
    );
    const embed = new EmbedBuilder().setColor(THEME_COLOR).setTitle('🔁 Loop Control').setDescription('Choose repeat mode:');
    return interaction.reply({ embeds: [embed], components: [row] });
  }

  if (commandName === 'queue') {
    if (!player || (!player.currentTrack && player.queue.length === 0)) {
      return interaction.reply({ content: 'Queue is currently empty.', ephemeral: true });
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
});

// ==========================================
// 🖱️ INTERACTIVE PANEL BUTTON HANDLER
// ==========================================
async function handleButtonInteraction(interaction) {
  const { customId, guild, member } = interaction;
  const player = client.poru.players.get(guild.id);

  if (customId.startsWith('loop_')) {
    if (!player) return interaction.reply({ content: 'Player is no longer active.', ephemeral: true });
    const mode = customId.split('_')[1];
    if (mode === 'off') player.setLoop('NONE');
    else if (mode === 'track') player.setLoop('TRACK');
    else if (mode === 'queue') player.setLoop('QUEUE');
    return interaction.reply({ content: `Loop set to \`${mode.toUpperCase()}\` 🔁`, ephemeral: true });
  }

  if (!player) return interaction.reply({ content: 'No music is currently playing.', ephemeral: true });
  if (!member.voice.channel || member.voice.channel.id !== player.voiceChannel) {
    return interaction.reply({ content: 'Please join my voice channel to use the controls!', ephemeral: true });
  }

  await interaction.deferUpdate();

  switch (customId) {
    case 'btn_pause':
      player.pause(!player.isPaused);
      break;
    case 'btn_skip':
      player.skip();
      break;
    case 'btn_stop':
      stopMusic(player, guild.id);
      break;
    case 'btn_prev':
      const state = getState(guild.id);
      if (state.previousTrack) {
        player.queue.unshift(state.previousTrack);
        player.skip();
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
      setBassBoost(player, !curState.bassboost);
      break;
    case 'btn_queue':
      const qList = player.queue.slice(0, 5).map((t, i) => `${i + 1}. ${t.info.title.substring(0, 30)}...`).join('\n');
      await interaction.followUp({
        embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`**Up Next:**\n${qList || 'No more songs in queue.'}`)],
        ephemeral: true
      });
      break;
  }

  // Update panel status or disable buttons when stopped
  const panel = activePanels.get(guild.id);
  if (customId === 'btn_stop') {
    if (panel?.msg) {
      panel.msg.edit({
        embeds: [
          new EmbedBuilder()
            .setColor(THEME_COLOR)
            .setDescription('˗ˏˋ ⏹️ **Playback stopped and queue cleared.** ˎˊ˗')
        ],
        components: []
      }).catch(() => {});
    }
  } else if (panel?.msg && player.currentTrack) {
    panel.msg.edit({
      embeds: [buildPanelEmbed(player, player.currentTrack)],
      components: buildPanelButtons(player)
    }).catch(() => {});
  }
}

// ==========================================
// ⌨️ UNIVERSAL PREFIX & ALIAS COMMAND ROUTER
// ==========================================
client.on(Events.MessageCreate, async (message) => {
  if (message.author.bot || !message.guild) return;
  if (!message.content.toLowerCase().startsWith(prefix.toLowerCase())) return;

  let rawContent = message.content.slice(prefix.length).trim();
  const args = rawContent.split(/ +/);
  const cmd = args.shift()?.toLowerCase();
  if (!cmd) return;

  const isOwner = owner.includes(message.author.id);
  const isMatch = (aliases) => aliases.includes(cmd);

  // --- OWNER PREFIX COMMANDS ---
  if (isMatch(['say', 'dm', 'status'])) {
    if (!isOwner) return;

    if (cmd === 'say') {
      const content = args.join(' ');
      if (!content) return;
      await message.delete().catch(() => {});
      return message.channel.send(content);
    }

    if (cmd === 'dm') {
      const targetUser = message.mentions.users.first() || await client.users.fetch(args[0]).catch(() => null);
      const text = args.slice(1).join(' ');
      if (!targetUser || !text) return;
      return targetUser.send(text).then(() => message.react('💌')).catch(() => message.react('❌'));
    }

    if (cmd === 'status') {
      const statusType = args[0]?.toLowerCase();
      if (['online', 'idle', 'dnd'].includes(statusType)) {
        client.user.setPresence({ status: statusType });
        return message.react('✨');
      }
      return;
    }
  }

  // --- MUSIC PREFIX & SHORT ALIAS COMMANDS ---
  const sendReply = (opts) => message.channel.send(opts);
  let player = client.poru.players.get(message.guild.id);

  // Play: iplay / ip
  if (isMatch(['play', 'p'])) {
    const query = args.join(' ');
    if (!query) {
      return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`🌸 Usage: \`${prefix}play <song title / url>\``)] });
    }
    return executePlay(message.guild, message.member, message.channel, query, sendReply);
  }

  // Connect: iconnect / ic / ijoin / ij
  if (isMatch(['connect', 'c', 'join', 'j'])) {
    if (!message.member.voice.channel) {
      return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('🌸 Please join a voice channel first!')] });
    }
    client.poru.createConnection({
      guildId: message.guild.id,
      voiceChannel: message.member.voice.channel.id,
      textChannel: message.channel.id,
      deaf: true
    });
    return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`Joined **${message.member.voice.channel.name}** ♡`)] });
  }

  // Disconnect: idisconnect / idc / ileave / il
  if (isMatch(['disconnect', 'dc', 'leave', 'l'])) {
    if (!player) return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('🌸 I am not in any voice channel!')] });
    clearTicker(message.guild.id);
    player.destroy();
    return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('Disconnected from voice channel 🌸')] });
  }

  // Pause: ipause
  if (isMatch(['pause'])) {
    if (!player) return;
    player.pause(true);
    return message.react('⏸️');
  }

  // Resume: iresume / ir
  if (isMatch(['resume', 'r'])) {
    if (!player) return;
    player.pause(false);
    return message.react('▶️');
  }

  // Skip: iskip / is / next
  if (isMatch(['skip', 's', 'next'])) {
    if (!player) return;
    player.skip();
    return message.react('⏭️');
  }

  // Previous: iprevious / iprev / iback
  if (isMatch(['previous', 'prev', 'back'])) {
    if (!player) return;
    const state = getState(message.guild.id);
    if (!state.previousTrack) return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription('No previous track found.')] });
    player.queue.unshift(state.previousTrack);
    player.skip();
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
      return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`Removed: **${removed[0]?.info.title}**`)] });
    } else {
      const songIndex = player.queue.findIndex(t => t.info.title.toLowerCase().includes(target.toLowerCase()));
      if (songIndex !== -1) {
        const removed = player.queue.remove(songIndex);
        return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`Removed: **${removed[0]?.info.title}**`)] });
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
    setBassBoost(player, enable);
    return sendReply({ embeds: [new EmbedBuilder().setColor(THEME_COLOR).setDescription(`🎧 **Bass Boost:** \`${enable ? 'ON' : 'OFF'}\``)] });
  }

  // Loop: iloop / irepeat / rep / lp
  if (isMatch(['loop', 'repeat', 'repeate', 'rep', 'lp'])) {
    const row = new ActionRowBuilder().addComponents(
      new ButtonBuilder().setCustomId('loop_off').setLabel('Off').setStyle(ButtonStyle.Secondary),
      new ButtonBuilder().setCustomId('loop_track').setLabel('Track').setStyle(ButtonStyle.Primary),
      new ButtonBuilder().setCustomId('loop_queue').setLabel('Queue').setStyle(ButtonStyle.Success)
    );
    const embed = new EmbedBuilder().setColor(THEME_COLOR).setTitle('🔁 Loop Control').setDescription('Select repeat mode:');
    return sendReply({ embeds: [embed], components: [row] });
  }

  // Help: ihelp / ih
  if (isMatch(['help', 'h'])) {
    return sendReply({ embeds: [buildHelpEmbed()] });
  }
});

// ==========================================
// 📖 AESTHETIC HELP MENU
// ==========================================
function buildHelpEmbed() {
  return new EmbedBuilder()
    .setColor(THEME_COLOR)
    .setAuthor({ name: 'Isai • Music Commands', iconURL: client.user.displayAvatarURL() })
    .setDescription(
      `Welcome to **Isai (இசை)** — aesthetic music companion. 𝜗𝜚\n` +
      `Current Prefix: \`${prefix}\` | All commands work with **Slash (/)** & **Short Aliases**!\n`
    )
    .addFields(
      {
        name: '🎧 Playback Commands',
        value:
          `\`${prefix}play\` • \`${prefix}p\` • \`/play\` ➔ Play YouTube, Spotify & URL\n` +
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
          `\`${prefix}disconnect\` • \`${prefix}leave\` • \`${prefix}dc\` ➔ Leave VC`
      }
    )
    .setFooter({ text: 'Handcrafted with warmth & aesthetic care ♡', iconURL: client.user.displayAvatarURL() });
}

// Log in
client.login(process.env.TOKEN);
