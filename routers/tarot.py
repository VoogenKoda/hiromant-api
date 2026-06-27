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

def get_db_connection():
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url.replace('"', ''))
    raise Exception("DATABASE_URL is missing")

@router.get("/draw")
async def draw_cards():
    """Tõmbab andmebaasist 3 juhuslikku Taro kaarti."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, name, img FROM tarot_interpretations ORDER BY RANDOM() LIMIT 3")
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
    """Võtab vastu 3 kaardi ID-d, loeb andmebaasist tähendused ja saadab Geminile analüüsimiseks."""
    if len(req.cards) != 3:
        raise HTTPException(status_code=400, detail="Vaja on täpselt 3 kaarti (Minevik, Olevik, Tulevik)")
        
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
        
        spread_layouts = {
            "ajavoo": {
                "name": "Ajavoo laotus (Minevik - Olevik - Tulevik)",
                "pos": ["Minevik", "Olevik", "Tulevik"]
            },
            "probleemi": {
                "name": "Probleemi laotus (Situatsioon - Takistus - Nõuanne)",
                "pos": ["Situatsioon", "Takistus", "Nõuanne"]
            },
            "enesearengu": {
                "name": "Enesearengu laotus (Keha - Mõistus - Vaim)",
                "pos": ["Keha", "Mõistus", "Vaim"]
            },
            "valiku": {
                "name": "Valiku laotus (Valik A - Valik B - Mida peaksin tegema?)",
                "pos": ["Valik A", "Valik B", "Mida peaksin tegema?"]
            },
            "suhte": {
                "name": "Suhtelaotus (Küsija panus - Partneri panus - Suhte dünaamika)",
                "pos": ["Kuidas küsija suhet näeb / Mida ta annab", "Kuidas partner suhet näeb / Mida tema annab", "Suhte dünaamika / Kuhu suhe suundub"]
            }
        }
        
        layout = spread_layouts.get(req.spread_type, spread_layouts["ajavoo"])
        
        cards_info = []
        for i, card_input in enumerate(req.cards):
            cur.execute("""
                SELECT name, keywords, meanings_light, meanings_shadow, archetype, mythical_spiritual 
                FROM tarot_interpretations WHERE id = %s
            """, (card_input.id,))
            row = cur.fetchone()
            if row:
                pos = layout["pos"][i] if i < 3 else f"Positsioon {i+1}"
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
        
        if len(cards_info) != 3:
            raise HTTPException(status_code=404, detail="Mõnda kaarti ei leitud andmebaasist")
            
        context_str = "\n".join(cards_info)
        
        synthesis_prompt = f"""
        Oled väga professionaalne, müstiline ja elutark Taro kaardilugeja. 
        Kliendile tõmmati 3 kaarti. Valitud ladumise stiil on: {layout["name"]}. 
        Allpool on toodud iga kaardi täpsed andmed ja tähendused otse vanadest tarkusteraamatutest vastavalt nende positsioonile laotuses.
        
        Sinu ülesanne on koostada kliendile sügav, empaatiline ja isikupärane eestikeelne kaardilugemise analüüs, toetudes AINULT nendele tähendustele ja sidudes need kokku valitud laotuse loogikaga. 
        Analüüs peab olema kirjutatud ilusasse Markdown formaati (kasuta pealkirju, paksu kirja, tsitaate). 
        Struktuur peab sisaldama sissejuhatust, iga positsiooni (näiteks {layout["pos"][0]}, {layout["pos"][1]}, {layout["pos"][2]}) lahtiseletamist ja loogilist lõppkokkuvõtet/nõuannet.
        
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
