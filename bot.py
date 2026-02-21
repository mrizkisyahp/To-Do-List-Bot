import discord
from discord.ext import commands
import json
import os
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from llm_handler import extract_tasks_from_text, get_priority_label
from storage import load_tasks, save_tasks, add_tasks, delete_task, update_task, get_all_tasks

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# State management
pending_deletes = {}   # user_id: {task_id, task_name, step}
pending_edits = {}     # user_id: {task_id, task_name, step, field}
REMINDER_CHANNEL_ID = int(os.environ.get("REMINDER_CHANNEL_ID", 0))


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]

def format_deadline(deadline_str: str) -> str:
    """Ubah '2026-02-23 23:59' jadi 'Senin, 23 Feb 2026 23:59'"""
    if not deadline_str or deadline_str == "—":
        return "—"
    try:
        try:
            dt = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M")
            jam = f" {dt.strftime('%H:%M')}"
        except ValueError:
            dt = datetime.strptime(deadline_str, "%Y-%m-%d")
            jam = ""
        hari = HARI[dt.weekday()]
        bulan = BULAN[dt.month - 1]
        return f"{hari}, {dt.day} {bulan} {dt.year}{jam}"
    except Exception:
        return deadline_str


def render_links(task_links: list) -> list:
    parts = []
    for lnk in task_links:
        if isinstance(lnk, dict):
            parts.append(f"[{lnk.get('label', 'Link')}]({lnk.get('url', '')})")
        else:
            parts.append(f"[Link]({lnk})")
    return parts


def format_task_embed(tasks: list) -> discord.Embed:
    if not tasks:
        return discord.Embed(
            title="📭 Tidak Ada Tugas",
            description="Belum ada tugas.\nPaste teks/pengumuman untuk menambah tugas!",
            color=0x95a5a6
        )

    now = datetime.now()
    sorted_tasks = sorted(tasks, key=lambda t: (t.get("deadline") or "9999-99-99"))
    urgent = sum(1 for t in sorted_tasks if any(
        x in get_priority_label(t.get("deadline"), now) for x in ["MENDESAK", "HARI INI", "LEWAT"]
    ))

    lines = []
    for i, task in enumerate(sorted_tasks, 1):
        priority = get_priority_label(task.get("deadline"), now)
        deadline_str = task.get("deadline") or "—"
        desc = task.get("description", "")
        if desc and len(desc) > 55:
            desc = desc[:52] + "..."
        link_parts = render_links(task.get("links", []))

        line = f"`{i}.` {priority} **{task['name']}**"
        line += f"\n> 📅 {format_deadline(deadline_str)}"
        if desc:
            line += f"  •  {desc}"
        if link_parts:
            line += "\n> 🔗 " + "  ·  ".join(link_parts)
        line += f"\n> 🆔 `{task['id']}`"
        lines.append(line)

    embed = discord.Embed(
        title="📋 Daftar Tugas",
        description=f"**{len(tasks)}** tugas  •  **{urgent}** perlu perhatian\n\n" + "\n\n".join(lines),
        color=0xe74c3c if urgent > 0 else 0x2ecc71,
        timestamp=datetime.now()
    )
    embed.set_footer(text="done <keyword>  •  !edit <keyword>  •  !snooze <keyword> <1h/2d>")
    return embed


def parse_snooze_duration(duration_str: str) -> timedelta | None:
    """Parse '2h', '1d', '30m' jadi timedelta."""
    duration_str = duration_str.strip().lower()
    try:
        if duration_str.endswith("m"):
            return timedelta(minutes=int(duration_str[:-1]))
        elif duration_str.endswith("h"):
            return timedelta(hours=int(duration_str[:-1]))
        elif duration_str.endswith("d"):
            return timedelta(days=int(duration_str[:-1]))
    except ValueError:
        return None
    return None


# ─────────────────────────────────────────────
# BACKGROUND: REMINDER LOOP
# ─────────────────────────────────────────────

