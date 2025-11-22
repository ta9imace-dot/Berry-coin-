import os
import discord
from discord.ext import commands
from discord import ui
import sqlite3
import asyncio

# ---------- CONFIG ----------
TOKEN = os.getenv("TOKEN")
OWNER_ID = 1268438720227311661
LOG_CHANNEL_ID = None  # لو بتحب تحط روم للوغ غير اللي في الكود
# ----------------------------

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ========== DATABASE ==========
DB_PATH = "currency.db"
db = sqlite3.connect(DB_PATH)
cur = db.cursor()

# existing tables
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    balance INTEGER DEFAULT 0
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS blacklist (
    id TEXT PRIMARY KEY
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS used_invites (
    user_id TEXT PRIMARY KEY
)
""")

# meta table to store panel message ids / page etc.
cur.execute("""
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

db.commit()

# ---------- META HELPERS ----------
def meta_set(key: str, value: str):
    cur.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(value)))
    db.commit()

def meta_get(key: str, default=None):
    cur.execute("SELECT value FROM meta WHERE key=?", (key,))
    r = cur.fetchone()
    return r[0] if r else default

# keys we'll use:
PANEL_CHANNEL_KEY = "panel_channel"
PANEL_MESSAGE_KEY = "panel_message"
PANEL_PAGE_KEY = "panel_page"

def get_panel_info():
    ch = meta_get(PANEL_CHANNEL_KEY)
    mid = meta_get(PANEL_MESSAGE_KEY)
    page = meta_get(PANEL_PAGE_KEY, "0")
    try:
        page = int(page)
    except:
        page = 0
    return (int(ch) if ch else None, int(mid) if mid else None, page)

def set_panel_message(channel_id: int, message_id: int):
    meta_set(PANEL_CHANNEL_KEY, str(channel_id))
    meta_set(PANEL_MESSAGE_KEY, str(message_id))
    meta_set(PANEL_PAGE_KEY, "0")

def set_panel_page(page: int):
    meta_set(PANEL_PAGE_KEY, str(page))

# ---------- HELPERS ----------
def format_coin(n):
    return f"{n} 🪙 berrycoin" if n == 1 else f"{n} 🪙 berrycoins"

def parse_number(s: str) -> int:
    s = s.strip().lower().replace(",", "")
    if s.endswith("k"):
        return int(float(s[:-1]) * 1_000)
    if s.endswith("m"):
        return int(float(s[:-1]) * 1_000_000)
    if s.endswith("b"):
        return int(float(s[:-1]) * 1_000_000_000)
    return int(float(s))

def nice_format(n: int) -> str:
    if n >= 1_000_000_000:
        v = n / 1_000_000_000
        if v.is_integer(): v = int(v)
        return f"{v}b"
    if n >= 1_000_000:
        v = n / 1_000_000
        if v.is_integer(): v = int(v)
        return f"{v}m"
    if n >= 1_000:
        v = n / 1_000
        if v.is_integer(): v = int(v)
        return f"{v}k"
    return str(n)

def get_top(limit=10, offset=0):
    cur.execute("SELECT id, balance FROM users ORDER BY balance DESC LIMIT ? OFFSET ?", (limit, offset))
    return cur.fetchall()

def set_value(uid: str, amount: int):
    cur.execute("INSERT OR REPLACE INTO users(id, balance) VALUES (?, ?)", (uid, amount))
    db.commit()

def add_value(uid: str, delta: int):
    cur.execute("SELECT balance FROM users WHERE id=?", (uid,))
    r = cur.fetchone()
    new = (r[0] if r else 0) + delta
    set_value(uid, new)
    return new

# ---------- PANEL EMBED + VIEW ----------
class PanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, custom_id="panel_prev")
    async def prev(self, interaction: discord.Interaction, button: ui.Button):
        ch_id, msg_id, page = get_panel_info()
        if page <= 0:
            await interaction.response.defer()
            return
        page -= 1
        set_panel_page(page)
        await update_panel_embed(interaction.guild, page)
        await interaction.response.defer()

    @ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, custom_id="panel_next")
    async def nxt(self, interaction: discord.Interaction, button: ui.Button):
        ch_id, msg_id, page = get_panel_info()
        offset = (page + 1) * 10
        row = get_top(limit=1, offset=offset)
        if not row:
            await interaction.response.defer()
            return
        page += 1
        set_panel_page(page)
        await update_panel_embed(interaction.guild, page)
        await interaction.response.defer()

