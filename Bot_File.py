
import os
import disnake
from disnake.ext import commands
from yt_dlp import YoutubeDL
import asyncio
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")


intents = disnake.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

music_queues = {}
current_song = {}
DJ_ROLE_NAME = "DJ"

YDL_OPTIONS = {'format': 'bestaudio[ext=m4a]/bestaudio/best', 'noplaylist': 'True'}
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 15',
    'options': '-vn'
}

sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIPY_CLIENT_ID,
    client_secret=SPOTIPY_CLIENT_SECRET
))

def extract_spotify_queries(spotify_url: str) -> list:
    queries = []
    if "track" in spotify_url:
        track = sp.track(spotify_url)
        name = track["name"]
        artists = ", ".join([a["name"] for a in track["artists"]])
        queries.append(f"{name} - {artists}")

    elif "playlist" in spotify_url:
        results = sp.playlist_tracks(spotify_url)
        for item in results["items"]:
            track = item["track"]
            name = track["name"]
            artists = ", ".join([a["name"] for a in track["artists"]])
            queries.append(f"{name} - {artists}")

    elif "album" in spotify_url:
        results = sp.album_tracks(spotify_url)
        for track in results["items"]:
            name = track["name"]
            full_track = sp.track(track["id"])
            artists = ", ".join([a["name"] for a in full_track["artists"]])
            queries.append(f"{name} - {artists}")
    return queries

@bot.command()
async def join(ctx):
    if ctx.author.voice:
        await ctx.author.voice.channel.connect()
        await ctx.send(f"Joined {ctx.author.voice.channel.mention}")
    else:
        await ctx.send("Join a voice channel first.")

@bot.command(aliases=["p"])
async def play(ctx, *, query: str):
    if ctx.author.voice is None:
        await ctx.send("Join a voice channel first.")
        return

    if not ctx.voice_client:
        await ctx.author.voice.channel.connect()

    guild_id = ctx.guild.id
    music_queues.setdefault(guild_id, [])

    if "open.spotify.com" in query:
        try:
            search_terms = extract_spotify_queries(query)
        except Exception as e:
            await ctx.send(f"Spotify error: {e}")
            return

        if not ctx.voice_client.is_playing():
            first = search_terms.pop(0)
            await search_and_play(ctx, first)
        for term in search_terms:
            music_queues[guild_id].append((term, None))
        await ctx.send(f"Queued {len(search_terms)+1} Spotify tracks.")
        return

    await search_and_play(ctx, query)

async def search_and_play(ctx, search_term):
    yt_query = f"ytsearch2:{search_term}"
    try:
        with YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(yt_query, download=False)
    except Exception as e:
        return await ctx.send(f"yt-dl error: {e}")

    if "entries" in info and not info["entries"]:
        return await ctx.send("No YouTube results for that query.")

    chosen = None
    for entry in info["entries"]:
        if entry and entry.get("url"):
            chosen = entry
            break

    if chosen is None:
        return await ctx.send("Couldn’t find a playable video in the top results.")


    if "entries" in info:
        info = info["entries"][0]
    title = info.get("title", "Unknown")
    url   = info.get("url")
    ...


    if ctx.voice_client.is_playing():
        music_queues[ctx.guild.id].append((title, url))
        await ctx.send(f"Queued: **{title}**")
    else:
        await play_song(ctx, title, url)

async def play_song(ctx: commands.Context, title: str, source_url: str | None):
    voice_client = ctx.voice_client
    if not voice_client:
        return

    if source_url is None:
        yt_query = f"ytsearch:{title}"
        try:
            with YoutubeDL(YDL_OPTIONS) as ydl:
                info = ydl.extract_info(yt_query, download=False)
                if 'entries' in info:
                    info = info['entries'][0]
                source_url = info.get("url")
                title = info.get("title", title)

        except Exception as e:
            await ctx.send(f"Failed to find audio for `{title}`")
            return

    try:
        audio_source = disnake.FFmpegPCMAudio(source_url, **FFMPEG_OPTIONS)
    except Exception as e:
        await ctx.send(f"Failed to play audio: {e}")
        return

    current_song[ctx.guild.id] = (title, source_url)

    async def auto_disconnect(ctx: commands.Context, delay: int = 60):
        """Disconnect the bot after a delay if no music is playing."""
        await asyncio.sleep(delay)
        voice_client = ctx.voice_client
        if voice_client and not voice_client.is_playing():
            await voice_client.disconnect()

    def after_play(error):
        if error:
            print(f"Playback error: {error}")
        guild_id = ctx.guild.id
        if guild_id in music_queues and music_queues[guild_id]:
            next_title, next_url = music_queues[guild_id].pop(0)
            fut = asyncio.run_coroutine_threadsafe(
                play_song(ctx, next_title, next_url), bot.loop
            )
            try:
                fut.result()
            except Exception as e:
                print(f"Error starting next song: {e}")
        else:
            current_song.pop(ctx.guild.id, None)
            asyncio.run_coroutine_threadsafe(auto_disconnect(ctx), bot.loop)

    voice_client.play(audio_source, after=after_play)
    await ctx.send(f"**Now playing:** {title}")


@bot.command()
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("Skipped.")

@bot.command()
async def stop(ctx):
    if ctx.voice_client:
        music_queues[ctx.guild.id] = []
        current_song.pop(ctx.guild.id, None)
        await ctx.voice_client.disconnect()
        await ctx.send("Stopped and left the voice channel.")

@bot.command()
async def queue(ctx):
    queue = music_queues.get(ctx.guild.id, [])
    now = current_song.get(ctx.guild.id)
    if not now and not queue:
        await ctx.send("Nothing is playing or queued.")
        return
    msg = []
    if now:
        msg.append(f"**Now Playing:** {now[0]}")
    if queue:
        msg.append("**Up Next:**")
        for i, (title, _) in enumerate(queue, 1):
            msg.append(f"{i}. {title}")
    await ctx.send("\n".join(msg))

bot.run(os.getenv("BOT_TOKEN"))
