import discord
from discord.ext import commands
import yt_dlp
import asyncio
import re
import os
import subprocess
import sys
from collections import deque
from urllib.parse import urlparse, parse_qs

# ═══════════════════════════════════════════════════════════════
# AUTO UPDATE YT-DLP (PENTING!)
# ═══════════════════════════════════════════════════════════════

def update_ytdlp():
    """Update yt-dlp ke versi terbaru"""
    try:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", 
            "--upgrade", "yt-dlp", "-q"
        ])
        print("✅ yt-dlp updated!")
    except Exception as e:
        print(f"⚠️ Failed to update yt-dlp: {e}")

# Update saat startup
update_ytdlp()

# ═══════════════════════════════════════════════════════════════
# KONFIGURASI YT-DLP YANG LEBIH ROBUST
# ═══════════════════════════════════════════════════════════════

def get_ytdl_options(use_cookies=False):
    """Generate YT-DLP options"""
    options = {
        'format': 'bestaudio[ext=webm][acodec=opus]/bestaudio[ext=m4a][acodec=aac]/bestaudio/best',
        'noplaylist': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'ytsearch5',  # Ambil 5 hasil untuk fallback
        'source_address': '0.0.0.0',
        'force_ipv4': True,
        'geo_bypass': True,
        'geo_bypass_country': 'US',
        
        # PENTING: Headers untuk bypass bot detection
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        },
        
        # Ekstraksi
        'extract_flat': False,
        'youtube_include_dash_manifest': False,
        'youtube_include_hls_manifest': False,
        
        # Retry dan timeout
        'retries': 5,
        'fragment_retries': 5,
        'skip_unavailable_fragments': True,
        'socket_timeout': 30,
        
        # Age gate bypass
        'age_limit': None,
        
        # Extractor args untuk bypass restrictions
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
                'skip': ['dash', 'hls']
            }
        },
    }
    
    # Tambahkan cookies jika ada
    cookies_path = 'cookies.txt'
    if use_cookies and os.path.exists(cookies_path):
        options['cookiefile'] = cookies_path
        print("🍪 Using cookies.txt")
    
    return options

# FFMPEG Options untuk audio jernih
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin -loglevel warning',
    'options': '-vn -b:a 256k -bufsize 512k'
}


class YouTubeURLParser:
    """Parser untuk berbagai format URL YouTube"""
    
    YOUTUBE_PATTERNS = [
        # Standard YouTube
        r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})',
        # YouTube Short URL
        r'(?:https?://)?(?:www\.)?youtu\.be/([a-zA-Z0-9_-]{11})',
        # YouTube Music
        r'(?:https?://)?music\.youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})',
        # YouTube Shorts
        r'(?:https?://)?(?:www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
        # YouTube Embed
        r'(?:https?://)?(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]{11})',
        # YouTube v/ format
        r'(?:https?://)?(?:www\.)?youtube\.com/v/([a-zA-Z0-9_-]{11})',
    ]
    
    @classmethod
    def extract_video_id(cls, url: str) -> str:
        """Ekstrak video ID dari berbagai format URL"""
        # Cek pattern regex
        for pattern in cls.YOUTUBE_PATTERNS:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        # Cek query parameter
        try:
            parsed = urlparse(url)
            if 'youtube.com' in parsed.netloc or 'youtu.be' in parsed.netloc:
                query_params = parse_qs(parsed.query)
                if 'v' in query_params:
                    return query_params['v'][0]
        except:
            pass
        
        return None
    
    @classmethod
    def is_youtube_url(cls, url: str) -> bool:
        """Cek apakah URL adalah YouTube URL"""
        youtube_domains = [
            'youtube.com', 'youtu.be', 'music.youtube.com',
            'www.youtube.com', 'm.youtube.com'
        ]
        try:
            parsed = urlparse(url)
            return any(domain in parsed.netloc for domain in youtube_domains)
        except:
            return False
    
    @classmethod
    def normalize_url(cls, url: str) -> str:
        """Normalize URL ke format standard"""
        video_id = cls.extract_video_id(url)
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
        return url


