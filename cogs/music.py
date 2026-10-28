import logging
import aiohttp
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from requests import get

import config
from player import GuildPlayer

log = logging.getLogger(__name__)

QUEUE_PREVIEW_COUNT = 10

# Returns all members in a channel that are not bots.
def get_humans(channel: discord.VoiceChannel | discord.StageChannel) -> list[discord.Member]:
    return [member for member in channel.members if not member.bot]

def shorten_path(path: Path) -> str:
    return path.stem if len(path.stem) <= 80 else path.stem[:77] + "..."

def trim_text(text: str, limit: int = 100) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"

def format_queue(current: Path | None, upcoming: list[Path]) -> str:
    if current is None:
        return "Nothing is playing."
    lines = [f"**Now playing:** {shorten_path(current)}"]
    if upcoming:
        lines.append("**Up next:**")
        lines += [f"{i}. {shorten_path(p)}" for i, p in enumerate(upcoming, start=1)]
    return "\n".join(lines)

def resolve_song(file_path: str) -> Path | None:
    root = config.MUSIC_DIR.resolve()
    try:
        audio_file = (root / file_path).resolve()
    except (OSError, ValueError):
        return None
    if audio_file.is_relative_to(root) and audio_file.is_file():
        return audio_file
    return None

class SongChoiceView(discord.ui.View):
    def __init__(self, cog: "Music", owner_id: int, songs: list[tuple[str, Path]]):
        super().__init__(timeout=60)
        self.cog = cog
        self.owner_id = owner_id
        self.songs = songs
        self.picker.options = [
            discord.SelectOption(label=trim_text(label), value=str(i))
            for i, (label, _) in enumerate(songs)
        ]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the person who ran /search can choose.", ephemeral=True)
            return False
        return True

    @discord.ui.select(placeholder="Choose a song...")
    async def picker(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        label, path = self.songs[int(select.values[0])]
        self.stop()
        await interaction.response.edit_message(content=f"Selected {label}.", view=None)
        await self.cog.request_song(interaction, label, path)

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players: dict[int, GuildPlayer] = {}

    async def cog_unload(self):
        for player in list(self.players.values()):
            await player.close()
        self.players.clear()

    def forget(self, guild_id: int, player: GuildPlayer) -> None:
        if self.players.get(guild_id) is player:
            del self.players[guild_id]

    async def require_player(self, interaction: discord.Interaction) -> GuildPlayer | None:
        guild = interaction.guild
        if guild is None:
            return None
        player = self.players.get(guild.id)
        if player is None:
            await interaction.response.send_message("Use /join first.", ephemeral=True)
        return player

    async def request_song(self, interaction: discord.Interaction, label: str, path: Path) -> None:
        guild = interaction.guild
        player = self.players.get(guild.id) if guild is not None else None
        if player is None:
            await interaction.followup.send("Use /join first.", ephemeral=True)
            return

        await player.add_request(path)
        requesting_user = interaction.user.display_name

        message = f"{requesting_user} requested: {label}"
        await interaction.followup.send(message, ephemeral=False)

    @app_commands.command(name="join", description="Join your voice channel")
    @app_commands.guild_only()
    async def join(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user
        if guild is None or not isinstance(user, discord.Member):
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        
        voice_state = user.voice
        if voice_state is None or voice_state.channel is None:
            await interaction.response.send_message("Join a voice channel first.", ephemeral=True)
            return

        await interaction.response.defer()

        channel = voice_state.channel
        vc: discord.VoiceClient
        existing = guild.voice_client
        if existing is None:
            vc = await channel.connect()
        elif isinstance(existing, discord.VoiceClient):
            vc = existing
            if vc.channel != channel:
                await vc.move_to(channel)

        player = self.players.get(guild.id)
        if player is None or player.voice_client is not vc:
            if player is not None:
                await player.close(disconnect=False)
            player = GuildPlayer(vc)

            player.on_disconnect = lambda: self.forget(guild.id, player)
            self.players[guild.id] = player
        player.on_humans_changed(bool(get_humans(channel)))

        await interaction.followup.send(f"Joined {channel.name}.")

    @app_commands.command(name="play", description="Play Audio Playlist")
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction):
        player = await self.require_player(interaction)
        if player is None:
            return
        await player.start()
        if not player.queue:
            await interaction.response.send_message(
                f"No audio files found in {config.MUSIC_DIR}.", ephemeral=True)
            return
        mode = "on" if player.shuffle else "off"
        await interaction.response.send_message(
            f"Playing {len(player.queue)} tracks (shuffle {mode}).")

    @app_commands.command(name="skip", description="Skip the current audio")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction):
        player = await self.require_player(interaction)
        if player is None:
            return
        skipped_audio = await player.skip()
        if not skipped_audio:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        elif player.current is not None:
            await interaction.response.send_message(f"Skipped {skipped_audio.stem}. Now playing: {player.current.stem}")
        else:
            await interaction.response.send_message(f"Skipped {skipped_audio.stem}. Playlist is now empty.")

    @app_commands.command(name="queue", description=f"Show the next {QUEUE_PREVIEW_COUNT} items in the queue")
    @app_commands.guild_only()
    async def queue(self, interaction: discord.Interaction):
        player = await self.require_player(interaction)
        if player is None:
            return
        await interaction.response.send_message(
            format_queue(player.current, player.get_upcoming(QUEUE_PREVIEW_COUNT)))

    @app_commands.command(name="stop", description="Stop playback")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction):
        player = await self.require_player(interaction)
        if player is None:
            return
        player.stop()
        await interaction.response.send_message("Stopped.")

    @app_commands.command(name="shuffle", description="Toggle whether the playlist should shuffle")
    @app_commands.guild_only()
    async def shuffle(self, interaction: discord.Interaction, enabled: bool):
        player = await self.require_player(interaction)
        if player is None:
            return
        player.set_shuffle(enabled)
        await interaction.response.send_message(
            f"Shuffle {'on' if enabled else 'off'}.")

    @app_commands.command(name="leave", description="Leave the voice channel")
    @app_commands.guild_only()
    async def leave(self, interaction: discord.Interaction):
        player = await self.require_player(interaction)
        if player is None:
            return
        guild = interaction.guild
        if guild is None:
            return
        self.forget(guild.id, player)
        await player.close()
        await interaction.response.send_message("Left the voice channel.")

    @app_commands.command(name="np", description="Show the current audio")
    @app_commands.guild_only()
    async def now_playing(self, interaction: discord.Interaction):
        player = await self.require_player(interaction)
        if player is None:
            return

        if player.current is None:
            message = "Nothing is playing."
        else:
            message = f"**Now playing:** {shorten_path(player.current)}"
        await interaction.response.send_message(message)

    @app_commands.command(name="search", description="Search for a song by its title, artist, and source media.")
    @app_commands.guild_only()
    async def search_for_song(self, interaction: discord.Interaction, *, title: str | None, artist: str | None, source: str | None):
        player = await self.require_player(interaction)
        if player is None:
            return

        params = {
            key: value
            for key, value in (("title", title), ("artist", artist), ("source", source))
            if value is not None
        }

        await interaction.response.defer(ephemeral=True)
        async with aiohttp.ClientSession() as session:
            async with session.get(config.DB_PATH, params=params) as response:
                data = await response.json()

        songs: list[tuple[str, Path]] = []
        for entry in data[:10]:
            path = resolve_song(entry["file_path"])
            if path is None:
                continue
            name = entry.get("search_title") or entry.get("title") or path.stem
            artist_name = entry.get("artist")
            songs.append((f"{artist_name} – {name}" if artist_name else name, path))

        if not songs:
            await interaction.edit_original_response(content="No matching songs found.")
        elif len(songs) == 1:
            label, path = songs[0]
            await interaction.edit_original_response(content=f"Selected {label}.")
            await self.request_song(interaction, label, path)
        else:
            await interaction.edit_original_response(content="Pick a song:", view=SongChoiceView(self, interaction.user.id, songs))
                
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        guild = member.guild
        player = self.players.get(guild.id)
        if player is None:
            return

        bot_user = self.bot.user
        if bot_user is not None and member.id == bot_user.id and after.channel is None:
            self.forget(guild.id, player)
            await player.close(disconnect=False)
            return

        vc = guild.voice_client
        if not isinstance(vc, discord.VoiceClient) or vc.channel is None:
            return

        if before.channel != vc.channel and after.channel != vc.channel:
            return
        
        player.on_humans_changed(bool(get_humans(vc.channel)))


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