def build_panel_embed(page=0):
    offset = page * 10
    rows = get_top(limit=10, offset=offset)
    title = "🪙 Berry Coin — Leaderboard"
    if rows:
        desc_lines = []
        rank = offset + 1
        for uid, bal in rows:
            desc_lines.append(f"**{rank}.** <@{uid}> — `{nice_format(bal)}`")
            rank += 1
        desc = "\n".join(desc_lines)
    else:
        desc = "_No entries yet._"
    emb = discord.Embed(title=title, description=desc, color=0xFFFFFF)  # white color
    emb.set_footer(text=f"Page {page+1}")
    return emb

async def update_panel_embed(guild: discord.Guild, page=0):
    ch_id, msg_id, _ = get_panel_info()
    if not ch_id or not msg_id:
        return
    ch = guild.get_channel(ch_id)
    if not ch:
        return
    try:
        msg = await ch.fetch_message(msg_id)
    except:
        return
    emb = build_panel_embed(page)
    view = PanelView()
    try:
        await msg.edit(embed=emb, view=view)
    except Exception as e:
        print("Failed to edit panel message:", e)

# ---------- EVENTS: invite tracking ----------
guild_invites = {}

@bot.event
async def on_ready():
    print(f"Bot ready: {bot.user} ({bot.user.id})")

    # register persistent view so old message buttons keep working
    bot.add_view(PanelView())

    # load invites cache
    for guild in bot.guilds:
        try:
            invs = await guild.invites()
            guild_invites[guild.id] = {i.code: i.uses for i in invs}
        except:
            guild_invites[guild.id] = {}

    # try to restore panel embed (edit to current data) if saved
    ch_id, msg_id, page = get_panel_info()
    if ch_id and msg_id:
        # find guild that contains the channel id
        for g in bot.guilds:
            ch = g.get_channel(ch_id)
            if ch:
                try:
                    await update_panel_embed(g, page)
                except Exception as e:
                    print("Error restoring panel:", e)
                break

@bot.event
async def on_member_join(member):
    guild = member.guild
    before = guild_invites.get(guild.id, {})
    invites_now = await guild.invites()
    after = {i.code: i.uses for i in invites_now}

    used_code = None
    for code, uses in after.items():
        if code in before and uses > before[code]:
            used_code = code
            break

    guild_invites[guild.id] = after

    if not used_code:
        return

    cur.execute("SELECT 1 FROM used_invites WHERE user_id=?", (str(member.id),))
    if cur.fetchone():
        return

    cur.execute("INSERT INTO used_invites(user_id) VALUES(?)", (str(member.id),))
    db.commit()

    inviter = None
    for inv in invites_now:
        if inv.code == used_code:
            inviter = inv.inviter
            break

    if inviter:
        add_value(str(inviter.id), 1)
        try:
            await inviter.send(
                f"🎉 شخص دخل من رابطك!\n"
                f"تم إضافة **1 🪙 berrycoins** إلى حسابك."
            )
        except:
            pass