class Song:
    """Class untuk menyimpan informasi lagu"""
    def __init__(self, source, data, requester):
        self.source = source
        self.data = data
        self.requester = requester
        self.title = data.get('title', 'Unknown')
        self.url = data.get('webpage_url', data.get('url', ''))
        self.original_url = data.get('original_url', self.url)
        self.thumbnail = data.get('thumbnail', '')
        self.duration = data.get('duration', 0)
        self.channel = data.get('channel', data.get('uploader', 'Unknown'))
        self.stream_url = data.get('url', '')
    
    def format_duration(self):
        if not self.duration:
            return "Live 🔴"
        minutes, seconds = divmod(int(self.duration), 60)
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
    """🎵 Music Cog dengan error handling yang lebih baik"""
    
    def __init__(self, bot):
        self.bot = bot
        self.players = {}
        self.ytdl = yt_dlp.YoutubeDL(get_ytdl_options())
        self.use_cookies = os.path.exists('cookies.txt')
        
        # Setup Spotify
        self.spotify = None
        self._setup_spotify()
    
    def _setup_spotify(self):
        """Setup Spotify client"""
        try:
            import spotipy
            from spotipy.oauth2 import SpotifyClientCredentials
            
            spotify_id = os.environ.get('SPOTIFY_CLIENT_ID')
            spotify_secret = os.environ.get('SPOTIFY_CLIENT_SECRET')
            
            if spotify_id and spotify_secret:
                self.spotify = spotipy.Spotify(
                    auth_manager=SpotifyClientCredentials(
                        client_id=spotify_id,
                        client_secret=spotify_secret
                    )
                )
                print("✅ Spotify connected!")
        except Exception as e:
            print(f"⚠️ Spotify not available: {e}")

    def get_player(self, ctx):
        """Mendapatkan atau membuat player untuk guild"""
        if ctx.guild.id not in self.players:
            self.players[ctx.guild.id] = MusicPlayer(ctx)
        return self.players[ctx.guild.id]

    def refresh_ytdl(self):
        """Refresh YT-DLP instance dengan options baru"""
        self.ytdl = yt_dlp.YoutubeDL(get_ytdl_options(self.use_cookies))

    async def search_youtube(self, query: str, max_retries: int = 3):
        """
        Mencari lagu di YouTube dengan multiple fallback methods
        """
        loop = asyncio.get_event_loop()
        last_error = None
        
        # Normalize URL jika itu adalah YouTube URL
        if YouTubeURLParser.is_youtube_url(query):
            query = YouTubeURLParser.normalize_url(query)
            print(f"📎 Normalized URL: {query}")
        
        # Method 1: Direct extraction (untuk URL)
        # Method 2: Search dengan ytsearch
        # Method 3: Search dengan ytsearch1 (single result)
        # Method 4: Dengan cookies (jika ada)
        
        search_methods = []
        
        # Jika URL langsung
        if YouTubeURLParser.is_youtube_url(query):
            video_id = YouTubeURLParser.extract_video_id(query)
            if video_id:
                search_methods.append({
                    'query': f"https://www.youtube.com/watch?v={video_id}",
                    'name': 'Direct URL'
                })
                # Fallback dengan format berbeda
                search_methods.append({
                    'query': f"https://youtu.be/{video_id}",
                    'name': 'Short URL'
                })
        
        # Search query
        clean_query = re.sub(r'https?://\S+', '', query).strip()
        if clean_query or not YouTubeURLParser.is_youtube_url(query):
            search_query = clean_query if clean_query else query
            search_methods.append({
                'query': f"ytsearch:{search_query}",
                'name': 'YouTube Search'
            })
            search_methods.append({
                'query': f"ytsearch5:{search_query}",
                'name': 'YouTube Search (5 results)'
            })
        
        for attempt, method in enumerate(search_methods):
            for retry in range(max_retries):
                try:
                    print(f"🔍 Attempt {attempt+1}.{retry+1}: {method['name']} - {method['query'][:50]}...")
                    
                    # Refresh YTDL setiap beberapa attempt
                    if retry > 0:
                        self.refresh_ytdl()
                    
                    data = await loop.run_in_executor(
                        None,
                        lambda q=method['query']: self.ytdl.extract_info(q, download=False)
                    )
                    
                    if data:
                        # Handle playlist/search results
                        if 'entries' in data:
                            entries = [e for e in data['entries'] if e]  # Filter None
                            if entries:
                                data = entries[0]
                            else:
                                continue
                        
                        # Validasi data
                        if data.get('url') or data.get('formats'):
                            print(f"✅ Found: {data.get('title', 'Unknown')}")
                            return data
                        
                except yt_dlp.utils.DownloadError as e:
                    last_error = str(e)
                    error_msg = str(e).lower()
                    
                    # Handle specific errors
                    if 'video unavailable' in error_msg:
                        print(f"❌ Video unavailable")
                        break  # Skip to next method
                    elif 'private video' in error_msg:
                        print(f"❌ Private video")
                        break
                    elif 'sign in' in error_msg or 'age' in error_msg:
                        print(f"⚠️ Age restricted - trying with cookies...")
                        self.use_cookies = True
                        self.refresh_ytdl()
                    elif 'no video formats' in error_msg:
                        print(f"⚠️ No formats found, retrying...")
                    else:
                        print(f"⚠️ Download error: {e}")
                    
                    await asyncio.sleep(1)  # Wait before retry
                    
                except Exception as e:
                    last_error = str(e)
                    print(f"⚠️ Error ({method['name']}): {e}")
                    await asyncio.sleep(1)
        
        print(f"❌ All methods failed. Last error: {last_error}")
        return None

    async def get_stream_url(self, data: dict) -> str:
        """Mendapatkan URL stream yang valid"""
        # Prioritas: url langsung > formats
        if data.get('url') and not data['url'].startswith('ytsearch'):
            return data['url']
        
        formats = data.get('formats', [])
        if not formats:
            return data.get('url', '')
        
        # Filter dan sort formats
        audio_formats = []
        for f in formats:
            if f.get('acodec') != 'none' and f.get('url'):
                audio_formats.append(f)
        
        if not audio_formats:
            audio_formats = formats
        
        # Prioritaskan opus/webm
        for f in audio_formats:
            if f.get('acodec') == 'opus':
                return f['url']
        
        # Fallback ke format dengan bitrate tertinggi
        audio_formats.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)
        
        return audio_formats[0].get('url', data.get('url', ''))

    async def create_source(self, data: dict, requester):
        """Membuat audio source"""
        stream_url = await self.get_stream_url(data)
        
        if not stream_url:
            raise ValueError("No stream URL found")
        
        # Buat FFmpeg source
        source = discord.FFmpegOpusAudio(
            stream_url,
            **FFMPEG_OPTIONS,
            bitrate=256
        )
        
        # Simpan stream URL di data
        data['url'] = stream_url
        
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
            
            # Disconnect after timeout
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
            search_query = song.original_url or song.url or song.title
            data = await self.search_youtube(search_query)
            
            if data:
                new_song = await self.create_source(data, song.requester)
                ctx.voice_client.play(new_song.source, after=after_playing)
                
                # Send Now Playing embed
                embed = discord.Embed(
                    title="🎵 Now Playing",
                    description=f"**[{new_song.title}]({new_song.url})**",
                    color=discord.Color.green()
                )
                embed.add_field(name="⏱️ Duration", value=new_song.format_duration(), inline=True)
                embed.add_field(name="🎤 Channel", value=new_song.channel, inline=True)
                embed.add_field(name="👤 Requested", value=new_song.requester.mention, inline=True)
                
                if new_song.thumbnail:
                    embed.set_thumbnail(url=new_song.thumbnail)
                
                if player.loop:
                    embed.set_footer(text="🔂 Loop: ON")
                elif player.loop_queue:
                    embed.set_footer(text="🔁 Loop Queue: ON")
                
                await player.channel.send(embed=embed)
            else:
                await player.channel.send(f"❌ **Gagal memutar:** {song.title}\nMencoba lagu berikutnya...")
                await self.play_next(ctx)
                
        except Exception as e:
            print(f"Error playing: {e}")
            await player.channel.send(f"❌ **Error:** {str(e)[:100]}")
            await self.play_next(ctx)

    # ═══════════════════════════════════════════════════════════════
    # COMMANDS
    # ═══════════════════════════════════════════════════════════════

    @commands.command(name='play', aliases=['p', 'putar'])
    async def play(self, ctx, *, query: str):
        """Memutar lagu dari YouTube/Spotify"""
        if not ctx.author.voice:
            return await ctx.send("❌ **Kamu harus berada di voice channel!**")
        
        # Join channel
        if not ctx.voice_client:
            await ctx.author.voice.channel.connect(self_deaf=True)
        elif ctx.voice_client.channel != ctx.author.voice.channel:
            await ctx.voice_client.move_to(ctx.author.voice.channel)
        
        player = self.get_player(ctx)
        player.channel = ctx.channel
        
        # Send searching message
        search_msg = await ctx.send(f"🔍 **Mencari:** `{query[:50]}{'...' if len(query) > 50 else ''}`")
        
        try:
            # Cek Spotify URL
            if 'spotify.com' in query:
                await self._handle_spotify(ctx, query, player, search_msg)
                return
            
            # YouTube
            data = await self.search_youtube(query)
            
            if not data:
                error_embed = discord.Embed(
                    title="❌ Lagu Tidak Ditemukan",
                    description=f"**Query:** `{query}`",
                    color=discord.Color.red()
                )
                error_embed.add_field(
                    name="💡 Tips",
                    value=(
                        "• Coba gunakan judul lagu yang lebih spesifik\n"
                        "• Pastikan video tidak private/age-restricted\n"
                        "• Coba copy link langsung dari YouTube\n"
                        "• Gunakan `!debug <url>` untuk diagnosa"
                    ),
                    inline=False
                )
                await search_msg.edit(content=None, embed=error_embed)
                return
            
            song = await self.create_source(data, ctx.author)
            player.add_to_queue(song)
            
            # Update message
            if ctx.voice_client.is_playing() or (player.current and player.is_playing):
                embed = discord.Embed(
                    title="📝 Added to Queue",
                    description=f"**[{song.title}]({song.url})**",
                    color=discord.Color.blue()
                )
                embed.add_field(name="⏱️ Duration", value=song.format_duration(), inline=True)
                embed.add_field(name="📊 Position", value=f"#{len(player.queue)}", inline=True)
                if song.thumbnail:
                    embed.set_thumbnail(url=song.thumbnail)
                await search_msg.edit(content=None, embed=embed)
            else:
                await search_msg.delete()
            
            # Start playing if not already
            if not ctx.voice_client.is_playing() and not player.is_playing:
                await self.play_next(ctx)
                
        except Exception as e:
            await search_msg.edit(content=f"❌ **Error:** {str(e)[:200]}")
            print(f"Play error: {e}")

    async def _handle_spotify(self, ctx, url: str, player, search_msg):
        """Handle Spotify URLs"""
        if not self.spotify:
            await search_msg.edit(
                content="❌ **Spotify tidak dikonfigurasi!**\n"
                        "Tambahkan `SPOTIFY_CLIENT_ID` dan `SPOTIFY_CLIENT_SECRET` ke Secrets."
            )
            return
        
        try:
            tracks = await self._get_spotify_tracks(url)
            
            if not tracks:
                await search_msg.edit(content="❌ **Tidak dapat mengambil data dari Spotify!**")
                return
            
            await search_msg.edit(content=f"🎵 **Menambahkan {len(tracks)} lagu dari Spotify...**")
            
            added = 0
            for track in tracks:
                data = await self.search_youtube(track['search_query'])
                if data:
                    song = await self.create_source(data, ctx.author)
                    player.add_to_queue(song)
                    added += 1
            
            await search_msg.edit(content=f"✅ **Berhasil menambahkan {added}/{len(tracks)} lagu dari Spotify!**")
            
            if not ctx.voice_client.is_playing() and not player.is_playing:
                await self.play_next(ctx)
                
        except Exception as e:
            await search_msg.edit(content=f"❌ **Spotify Error:** {str(e)[:100]}")

    async def _get_spotify_tracks(self, url: str) -> list:
        """Get tracks from Spotify URL"""
        tracks = []
        
        try:
            if 'track' in url:
                track = self.spotify.track(url)
                tracks.append({
                    'name': track['name'],
                    'artist': track['artists'][0]['name'],
                    'search_query': f"{track['name']} {track['artists'][0]['name']} audio"
                })
            elif 'playlist' in url:
                results = self.spotify.playlist_tracks(url)
                for item in results['items'][:30]:
                    track = item.get('track')
                    if track:
                        tracks.append({
                            'name': track['name'],
                            'artist': track['artists'][0]['name'],
                            'search_query': f"{track['name']} {track['artists'][0]['name']} audio"
                        })
            elif 'album' in url:
                album = self.spotify.album(url)
                for track in album['tracks']['items'][:30]:
                    tracks.append({
                        'name': track['name'],
                        'artist': album['artists'][0]['name'],
                        'search_query': f"{track['name']} {album['artists'][0]['name']} audio"
                    })
        except Exception as e:
            print(f"Spotify parsing error: {e}")
        
        return tracks

    @commands.command(name='debug', aliases=['diagnose', 'test'])
    async def debug(self, ctx, *, url: str):
        """Debug URL yang bermasalah"""
        msg = await ctx.send("🔍 **Menganalisa URL...**")
        
        results = []
        
        # Check URL type
        if YouTubeURLParser.is_youtube_url(url):
            video_id = YouTubeURLParser.extract_video_id(url)
            results.append(f"✅ YouTube URL detected")
            results.append(f"📎 Video ID: `{video_id}`")
            normalized = YouTubeURLParser.normalize_url(url)
            results.append(f"🔗 Normalized: `{normalized}`")
        else:
            results.append(f"📝 Search query: `{url}`")
        
        # Try to fetch
        results.append("\n**🔄 Testing extraction...**")
        
        try:
            loop = asyncio.get_event_loop()
            
            # Test dengan berbagai options
            test_options = [
                ("Default", get_ytdl_options()),
                ("With cookies", get_ytdl_options(use_cookies=True)),
            ]
            
            for name, options in test_options:
                try:
                    ytdl = yt_dlp.YoutubeDL(options)
                    data = await loop.run_in_executor(
                        None,
                        lambda: ytdl.extract_info(url, download=False)
                    )
                    
                    if data:
                        if 'entries' in data:
                            data = data['entries'][0] if data['entries'] else None
                        
                        if data:
                            results.append(f"✅ **{name}:** Success!")
                            results.append(f"   📺 Title: {data.get('title', 'N/A')[:50]}")
                            results.append(f"   ⏱️ Duration: {data.get('duration', 'N/A')}s")
                            results.append(f"   🔊 Formats: {len(data.get('formats', []))}")
                            break
                    else:
                        results.append(f"⚠️ **{name}:** No data returned")
                        
                except Exception as e:
                    error_short = str(e)[:100]
                    results.append(f"❌ **{name}:** {error_short}")
                    
        except Exception as e:
            results.append(f"❌ Fatal error: {str(e)[:100]}")
        
        # Send results
        embed = discord.Embed(
            title="🔧 Debug Results",
            description="\n".join(results),
            color=discord.Color.blue()
        )
        embed.add_field(
            name="💡 Jika gagal",
            value=(
                "• Pastikan video tidak private\n"
                "• Video mungkin age-restricted\n"
                "• Coba tambahkan `cookies.txt`\n"
                "• Regional blocking mungkin aktif"
            ),
            inline=False
        )
        
        await msg.edit(content=None, embed=embed)

    @commands.command(name='forceplay', aliases=['fp'])
    async def forceplay(self, ctx, *, query: str):
        """Force play dengan refresh yt-dlp"""
        # Update yt-dlp
        msg = await ctx.send("🔄 **Updating yt-dlp...**")
        update_ytdlp()
        self.refresh_ytdl()
        
        await msg.edit(content="✅ **Updated! Mencari lagu...**")
        await msg.delete()
        
        # Call normal play
        await self.play(ctx, query=query)

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

    @commands.command(name='pause', aliases=['ps'])
    async def pause(self, ctx):
        """Pause musik"""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("⏸️ **Musik di-pause**")
        else:
            await ctx.send("❌ **Tidak ada musik yang diputar!**")

    @commands.command(name='resume', aliases=['r'])
    async def resume(self, ctx):
        """Resume musik"""
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("▶️ **Musik dilanjutkan**")
        else:
            await ctx.send("❌ **Musik tidak di-pause!**")

    @commands.command(name='skip', aliases=['s', 'next'])
    async def skip(self, ctx):
        """Skip lagu"""
        if ctx.voice_client and ctx.voice_client.is_playing():
            player = self.get_player(ctx)
            player.loop = False
            ctx.voice_client.stop()
            await ctx.send("⏭️ **Lagu di-skip**")
        else:
            await ctx.send("❌ **Tidak ada musik!**")

    @commands.command(name='stop', aliases=['dc', 'leave', 'disconnect'])
    async def stop(self, ctx):
        """Stop dan keluar"""
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

    @commands.command(name='queue', aliases=['q'])
    async def queue(self, ctx):
        """Lihat antrian"""
        player = self.get_player(ctx)
        
        if not player.current and not player.queue:
            return await ctx.send("📭 **Antrian kosong!**")
        
        embed = discord.Embed(title="🎵 Queue", color=discord.Color.purple())
        
        if player.current:
            embed.add_field(
                name="▶️ Now Playing",
                value=f"**{player.current.title}** [{player.current.format_duration()}]",
                inline=False
            )
        
        if player.queue:
            queue_text = ""
            for i, song in enumerate(list(player.queue)[:10], 1):
                queue_text += f"`{i}.` {song.title} [{song.format_duration()}]\n"
            
            if len(player.queue) > 10:
                queue_text += f"\n*+{len(player.queue) - 10} more...*"
            
            embed.add_field(name="📝 Up Next", value=queue_text, inline=False)
        
        await ctx.send(embed=embed)

    @commands.command(name='nowplaying', aliases=['np'])
    async def nowplaying(self, ctx):
        """Lagu yang sedang diputar"""
        player = self.get_player(ctx)
        
        if not player.current:
            return await ctx.send("❌ **Tidak ada musik!**")
        
        song = player.current
        embed = discord.Embed(
            title="🎵 Now Playing",
            description=f"**[{song.title}]({song.url})**",
            color=discord.Color.green()
        )
        embed.add_field(name="⏱️", value=song.format_duration(), inline=True)
        embed.add_field(name="🎤", value=song.channel, inline=True)
        
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)
        
        await ctx.send(embed=embed)

    @commands.command(name='loop', aliases=['lp'])
    async def loop(self, ctx):
        """Toggle loop"""
        player = self.get_player(ctx)
        player.loop = not player.loop
        player.loop_queue = False
        
        status = "ON 🔂" if player.loop else "OFF"
        await ctx.send(f"**Loop: {status}**")

    @commands.command(name='shuffle', aliases=['sh'])
    async def shuffle(self, ctx):
        """Acak queue"""
        import random
        player = self.get_player(ctx)
        
        if len(player.queue) < 2:
            return await ctx.send("❌ **Queue terlalu sedikit!**")
        
        queue_list = list(player.queue)
        random.shuffle(queue_list)
        player.queue = deque(queue_list)
        
        await ctx.send("🔀 **Queue diacak!**")

    @commands.command(name='clear', aliases=['cl'])
    async def clear(self, ctx):
        """Hapus queue"""
        player = self.get_player(ctx)
        player.queue.clear()
        await ctx.send("🗑️ **Queue dikosongkan!**")

    @commands.command(name='help', aliases=['h'])
    async def help(self, ctx):
        """Bantuan"""
        embed = discord.Embed(
            title="🎵 Music Bot Help",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="🎶 Music",
            value=(
                "`!play <url/judul>` - Putar musik\n"
                "`!pause` - Pause\n"
                "`!resume` - Resume\n"
                "`!skip` - Skip\n"
                "`!stop` - Stop & keluar"
            ),
            inline=True
        )
        
        embed.add_field(
            name="📝 Queue",
            value=(
                "`!queue` - Lihat antrian\n"
                "`!nowplaying` - Now playing\n"
                "`!shuffle` - Acak\n"
                "`!clear` - Hapus queue"
            ),
            inline=True
        )
        
        embed.add_field(
            name="🔧 Debug",
            value=(
                "`!debug <url>` - Test URL\n"
                "`!forceplay <url>` - Force play"
            ),
            inline=True
        )
        
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Music(bot))