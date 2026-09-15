import re
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from groq import Groq
from sqlmodel import Session, select
from app.core.config import settings
from app.api.deps import SessionDep
from app.services.rag_service import get_rag_response
from app.models.product import Product

router = APIRouter(prefix="/chat", tags=["ChatBot"])

# ✅ Initialize Groq client
client = Groq(
    api_key=settings.GROQ_API_KEY
)

SYSTEM_PROMPT = """You are a friendly customer support assistant for an e-commerce store.

## Your Role
Help customers with product questions, shipping, and orders.
Keep answers short (2-3 sentences), friendly, and helpful.

## What You CAN Help With
- Product information and availability
- Shipping costs and delivery times
- Order status (redirect to human agent)
- COD availability and limits

## What You CANNOT Help With (Redirect to Human Agent)
- Returns and refunds - we don't have a return policy yet
- Order cancellations - please contact support
- Damaged or missing items - please contact support
- Account issues - please contact support

## Cancellation Policy
- Orders can be cancelled BEFORE shipping
- Online orders: 5% restocking fee (15% while processing)
- Once SHIPPED → CANNOT cancel

## Shipping Policy
- Free shipping on orders above ₹500
- Standard: ₹50 (3-5 days)
- Express: ₹150 (1-2 days)

## COD Policy
- Available for orders between ₹100 and ₹10,000
- COD fee: ₹50

## IMPORTANT RULES
1. If a customer asks about returns or refunds, say:
   "I don't have information about returns yet. Please contact our support team at support@store.com or call +91-XXXXX-XXXXX."

2. If a customer asks about a specific brand or product NOT in our store, say:
   "Sorry, we don't have [brand] products right now. Would you like to see our available products?"

3. ONLY provide information that is explicitly stated in these policies.

4. If you don't know something, say:
   "I don't have that information right now. Let me connect you with a human agent!"
"""

PRODUCT_KEYWORDS = [
    "product", "item", "buy", "price", "shop", "available", 
    "stock", "show me", "find", "top", "best", "recommend",
    "cheap", "affordable", "expensive", "cost", "worth",
    "suggestion", "offer", "deal", "discount", "sale"
]

# ✅ Only policies that actually exist
POLICY_KEYWORDS = [
    "shipping", "delivery", "cod", "cancel", "cancellation"
]

# ✅ Store conversation history per session
conversation_history = {}

# ✅ Cache product names for quick lookup
_product_names_cache = None
_product_names_cache_time = None

def get_product_names(session: Session) -> list[str]:
    """Get all product names from database (cached)"""
    global _product_names_cache, _product_names_cache_time
    
    if _product_names_cache is not None and _product_names_cache_time is not None:
        if (datetime.now() - _product_names_cache_time).seconds < 300:
            return _product_names_cache
    
    statement = select(Product.name).where(Product.is_active == True)
    products = session.exec(statement).all()
    _product_names_cache = [p.lower() for p in products]
    _product_names_cache_time = datetime.now()
    return _product_names_cache

def is_product_query(message: str, session: Session) -> bool:
    """Check if message is asking about a product"""
    message_lower = message.lower()
    message_words = set(message_lower.split())
    
    product_names = get_product_names(session)
    for name in product_names:
        if name in message_lower:
            return True
        name_words = set(name.split())
        if name_words.intersection(message_words):
            return True
    
    for keyword in PRODUCT_KEYWORDS:
        if keyword in message_lower:
            return True
    
    return False

@router.post("")
def chat(req: dict, session: SessionDep):
    message = req.get("message", "").strip()
    
    # ✅ REQUIRED: Get session_id from request
    session_id = req.get("session_id")
    
    # ✅ If no session_id, return error (no default fallback!)
    if not session_id:
        return {"reply": "Session ID required. Please refresh the page."}
    
    if not message:
        return {"reply": "Please type a message 🙂"}

    try:
        if session_id not in conversation_history:
            conversation_history[session_id] = []
        
        # ✅ Check if it's a policy question FIRST
        is_policy_query = any(keyword in message.lower() for keyword in POLICY_KEYWORDS)
        
        if is_policy_query:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
            ]
            for msg in conversation_history[session_id][-5:]:
                messages.append(msg)
            messages.append({"role": "user", "content": message})
            
            completion = client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=messages,
                max_tokens=500,
                temperature=0.7,
            )
            reply = completion.choices[0].message.content
            
            conversation_history[session_id].append({"role": "user", "content": message})
            conversation_history[session_id].append({"role": "assistant", "content": reply})
            return {"reply": reply}
        
        # ✅ Check if it's a product query
        is_product = is_product_query(message, session)
        
        if is_product:
            reply = get_rag_response(message, session, conversation_history[session_id])
            conversation_history[session_id].append({"role": "user", "content": message})
            conversation_history[session_id].append({"role": "assistant", "content": reply})
            return {"reply": reply}
        
        # ✅ Default: Use LLM with history
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in conversation_history[session_id][-5:]:
            messages.append(msg)
        messages.append({"role": "user", "content": message})
        
        completion = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=messages,
            max_tokens=500,
            temperature=0.7,
        )
        reply = completion.choices[0].message.content
        
        conversation_history[session_id].append({"role": "user", "content": message})
        conversation_history[session_id].append({"role": "assistant", "content": reply})
        return {"reply": reply}

    except Exception as e:
        print("Chatbot error:", e)
        return {"reply": "Sorry, I'm having trouble right now. Please try again."}

@router.get("/history")
def get_history(session_id: str):
    """Get history for a specific session"""
    if not session_id:
        return {"error": "session_id required"}
    return conversation_history.get(session_id, [])

@router.delete("/history")
def clear_history(session_id: str):
    """Clear history for a specific session"""
    if not session_id:
        return {"error": "session_id required"}
    if session_id in conversation_history:
        conversation_history[session_id] = []
    return {"message": f"History cleared for session {session_id}"}