async def reminder_loop():
    await bot.wait_until_ready()
    print("⏰ Reminder loop started")

    while not bot.is_closed():
        try:
            if REMINDER_CHANNEL_ID:
                channel = bot.get_channel(REMINDER_CHANNEL_ID)
                if channel:
                    tasks = load_tasks()
                    now = datetime.now()
                    updated = False

                    for task in tasks:
                        deadline_str = task.get("deadline")
                        if not deadline_str:
                            continue

                        try:
                            try:
                                deadline = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M")
                            except ValueError:
                                deadline = datetime.strptime(deadline_str + " 23:59", "%Y-%m-%d %H:%M")
                        except Exception:
                            continue

                        delta_seconds = (deadline - now).total_seconds()
                        if delta_seconds < 0:
                            continue

                        reminded = task.get("reminded", [])

                        # Threshold: 24 jam, 3 jam, 1 jam
                        thresholds = [
                            (86400, "24h", "⏰ 24 jam lagi", 0xf39c12),
                            (10800, "3h",  "🔔 3 jam lagi",  0xe67e22),
                            (3600,  "1h",  "🚨 1 jam lagi!",  0xe74c3c),
                        ]

                        for limit, key, label, color in thresholds:
                            if delta_seconds <= limit and key not in reminded:
                                embed = discord.Embed(
                                    title=f"{label} — {task['name']}",
                                    description=f"📅 Deadline: {format_deadline(deadline_str)}",
                                    color=color
                                )
                                link_parts = render_links(task.get("links", []))
                                if link_parts:
                                    embed.add_field(name="🔗 Links", value="  ·  ".join(link_parts), inline=False)
                                await channel.send(embed=embed)
                                reminded.append(key)
                                task["reminded"] = reminded
                                updated = True
                                break  # 1 notif per cek

                    if updated:
                        save_tasks(tasks)

        except Exception as e:
            print(f"Reminder error: {e}")

        await asyncio.sleep(60)  # cek tiap menit


