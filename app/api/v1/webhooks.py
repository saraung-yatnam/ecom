from fastapi import APIRouter, Request, HTTPException
from sqlmodel import Session

from app.api.deps import SessionDep
from app.repositories import payment as payment_repo
from app.services.payment_service import get_payment_service


router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/payment")
async def payment_webhook(
    request: Request,
    session: SessionDep,
):
    """
    Payment webhook endpoint.
    
    - Dummy mode: Just logs the webhook
    - Real mode: Verifies signature and processes
    """
    # Get payload
    payload = await request.json()
    signature = request.headers.get("x-payment-signature", "")
    
    # Get payment service
    payment_service = get_payment_service()
    
    try:
        # Process webhook
        event = payment_service.handle_webhook(payload, signature)
        
        # Handle event
        if event["event_type"] == "payment.succeeded":
            payment_data = event["data"]
            payment_repo.mark_payment_succeeded(
                session,
                payment_data.get("payment_intent_id"),
            )
        
        return {"status": "received"}
    
    except Exception as e:
        raise HTTPException(400, f"Webhook error: {str(e)}")