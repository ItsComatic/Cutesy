import os
import re
import datetime
import discord
import aiohttp
from discord.ext import commands
import random
import asyncio

TARGET_CHANNEL_ID = int(os.getenv("CLAN_INVITES_CHANNEL"))
CLAN_TAG = os.getenv("CLAN_TAG")
DISCORD_TOKEN = os.getenv("CUTESY_TOKEN")

BL_COOKIE = os.getenv("BL_COOKIE")

INVITE_URL = "https://api.beatleader.com/clan/invite"

ROLE_IDS = [
    1497994307616116947,
    1497994343045136535,
    1497994377295958037,
]

REMOVE_ROLE_ID = 1513823584013778964

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

_http_session: aiohttp.ClientSession | None = None


def _session() -> aiohttp.ClientSession:
    global _http_session
    if _http_session is None or _http_session.closed:
        _http_session = aiohttp.ClientSession()
    return _http_session


_owner: discord.User | None = None


async def _log(content: str) -> None:
    """DM the bot owner with a log message. Silently drops if owner is unknown."""
    if _owner is None:
        return
    try:
        await _owner.send(content)
    except (discord.Forbidden, discord.HTTPException):
        pass

@bot.tree.command(name="shuffle", description="Shuffles all division members.")
async def ping(interaction: discord.Interaction):
    if interaction.user.id == 1412589790649647216:
        await interaction.response.defer(ephemeral=True)

        ROLE_1_ID = 1497994307616116947
        ROLE_2_ID = 1497994343045136535
        ROLE_3_ID = 1497994377295958037

        guild = interaction.guild
        role1 = guild.get_role(ROLE_1_ID)
        role2 = guild.get_role(ROLE_2_ID)
        role3 = guild.get_role(ROLE_3_ID)

        if not role1 or not role2 or not role3:
            await interaction.followup.send("One or more role IDs could not be found.", ephemeral=True)
            return

        all_members = list(set(role1.members + role2.members + role3.members))
        
        if all_members:
            size1 = len(role1.members)
            size2 = len(role2.members)

            shuffled_members = all_members.copy()
            random.shuffle(shuffled_members)

            new_role1_members = shuffled_members[:size1]
            new_role2_members = shuffled_members[size1:size1 + size2]
            new_role3_members = shuffled_members[size1 + size2:]

            assignments = {
                role1: new_role1_members,
                role2: new_role2_members,
                role3: new_role3_members
            }

            try:
                for member in all_members:
                    roles_to_have = []
                    for role, members_list in assignments.items():
                        if member in members_list:
                            roles_to_have.append(role)

                    current_roles = [r for r in member.roles if r not in (role1, role2, role3)]
                    updated_roles = current_roles + roles_to_have

                    await member.edit(roles=updated_roles, reason="Division shuffle executed.")
                
                await interaction.followup.send("Roles successfully shuffled!", ephemeral=True)
            except discord.Forbidden:
                await interaction.followup.send("Bot lacks permissions to modify these roles.", ephemeral=True)
            except discord.HTTPException as e:
                await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)
        else:
            await interaction.followup.send("No members found in those roles to shuffle.", ephemeral=True)
            return
    else:
        await interaction.followup.send("You aren't my owner silly!")


