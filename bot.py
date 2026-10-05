import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from datetime import datetime

TOKEN = os.getenv("TOKEN")
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))
CATEGORY_TICKETS = int(os.getenv("CATEGORY_TICKETS"))
LEGIT_CHANNEL_ID = int(os.getenv("LEGIT_CHANNEL_ID"))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "produkty.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"produkty": {}}, f, indent=4, ensure_ascii=False)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

class LegitModal(discord.ui.Modal, title="Wystaw legitkę"):
    def __init__(self, produkt_id: str, buyer_id: int):
        super().__init__()
        self.produkt_id = produkt_id
        self.buyer_id = buyer_id

    legit_text = discord.ui.TextInput(
        label="Twoja legitka / opinia",
        placeholder="Np. Wszystko OK, konto działa, polecam!",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        data = load_data()
        produkt = data["produkty"].get(self.produkt_id, {"nazwa": "Nieznany produkt"})

        legit_channel = interaction.guild.get_channel(LEGIT_CHANNEL_ID)
        
        embed = discord.Embed(
            title="✅ Nowa Legitka",
            description=self.legit_text.value,
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        embed.add_field(name="Produkt", value=produkt["nazwa"], inline=True)
        embed.add_field(name="Kupujący", value=interaction.user.mention, inline=True)
        embed.set_footer(text=f"Ticket: {interaction.channel.name}")

        if legit_channel:
            await legit_channel.send(embed=embed)

        if self.produkt_id in data["produkty"]:
            data["produkty"][self.produkt_id]["stock"] = max(0, data["produkty"][self.produkt_id]["stock"] - 1)
            save_data(data)

        await interaction.response.send_message(
            "✅ Dziękujemy za legitkę! Ticket zostanie zamknięty za 8 sekund...",
            ephemeral=False
        )
        await interaction.channel.send("Legitka wystawiona. Zamykam ticket...")
        await interaction.channel.delete(delay=8)

class TicketView(discord.ui.View):
    def __init__(self, produkt_id: str, buyer_id: int):
        super().__init__(timeout=None)
        self.produkt_id = produkt_id
        self.buyer_id = buyer_id

    @discord.ui.button(label="Wystaw legitkę / Potwierdzam odbiór", style=discord.ButtonStyle.success, emoji="✅", custom_id="client_legit")
    async def client_legit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.buyer_id:
            return await interaction.response.send_message("Tylko kupujący może wystawić legitkę.", ephemeral=True)
        await interaction.response.send_modal(LegitModal(self.produkt_id, self.buyer_id))

    @discord.ui.button(label="Zamknij ticket (Admin)", style=discord.ButtonStyle.danger, custom_id="admin_close")
    async def admin_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any(r.id == ADMIN_ROLE_ID for r in interaction.user.roles):
            return await interaction.response.send_message("Tylko admin.", ephemeral=True)
        await interaction.response.send_message("Ticket zostanie usunięty za 5 sekund...")
        await interaction.channel.delete(delay=5)

class KupView(discord.ui.View):
    def __init__(self, produkt_id: str, nazwa: str, cena: float):
        super().__init__(timeout=120)
        self.produkt_id = produkt_id
        self.nazwa = nazwa
        self.cena = cena

    @discord.ui.button(label="Kup teraz", style=discord.ButtonStyle.success, emoji="🛒")
    async def kup(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()
        produkt = data["produkty"].get(self.produkt_id)

        if not produkt or produkt["stock"] <= 0:
            return await interaction.response.send_message("❌ Ten produkt jest już niedostępny.", ephemeral=True)

        guild = interaction.guild
        category = guild.get_channel(CATEGORY_TICKETS)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            guild.get_role(ADMIN_ROLE_ID): discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }

        channel = await guild.create_text_channel(
            name=f"zakup-{interaction.user.name}",
            category=category,
            overwrites=overwrites,
            topic=str(interaction.user.id)
        )

        embed = discord.Embed(
            title=f"🛒 Nowy zakup: {self.nazwa}",
            description=(
                f"**Kupujący:** {interaction.user.mention}\n"
                f"**Cena:** `{self.cena} zł`\n"
                f"**Stock:** {produkt['stock']}\n\n"
                f"Po otrzymaniu konta kliknij przycisk **Wystaw legitkę**."
            ),
            color=discord.Color.green(),
            timestamp=datetime.now()
        )

        await channel.send(
            content=f"{interaction.user.mention} | <@&{ADMIN_ROLE_ID}>",
            embed=embed,
            view=TicketView(self.produkt_id, interaction.user.id)
        )

        log = guild.get_channel(LOG_CHANNEL_ID)
        if log:
            await log.send(f"🛒 **Ticket:** {channel.mention} | {interaction.user.mention} → **{self.nazwa}**")

        await interaction.response.send_message(f"✅ Utworzono ticket: {channel.mention}", ephemeral=True)
        self.stop()

class SklepSelect(discord.ui.Select):
    def __init__(self):
        data = load_data()
        options = []
        for pid, p in data["produkty"].items():
            if p["stock"] > 0:
                options.append(discord.SelectOption(
                    label=f"{p['nazwa']} — {p['cena']} zł",
                    description=f"Stock: {p['stock']}",
                    value=pid,
                    emoji="🎮"
                ))
        if not options:
            options.append(discord.SelectOption(label="Brak dostępnych kont", value="empty"))

        super().__init__(
            placeholder="Wybierz konto z listy...",
            min_values=1,
            max_values=1,
            options=options[:25],
            custom_id="sklep_select"
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "empty":
            return await interaction.response.send_message("Aktualnie brak dostępnych kont.", ephemeral=True)

        data = load_data()
        produkt = data["produkty"][self.values[0]]

        embed = discord.Embed(
            title=produkt["nazwa"],
            description=f"**Cena:** `{produkt['cena']} zł`\n**Dostępne sztuki:** `{produkt['stock']}`",
            color=discord.Color.blurple()
        )
        if produkt.get("opis"):
            embed.add_field(name="Opis", value=produkt["opis"], inline=False)

        await interaction.response.send_message(
            embed=embed,
            view=KupView(self.values[0], produkt["nazwa"], produkt["cena"]),
            ephemeral=True
        )

class SklepView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(SklepSelect())

@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    bot.add_view(SklepView())
    try:
        synced = await bot.tree.sync()
        print(f"Zsynchronizowano {len(synced)} komend")
    except Exception as e:
        print(e)

@bot.tree.command(name="setup_sklep", description="Wystaw stałą wiadomość sklepu")
@app_commands.checks.has_role(ADMIN_ROLE_ID)
async def setup_sklep(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛒 Sklep z kontami",
        description="Wybierz konto z listy poniżej, a następnie kliknij **Kup**.\nPo zakupie powstanie prywatny ticket.",
        color=discord.Color.green()
    )
    await interaction.channel.send(embed=embed, view=SklepView())
    await interaction.response.send_message("✅ Sklep wystawiony!", ephemeral=True)

@bot.tree.command(name="dodaj", description="Dodaj produkt")
@app_commands.describe(nazwa="Nazwa", cena="Cena", stock="Ilość", opis="Opis (opcjonalny)")
@app_commands.checks.has_role(ADMIN_ROLE_ID)
async def dodaj(interaction: discord.Interaction, nazwa: str, cena: float, stock: int, opis: str = None):
    data = load_data()
    nowy_id = str(len(data["produkty"]) + 1)
    data["produkty"][nowy_id] = {
        "nazwa": nazwa,
        "cena": cena,
        "stock": stock,
        "opis": opis or ""
    }
    save_data(data)
    await interaction.response.send_message(f"✅ Dodano **{nazwa}** (ID: `{nowy_id}`)")

@bot.tree.command(name="stock", description="Zmień stock")
@app_commands.describe(produkt_id="ID", nowy_stock="Nowa ilość")
@app_commands.checks.has_role(ADMIN_ROLE_ID)
async def stock(interaction: discord.Interaction, produkt_id: str, nowy_stock: int):
    data = load_data()
    if produkt_id not in data["produkty"]:
        return await interaction.response.send_message("Nie ma takiego ID", ephemeral=True)
    data["produkty"][produkt_id]["stock"] = nowy_stock
    save_data(data)
    await interaction.response.send_message(f"✅ Stock **{data['produkty'][produkt_id]['nazwa']}** = {nowy_stock}")

@bot.tree.command(name="usun", description="Usuń produkt")
@app_commands.describe(produkt_id="ID")
@app_commands.checks.has_role(ADMIN_ROLE_ID)
async def usun(interaction: discord.Interaction, produkt_id: str):
    data = load_data()
    if produkt_id not in data["produkty"]:
        return await interaction.response.send_message("Nie ma takiego ID", ephemeral=True)
    nazwa = data["produkty"][produkt_id]["nazwa"]
    del data["produkty"][produkt_id]
    save_data(data)
    await interaction.response.send_message(f"🗑️ Usunięto **{nazwa}**")

@bot.tree.command(name="lista", description="Lista produktów")
@app_commands.checks.has_role(ADMIN_ROLE_ID)
async def lista(interaction: discord.Interaction):
    data = load_data()
    if not data["produkty"]:
        return await interaction.response.send_message("Brak produktów", ephemeral=True)
    text = ""
    for pid, p in data["produkty"].items():
        text += f"`{pid}` | **{p['nazwa']}** | {p['cena']} zł | Stock: {p['stock']}\n"
    embed = discord.Embed(title="Lista produktów", description=text, color=discord.Color.blue())
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="platnosci", description="Metody płatności")
async def platnosci(interaction: discord.Interaction):
    embed = discord.Embed(
        title="💳 Metody płatności",
        description=(
            "**Dostępne metody:**\n\n"
            "• **BLIK**\n"
            "• **Przelew**\n"
            "• **Crypto** (USDT / LTC)\n"
            "• **PayPal** (Friends & Family)\n\n"
            "Szczegóły dostaniesz w tickecie."
        ),
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@setup_sklep.error
@dodaj.error
@stock.error
@usun.error
@lista.error
async def admin_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingRole):
        await interaction.response.send_message("Nie masz uprawnień admina.", ephemeral=True)

bot.run(TOKEN)
