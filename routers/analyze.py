from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
import os
import io
import base64
import sys
import logging
from PIL import Image, ImageDraw
from google import genai
from api.services.vision import enhance_hand_image, analyze_image
from api.services.database import fetch_claims

logging.basicConfig(filename='api_debug.log', level=logging.INFO)

router = APIRouter()

@router.post("/analyze-hand")
async def analyze_hand_api(file: UploadFile = File(...), user_id: str = Form(None)):
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Fail peab olema pilt.")
        
    try:
        if not user_id:
            return JSONResponse({"status": "error", "message": "Palun logi sisse."}, status_code=401)
            
        import psycopg2
        db_url = os.environ.get("DATABASE_URL").replace('"', '')
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        
        cur.execute("SELECT has_paid, free_credits FROM user_profiles WHERE id = %s", (user_id,))
        user_row = cur.fetchone()
        
        if not user_row:
            cur.close()
            conn.close()
            return JSONResponse({"status": "error", "message": "Kasutajat ei leitud."}, status_code=401)
            
        has_paid, free_credits = user_row
        free_credits = free_credits or 0
        
        if not has_paid and free_credits <= 0:
            cur.close()
            conn.close()
            return JSONResponse({"status": "error", "message": "Sul ei ole piisavalt krediiti. Palun osta Premium pakett."}, status_code=402)
            
        contents = await file.read()
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        
        img = Image.open(io.BytesIO(contents))
        enhanced_img, edges_img = enhance_hand_image(img)
        
        analysis = analyze_image(client, img, enhanced_img, edges_img)
        if not analysis or not analysis.detected_features:
            print("Pildilt ei leitud ühtegi selget hiromantia tunnust.")
            return
            
        knowledge_context, total = fetch_claims(analysis.detected_features)
        if total == 0:
            print("Andmebaasist ei leitud tunnustele vastavaid reegleid.")
            return
            
        synthesis_prompt = f"""
        Oled professionaalne ja empaatiline hiromant. Kliendi käe visuaalne analüüs on tehtud ja andmebaasist leiti alljärgnevad ajaloolised reeglid.
        Sinu ülesanne on koostada kliendile personaalne, müstiline, kuid samas struktureeritud ja viisakas eestikeelne raport, toetudes AINULT neile reeglitele.
        Kirjuta see ilusas markdown formaadis (kasuta paksu kirja, pealkirju jne).
        
        LEITUD ANDMEBAASI REEGLID (Kliendi käe põhjal):
        {knowledge_context}
        """
        
        response = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=synthesis_prompt,
            config=genai.types.GenerateContentConfig(
                temperature=0.0
            )
        )
        
        # Joonistame pildile punktid ja jooned
        annotated_img = img.copy()
        draw = ImageDraw.Draw(annotated_img)
        width, height = annotated_img.size
        colors = ['#FF3366', '#33CCFF', '#00FF66', '#FFFF00', '#FF9900', '#CC33FF']
        
        for i, feature in enumerate(analysis.detected_features):
            color = colors[i % len(colors)]
            pts = [(int(p.x / 100.0 * width), int(p.y / 100.0 * height)) for p in feature.path]
            
            if len(pts) > 1 and 'line' in feature.concept_canonical_name:
                draw.line(pts, fill=color, width=6)
            elif len(pts) > 2 and 'mount' in feature.concept_canonical_name:
                draw.polygon(pts, outline=color, width=4)
            else:
                for x, y in pts:
                    r = 12
                    draw.ellipse((x-r, y-r, x+r, y+r), outline=color, width=4)
                    
            if pts:
                x, y = pts[0]
                draw.text((x + 15, y - 15), feature.concept_canonical_name, fill=color)
                
        # Konverteerime pildi base64 kujule
        buffered = io.BytesIO()
        annotated_img.save(buffered, format="JPEG", quality=85)
        img_str = base64.b64encode(buffered.getvalue()).decode()
        final_image_data = f"data:image/jpeg;base64,{img_str}"
        
        # Salvestame tulemuse otse andmebaasi
        if user_id:
            import psycopg2
            try:
                db_url = os.environ.get("DATABASE_URL").replace('"', '')
                conn = psycopg2.connect(db_url)
                cur = conn.cursor()
                
                # Delete any existing readings for this user so they only ever have one
                cur.execute("DELETE FROM palmistry_readings WHERE user_id = %s", (user_id,))
                
                cur.execute(
                    "INSERT INTO palmistry_readings (user_id, image_url, reading_text) VALUES (%s, %s, %s)",
                    (user_id, final_image_data, response.text)
                )
                # Decrease credits
                if not has_paid:
                    cur.execute("UPDATE user_profiles SET free_credits = free_credits - 1 WHERE id = %s", (user_id,))
                
                conn.commit()
                cur.close()
                conn.close()
                logging.info("Edukalt andmebaasi salvestatud!")
            except Exception as dbe:
                logging.error(f"Error saving to db: {dbe}")
                
        result_data = {
            "status": "success",
            "reading": response.text,
            "features_detected": [f.model_dump() for f in analysis.detected_features],
            "claims_found": total,
            "annotated_image": final_image_data
        }
        
        return JSONResponse(result_data)
        
    except Exception as e:
        logging.error(f"Error in analysis: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
