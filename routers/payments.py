from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
import os
from pydantic import BaseModel
import psycopg2
import httpx
import base64
import json
from datetime import datetime, timedelta

router = APIRouter()

MK_API_URL = os.getenv("MK_API_URL", "https://api-test.maksekeskus.ee/v1")
MK_SHOP_ID = os.getenv("MK_SHOP_ID", "mock_shop")
MK_SECRET_KEY = os.getenv("MK_SECRET_KEY", "mock_secret")
DOMAIN = os.getenv("DOMAIN", "http://localhost:4321")

class CheckoutRequest(BaseModel):
    user_id: str
    product_type: str # "vip_1_month" või "report_celtic"

def get_mk_auth_header():
    auth_str = f"{MK_SHOP_ID}:{MK_SECRET_KEY}"
    encoded_auth = base64.b64encode(auth_str.encode()).decode()
    return {"Authorization": f"Basic {encoded_auth}", "Content-Type": "application/json"}

@router.post("/checkout")
async def create_checkout_session(req: CheckoutRequest):
    # Hinna loogika
    if req.product_type == "vip_1_month":
        amount = 5.99
        desc = "VIP Pakett (1 Kuu)"
    elif req.product_type == "report_celtic":
        amount = 14.99
        desc = "Sinu Elu Raamat (Põhjalik Raport)"
    else:
        raise HTTPException(status_code=400, detail="Invalid product type")

    # Maksekeskuse loogika
    try:
        if MK_SHOP_ID == "mock_shop":
            # Kui oleme test-režiimis ilma võtmeteta, tagastame mock URL-i
            mock_url = f"{DOMAIN}/premium?payment=success_mock&user_id={req.user_id}&type={req.product_type}"
            return {"url": mock_url}

        # Reaalne Maksekeskuse päring
        async with httpx.AsyncClient() as client:
            payload = {
                "transaction": {
                    "amount": amount,
                    "currency": "EUR",
                    "reference": f"{req.user_id}|{req.product_type}",
                    "transaction_url": {
                        "return_url": f"{DOMAIN}/premium?payment=success",
                        "cancel_url": f"{DOMAIN}/premium?payment=cancelled",
                        "notification_url": f"{os.getenv('PUBLIC_API_URL', 'http://localhost:8000')}/payments/webhook"
                    }
                },
                "customer": {
                    "email": "klient@example.com", # Siin võiks pärida AB-st tegeliku e-maili
                    "country": "ee",
                    "locale": "et"
                }
            }
            
            resp = await client.post(
                f"{MK_API_URL}/transactions",
                json=payload,
                headers=get_mk_auth_header()
            )
            
            if resp.status_code == 201:
                data = resp.json()
                # Maksekeskus tagastab transaktsiooni ID, mille abil suuname kasutaja makselehele
                transaction_id = data.get("id")
                # Maksekeskuse lüli
                payment_url = f"https://payment-test.maksekeskus.ee/pay/1/transaction.html?transaction={transaction_id}"
                return {"url": payment_url}
            else:
                raise Exception(f"Maksekeskuse viga: {resp.text}")

    except Exception as e:
        print("Payment error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/webhook")
async def mk_webhook(request: Request):
    payload = await request.json()
    
    # Maksekeskus saadab transaction statuse. Edukas on "COMPLETED"
    if payload.get("status") == "COMPLETED":
        reference = payload.get("reference") # "user_id|product_type"
        if reference:
            user_id, product_type = reference.split("|")
            
            try:
                url = os.environ.get("DATABASE_URL").replace('"', '')
                conn = psycopg2.connect(url)
                cur = conn.cursor()
                
                if product_type == "vip_1_month":
                    # Anname 30 päeva premiumit
                    premium_until = datetime.now() + timedelta(days=30)
                    cur.execute(
                        "UPDATE user_profiles SET is_premium = TRUE, premium_until = %s WHERE id = %s",
                        (premium_until, user_id)
                    )
                else:
                    # Salvestame ühekordse ostu JSONB massiivi
                    cur.execute(
                        "UPDATE user_profiles SET purchased_items = purchased_items || %s::jsonb WHERE id = %s",
                        (json.dumps([product_type]), user_id)
                    )
                    
                conn.commit()
                cur.close()
                conn.close()
                print(f"Kasutaja {user_id} ostis edukalt: {product_type}")
            except Exception as e:
                print("Viga andmebaasi uuendamisel:", e)

    return {"status": "success"}

@router.get("/mock-success")
async def mock_success(user_id: str, type: str):
    # See on abiline lokaalseks testimiseks (mock webhook)
    try:
        url = os.environ.get("DATABASE_URL").replace('"', '')
        conn = psycopg2.connect(url)
        cur = conn.cursor()
        if type == "vip_1_month":
            premium_until = datetime.now() + timedelta(days=30)
            cur.execute("UPDATE user_profiles SET is_premium = TRUE, premium_until = %s WHERE id = %s", (premium_until, user_id))
        else:
            cur.execute("UPDATE user_profiles SET purchased_items = purchased_items || %s::jsonb WHERE id = %s", (json.dumps([type]), user_id))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print("Mock viga:", e)
        
    return {"status": "mock_applied"}
