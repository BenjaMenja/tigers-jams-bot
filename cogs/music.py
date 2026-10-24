import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

import config
from player import GuildPlayer

log = logging.getLogger(__name__)

QUEUE_PREVIEW_COUNT = 10

# Returns all members in a channel that are not bots.
def get_humans(channel: discord.VoiceChannel | discord.StageChannel) -> list[discord.Member]:
    return [member for member in channel.members if not member.bot]

def shorten_path(path: Path) -> str:
    return path.stem if len(path.stem) <= 80 else path.stem[:77] + "..."

def format_queue(current: Path | None, upcoming: list[Path]) -> str:
    if current is None:
        return "Nothing is playing."
    lines = [f"**Now playing:** {shorten_path(current)}"]
    if upcoming:
        lines.append("**Up next:**")
        lines += [f"{i}. {shorten_path(p)}" for i, p in enumerate(upcoming, start=1)]
    return "\n".join(lines)


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