@bot.tree.command(name="start-poll", description="Starts a division poll for D1, D2, or D3.")
@discord.app_commands.describe(division="Choose which division to poll (d1, d2, or d3)")
@discord.app_commands.choices(division=[
    discord.app_commands.Choice(name="D1", value="d1"),
    discord.app_commands.Choice(name="D2", value="d2"),
    discord.app_commands.Choice(name="D3", value="d3"),
])
async def start_poll(interaction: discord.Interaction, division: str):
    if interaction.user.id != 1412589790649647216:
        await interaction.response.send_message("You aren't my owner silly!", ephemeral=True)
        return

    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    division_mapping = {
        "d1": {"role_id": ROLE_IDS[0], "channel_id": 1515577775606464694, "winner_role_id": 1497994471122403369},
        "d2": {"role_id": ROLE_IDS[1], "channel_id": 1515575749615157288, "winner_role_id": 1498000327755038892},
        "d3": {"role_id": ROLE_IDS[2], "channel_id": 1515575523651092581, "winner_role_id": 1498000473746182144}
    }
    
    config = division_mapping.get(division)
    role = interaction.guild.get_role(config["role_id"])
    channel = interaction.guild.get_channel(config["channel_id"])
    winner_role = interaction.guild.get_role(config["winner_role_id"])

    if not role or not channel or not winner_role:
        await interaction.response.send_message("Error: Could not find the required roles or channels.", ephemeral=True)
        return

    members = [m for m in role.members if not m.bot]

    if not members:
        await interaction.response.send_message(f"No members found with the {division.upper()} role.", ephemeral=True)
        return
        
    if len(members) > 25:
        await interaction.response.send_message("Discord limits buttons to 25 max per message. Too many people in this role.", ephemeral=True)
        return

    end_time_unix = int(datetime.datetime.now(datetime.timezone.utc).timestamp()) + 86400

    class DynamicPollView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)
            self.votes = {}
            self.tally = {m.id: 0 for m in members}
            self.members_map = {m.id: m for m in members}

            for member in members:
                btn = discord.ui.Button(
                    label=member.display_name, 
                    custom_id=f"vote_{division}_{member.id}", 
                    style=discord.ButtonStyle.primary
                )
                btn.callback = self.create_callback(member)
                self.add_item(btn)

        def create_callback(self, candidate):
            async def callback(btn_interaction: discord.Interaction):
                voter = btn_interaction.user

                if voter.id == candidate.id:
                    await btn_interaction.response.send_message("You cannot vote for yourself!", ephemeral=True)
                    return

                if voter.id in self.votes:
                    await btn_interaction.response.send_message("You have already voted in this poll!", ephemeral=True)
                    return

                self.votes[voter.id] = candidate.id
                self.tally[candidate.id] += 1

                await btn_interaction.response.edit_message(embed=self.build_embed())
            return callback

        def build_embed(self, is_closed=False, status_text=""):
            title_prefix = "🛑" if is_closed else "🏆"
            title_suffix = " - Closed" if is_closed else ""
            color = discord.Color.red() if is_closed else discord.Color.green()
            
            embed = discord.Embed(title=f"{title_prefix} {division.upper()} Division Poll{title_suffix}", color=color)
            
            if is_closed:
                desc = f"**Results Are Finalized!**\n{status_text}\n\n"
            else:
                desc = f"Vote for a member below!\n*Note: You cannot vote for yourself and can only vote once.*\n"
                desc += f"⏳ **Ends:** <t:{end_time_unix}:R> (In 24 hours)\n\n"
                
            for m_id, count in self.tally.items():
                desc += f"**{self.members_map[m_id].display_name}**: {count} votes\n"
            embed.description = desc
            return embed

    await interaction.response.send_message(f"Poll successfully sent to {channel.mention}!", ephemeral=True)

    view = DynamicPollView()
    poll_message = await channel.send(embed=view.build_embed(), view=view)

    async def automated_poll_countdown():
        await asyncio.sleep(86400)

        fresh_winner_role = interaction.guild.get_role(config["winner_role_id"])
        
        max_votes = max(view.tally.values())
        
        if max_votes == 0:
            for item in view.children:
                item.disabled = True
            closed_embed = view.build_embed(is_closed=True, status_text="**Poll closed with no votes cast. No roles were adjusted.**")
            await poll_message.edit(embed=closed_embed, view=view)
            return

        winners = [m_id for m_id, count in view.tally.items() if count == max_votes]

        if fresh_winner_role:
            for old_member in fresh_winner_role.members:
                try:
                    await old_member.remove_roles(fresh_winner_role, reason="24hr Poll automation cleanup.")
                except discord.HTTPException:
                    pass

        winner_text = ""
        if len(winners) > 1:
            winner_text = "It's a tie between: " + ", ".join([view.members_map[w_id].mention for w_id in winners]) + "\n"
            for w_id in winners:
                try:
                    await view.members_map[w_id].add_roles(fresh_winner_role, reason="24hr Poll automated tie-victory.")
                except discord.HTTPException:
                    pass
            winner_text += f"All tied members have been given the {fresh_winner_role.mention} role!"
        else:
            final_winner = view.members_map[winners[0]]
            try:
                await final_winner.add_roles(fresh_winner_role, reason="24hr Poll automated clean-victory.")
            except discord.HTTPException:
                pass
            winner_text = f"🏆 **Winner:** {final_winner.mention} has been awarded the {fresh_winner_role.mention} role!"

        for item in view.children:
            item.disabled = True

        closed_embed = view.build_embed(is_closed=True, status_text=winner_text)
        await poll_message.edit(embed=closed_embed, view=view)

    asyncio.create_task(automated_poll_countdown())


