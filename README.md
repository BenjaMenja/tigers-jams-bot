# Tiger's Jams Bot
A small discord bot designed to create and play a playlist from a local audio collection.

## Setup
Clone the repository, then take a look at the `.env.example` file. The `env.example` should be renamed to `.env`, and the variables there should be populated with the appropriate information. <br/>
Next, in the root of the project, open a terminal, create a python virtual environment, and install the required packages.
```python
python -m venv ./venv
pip install -r requirements.txt
```
From there, the bot can be ran by running the bot script:
```
python bot.py
```

## Features

### Startup and Joining

To begin using the bot, it must be in a voice channel. Players can tell it to join with the `/join` command. Once users are done with it, `/leave` will remove it from the channel, or it will remove itself after 5 minutes of inactivity.

### Playlist
The bot, by default, is designed to play a playlist of audio files from a local directory. Environment variables point to this directory, and the `/play` command can start playback of the playlist. By default, the playlist is shuffled, but this can be modified with a `/shuffle` command. To stop the playlist, `/stop` takes care of that.

### Queue
The `/queue` command shows users the current playing song, as well as up to the next 10 items in the queue. If a user only wants to see the current song, `/np` takes care of that.

### Search
The search feature is an advanced feature, accessible through the `/search` command. This command takes up to three arguments, namely the title, artist, and source of a particular audio. These fields are associated with a file through the [Song Library](https://github.com/BenjaMenja/song-library) project, which is a simple Django app that supports this feature. Searching for a file allows the user to put said file at the beginning of the queue if the playlist is running, or will otherwise immediately play it.