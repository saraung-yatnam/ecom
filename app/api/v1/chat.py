from fastapi import APIRouter
from google import genai
from google.genai import types
from app.core.config import settings

router = APIRouter(prefix="/chat", tags=["ChatBot"])

client = genai.Client(api_key=settings.GEMINI_API_KEY)

SYSTEM_PROMPT = """You are a friendly customer support assistant for an e-commerce store.
Help customers with product questions, shipping, returns, and orders.
Keep answers short (2-3 sentences), friendly, and helpful.
If you don't know something, politely say you'll connect them with a human agent."""


@router.post("")
def chat(req: dict):
    message = req.get("message", "").strip()
    if not message:
        return {"reply": "Please type a message 🙂"}

    try:
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=message,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
        )
        return {"reply": response.text}
    except Exception as e:
        print("Chatbot error:", e)
        return {"reply": "Sorry, I'm having trouble right now. Please try again."}


@router.get("/history")
def get_history():
    return []


@router.delete("/history")
def clear_history():
    return {"message": "History cleared"}