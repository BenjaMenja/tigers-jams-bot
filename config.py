import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

def parse_guild_ids(id_list: str) -> list[int]:
    return [int(part) for part in id_list.replace(" ", "").split(",") if part]

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_IDS = parse_guild_ids(os.getenv("GUILD_IDS") or os.getenv("GUILD_ID", ""))
MUSIC_DIR = Path(os.getenv("MUSIC_DIR", r"./audio"))
AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".ogg", ".m4a", ".opus"}
IDLE_TIMEOUT_SECONDS = 5 * 60
PLAYLIST_NAME = os.getenv("PLAYLIST_NAME") or "Audio Playlist"