# ─────────────────────────────────────────────
# BOT EVENTS
# ─────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ Bot online: {bot.user}")
    bot.loop.create_task(reminder_loop())


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = str(message.author.id)
    content = message.content.strip()
    content_lower = content.lower()

    # ── DELETE CONFIRMATION FLOW ──
    if user_id in pending_deletes:
        state = pending_deletes[user_id]
        if state["step"] == 1:
            if any(w in content_lower for w in ["ya", "yes", "iya", "yep", "yup", "ok", "oke"]):
                state["step"] = 2
                embed = discord.Embed(
                    title="⚠️ Konfirmasi Ke-2",
                    description=f"Yakin **bener-bener** udah selesai?\n\n**{state['task_name']}**",
                    color=0xe67e22
                )
                embed.set_footer(text="Balas 'ya' untuk hapus permanen, atau 'tidak' untuk batal")
                await message.channel.send(embed=embed)
            else:
                del pending_deletes[user_id]
                await message.channel.send("❌ Penghapusan dibatalkan.")
            return

        elif state["step"] == 2:
            if any(w in content_lower for w in ["ya", "yes", "iya", "yep", "yup", "ok", "oke"]):
                tasks = load_tasks()
                if delete_task(tasks, state["task_id"]):
                    save_tasks(tasks)
                    await message.channel.send(embed=discord.Embed(
                        title="✅ Tugas Selesai!",
                        description=f"**{state['task_name']}** dihapus. Good job! 🎉",
                        color=0x2ecc71
                    ))
                else:
                    await message.channel.send("⚠️ Tugas tidak ditemukan.")
            else:
                await message.channel.send("❌ Penghapusan dibatalkan.")
            del pending_deletes[user_id]
            return

    # ── EDIT FLOW ──
    if user_id in pending_edits:
        state = pending_edits[user_id]

        if state["step"] == "choose_field":
            choice = content_lower.strip()
            field_map = {"1": "name", "2": "deadline", "3": "description"}
            if choice not in field_map:
                await message.channel.send("⚠️ Pilih 1, 2, atau 3. Atau ketik `batal` untuk membatalkan.")
                if "batal" in choice:
                    del pending_edits[user_id]
                return
            state["field"] = field_map[choice]
            state["step"] = "input_value"
            field_labels = {"name": "Nama baru", "deadline": "Deadline baru (format: YYYY-MM-DD HH:MM atau YYYY-MM-DD)", "description": "Deskripsi baru"}
            await message.channel.send(f"✏️ **{field_labels[state['field']]}:**")
            return

        elif state["step"] == "input_value":
            tasks = load_tasks()
            field = state["field"]
            new_value = content.strip()

            # Validasi deadline
            if field == "deadline":
                try:
                    try:
                        datetime.strptime(new_value, "%Y-%m-%d %H:%M")
                    except ValueError:
                        datetime.strptime(new_value, "%Y-%m-%d")
                except ValueError:
                    await message.channel.send("⚠️ Format deadline salah. Gunakan `YYYY-MM-DD HH:MM` atau `YYYY-MM-DD`.")
                    return

            update_task(tasks, state["task_id"], {field: new_value})
            save_tasks(tasks)
            del pending_edits[user_id]

            field_labels = {"name": "Nama", "deadline": "Deadline", "description": "Deskripsi"}
            await message.channel.send(embed=discord.Embed(
                title="✅ Tugas Diperbarui!",
                description=f"**{field_labels[field]}** tugas **{state['task_name']}** berhasil diubah.",
                color=0x2ecc71
            ))
            return

    # ── COMMAND: !jadwal ──
    if any(kw in content_lower for kw in ["!jadwal", "!schedule", "!list", "!tugas"]):
        tasks = load_tasks()
        await message.channel.send(embed=format_task_embed(tasks))
        return

    # ── COMMAND: !edit <keyword> ──
    if content_lower.startswith("!edit "):
        keyword = content[6:].strip()
        tasks = load_tasks()
        matches = [t for t in tasks if keyword.lower() in t["name"].lower()]

        if not matches:
            await message.channel.send(embed=discord.Embed(
                title="🔍 Tidak Ditemukan",
                description=f"Tidak ada tugas dengan keyword **\"{keyword}\"**.",
                color=0x95a5a6
            ))
            return

        if len(matches) > 1:
            opts = "\n".join([f"• **{t['name']}** — `{t.get('deadline','?')}`" for t in matches])
            await message.channel.send(embed=discord.Embed(
                title="🔍 Beberapa Tugas Ditemukan",
                description=f"{opts}\n\nGunakan keyword yang lebih spesifik.",
                color=0xf39c12
            ))
            return

        task = matches[0]
        pending_edits[user_id] = {
            "task_id": task["id"],
            "task_name": task["name"],
            "step": "choose_field"
        }
        embed = discord.Embed(
            title=f"✏️ Edit: {task['name']}",
            description=(
                f"📅 Deadline: {format_deadline(task.get('deadline','—'))}\n"
                f"📝 Deskripsi: {task.get('description','—')}\n\n"
                "Mau edit apa?\n"
                "`1` — Nama\n"
                "`2` — Deadline\n"
                "`3` — Deskripsi"
            ),
            color=0x3498db
        )
        embed.set_footer(text="Ketik nomor pilihanmu, atau 'batal' untuk membatalkan")
        await message.channel.send(embed=embed)
        return

    # ── COMMAND: !snooze <keyword> <durasi> ──
    if content_lower.startswith("!snooze "):
        parts = content[8:].strip().rsplit(" ", 1)
        if len(parts) != 2:
            await message.channel.send("⚠️ Format: `!snooze <keyword> <durasi>`\nContoh: `!snooze python 2h` atau `!snooze raker 1d`")
            return

        keyword, duration_str = parts
        delta = parse_snooze_duration(duration_str)
        if not delta:
            await message.channel.send("⚠️ Format durasi salah. Gunakan `30m`, `2h`, atau `1d`.")
            return

        tasks = load_tasks()
        matches = [t for t in tasks if keyword.lower() in t["name"].lower()]

        if not matches:
            await message.channel.send(embed=discord.Embed(
                title="🔍 Tidak Ditemukan",
                description=f"Tidak ada tugas dengan keyword **\"{keyword}\"**.",
                color=0x95a5a6
            ))
            return

        if len(matches) > 1:
            opts = "\n".join([f"• **{t['name']}** — `{t.get('deadline','?')}`" for t in matches])
            await message.channel.send(embed=discord.Embed(
                title="🔍 Beberapa Tugas Ditemukan",
                description=f"{opts}\n\nGunakan keyword yang lebih spesifik.",
                color=0xf39c12
            ))
            return

        task = matches[0]
        old_deadline = task.get("deadline")

        # Hitung deadline baru
        try:
            try:
                current = datetime.strptime(old_deadline, "%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                try:
                    current = datetime.strptime(old_deadline, "%Y-%m-%d")
                except (ValueError, TypeError):
                    current = datetime.now()
        except Exception:
            current = datetime.now()

        new_deadline = current + delta
        new_deadline_str = new_deadline.strftime("%Y-%m-%d %H:%M")

        update_task(tasks, task["id"], {"deadline": new_deadline_str, "reminded": []})
        save_tasks(tasks)

        await message.channel.send(embed=discord.Embed(
            title="💤 Tugas Di-snooze!",
            description=f"**{task['name']}**\n📅 ~~{format_deadline(old_deadline)}~~ → {format_deadline(new_deadline_str)}",
            color=0x9b59b6
        ))
        return

    # ── COMMAND: done / selesai ──
    if content_lower.startswith("done ") or content_lower.startswith("selesai "):
        keyword = content.split(" ", 1)[1].strip()
        tasks = load_tasks()
        matches = [t for t in tasks if keyword.lower() in t["name"].lower()]

        if not matches:
            await message.channel.send(embed=discord.Embed(
                title="🔍 Tidak Ditemukan",
                description=f"Tidak ada tugas dengan keyword **\"{keyword}\"**.",
                color=0x95a5a6
            ))
            return

        if len(matches) > 1:
            opts = "\n".join([f"• **{t['name']}** — `{t.get('deadline','?')}`" for t in matches])
            await message.channel.send(embed=discord.Embed(
                title="🔍 Beberapa Tugas Ditemukan",
                description=f"{opts}\n\nGunakan keyword yang lebih spesifik.",
                color=0xf39c12
            ))
            return

        task = matches[0]
        pending_deletes[user_id] = {"task_id": task["id"], "task_name": task["name"], "step": 1}
        await message.channel.send(embed=discord.Embed(
            title="🗑️ Konfirmasi Ke-1",
            description=f"Mau hapus tugas ini?\n\n**{task['name']}**\n📅 {format_deadline(task.get('deadline', '—'))}",
            color=0xe74c3c
        ).set_footer(text="Balas 'ya' untuk lanjut, atau 'tidak' untuk batal"))
        return

    # ── AUTO-DETECT TUGAS DARI TEKS BEBAS ──
    if len(content) > 20 and not content.startswith("!"):
        async with message.channel.typing():
            extracted = await extract_tasks_from_text(content)

        if not extracted:
            await message.channel.send("🤖 Hmm, tidak ada tugas yang terdeteksi dari teks itu.")
            return

        tasks = load_tasks()
        added = add_tasks(tasks, extracted)
        save_tasks(tasks)

        now = datetime.now()
        embed = discord.Embed(title=f"✅ {len(added)} Tugas Ditambahkan!", color=0x3498db)
        for t in added:
            priority = get_priority_label(t.get("deadline"), now)
            val = [f"📅 {format_deadline(t.get('deadline', '—'))}"]
            if t.get("description"):
                desc = t["description"]
                if len(desc) > 80:
                    desc = desc[:77] + "..."
                val.append(f"📝 {desc}")
            link_parts = render_links(t.get("links", []))
            if link_parts:
                val.append("🔗 " + "  ·  ".join(link_parts))
            embed.add_field(name=f"{priority} {t['name']}", value="\n".join(val), inline=False)
        embed.set_footer(text="Ketik !jadwal untuk lihat semua tugas")
        await message.channel.send(embed=embed)
        return

    await bot.process_commands(message)


bot.run(os.environ.get("DISCORD_TOKEN"))