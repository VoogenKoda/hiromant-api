from fastapi import APIRouter, HTTPException, Form
from fastapi.responses import JSONResponse
import os
import requests
import datetime
from google import genai
import psycopg2
import logging
import time
import json

router = APIRouter()
# Mtime update

def get_db_connection():
    db_url = os.environ.get("DATABASE_URL").replace('"', '')
    return psycopg2.connect(db_url)

@router.post("/daily-horoscope")
def get_daily_horoscope(user_id: str = Form(...)):
    """
    Genereerib igapäevase horoskoobi kasutaja sünniandmete põhjal, kasutades FreeAstroAPI 
    personaalse horoskoobi otspunkt-i ning tõlgib/kujundab tulemuse Gemini abil eestikeelseks.
    """
    try:
        # 1. Tõmbame kasutaja andmed andmebaasist
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT synnikuupaev, synnikellaaeg, lat, lon FROM user_profiles WHERE id = %s", (user_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return JSONResponse({"status": "error", "message": "Kasutaja profiili ei leitud. Palun seadista oma sünniandmed."}, status_code=404)

        synnikuupaev, synnikellaaeg, lat, lon = row
        
        if not synnikuupaev or not synnikellaaeg or lat is None or lon is None:
             return JSONResponse({"status": "error", "message": "Sünniandmed on puudulikud."}, status_code=400)

        # Teisendame andmed FreeAstroAPI formaati
        year, month, day = synnikuupaev.year, synnikuupaev.month, synnikuupaev.day
        hour, minute = synnikellaaeg.hour, synnikellaaeg.minute

        api_key = os.environ.get("FREEASTRO_API_KEY", "").replace('"', '')
        headers = {"x-api-key": api_key, "Content-Type": "application/json"}

        # 2. Päring FreeAstroAPI isikliku päevahoroskoobi endpointi
        payload = {
            "birth": {
                "year": year,
                "month": month,
                "day": day,
                "hours": hour,
                "minutes": minute,
                "lat": float(lat),
                "lng": float(lon),
                "timezone": "Europe/Tallinn"
            },
            "locale": "et"
        }

        horoscope_url = "https://api.freeastroapi.com/api/v1/horoscope/daily/personal"
        response = requests.post(horoscope_url, json=payload, headers=headers)
        
        if response.status_code != 200:
            print(f"FreeAstroAPI error: {response.text}", flush=True)
            raise Exception(f"API viga: {response.status_code} - {response.text}")

        horoscope_data = response.json()
        
        # Ekstraheerime inglisekeelse horoskoobi teksti ja aspektid
        eng_text = horoscope_data.get("data", {}).get("content", {}).get("text", "")
        theme = horoscope_data.get("data", {}).get("content", {}).get("theme", "")
        
        if not eng_text:
            eng_text = str(horoscope_data) # Failback

        # 3. Anname andmed Geminile, et tõlkida ja luua ilus eestikeelne horoskoop
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        
        prompt = f"""
        Oled emakeelena eesti keelt rääkiv, kaasaegne ja intuitiivne astroloog. 
        Allpool on tänase päeva astroloogiline lühikokkuvõte inglise keeles. 
        ÄRA tõlgi seda sõna-sõnalt, sest see muudab keele kohmakaks.
        Loe sõnumi mõte läbi ja KOOSTA SELLE PÕHJAL täiesti uus, loomuliku sõnastusega ja väga ilusas, sujuvas eesti keeles personaalne horoskoop (1-2 lühikest lõiku).
        Stiil peaks olema inspireeriv, tabav ja eluline (nagu sõber annaks head nõu).
        Vorminda tekst Markdownis ja pane algusesse rasvaselt päeva põhiteema.
        
        PÄEVA INFO INGLISE KEELES (Teema: {theme}):
        {eng_text}
        """

        gemini_response = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=prompt,
            config=genai.types.GenerateContentConfig(temperature=0.7)
        )

        return JSONResponse({
            "status": "success",
            "horoscope": gemini_response.text
        })

    except Exception as e:
        print(f"Horoscope error: {e}", flush=True)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@router.post("/n8n-horoscope")
def get_n8n_horoscope(user_id: str = Form(...)):
    """
    Kogub andmebaasist kasutaja sünniandmed ja saadab n8n webhookile.
    Tagastab n8n-st saadud vastuse frontendile.
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT synnikuupaev, synnikellaaeg, lat, lon FROM user_profiles WHERE id = %s", (user_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return JSONResponse({"status": "error", "message": "Kasutaja profiili ei leitud."}, status_code=404)

        synnikuupaev, synnikellaaeg, lat, lon = row
        
        if not synnikuupaev or not synnikellaaeg or lat is None or lon is None:
             return JSONResponse({"status": "error", "message": "Sünniandmed on puudulikud."}, status_code=400)

        # Teisendame stringiks n8n jaoks
        payload = {
            "user_id": user_id,
            "dob": synnikuupaev.strftime("%Y-%m-%d"),
            "time": synnikellaaeg.strftime("%H:%M:%S"),
            "lat": float(lat),
            "lon": float(lon)
        }

        n8n_url = os.environ.get("N8N_WEBHOOK_URL", "")
        if not n8n_url:
            raise Exception("N8N_WEBHOOK_URL on seadistamata.")

        response = requests.post(n8n_url, json=payload)
        
        if response.status_code != 200:
            raise Exception(f"Viga n8n API-st: {response.status_code} - {response.text}")

        n8n_data = response.json()
        n8n_data["status"] = "success"
        
        return JSONResponse(n8n_data)

    except Exception as e:
        print(f"n8n Horoscope error: {e}", flush=True)
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

