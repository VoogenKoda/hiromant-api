import os
import psycopg2
import logging
import random
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from google import genai
from fastapi.responses import JSONResponse

router = APIRouter()

class CardSelection(BaseModel):
    id: int
    is_reversed: bool = False

class TarotAnalyzeRequest(BaseModel):
    cards: List[CardSelection]
    spread_type: str = "ajavoo"
    user_id: str

SPREAD_LAYOUTS = {
    "ajavoo": {
        "name": "Ajavoo laotus (Minevik - Olevik - Tulevik)",
        "count": 3,
        "pos": ["Minevik", "Olevik", "Tulevik"]
    },
    "probleemi": {
        "name": "Probleemi laotus (Situatsioon - Takistus - Nõuanne)",
        "count": 3,
        "pos": ["Situatsioon", "Takistus", "Nõuanne"]
    },
    "enesearengu": {
        "name": "Enesearengu laotus (Keha - Mõistus - Vaim)",
        "count": 3,
        "pos": ["Keha", "Mõistus", "Vaim"]
    },
    "valiku": {
        "name": "Valiku laotus (Valik A - Valik B - Mida peaksin tegema?)",
        "count": 3,
        "pos": ["Valik A", "Valik B", "Mida peaksin tegema?"]
    },
    "suhte": {
        "name": "Suhtelaotus (Küsija panus - Partneri panus - Suhte dünaamika)",
        "count": 3,
        "pos": ["Kuidas küsija suhet näeb", "Kuidas partner suhet näeb", "Suhte dünaamika"]
    },
    "armastuse": {
        "name": "Armastuse laotus (5 kaarti)",
        "count": 5,
        "pos": ["Mina", "Partner", "Suhte minevik", "Suhte hetkeseis", "Suhte tulevik"]
    },
    "keldi_rist": {
        "name": "Keldi Rist (10 kaarti)",
        "count": 10,
        "pos": [
            "Olevik / Küsija olukord",
            "Väljakutse / Ristuv energia",
            "Teadlikud eesmärgid / Kroon",
            "Alateadvus / Vundament",
            "Lähiminevik",
            "Lähitulevik",
            "Küsija ise",
            "Keskkond / Teised inimesed",
            "Lootused ja hirmud",
            "Lõpptulemus"
        ]
    }
}

def get_db_connection():
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url.replace('"', ''))
    raise Exception("DATABASE_URL is missing")

@router.get("/draw")
async def draw_cards(spread_type: str = "ajavoo"):
    """Tõmbab andmebaasist õige arvu juhuslikke Taro kaarte vastavalt laotusele."""
    layout = SPREAD_LAYOUTS.get(spread_type, SPREAD_LAYOUTS["ajavoo"])
    count = layout["count"]
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, name, img FROM tarot_interpretations ORDER BY RANDOM() LIMIT %s", (count,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        cards = []
        for r in rows:
            is_reversed = random.random() < 0.25
            cards.append({"id": r[0], "name": r[1], "img": r[2], "is_reversed": is_reversed})
        return {"status": "success", "cards": cards}
    except Exception as e:
        logging.error(f"Error drawing cards: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/analyze")
async def analyze_tarot(req: TarotAnalyzeRequest):
    """Võtab vastu kaardid, loeb andmebaasist tähendused ja saadab Geminile analüüsimiseks."""
    layout = SPREAD_LAYOUTS.get(req.spread_type, SPREAD_LAYOUTS["ajavoo"])
    count = layout["count"]

    if len(req.cards) != count:
        raise HTTPException(status_code=400, detail=f"Vaja on täpselt {count} kaarti selle laotuse jaoks.")
        
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Check credits
        cur.execute("SELECT has_paid, free_credits FROM user_profiles WHERE id = %s", (req.user_id,))
        user_row = cur.fetchone()
        if not user_row:
            cur.close()
            conn.close()
            raise HTTPException(status_code=401, detail="Kasutajat ei leitud. Palun logi sisse.")
            
        has_paid, free_credits = user_row
        free_credits = free_credits or 0
        
        if not has_paid and free_credits <= 0:
            cur.close()
            conn.close()
            raise HTTPException(status_code=402, detail="Sul ei ole piisavalt krediiti. Palun osta Premium pakett.")
        
        cards_info = []
        for i, card_input in enumerate(req.cards):
            cur.execute("""
                SELECT name, keywords, meanings_light, meanings_shadow, archetype, mythical_spiritual 
                FROM tarot_interpretations WHERE id = %s
            """, (card_input.id,))
            row = cur.fetchone()
            if row:
                pos = layout["pos"][i] if i < len(layout["pos"]) else f"Positsioon {i+1}"
                reversed_notice = "**TÄHELEPANU: SEE KAART ON TAGURPIDI (REVERSED)**\nKeskendu peamiselt varjatud/hoiatavatele tähendustele või selle kaardi blokeeritud energiale." if card_input.is_reversed else ""
                cards_info.append(f"""
                ---
                Positsioon laotuses: {pos}
                Kaart: {row[0]} {'(Tagurpidi)' if card_input.is_reversed else ''}
                {reversed_notice}
                Arhetüüp: {row[4]}
                Märksõnad: {row[1]}
                Valged/positiivsed tähendused: {row[2]}
                Varjatud/hoiatavad tähendused: {row[3]}
                Müstiline taust: {row[5]}
                """)
                
        cur.close()
        conn.close()
        
        if len(cards_info) != count:
            raise HTTPException(status_code=404, detail="Mõnda kaarti ei leitud andmebaasist")
            
        context_str = "\n".join(cards_info)
        pos_examples = ", ".join(layout["pos"][:3]) + ("..." if count > 3 else "")
        
        synthesis_prompt = f"""
        Oled väga professionaalne, müstiline ja elutark Taro kaardilugeja. 
        Kliendile tõmmati {count} kaarti. Valitud ladumise stiil on: {layout["name"]}. 
        Allpool on toodud iga kaardi täpsed andmed ja tähendused otse vanadest tarkusteraamatutest vastavalt nende positsioonile laotuses.
        
        Sinu ülesanne on koostada kliendile sügav, empaatiline ja isikupärane eestikeelne kaardilugemise analüüs, toetudes AINULT nendele tähendustele ja sidudes need kokku valitud laotuse loogikaga. 
        Analüüs peab olema kirjutatud ilusasse Markdown formaati (kasuta pealkirju, paksu kirja, tsitaate). 
        Struktuur peab sisaldama sissejuhatust, iga positsiooni (näiteks {pos_examples}) lahtiseletamist ja loogilist lõppkokkuvõtet/nõuannet.
        
        KAARDID JA NENDE TÄHENDUSED:
        {context_str}
        """
        
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        response = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=synthesis_prompt,
            config=genai.types.GenerateContentConfig(temperature=0.7)
        )
        
        # Decrement credits
        if not has_paid:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("UPDATE user_profiles SET free_credits = free_credits - 1 WHERE id = %s", (req.user_id,))
            conn.commit()
            cur.close()
            conn.close()
        
        return {"status": "success", "reading": response.text}
        
    except Exception as e:
        logging.error(f"Error analyzing tarot: {e}")
        raise HTTPException(status_code=500, detail=str(e))
