import logging
import discord
from discord.ext import commands
import config

log = logging.getLogger(__name__)

class TJBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.default(),
        )

    async def setup_hook(self):
        await self.load_extension("cogs.music")

        # Currently for personal use, only exists in allowed servers
        for guild_id in config.GUILD_IDS:
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            try:
                await self.tree.sync(guild=guild)
                log.info("Synced commands to guild %s", guild_id)
            except discord.HTTPException as exc:
                log.error("Could not sync commands to guild %s: %s", guild_id, exc)


    def check_valid_server(self, guild: discord.Guild) -> None:
        if guild.id not in config.GUILD_IDS:
            log.warning(f"Invalid guild: {guild.name}, {guild.id}")

    async def on_ready(self):
        for guild in self.guilds:
            self.check_valid_server(guild)

    async def on_guild_join(self, guild: discord.Guild):
        self.check_valid_server(guild)

def main():
    if not config.DISCORD_TOKEN or not config.GUILD_IDS:
        raise SystemExit("No DISCORD_TOKEN or GUILD_IDS found. Add them to your .env, or create one if it doesn't exist.")
    logging.basicConfig(level=logging.INFO)
    TJBot().run(config.DISCORD_TOKEN)


if __name__ == "__main__":
    main()
