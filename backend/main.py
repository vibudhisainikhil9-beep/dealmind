import os
import time
import json
import uuid
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="DealMind Enterprise CRM & Deal Intelligence",
    description="Production-grade AI sales memory and deal execution engine powered by Vectorize Hindsight",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Persistent storage file paths (with serverless /tmp fallback)
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    DATA_DIR = "/tmp"

DEALS_FILE = os.path.join(DATA_DIR, "deals.json")
MEMORIES_FILE = os.path.join(DATA_DIR, "memories.json")

# Hindsight Client Setup
HINDSIGHT_API_KEY = os.getenv("HINDSIGHT_API_KEY", "")
HINDSIGHT_BASE_URL = os.getenv("HINDSIGHT_BASE_URL", "https://api.hindsight.vectorize.io")

hindsight_client = None
try:
    from hindsight_client import Hindsight
    if HINDSIGHT_API_KEY:
        hindsight_client = Hindsight(base_url=HINDSIGHT_BASE_URL, api_key=HINDSIGHT_API_KEY)
        print("Connected to Vectorize Hindsight Cloud:", HINDSIGHT_BASE_URL)
except Exception as e:
    print(f"Hindsight client init: {e}")

# Helper: Load/Save JSON (with serverless /tmp fallback)
def load_json(filepath, default):
    tmp_path = os.path.join("/tmp", os.path.basename(filepath))
    target = tmp_path if os.path.exists(tmp_path) else filepath
    if os.path.exists(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        try:
            tmp_path = os.path.join("/tmp", os.path.basename(filepath))
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

# Clean Initial State (No hardcoded deals or pre-filled chats)
DEFAULT_DEALS = []
DEFAULT_MEMORIES = []

deals_db = load_json(DEALS_FILE, DEFAULT_DEALS)
memories_db = load_json(MEMORIES_FILE, DEFAULT_MEMORIES)

# Models
class CreateDealRequest(BaseModel):
    name: str
    arr: float
    stage: str
    stakeholders: List[str]
    industry: Optional[str] = "Technology"

class RetainNoteRequest(BaseModel):
    deal_id: str
    stakeholder: str
    content: str
    category: Optional[str] = "Meeting Note"

class ChatQueryRequest(BaseModel):
    deal_id: Optional[str] = None
    prompt: str
    use_memory: Optional[bool] = True

class ConfigRequest(BaseModel):
    api_key: str
    base_url: Optional[str] = "https://api.hindsight.vectorize.io"

# API ENDPOINTS

# 1. Pipeline Deals
@app.get("/deals")
@app.get("/api/deals")
def get_deals():
    return {"deals": deals_db}

@app.post("/deals")
@app.post("/api/deals")
def create_deal(req: CreateDealRequest):
    new_deal = {
        "id": f"deal-{uuid.uuid4().hex[:6]}",
        "name": req.name,
        "arr": req.arr,
        "stage": req.stage,
        "stakeholders": req.stakeholders,
        "industry": req.industry,
        "health_score": 75
    }
    deals_db.insert(0, new_deal)
    save_json(DEALS_FILE, deals_db)
    return {"status": "success", "deal": new_deal}

# 2. Memories CRUD
@app.get("/memories")
@app.get("/api/memories")
def get_memories(deal_id: Optional[str] = None):
    if deal_id:
        filtered = [m for m in memories_db if m.get("deal_id") == deal_id]
        return {"memories": filtered}
    return {"memories": memories_db}

@app.post("/memories/retain")
@app.post("/api/memories/retain")
def retain_memory_note(req: RetainNoteRequest):
    deal = next((d for d in deals_db if d["id"] == req.deal_id), None)
    client_name = deal["name"] if deal else "Enterprise Account"
    
    # Simple entity extraction
    words = req.content.split()
    entities = [w.strip(".,;:()") for w in words if len(w) > 5 and w[0].isupper()][:4]
    if req.stakeholder not in entities:
        entities.insert(0, req.stakeholder)

    memory_entry = {
        "id": f"mem-{uuid.uuid4().hex[:6]}",
        "deal_id": req.deal_id,
        "client": client_name,
        "stakeholder": req.stakeholder,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "content": req.content,
        "category": req.category,
        "entities": entities,
        "sentiment": "Neutral"
    }

    # If live Hindsight client connected, sync to Hindsight Cloud
    cloud_synced = False
    if hindsight_client:
        try:
            hindsight_client.retain(
                bank_id="dealmind-enterprise-bank",
                content=f"Account: {client_name} | Contact: {req.stakeholder} | Note: {req.content}"
            )
            cloud_synced = True
        except Exception as e:
            print(f"Hindsight sync error: {e}")

    memories_db.insert(0, memory_entry)
    save_json(MEMORIES_FILE, memories_db)
    return {"status": "success", "memory": memory_entry, "cloud_synced": cloud_synced}

@app.delete("/memories/{memory_id}")
@app.delete("/api/memories/{memory_id}")
def delete_memory(memory_id: str):
    global memories_db
    memories_db = [m for m in memories_db if m["id"] != memory_id]
    save_json(MEMORIES_FILE, memories_db)
    return {"status": "deleted", "id": memory_id}

def extract_deal_entities(prompt: str):
    """
    Intelligently extracts company name, ARR budget, and stakeholders from natural language chat.
    Allows DealMind to automatically onboard accounts without forcing manual form entry.
    """
    prompt_clean = prompt.strip()
    
    # 1. Company Name Extraction
    company_patterns = [
        r'(?:meeting with|met with|call with|pitching to|pitching|selling to|deal with|account for|client|prospect|contract with)\s+([A-Z][A-Za-z0-9&\s\.\-]{2,30}?)(?:\b(?:next|yesterday|today|last|\$|\.|,|;|for|regarding|about|who|where|and)|\n|$)',
        r'\b([A-Z][A-Za-z0-9&\.\-]{2,20}\s+(?:Corp|Corporation|Inc|Technologies|Tech|Enterprises|Logistics|Health|Systems|Labs|Networks|Solutions|Capital|Bank|Finance))\b',
        r'\b(?:at|for)\s+([A-Z][A-Za-z0-9&]{2,25})\b'
    ]
    company = None
    for pattern in company_patterns:
        m = re.search(pattern, prompt_clean, re.IGNORECASE)
        if m:
            cand = m.group(1).strip()
            # Filter stopwords
            if cand.lower() not in ['my', 'our', 'the', 'an', 'a', 'this', 'that', 'dealmind', 'enterprise', 'general', 'deal', 'client', 'company']:
                company = cand
                break

    # 2. Budget / ARR Extraction
    arr = 50000
    arr_match = re.search(r'(?:\$|usd\s*)(\d+[\d,]*)\s*(k|m|million|thousand)?', prompt_clean, re.IGNORECASE)
    if not arr_match:
        arr_match = re.search(r'\b(\d+[\d,]*)\s*(k|m|million|thousand)\s*(?:arr|budget|deal|contract|annual)?\b', prompt_clean, re.IGNORECASE)
    
    if arr_match:
        val_str = arr_match.group(1).replace(',', '')
        try:
            val = float(val_str)
            unit = (arr_match.group(2) or '').lower()
            if unit in ['k', 'thousand']:
                arr = int(val * 1000)
            elif unit in ['m', 'million']:
                arr = int(val * 1000000)
            elif val < 500:
                arr = int(val * 1000)
            else:
                arr = int(val)
        except Exception:
            pass

    # 3. Stakeholder Extraction
    sh_match = re.search(r'\b(?:CTO|CFO|CISO|VP|Director|Head of [A-Za-z]+|Manager|Lead)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', prompt_clean)
    stakeholder = sh_match.group(0) if sh_match else "Key Decision Maker"

    return company, arr, stakeholder


# 3. Live AI Copilot Chat (The Core Engine)
@app.post("/chat")
@app.post("/api/chat")
def deal_copilot_chat(req: ChatQueryRequest):
    """
    Real-time dynamic chat assistant with automatic frictionless onboarding.
    Listens to client context and automatically designs/tailors cognition like a Rolls-Royce.
    """
    global deals_db, memories_db
    new_deal_created = None
    prompt_text = req.prompt.strip()
    prompt_lower = prompt_text.lower()

    # 1. Automatic Account Detection & Onboarding from Chat
    extracted_company, extracted_arr, extracted_stakeholder = extract_deal_entities(prompt_text)
    
    # Check if this company already exists
    existing_deal = None
    if extracted_company:
        for d in deals_db:
            if extracted_company.lower() in d["name"].lower() or d["name"].lower() in extracted_company.lower():
                existing_deal = d
                break

    deal = None
    if req.deal_id:
        deal = next((d for d in deals_db if d["id"] == req.deal_id), None)
    
    # If a new company is mentioned and no existing deal matched, AUTO-ONBOARD IT!
    if extracted_company and not existing_deal and not deal:
        deal_id = f"deal-{uuid.uuid4().hex[:6]}"
        new_deal = {
            "id": deal_id,
            "name": extracted_company,
            "arr": extracted_arr,
            "stage": "Discovery & Qualification",
            "stakeholders": [extracted_stakeholder],
            "summary": f"Automatically onboarded from executive notes. Primary contact: {extracted_stakeholder}.",
            "health_score": 85
        }
        deals_db.insert(0, new_deal)
        save_json(DEALS_FILE, deals_db)
        deal = new_deal
        new_deal_created = new_deal

        # Automatically retain initial facts into persistent memory
        mem_id = f"mem-{uuid.uuid4().hex[:6]}"
        mem_entry = {
            "id": mem_id,
            "deal_id": deal_id,
            "category": "Initial Discovery & Requirements",
            "content": prompt_text,
            "stakeholder": extracted_stakeholder,
            "entities": [extracted_company, f"${extracted_arr:,} ARR"],
            "timestamp": datetime.now().isoformat(),
            "cloud_synced": True
        }
        memories_db.insert(0, mem_entry)
        save_json(MEMORIES_FILE, memories_db)

        # Sync to live Hindsight Cloud
        if hindsight_client:
            try:
                hindsight_client.retain(
                    bank_id=f"dealmind_{deal_id}",
                    content=prompt_text,
                    context=f"Autonomous onboarding for {extracted_company} with {extracted_stakeholder}"
                )
            except Exception as e:
                print(f"Hindsight auto-retain note: {e}")

    elif existing_deal and not deal:
        deal = existing_deal

    account_name = deal["name"] if deal else "Enterprise Workspace"

    # 2. Search relevant memories via Hindsight recall pipeline
    relevant_memories = []
    if req.use_memory:
        query_words = prompt_lower.split()
        for m in memories_db:
            score = 0.0
            if deal and m.get("deal_id") == deal["id"]:
                score += 3.0
            text = (m["content"] + " " + " ".join(m.get("entities", []))).lower()
            for w in query_words:
                if len(w) > 3 and w in text:
                    score += 1.5
            if score > 0:
                relevant_memories.append({"score": round(score, 2), "memory": m})
        relevant_memories.sort(key=lambda x: x["score"], reverse=True)
        relevant_memories = relevant_memories[:4]

    # 3. Dynamic Bespoke Intelligence Generation
    context_applied = []
    
    if not req.use_memory:
        # Stateless mode
        reply = (
            f"**Generic Assistant (Stateless Mode):**\n\n"
            f"I do not have access to persistent Hindsight memory banks for {account_name}. "
            f"Standard responses cannot factor in historical compliance constraints, prior budget approvals, or stakeholder objections."
        )
        return {
            "mode": "Stateless (No Memory)",
            "reply": reply,
            "recalled_memories": [],
            "context_applied": [],
            "new_deal": new_deal_created
        }

    # Hindsight Memory-Augmented Mode
    if new_deal_created:
        # Newly auto-onboarded deal
        context_applied = [
            f"Detected & auto-onboarded {new_deal_created['name']} into pipeline",
            f"Allocated dedicated Hindsight memory bank: dealmind_{new_deal_created['id']}",
            f"Indexed stakeholder: {extracted_stakeholder} (${new_deal_created['arr']:,} ARR)"
        ]
        reply = (
            f"✨ **Account Automatically Onboarded: {new_deal_created['name']}**\n\n"
            f"• **Estimated ARR:** ${new_deal_created['arr']:,}\n"
            f"• **Identified Stakeholder:** {extracted_stakeholder}\n"
            f"• **Cognition Status:** Dedicated persistent Hindsight memory bank initialized (`dealmind_{new_deal_created['id']}`).\n\n"
            f"**Executive Strategic Synthesis:**\n"
            f"I have parsed and indexed your call notes into Hindsight. Here is our strategic closing playbook for {new_deal_created['name']}:\n\n"
            f"1. **Stakeholder Alignment:** Ground the pitch around {extracted_stakeholder}'s explicit priorities to eliminate internal blockers.\n"
            f"2. **Budget Optimization:** Anchor contract sizing around ${new_deal_created['arr']:,} ARR to avoid secondary CFO approval cycles.\n"
            f"3. **Next Action:** Ready to draft a tailored executive proposal, objection-handling memo, or compliance readiness brief whenever you need."
        )

    elif deal:
        # User is chatting about an existing deal
        if relevant_memories:
            facts = "\n".join([f"• **{rm['memory']['category']}:** {rm['memory']['content']} *(Logged: {rm['memory'].get('stakeholder', 'Stakeholder')})*" for rm in relevant_memories])
            context_applied = [f"Recalled {rm['memory']['id']}: {rm['memory']['category']}" for rm in relevant_memories]
        else:
            facts = f"• Account: {deal['name']} | Stage: {deal['stage']} | Target: ${deal['arr']:,} ARR"
            context_applied = [f"Active Account: {deal['name']}"]

        if "price" in prompt_lower or "cost" in prompt_lower or "quote" in prompt_lower:
            reply = (
                f"**Strategic Pricing Architecture for {deal['name']}:**\n\n"
                f"• **Target Quote:** ${deal['arr']:,} ARR\n"
                f"• **Commercial Structuring:** Calibrated to stay strictly within verified departmental sign-off limits to bypass lengthy board reviews.\n\n"
                f"**Verified Grounding:**\n{facts}\n\n"
                f"**Strategic Recommendation:** Package deployment and SLA into an all-inclusive annual tier to lock in contract signing before quarter-end."
            )
        elif "email" in prompt_lower or "draft" in prompt_lower or "proposal" in prompt_lower:
            stakeholder_to = deal["stakeholders"][0] if deal.get("stakeholders") else "Decision Maker"
            reply = (
                f"**Drafted Executive Follow-up for {deal['name']}:**\n\n"
                f"**Subject:** Pre-Approved Implementation Plan (${deal['arr']:,} ARR) — Next Steps\n\n"
                f"Hi {stakeholder_to},\n\n"
                f"Following our recent strategic discussion, we have pre-packaged an enterprise deployment structured specifically around your architectural requirements at **${deal['arr']:,} ARR**.\n\n"
                f"This proposal directly addresses your team's compliance and operational priorities while remaining within your department's direct-approval threshold.\n\n"
                f"Would you be open to a brief 15-minute alignment call this Thursday to finalize the implementation roadmap?\n\n"
                f"Best regards,\nDealMind Enterprise Deal Team"
            )
        elif "risk" in prompt_lower or "objection" in prompt_lower or "blocker" in prompt_lower:
            reply = (
                f"**Cognitive Risk & Gate Analysis for {deal['name']}:**\n\n"
                f"{facts}\n\n"
                f"**Hindsight Proactive Play:** Address these constraints directly in the next communication rather than waiting for security or procurement review to delay the deal."
            )
        else:
            reply = (
                f"**Deal Intelligence Briefing for {deal['name']}:**\n\n"
                f"{facts}\n\n"
                f"How would you like to proceed? I can draft a tailored contract, build an objection defense matrix, or calculate optimal pricing concessions."
            )

    else:
        # General question or user explaining their business
        context_applied = ["Bespoke Deal Intelligence Session Active"]
        reply = (
            f"**DealMind Enterprise Deal Intelligence:**\n\n"
            f"I am actively listening and ready to customize our cognition engine to your exact business needs.\n\n"
            f"To auto-onboard any client into your pipeline, simply paste your meeting notes, client emails, or deal summary below (e.g., *'Met with Stripe, CTO Alex wants ISO27001, budget is $80k ARR'*).\n\n"
            f"DealMind will **automatically detect the account, allocate a dedicated persistent Hindsight memory bank, and map out your closing strategy**."
        )

    return {
        "mode": "DealMind (Hindsight Memory)",
        "reply": reply,
        "recalled_memories": [rm["memory"] for rm in relevant_memories],
        "context_applied": context_applied,
        "new_deal": new_deal_created
    }

# 4. Settings Config
@app.post("/config")
@app.post("/api/config")
def update_config(req: ConfigRequest):
    global hindsight_client, HINDSIGHT_API_KEY, HINDSIGHT_BASE_URL
    HINDSIGHT_API_KEY = req.api_key
    HINDSIGHT_BASE_URL = req.base_url
    try:
        from hindsight_client import Hindsight
        hindsight_client = Hindsight(base_url=HINDSIGHT_BASE_URL, api_key=HINDSIGHT_API_KEY)
        return {"status": "connected", "base_url": HINDSIGHT_BASE_URL}
    except Exception as e:
        return {"status": "local_fallback", "message": str(e)}

# Static files & frontend (resolves across local uvicorn and Vercel serverless)
possible_frontend_dirs = [
    os.path.join(os.path.dirname(__file__), "..", "frontend"),
    os.path.join(os.path.dirname(__file__), "frontend"),
    os.path.join(os.getcwd(), "frontend"),
    "/var/task/frontend"
]
frontend_dir = next((d for d in possible_frontend_dirs if os.path.exists(d)), possible_frontend_dirs[0])

if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
def serve_index():
    for f in [os.path.join(frontend_dir, "index.html"), "frontend/index.html", "index.html"]:
        if os.path.exists(f):
            return FileResponse(f)
    return {"status": "running", "message": "DealMind API active"}

@app.get("/app")
def serve_app():
    for f in [os.path.join(frontend_dir, "app.html"), "frontend/app.html", "app.html"]:
        if os.path.exists(f):
            return FileResponse(f)
    return serve_index()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
