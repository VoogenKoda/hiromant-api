from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
import stripe
import os
from pydantic import BaseModel
import psycopg2

router = APIRouter()

# Need seadistatakse .env failist (praegu mockime, kui neid pole)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "sk_test_mock")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_mock")

# URL-id kuhu suunata pärast edukat või ebaõnnestunud makset
DOMAIN = os.getenv("DOMAIN", "http://localhost:4321")

class CheckoutRequest(BaseModel):
    user_id: int

@router.post("/create-checkout-session")
async def create_checkout_session(req: CheckoutRequest):
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'product_data': {
                        'name': 'Põhjalik Sünnikaardi Analüüs',
                        'description': 'Täielik 15+ leheküljeline isiksuse ja elueesmärgi tõlgendus.',
                    },
                    'unit_amount': 1490, # 14.90€
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=DOMAIN + '/astrology?payment=success',
            cancel_url=DOMAIN + '/astrology?payment=cancelled',
            client_reference_id=str(req.user_id),
        )
        return {"url": session.url}
    except Exception as e:
        print("Stripe error:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')

    try:
        # Kui sul on webhooki secret seadistatud
        if WEBHOOK_SECRET != "whsec_mock":
            event = stripe.Webhook.construct_event(
                payload, sig_header, WEBHOOK_SECRET
            )
        else:
            # Testimise ajal, kui secretit pole, laeme lihtsalt JSONi
            import json
            event = stripe.Event.construct_from(json.loads(payload), stripe.api_key)
            
    except ValueError as e:
        # Invalid payload
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Kontrollime sündmust
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        
        user_id_str = session.get('client_reference_id')
        if user_id_str:
            try:
                user_id = int(user_id_str)
                url = os.environ.get("DATABASE_URL").replace('"', '')
                conn = psycopg2.connect(url)
                cur = conn.cursor()
                cur.execute("UPDATE user_profiles SET has_paid = TRUE WHERE id = %s", (user_id,))
                conn.commit()
                cur.close()
                conn.close()
                print(f"Kasutaja {user_id} on edukalt maksnud!")
            except Exception as e:
                print("Viga andmebaasi uuendamisel:", e)

    return {"status": "success"}