@bot.tree.command(name="start-council-poll", description="Starts a 24-hour server vote for a new council member.")
async def start_council_poll(interaction: discord.Interaction):
    if interaction.user.id != 1412589790649647216:
        await interaction.response.send_message("You aren't my owner silly!", ephemeral=True)
        return

    if not interaction.guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    COUNCIL_ROLE_ID = 1497994078766370896
    POLL_CHANNEL_ID = 1497984652709855314

    council_role = interaction.guild.get_role(COUNCIL_ROLE_ID)
    channel = interaction.guild.get_channel(POLL_CHANNEL_ID)

    if not council_role or not channel:
        await interaction.response.send_message("Error: Could not find the Council role or target voting channel.", ephemeral=True)
        return

    candidates = [
        m for m in interaction.guild.members 
        if not m.bot and m.id != 1412589790649647216 and council_role not in m.roles
    ]

    if not candidates:
        await interaction.response.send_message("No eligible candidates found to vote for.", ephemeral=True)
        return
        
    if len(candidates) > 25:
        await interaction.response.send_message(f"Discord limits buttons to 25 max per message. There are currently {len(candidates)} candidates, which exceeds the limit.", ephemeral=True)
        return

    end_time_unix = int(datetime.datetime.now(datetime.timezone.utc).timestamp()) + 86400

    class CouncilPollView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)
            self.votes = {}
            self.tally = {m.id: 0 for m in candidates}
            self.members_map = {m.id: m for m in candidates}

            for member in candidates:
                btn = discord.ui.Button(
                    label=member.display_name, 
                    custom_id=f"council_vote_{member.id}", 
                    style=discord.ButtonStyle.primary
                )
                btn.callback = self.create_callback(member)
                self.add_item(btn)

        def create_callback(self, candidate):
            async def callback(btn_interaction: discord.Interaction):
                voter = btn_interaction.user

                if voter.id == candidate.id:
                    await btn_interaction.response.send_message("You cannot vote for yourself!", ephemeral=True)
                    return

                if voter.id in self.votes:
                    await btn_interaction.response.send_message("You have already voted in this poll!", ephemeral=True)
                    return

                self.votes[voter.id] = candidate.id
                self.tally[candidate.id] += 1

                await btn_interaction.response.edit_message(embed=self.build_embed())
            return callback

        def build_embed(self, is_closed=False, status_text=""):
            title_prefix = "🛑" if is_closed else "🗳️"
            title_suffix = " - Closed" if is_closed else ""
            color = discord.Color.red() if is_closed else discord.Color.blue()
            
            embed = discord.Embed(title=f"{title_prefix} Council Election Poll{title_suffix}", color=color)
            
            if is_closed:
                desc = f"**Results Are Finalized!**\n{status_text}\n\n"
            else:
                desc = f"Vote for a new Council member below!\n*Note: You cannot vote for yourself and can only vote once.*\n"
                desc += f"⏳ **Ends:** <t:{end_time_unix}:R> (In 24 hours)\n\n"
                
            for m_id, count in self.tally.items():
                desc += f"**{self.members_map[m_id].display_name}**: {count} votes\n"
            embed.description = desc
            return embed

    await interaction.response.send_message(f"Council election poll successfully sent to {channel.mention}!", ephemeral=True)

    view = CouncilPollView()
    poll_message = await channel.send(embed=view.build_embed(), view=view)

    async def automated_council_countdown():
        await asyncio.sleep(86400)

        fresh_council_role = interaction.guild.get_role(COUNCIL_ROLE_ID)
        max_votes = max(view.tally.values())
        
        if max_votes == 0:
            for item in view.children:
                item.disabled = True
            closed_embed = view.build_embed(is_closed=True, status_text="**Poll closed with no votes cast. No roles were adjusted.**")
            await poll_message.edit(embed=closed_embed, view=view)
            return

        winners = [m_id for m_id, count in view.tally.items() if count == max_votes]
        winner_text = ""

        if len(winners) > 1:
            winner_text = "It's a tie between: " + ", ".join([view.members_map[w_id].mention for w_id in winners]) + "\n"
            for w_id in winners:
                try:
                    await view.members_map[w_id].add_roles(fresh_council_role, reason="24hr Council Poll automated tie-victory.")
                except discord.HTTPException:
                    pass
            winner_text += f"All tied members have been given the {fresh_council_role.mention} role!"
        else:
            final_winner = view.members_map[winners[0]]
            try:
                await final_winner.add_roles(fresh_council_role, reason="24hr Council Poll automated clean-victory.")
            except discord.HTTPException:
                pass
            winner_text = f"🏆 **Winner:** {final_winner.mention} has been added to the {fresh_council_role.mention} role!"

        for item in view.children:
            item.disabled = True

        closed_embed = view.build_embed(is_closed=True, status_text=winner_text)
        await poll_message.edit(embed=closed_embed, view=view)

    asyncio.create_task(automated_council_countdown())


