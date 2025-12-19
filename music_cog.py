import discord
from discord.ext import commands
import yt_dlp
import asyncio
import re
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import os
from collections import deque

# ═══════════════════════════════════════════════════════════════
# KONFIGURASI YT-DLP UNTUK AUDIO BERKUALITAS TINGGI (ANTI GRESEK)
# ═══════════════════════════════════════════════════════════════

YDL_OPTIONS = {
    'format': 'bestaudio[ext=webm][acodec=opus]/bestaudio[ext=m4a]/bestaudio/best',
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'extract_flat': False,
    'force_generic_extractor': False,
    'geo_bypass': True,
    'age_limit': 25,
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'opus',
        'preferredquality': '256',
    }],
}

# ═══════════════════════════════════════════════════════════════
# KONFIGURASI FFMPEG UNTUK AUDIO JERNIH (ANTI PATAH-PATAH)
# ═══════════════════════════════════════════════════════════════

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn -b:a 256k -bufsize 512k -af "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000"'
}

# Alternatif FFMPEG_OPTIONS untuk koneksi lambat
FFMPEG_OPTIONS_STABLE = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 10 -nostdin -probesize 200M -analyzeduration 200M',
    'options': '-vn -b:a 192k -bufsize 1024k'
}


class Song:
    """Class untuk menyimpan informasi lagu"""
    def __init__(self, source, data, requester):
        self.source = source
        self.data = data
        self.requester = requester
        self.title = data.get('title', 'Unknown')
        self.url = data.get('webpage_url', '')
        self.thumbnail = data.get('thumbnail', '')
        self.duration = data.get('duration', 0)
        self.channel = data.get('channel', data.get('uploader', 'Unknown'))

    def format_duration(self):
        if not self.duration:
            return "Live"
        minutes, seconds = divmod(self.duration, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"


class MusicPlayer:
    """Music Player untuk setiap guild"""
    def __init__(self, ctx):
        self.bot = ctx.bot
        self.guild = ctx.guild
        self.channel = ctx.channel
        self.queue = deque()
        self.current = None
        self.volume = 0.5
        self.loop = False
        self.loop_queue = False
        self.is_playing = False

    def add_to_queue(self, song):
        self.queue.append(song)

    def get_next(self):
        if self.loop and self.current:
            return self.current
        if self.loop_queue and self.current:
            self.queue.append(self.current)
        if self.queue:
            return self.queue.popleft()
        return None


class Music(commands.Cog):
    """🎵 Music Cog dengan kualitas audio HD"""
    
    def __init__(self, bot):
        self.bot = bot
        self.players = {}
        self.ytdl = yt_dlp.YoutubeDL(YDL_OPTIONS)
        
        # Setup Spotify jika credentials tersedia
        self.spotify = None
        spotify_id = os.environ.get('SPOTIFY_CLIENT_ID')
        spotify_secret = os.environ.get('SPOTIFY_CLIENT_SECRET')
        
        if spotify_id and spotify_secret:
            try:
                self.spotify = spotipy.Spotify(
                    auth_manager=SpotifyClientCredentials(
                        client_id=spotify_id,
                        client_secret=spotify_secret
                    )
                )
                print("✅ Spotify connected!")
            except Exception as e:
                print(f"⚠️ Spotify error: {e}")

    def get_player(self, ctx):
        """Mendapatkan atau membuat player untuk guild"""
        if ctx.guild.id not in self.players:
            self.players[ctx.guild.id] = MusicPlayer(ctx)
        return self.players[ctx.guild.id]

    async def search_youtube(self, query):
        """Mencari lagu di YouTube"""
        loop = asyncio.get_event_loop()
        
        # Cek apakah URL atau search query
        url_pattern = re.compile(
            r'(https?://)?(www\.)?(youtube\.com|youtu\.be|music\.youtube\.com)/.+'
        )
        
        if not url_pattern.match(query):
            query = f"ytsearch:{query}"
        
        try:
            data = await loop.run_in_executor(
                None, 
                lambda: self.ytdl.extract_info(query, download=False)
            )
            
            if 'entries' in data:
                data = data['entries'][0]
            
            return data
        except Exception as e:
            print(f"YouTube search error: {e}")
            return None

    async def get_spotify_track(self, url):
        """Mendapatkan info track dari Spotify"""
        if not self.spotify:
            return None
        
        try:
            # Extract track/album/playlist ID
            if 'track' in url:
                track = self.spotify.track(url)
                return [{
                    'name': track['name'],
                    'artist': track['artists'][0]['name'],
                    'search_query': f"{track['name']} {track['artists'][0]['name']}"
                }]
            elif 'playlist' in url:
                results = self.spotify.playlist_tracks(url)
                tracks = []
                for item in results['items'][:25]:  # Limit 25 lagu
                    track = item['track']
                    if track:
                        tracks.append({
                            'name': track['name'],
                            'artist': track['artists'][0]['name'],
                            'search_query': f"{track['name']} {track['artists'][0]['name']}"
                        })
                return tracks
            elif 'album' in url:
                results = self.spotify.album_tracks(url)
                album_info = self.spotify.album(url)
                tracks = []
                for track in results['items'][:25]:
                    tracks.append({
                        'name': track['name'],
                        'artist': album_info['artists'][0]['name'],
                        'search_query': f"{track['name']} {album_info['artists'][0]['name']}"
                    })
                return tracks
        except Exception as e:
            print(f"Spotify error: {e}")
            return None

    async def create_source(self, data, requester):
        """Membuat audio source dengan kualitas tinggi"""
        # Pilih format audio terbaik
        formats = data.get('formats', [data])
        
        # Prioritaskan Opus/WebM untuk kualitas terbaik
        best_audio = None
        for f in formats:
            if f.get('acodec') == 'opus':
                best_audio = f
                break
            elif f.get('acodec') in ['aac', 'mp4a', 'vorbis'] and not best_audio:
                best_audio = f
        
        if not best_audio:
            best_audio = data
        
        url = best_audio.get('url', data.get('url'))
        
        source = discord.FFmpegOpusAudio(
            url,
            **FFMPEG_OPTIONS,
            bitrate=256
        )
        
        return Song(source, data, requester)

    async def play_next(self, ctx):
        """Memutar lagu berikutnya"""
        player = self.get_player(ctx)
        
        if not ctx.voice_client:
            return
        
        song = player.get_next()
        
        if song is None:
            player.current = None
            player.is_playing = False
            
            # Timeout disconnect setelah 5 menit
            await asyncio.sleep(300)
            if ctx.voice_client and not ctx.voice_client.is_playing():
                await ctx.voice_client.disconnect()
                if ctx.guild.id in self.players:
                    del self.players[ctx.guild.id]
            return
        
        player.current = song
        player.is_playing = True
        
        def after_playing(error):
            if error:
                print(f"Player error: {error}")
            asyncio.run_coroutine_threadsafe(
                self.play_next(ctx), 
                self.bot.loop
            )
        
        try:
            # Re-fetch URL karena bisa expire
            data = await self.search_youtube(song.url or song.title)
            if data:
                new_song = await self.create_source(data, song.requester)
                ctx.voice_client.play(new_song.source, after=after_playing)
                
                # Kirim embed Now Playing
                embed = discord.Embed(
                    title="🎵 Now Playing",
                    description=f"**[{new_song.title}]({new_song.url})**",
                    color=discord.Color.green()
                )
                embed.add_field(name="⏱️ Duration", value=new_song.format_duration(), inline=True)
                embed.add_field(name="🎤 Channel", value=new_song.channel, inline=True)
                embed.add_field(name="👤 Requested by", value=new_song.requester.mention, inline=True)
                
                if new_song.thumbnail:
                    embed.set_thumbnail(url=new_song.thumbnail)
                
                if player.loop:
                    embed.set_footer(text="🔂 Loop: ON")
                elif player.loop_queue:
                    embed.set_footer(text="🔁 Loop Queue: ON")
                
                await player.channel.send(embed=embed)
        except Exception as e:
            print(f"Error playing: {e}")
            await self.play_next(ctx)

    # ═══════════════════════════════════════════════════════════════
    # COMMANDS
    # ═══════════════════════════════════════════════════════════════

    @commands.command(name='join', aliases=['j', 'connect'])
    async def join(self, ctx):
        """Bergabung ke voice channel"""
        if not ctx.author.voice:
            return await ctx.send("❌ **Kamu harus berada di voice channel!**")
        
        channel = ctx.author.voice.channel
        
        if ctx.voice_client:
            await ctx.voice_client.move_to(channel)
        else:
            await channel.connect(self_deaf=True)
        
        await ctx.send(f"✅ **Bergabung ke** `{channel.name}`")

    @commands.command(name='play', aliases=['p', 'putar'])
    async def play(self, ctx, *, query: str):
        """Memutar lagu dari YouTube/Spotify"""
        if not ctx.author.voice:
            return await ctx.send("❌ **Kamu harus berada di voice channel!**")
        
        # Join channel jika belum
        if not ctx.voice_client:
            await ctx.author.voice.channel.connect(self_deaf=True)
        
        player = self.get_player(ctx)
        player.channel = ctx.channel
        
        async with ctx.typing():
            # Cek apakah Spotify URL
            if 'spotify.com' in query:
                if not self.spotify:
                    return await ctx.send("❌ **Spotify tidak dikonfigurasi!** Tambahkan `SPOTIFY_CLIENT_ID` dan `SPOTIFY_CLIENT_SECRET`")
                
                tracks = await self.get_spotify_track(query)
                if not tracks:
                    return await ctx.send("❌ **Tidak dapat mengambil data dari Spotify!**")
                
                await ctx.send(f"🎵 **Menambahkan {len(tracks)} lagu dari Spotify...**")
                
                for track in tracks:
                    data = await self.search_youtube(track['search_query'])
                    if data:
                        song = await self.create_source(data, ctx.author)
                        player.add_to_queue(song)
            else:
                # YouTube/YouTube Music
                data = await self.search_youtube(query)
                if not data:
                    return await ctx.send("❌ **Lagu tidak ditemukan!**")
                
                song = await self.create_source(data, ctx.author)
                player.add_to_queue(song)
                
                if ctx.voice_client.is_playing() or player.current:
                    embed = discord.Embed(
                        title="📝 Added to Queue",
                        description=f"**[{song.title}]({song.url})**",
                        color=discord.Color.blue()
                    )
                    embed.add_field(name="⏱️ Duration", value=song.format_duration(), inline=True)
                    embed.add_field(name="📊 Position", value=f"#{len(player.queue)}", inline=True)
                    if song.thumbnail:
                        embed.set_thumbnail(url=song.thumbnail)
                    await ctx.send(embed=embed)
        
        # Mulai play jika tidak sedang playing
        if not ctx.voice_client.is_playing() and not player.is_playing:
            await self.play_next(ctx)

    @commands.command(name='pause', aliases=['ps'])
    async def pause(self, ctx):
        """Pause musik"""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("⏸️ **Musik di-pause**")
        else:
            await ctx.send("❌ **Tidak ada musik yang diputar!**")

    @commands.command(name='resume', aliases=['r', 'unpause'])
    async def resume(self, ctx):
        """Resume musik"""
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("▶️ **Musik dilanjutkan**")
        else:
            await ctx.send("❌ **Musik tidak sedang di-pause!**")

    @commands.command(name='skip', aliases=['s', 'next'])
    async def skip(self, ctx):
        """Skip lagu saat ini"""
        if ctx.voice_client and ctx.voice_client.is_playing():
            player = self.get_player(ctx)
            player.loop = False  # Disable loop sementara
            ctx.voice_client.stop()
            await ctx.send("⏭️ **Lagu di-skip**")
        else:
            await ctx.send("❌ **Tidak ada musik yang diputar!**")

    @commands.command(name='stop', aliases=['st', 'dc', 'leave', 'disconnect'])
    async def stop(self, ctx):
        """Stop musik dan keluar dari voice channel"""
        if ctx.voice_client:
            player = self.get_player(ctx)
            player.queue.clear()
            player.current = None
            player.is_playing = False
            ctx.voice_client.stop()
            await ctx.voice_client.disconnect()
            
            if ctx.guild.id in self.players:
                del self.players[ctx.guild.id]
            
            await ctx.send("⏹️ **Musik dihentikan**")
        else:
            await ctx.send("❌ **Bot tidak berada di voice channel!**")

    @commands.command(name='queue', aliases=['q', 'list'])
    async def queue(self, ctx):
        """Melihat antrian lagu"""
        player = self.get_player(ctx)
        
        if not player.current and not player.queue:
            return await ctx.send("📭 **Antrian kosong!**")
        
        embed = discord.Embed(
            title="🎵 Music Queue",
            color=discord.Color.purple()
        )
        
        if player.current:
            embed.add_field(
                name="▶️ Now Playing",
                value=f"**{player.current.title}** [{player.current.format_duration()}]",
                inline=False
            )
        
        if player.queue:
            queue_list = ""
            for i, song in enumerate(list(player.queue)[:10], 1):
                queue_list += f"`{i}.` **{song.title}** [{song.format_duration()}]\n"
            
            if len(player.queue) > 10:
                queue_list += f"\n*...dan {len(player.queue) - 10} lagu lainnya*"
            
            embed.add_field(name="📝 Up Next", value=queue_list, inline=False)
        
        embed.set_footer(text=f"Total: {len(player.queue)} lagu dalam antrian")
        await ctx.send(embed=embed)

    @commands.command(name='nowplaying', aliases=['np', 'now'])
    async def nowplaying(self, ctx):
        """Melihat lagu yang sedang diputar"""
        player = self.get_player(ctx)
        
        if not player.current:
            return await ctx.send("❌ **Tidak ada musik yang diputar!**")
        
        song = player.current
        embed = discord.Embed(
            title="🎵 Now Playing",
            description=f"**[{song.title}]({song.url})**",
            color=discord.Color.green()
        )
        embed.add_field(name="⏱️ Duration", value=song.format_duration(), inline=True)
        embed.add_field(name="🎤 Channel", value=song.channel, inline=True)
        embed.add_field(name="👤 Requested by", value=song.requester.mention, inline=True)
        
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)
        
        status = []
        if player.loop:
            status.append("🔂 Loop")
        if player.loop_queue:
            status.append("🔁 Loop Queue")
        if status:
            embed.set_footer(text=" | ".join(status))
        
        await ctx.send(embed=embed)

    @commands.command(name='loop', aliases=['lp'])
    async def loop(self, ctx):
        """Toggle loop lagu saat ini"""
        player = self.get_player(ctx)
        player.loop = not player.loop
        
        if player.loop:
            player.loop_queue = False
            await ctx.send("🔂 **Loop: ON** - Lagu saat ini akan diulang")
        else:
            await ctx.send("🔂 **Loop: OFF**")

    @commands.command(name='loopqueue', aliases=['lq', 'loopq'])
    async def loopqueue(self, ctx):
        """Toggle loop seluruh queue"""
        player = self.get_player(ctx)
        player.loop_queue = not player.loop_queue
        
        if player.loop_queue:
            player.loop = False
            await ctx.send("🔁 **Loop Queue: ON** - Seluruh antrian akan diulang")
        else:
            await ctx.send("🔁 **Loop Queue: OFF**")

    @commands.command(name='shuffle', aliases=['sh', 'acak'])
    async def shuffle(self, ctx):
        """Acak urutan queue"""
        import random
        player = self.get_player(ctx)
        
        if len(player.queue) < 2:
            return await ctx.send("❌ **Queue terlalu sedikit untuk diacak!**")
        
        queue_list = list(player.queue)
        random.shuffle(queue_list)
        player.queue = deque(queue_list)
        
        await ctx.send("🔀 **Queue telah diacak!**")

    @commands.command(name='clear', aliases=['cl'])
    async def clear(self, ctx):
        """Hapus semua lagu di queue"""
        player = self.get_player(ctx)
        player.queue.clear()
        await ctx.send("🗑️ **Queue telah dikosongkan!**")

    @commands.command(name='remove', aliases=['rm'])
    async def remove(self, ctx, index: int):
        """Hapus lagu dari queue berdasarkan nomor"""
        player = self.get_player(ctx)
        
        if index < 1 or index > len(player.queue):
            return await ctx.send(f"❌ **Index tidak valid! (1-{len(player.queue)})**")
        
        queue_list = list(player.queue)
        removed = queue_list.pop(index - 1)
        player.queue = deque(queue_list)
        
        await ctx.send(f"🗑️ **Removed:** {removed.title}")

    @commands.command(name='volume', aliases=['vol', 'v'])
    async def volume(self, ctx, vol: int = None):
        """Atur volume (0-100)"""
        player = self.get_player(ctx)
        
        if vol is None:
            return await ctx.send(f"🔊 **Volume saat ini:** {int(player.volume * 100)}%")
        
        if not 0 <= vol <= 100:
            return await ctx.send("❌ **Volume harus antara 0-100!**")
        
        player.volume = vol / 100
        
        if ctx.voice_client and ctx.voice_client.sourc
