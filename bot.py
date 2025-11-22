import discord
from discord.ext import commands
import json
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 1268438720227311661

DATA_FILE = "points.json"

# IDs ثابتة
THANKS_CHANNEL_ID = 1441500844875976865
LEADERBOARD_CHANNEL_ID = 1441532488097992736


# إنشاء ملف البيانات لو غير موجود
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w", encoding="utf8") as f:
        json.dump({}, f, ensure_ascii=False, indent=4)


def load_data():
    with open(DATA_FILE, "r", encoding="utf8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


intents = discord.Intents.all()
bot = commands.Bot(command_prefix=["+", "!"], intents=intents)


# تحويل 5k → 5000 ، 3m → 3000000
def parse_amount(txt):
    txt = txt.lower()
    if txt.endswith("k"):
        return int(float(txt[:-1]) * 1000)
    if txt.endswith("m"):
        return int(float(txt[:-1]) * 1_000_000)
    if txt.endswith("b"):
        return int(float(txt[:-1]) * 1_000_000_000)
    return int(txt)


# اختصار الأرقام
def format_number(num):
    if num >= 1_000_000_000:
        return f"{num/1_000_000_000:.1f}b"
    if num >= 1_000_000:
        return f"{num/1_000_000:.1f}m"
    if num >= 1_000:
        return f"{num/1_000:.1f}k"
    return str(num)


async def update_leaderboard(guild):
    data = load_data()

    channel = guild.get_channel(LEADERBOARD_CHANNEL_ID)

    # لو ما فيه رسالة قديمة، يسوي وحدة جديدة
    if "leaderboard_message_id" not in data:
        embed = discord.Embed(
            title="🤍 Top Supporters",
            description="No supporters yet.",
            color=discord.Color.from_rgb(255, 255, 255)
        )
        msg = await channel.send(embed=embed)
        data["leaderboard_message_id"] = msg.id
        save_data(data)
        return

    msg_id = data["leaderboard_message_id"]
    msg = await channel.fetch_message(msg_id)

    # ترتيب
    scores = {k: int(v) for k, v in data.items() if k.isdigit()}
    sorted_users = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    desc = ""
    rank = 1
    for uid, pts in sorted_users[:10]:
        desc += f"{rank}- <@{uid}> — {format_number(pts)}\n"
        rank += 1

    if desc == "":
        desc = "No supporters yet."

    embed = discord.Embed(
        title="🤍 Top Supporters",
        description=desc,
        color=discord.Color.from_rgb(255, 255, 255)
    )

    await msg.edit(embed=embed)


# رسالة شكر تلقائية
async def send_thanks(ctx, member, amount):
    channel = ctx.guild.get_channel(THANKS_CHANNEL_ID)

    embed = discord.Embed(
        description=(
            f"ノ **S__pecial__ t__hanks__ to {member.mention}** *!*! ♡\n"
            f"  ა　𓂃ㆍ for the generous s__upport__ of __``{format_number(amount)}``__\n"
            f"_ _ ~~---~~ Your contribution means a lot, t__ruly__ a__ppreciate__ it! `⏆`"
        ),
        color=discord.Color.from_rgb(255, 255, 255)
    )

    await channel.send(embed=embed)


# ────────────────
#    أوامر الأونر
# ────────────────

@bot.command()
async def give(ctx, member: discord.Member, amount):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ هذا الأمر للأونر فقط.")

    amount = parse_amount(amount)

    data = load_data()
    uid = str(member.id)

    data[uid] = data.get(uid, 0) + amount
    save_data(data)

    # رسالة شكر
    await send_thanks(ctx, member, amount)

    # تحديث لوحة المتصدرين
    await update_leaderboard(ctx.guild)

    await ctx.send(f"✔ تمت إضافة **{format_number(amount)}** إلى {member.mention}.")


@bot.command()
async def remove(ctx, member: discord.Member):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ هذا الأمر للأونر فقط.")

    data = load_data()
    uid = str(member.id)

    if uid in data:
        del data[uid]
        save_data(data)
        await update_leaderboard(ctx.guild)
        await ctx.send(f"✔ تمت إزالة {member.mention} من قائمة الداعمين.")
    else:
        await ctx.send("⚠ هذا الشخص غير موجود بالقائمة.")


@bot.command()
async def refresh(ctx):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ هذا الأمر للأونر فقط.")

    await update_leaderboard(ctx.guild)
    await ctx.send("🔄 تم تحديث لوحة المتصدرين بنجاح.")


bot.run(TOKEN)