@bot.event
async def on_ready():
    global _owner
    app_info = await bot.application_info()
    _owner = app_info.owner
    print(f"Logged in as {bot.user} | Logging failures to: {_owner}")

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s) successfully!")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    print("Caching guild members to prevent websocket lag...")
    for guild in bot.guilds:
        try:
            await guild.chunk()
        except Exception as e:
            print(f"Failed to chunk guild {guild.id}: {e}")
    print("Guild members fully cached and ready!")


@bot.event
async def on_message(message):
    if message.author.bot:
        await bot.process_commands(message)
        return

    if message.channel.id != TARGET_CHANNEL_ID:
        await bot.process_commands(message)
        return

    match = re.search(r"beatleader\.(?:xyz|com)/u/(\d+)", message.content)
    if not match:
        await bot.process_commands(message)
        return

    player_id = match.group(1)

    try:
        await message.delete()
    except (discord.Forbidden, discord.HTTPException):
        pass

    async def dm(content: str) -> None:
        try:
            await message.author.send(content)
        except (discord.Forbidden, discord.HTTPException):
            pass

    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    ctx = (
        f"**Time:** {ts}\n"
        f"**User:** {message.author} (`{message.author.id}`)\n"
        f"**Player ID:** `{player_id}`\n"
        f"**Guild:** {message.guild} | **Channel:** {message.channel.name}"
    )

    headers = {"Cookie": f".AspNetCore.Cookies={BL_COOKIE}"}
    params = {"player": player_id}

    try:
        async with _session().post(
            INVITE_URL,
            params=params,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            status = resp.status
    except aiohttp.ClientError as e:
        await dm("❌ Could not reach the BeatLeader API. Please try again later.")
        await _log(f"🔴 **API network error**\n{ctx}\n**Error:** `{e}`")
        await bot.process_commands(message)
        return

    if status != 200:
        await dm(
            f"❌ Failed to invite you to the clan. BeatLeader returned HTTP {status}."
        )
        await _log(f"🔴 **Invite failed (HTTP {status})**\n{ctx}")
        await bot.process_commands(message)
        return

    await dm("✅ Successfully invited you to the clan!")

    roles = [r for rid in ROLE_IDS if (r := message.guild.get_role(rid)) is not None]
    if not roles:
        await dm(
            "⚠️ Could not find any of the configured roles. Please contact an admin."
        )
        await _log(
            f"🟡 **Role assign failed — no roles found**\n{ctx}\n**Checked IDs:** `{ROLE_IDS}`"
        )
    else:
        role = min(roles, key=lambda r: len(r.members))
        try:
            await message.author.add_roles(role, reason="BeatLeader profile linked")
        except discord.Forbidden:
            await dm(
                "⚠️ The bot doesn't have permission to assign roles. Please contact an admin."
            )
            await _log(
                f"🟡 **Role assign failed — Forbidden**\n{ctx}\n**Role:** {role.name} (`{role.id}`)"
            )
        except discord.HTTPException as e:
            await dm(f"⚠️ Failed to assign your role: {e}")
            await _log(
                f"🟡 **Role assign failed — HTTPException**\n{ctx}\n**Role:** {role.name} (`{role.id}`)\n**Error:** `{e}`"
            )

    remove_role = message.guild.get_role(REMOVE_ROLE_ID)
    if remove_role is not None and remove_role in message.author.roles:
        try:
            await message.author.remove_roles(
                remove_role, reason="BeatLeader profile linked"
            )
        except discord.Forbidden:
            await dm(
                "⚠️ The bot doesn't have permission to remove roles. Please contact an admin."
            )
            await _log(
                f"🟡 **Role remove failed — Forbidden**\n{ctx}\n**Role:** {remove_role.name} (`{remove_role.id}`)"
            )
        except discord.HTTPException as e:
            await dm(f"⚠️ Failed to remove your old role: {e}")
            await _log(
                f"🟡 **Role remove failed — HTTPException**\n{ctx}\n**Role:** {remove_role.name} (`{remove_role.id}\n**Error:** `{e}`"
            )

    await bot.process_commands(message)


@bot.event
async def on_close():
    if _http_session and not _http_session.closed:
        await _http_session.close()


bot.run(DISCORD_TOKEN)