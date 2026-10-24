"""(I mostly only used this when I found I had duplicate definitions of some commands in a server)"""

import discord
from discord import app_commands

import config

class Cleaner(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.none())
        self.tree = app_commands.CommandTree(self)

    async def on_ready(self):
        commands = await self.tree.sync()
        print(f"Global commands now registered: {len(commands)}")
        await self.close()


if __name__ == "__main__":
    if not config.DISCORD_TOKEN:
        raise SystemExit("No DISCORD_TOKEN found in environment variables.")
    Cleaner().run(config.DISCORD_TOKEN)
