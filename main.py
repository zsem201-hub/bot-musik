import discord
from discord.ext import commands
import os
import asyncio
from keep_alive import keep_alive

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

# Bot Configuration
bot = commands.Bot(
    command_prefix=['!', '?', '.'],
    intents=intents,
    help_command=None
)

@bot.event
async def on_ready():
    print(f'╔══════════════════════════════════════╗')
    print(f'║  🎵 {bot.user.name} Online!          ')
    print(f'║  📡 Servers: {len(bot.guilds)}       ')
    print(f'║  🔗 Invite Bot ke Server kamu!       ')
    print(f'╚══════════════════════════════════════╝')
    
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening,
            name="!help | 🎶 Musik HD"
        )
    )

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ **Argumen tidak lengkap!** Cek `!help` untuk bantuan.")
    else:
        await ctx.send(f"❌ **Error:** {str(error)}")
        print(f"Error: {error}")

async def load_cogs():
    await bot.load_extension('music_cog')
    print("✅ Music Cog loaded!")

async def main():
    async with bot:
        await load_cogs()
        keep_alive()  # Keep bot alive di Replit
        await bot.start(os.environ['DISCORD_TOKEN'])

if __name__ == "__main__":
    asyncio.run(main())
