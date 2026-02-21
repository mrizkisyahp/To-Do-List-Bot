import os
import json
import httpx
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """Kamu adalah asisten penjadwalan. Tugasmu mengekstrak tugas/kegiatan dari teks yang diberikan.

Aturan penting:
- Satu pengumuman/event = SATU tugas, meskipun ada banyak hal yang harus dilakukan di dalamnya. Gabungkan semua action item dari satu event menjadi 1 tugas dengan deskripsi yang mencakup semuanya.
- Buat tugas terpisah HANYA jika deadline-nya berbeda atau jelas merupakan kegiatan yang benar-benar berbeda konteksnya.
- Format deadline: YYYY-MM-DD HH:MM (jika ada jam), atau YYYY-MM-DD (jika hanya tanggal). Jika tidak ada tahun, asumsikan tahun sekarang atau tahun depan (mana yang logis). Jika tidak ada deadline, isi dengan null.
- Untuk kata relatif: 'hari ini' = tanggal hari ini, 'besok' = tanggal besok yang sudah diberikan, 'lusa' = 2 hari dari hari ini, 'minggu depan' = 7 hari dari hari ini, dst. Gunakan tanggal yang sudah diberikan sebagai acuan TEPAT.
- Semua URL/link dalam teks masuk ke array "links" milik tugas yang paling relevan. Satu tugas bisa punya banyak link. Setiap link punya "label" (nama deskriptif berdasarkan konteks, contoh: "Jadwal Pra-Raker", "Template", "Form Pengumpulan", "Link GMeet") dan "url".

Jawab HANYA dengan JSON array seperti ini (tanpa penjelasan lain, tanpa markdown, tanpa backtick):
[
  {
    "name": "nama tugas singkat",
    "description": "deskripsi singkat yang mencakup semua hal yang harus dilakukan",
    "deadline": "2025-01-15 23:59",
    "links": [{"label": "nama link", "url": "https://..."}, {"label": "nama link 2", "url": "https://..."}]
  }
]

Jika tidak ada tugas sama sekali dalam teks, jawab dengan array kosong: []"""


async def extract_tasks_from_text(text: str) -> list:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY tidak ditemukan di environment variable!")

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now.replace(hour=0,minute=0,second=0,microsecond=0) + __import__('datetime').timedelta(days=1)).strftime("%Y-%m-%d")

    payload = {
        "model": GROQ_MODEL,
        "temperature": 0.1,
        "max_tokens": 1000,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Tanggal hari ini: {today} (besok: {tomorrow})\n\nTeks:\n{text}"}
        ]
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GROQ_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            timeout=30.0
        )
        if resp.status_code != 200:
            raise Exception(f"Groq API error {resp.status_code}: {resp.text}")
        data = resp.json()

    raw_text = data["choices"][0]["message"]["content"].strip()

    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]

    return json.loads(raw_text.strip())


def get_priority_label(deadline_str: str, now: datetime) -> str:
    if not deadline_str:
        return "⚪"

    try:
        try:
            deadline = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M")
        except ValueError:
            # Tanpa jam = anggap end of day 23:59
            deadline = datetime.strptime(deadline_str + " 23:59", "%Y-%m-%d %H:%M")

        deadline_date = deadline.date()
        today_date = now.date()
        diff_days = (deadline_date - today_date).days

        if diff_days < 0:
            return "🔴 [LEWAT DEADLINE]"
        elif diff_days == 0:
            return "🔴 [HARI INI - URGENT!]"
        elif diff_days <= 2:
            return "🟠 [SANGAT MENDESAK]"
        elif diff_days <= 7:
            return "🟡 [MENDESAK]"
        elif diff_days <= 14:
            return "🔵 [NORMAL]"
        else:
            return "🟢 [SANTAI]"
            
    except Exception:
        return "⚪"