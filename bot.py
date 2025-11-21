import discord
from discord.ext import commands
from discord import ui
import sqlite3

# ---------- CONFIG ----------
TOKEN = os.getenv("TOKEN")
OWNER_ID = 1268438720227311661
LOG_CHANNEL_ID = None
# ----------------------------

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ========== DATABASE ==========
db = sqlite3.connect("currency.db")
cur = db.cursor()

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

db.commit()

# ---------- HELPERS ----------
def format_coin(n):
    return f"{n} 🪙 berrycoin" if n == 1 else f"{n} 🪙 berrycoins"

def get_balance(uid):
    cur.execute("SELECT balance FROM users WHERE id=?", (uid,))
    row = cur.fetchone()
    return row[0] if row else 0

def set_balance(uid, amount):
    cur.execute("INSERT OR REPLACE INTO users(id, balance) VALUES(?, ?)", (uid, amount))
    db.commit()

def add_balance(uid, amount):
    bal = get_balance(uid)
    set_balance(uid, bal + amount)

def is_blacklisted(uid):
    cur.execute("SELECT 1 FROM blacklist WHERE id=?", (uid,))
    return cur.fetchone() is not None


# ---------- INVITE SYSTEM ----------
guild_invites = {}

@bot.event
async def on_ready():
    print("Bot is ready.")
    for guild in bot.guilds:
        try:
            invites = await guild.invites()
            guild_invites[guild.id] = {i.code: i.uses for i in invites}
        except:
            guild_invites[guild.id] = {}


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

    # منع تكرار المكافأة
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
        add_balance(str(inviter.id), 1)

        # رسالة خاصة
        try:
            await inviter.send(
                f"🎉 شخص دخل من رابطك!\n"
                f"تم إضافة **1 🪙 berrycoins** إلى حسابك."
            )
        except:
            pass


# ---------- TRANSFER MODAL ----------
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
            if amount <= 0:
                raise ValueError
        except:
            return await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)

        if get_balance(str(self.author_id)) < amount:
            return await interaction.response.send_message("❌ Not enough balance.", ephemeral=True)

        # confirmation
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
                        f"🔁 Transfer Log:\n"
                        f"**From:** <@{self.author_id}>\n"
                        f"**To:** <@{target_id}>\n"
                        f"**Amount:** {format_coin(amount)}"
                    )

            await i.response.edit_message(
                content=f"✅ Sent {format_coin(amount)} to <@{target_id}>",
                view=None
            )

        async def cancel(i):
            await i.response.edit_message(content="❌ Cancelled.", view=None)

        b1 = ui.Button(label="Confirm", style=discord.ButtonStyle.success)
        b2 = ui.Button(label="Cancel", style=discord.ButtonStyle.danger)

        b1.callback = confirm
        b2.callback = cancel
        view.add_item(b1)
        view.add_item(b2)

        emb = discord.Embed(
            title="Confirm Transfer",
            description=f"Send {format_coin(amount)} to <@{target_id}>?",
            color=0xFFFF00
        )
        await interaction.response.send_message(embed=emb, view=view, ephemeral=True)


# ---------- MAIN PANEL ----------
class MainView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Balance", style=discord.ButtonStyle.secondary)
    async def bal(self, interaction, btn):
        bal = get_balance(str(interaction.user.id))
        await interaction.response.send_message(
            f"🪙 Your balance: **{format_coin(bal)}**",
            ephemeral=True
        )

    @ui.button(label="Transfer", style=discord.ButtonStyle.secondary)
    async def tr(self, interaction, btn):
        if is_blacklisted(str(interaction.user.id)):
            return await interaction.response.send_message("❌ You are blacklisted.", ephemeral=True)
        await interaction.response.send_modal(TransferModal(interaction.user.id))

    @ui.button(label="Top 10", style=discord.ButtonStyle.secondary)
    async def top(self, interaction, btn):
        cur.execute("SELECT id, balance FROM users ORDER BY balance DESC LIMIT 10")
        rows = cur.fetchall()

        desc = ""
        for i, (uid, bal) in enumerate(rows, start=1):
            desc += f"**{i}.** <@{uid}> — `{format_coin(bal)}`\n"

        emb = discord.Embed(
            title="🏆 Top 10",
            description=desc or "No data yet.",
            color=0xFFFFFF
        )
        await interaction.response.send_message(embed=emb, ephemeral=True)


# ---------- OWNER COMMANDS ----------
@bot.command()
async def postmsg(ctx):
    if ctx.author.id != OWNER_ID: return
    emb = discord.Embed(title="🪙 Berry Coin", description="Interact using buttons.", color=0xFFFFFF)
    await ctx.send(embed=emb, view=MainView())

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
    if ctx.author.id != OWNER_ID:
        return
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


# ---------- RUN ----------
bot.run(TOKEN)