# ---------- TRANSFER MODAL (unchanged) ----------
class TransferModal(ui.Modal, title="Transfer"):
    userid = ui.TextInput(label="User ID Only", placeholder="123456789012345678")
    amount = ui.TextInput(label="Amount", placeholder="Number only", max_length=10)
    def __init__(self, author_id):
        super().__init__()
        self.author_id = author_id

    async def on_submit(self, interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ Not allowed.", ephemeral=True)
        if is_blacklisted(str(self.author_id)):
            return await interaction.response.send_message("❌ You are blacklisted from transferring.", ephemeral=True)
        if not self.userid.value.isdigit():
            return await interaction.response.send_message("❌ Invalid ID.", ephemeral=True)
        target_id = int(self.userid.value)
        try:
            member = await interaction.guild.fetch_member(target_id)
        except:
            return await interaction.response.send_message("❌ User not found in server.", ephemeral=True)
        try:
            amount = int(self.amount.value)
            if amount <= 0: raise ValueError
        except:
            return await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
        if get_balance(str(self.author_id)) < amount:
            return await interaction.response.send_message("❌ Not enough balance.", ephemeral=True)

        view = ui.View()

        async def confirm(i):
            if i.user.id != self.author_id:
                return await i.response.send_message("❌ Not allowed.", ephemeral=True)
            add_balance(str(target_id), amount)
            add_balance(str(self.author_id), -amount)
            if LOG_CHANNEL_ID:
                ch = interaction.guild.get_channel(LOG_CHANNEL_ID)
                if ch:
                    await ch.send(
                        f"🔁 Transfer Log:\n**From:** <@{self.author_id}>\n**To:** <@{target_id}>\n**Amount:** {format_coin(amount)}"
                    )
            await i.response.edit_message(content=f"✅ Sent {format_coin(amount)} to <@{target_id}>", view=None)

        async def cancel(i):
            await i.response.edit_message(content="❌ Cancelled.", view=None)

        b1 = ui.Button(label="Confirm", style=discord.ButtonStyle.success)
        b2 = ui.Button(label="Cancel", style=discord.ButtonStyle.danger)
        b1.callback = confirm
        b2.callback = cancel
        view.add_item(b1)
        view.add_item(b2)

        emb = discord.Embed(title="Confirm Transfer", description=f"Send {format_coin(amount)} to <@{target_id}>?", color=0xFFFF00)
        await interaction.response.send_message(embed=emb, view=view, ephemeral=True)

# ---------- MAIN PANEL ----------
class MainView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Balance", style=discord.ButtonStyle.secondary)
    async def bal(self, interaction, btn):
        bal = get_balance(str(interaction.user.id))
        await interaction.response.send_message(f"🪙 Your balance: **{format_coin(bal)}**", ephemeral=True)

    @ui.button(label="Transfer", style=discord.ButtonStyle.secondary)
    async def tr(self, interaction, btn):
        if is_blacklisted(str(interaction.user.id)):
            return await interaction.response.send_message("❌ You are blacklisted.", ephemeral=True)
        await interaction.response.send_modal(TransferModal(interaction.user.id))

    @ui.button(label="Top 10", style=discord.ButtonStyle.secondary)
    async def top(self, interaction, btn):
        ch_id, msg_id, page = get_panel_info()
        if not (ch_id and msg_id):
            # no panel posted yet
            await interaction.response.send_message("Panel is not posted yet. Owner can use !postmsg to post it.", ephemeral=True)
            return
        await update_panel_embed(interaction.guild, page)
        await interaction.response.send_message("Panel updated.", ephemeral=True)

# ---------- OWNER COMMANDS ----------
@bot.command()
async def postmsg(ctx):
    """Owner posts the persistent embed panel (once). Keep this message — do not re-post."""
    if ctx.author.id != OWNER_ID:
        return
    emb = build_panel_embed(page=0)
    view = PanelView()
    m = await ctx.send(embed=emb, view=view)
    set_panel_message(ctx.channel.id, m.id)
    await ctx.send("Panel posted and saved. (Keep this message; buttons will persist after restarts)")

@bot.command()
async def blacklist(ctx, member: discord.Member):
    if ctx.author.id != OWNER_ID: return
    cur.execute("INSERT OR IGNORE INTO blacklist(id) VALUES(?)", (str(member.id),))
    db.commit()
    await ctx.send("✅ Blacklisted.")

@bot.command()
async def unblacklist(ctx, member: discord.Member):
    if ctx.author.id != OWNER_ID: return
    cur.execute("DELETE FROM blacklist WHERE id=?", (str(member.id),))
    db.commit()
    await ctx.send("✅ Removed from blacklist.")

@bot.command()
async def give(ctx, member: discord.Member, amount: int):
    if ctx.author.id != OWNER_ID: return
    add_balance(str(member.id), amount)
    await ctx.send(f"Added {format_coin(amount)} to {member.mention}")

@bot.command()
async def remove(ctx, member: discord.Member, amount: int):
    if ctx.author.id != OWNER_ID: return
    bal = get_balance(str(member.id))
    new_bal = max(0, bal - amount)
    set_balance(str(member.id), new_bal)
    await ctx.send(f"🟥 Removed {amount} from {member.mention}")

@bot.command()
async def refresh(ctx):
    if ctx.author.id != OWNER_ID: return
    removed = 0
    cur.execute("SELECT id FROM users")
    rows = cur.fetchall()
    for (uid,) in rows:
        try:
            await ctx.guild.fetch_member(int(uid))
        except:
            cur.execute("DELETE FROM users WHERE id=?", (uid,))
            removed += 1
    db.commit()
    await ctx.send(f"🔄 Refresh complete. Removed **{removed}** invalid entries.")

@bot.command()
async def setlog(ctx, channel: discord.TextChannel):
    global LOG_CHANNEL_ID
    if ctx.author.id != OWNER_ID: return
    LOG_CHANNEL_ID = channel.id
    await ctx.send(f"✅ Log channel set to {channel.mention}")

# ---------- MESSAGE HANDLER for owner quick commands (+a / +e) ----------
async def handle_owner_quick(message: discord.Message):
    # only allow owner
    if message.author.id != OWNER_ID:
        return
    content = message.content.strip()
    if not (content.startswith("+a ") or content.startswith("+e ")):
        return
    parts = content.split()
    if len(parts) < 3:
        await message.channel.send("Usage: `+a @user <num>` or `+e @user <num>`")
        return
    cmd = parts[0].lower()
    raw = parts[1]
    # parse mention or id
    if raw.startswith("<@") and raw.endswith(">"):
        uid = raw.replace("<@", "").replace("!", "").replace(">", "")
    elif raw.isdigit():
        uid = raw
    else:
        await message.channel.send("Invalid user mention or ID.")
        return
    num_str = parts[2]
    try:
        amount = parse_number(num_str)
    except:
        await message.channel.send("Invalid number format (1k/5m/2b or plain).")
        return

    if cmd == "+a":
        set_value(str(uid), amount)
        new = amount
    else:
        new = add_value(str(uid), amount)

    # compute new page for that user and update panel
    ch_id, msg_id, page = get_panel_info()
    if ch_id and msg_id:
        # find rank index
        cur.execute("SELECT id FROM users ORDER BY balance DESC")
        rows = cur.fetchall()
        index = None
        for i, r in enumerate(rows):
            if str(r[0]) == str(uid):
                index = i
                break
        new_page = 0 if index is None else (index // 10)
        set_panel_page(new_page)
        # update embed
        for g in bot.guilds:
            ch = g.get_channel(ch_id)
            if ch:
                await update_panel_embed(g, new_page)
                break

    # send special thanks embed to LOG_CHANNEL_ID (white color)
    try:
        log_ch = bot.get_channel(LOG_CHANNEL_ID) if LOG_CHANNEL_ID else None
        if log_ch:
            embed = discord.Embed(
                title="Special Thanks 💛",
                description=(
                    f"**S__pecial__ t__hanks__ to <@{message.author.id}>** *!*! ♡*\n\n"
                    f"𓂃⠀for the generous s__upport__ of __`{nice_format(amount)}`__\n\n"
                    "~~---~~\nYour contribution means a lot — t__ruly__ a__ppreciate__ it! `⏆`"
                ),
                color=0xFFFFFF
            )
            embed.set_thumbnail(url=message.author.display_avatar.url)
            await log_ch.send(embed=embed)
    except Exception as e:
        print("Failed to send special thanks:", e)

    await message.channel.send(f"✅ Updated <@{uid}> → `{nice_format(new)}`")

# ---------- on_message ----------
@bot.event
async def on_message(message):
    # process normal commands
    await bot.process_commands(message)
    # skip bots
    if message.author.bot:
        return
    # owner quick commands
    await handle_owner_quick(message)

# ---------- AUTO-RESTART RUN ----------
async def start_bot_loop():
    while True:
        try:
            print("Starting bot...")
            await bot.start(TOKEN)
        except Exception as e:
            print("Bot crashed, restarting in 3s:", e)
            await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(start_bot_loop())
    
