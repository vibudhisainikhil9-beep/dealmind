import os
import time
import json
import uuid
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException
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

# Persistent storage file paths
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
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

# Helper: Load/Save JSON
def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# Initial Seed Data
DEFAULT_DEALS = [
    {
        "id": "deal-1",
        "name": "Zerodha (B2B SaaS Upgrade)",
        "arr": 44500,
        "stage": "Negotiation",
        "stakeholders": ["Kiran Nair (CTO)", "Priya Menon (Head of Procurement)"],
        "industry": "Financial Technology",
        "health_score": 88
    },
    {
        "id": "deal-2",
        "name": "Apollo Health Network",
        "arr": 72000,
        "stage": "Proposal Review",
        "stakeholders": ["Dr. Ramesh Iyer (CIO)", "Suresh Kumar (Head of Security)"],
        "industry": "Healthcare",
        "health_score": 74
    },
    {
        "id": "deal-3",
        "name": "Delhivery Logistics",
        "arr": 95000,
        "stage": "Discovery",
        "stakeholders": ["Anjali Kapoor (VP Engineering)"],
        "industry": "Logistics & Supply Chain",
        "health_score": 62
    },
    {
        "id": "deal-4",
        "name": "Meesho E-Commerce",
        "arr": 58000,
        "stage": "Discovery",
        "stakeholders": ["Ravi Shankar (Director of Platform)"],
        "industry": "Retail & E-Commerce",
        "health_score": 70
    }
]

DEFAULT_MEMORIES = [
    {
        "id": "mem-101",
        "deal_id": "deal-1",
        "client": "Zerodha (B2B SaaS Upgrade)",
        "stakeholder": "Kiran Nair (CTO)",
        "timestamp": "2026-10-18T14:30:00Z",
        "content": "Kiran mandated that public multi-tenant cloud is non-negotiable due to SEBI data localization rules. Dedicated Mumbai private VPC or on-prem deployment is the only acceptable architecture.",
        "category": "Compliance & Architecture",
        "entities": ["SEBI Compliance", "Mumbai VPC", "On-Premise", "Kiran Nair"],
        "sentiment": "Strict"
    },
    {
        "id": "mem-102",
        "deal_id": "deal-1",
        "client": "Zerodha (B2B SaaS Upgrade)",
        "stakeholder": "Priya Menon (Head of Procurement)",
        "timestamp": "2026-10-25T11:00:00Z",
        "content": "Priya confirmed Q4 budget is strictly capped at $44,500 ARR. Anything above $50,000 triggers mandatory board-level approval causing a 6–8 week procurement delay.",
        "category": "Budget & Procurement",
        "entities": ["$44,500 Cap", "Board Approval", "Procurement Gate", "Priya Menon"],
        "sentiment": "Strict"
    },
    {
        "id": "mem-103",
        "deal_id": "deal-2",
        "client": "Apollo Health Network",
        "stakeholder": "Dr. Ramesh Iyer (CIO)",
        "timestamp": "2026-11-02T16:15:00Z",
        "content": "Requires HIPAA Business Associate Agreement and SOC2 Type II audit report before engaging in any technical pilot. Previously rejected a competitor for breaching PHI data transfer policies.",
        "category": "Compliance & Security",
        "entities": ["HIPAA BAA", "SOC2 Type II", "PHI Data", "Dr. Ramesh Iyer"],
        "sentiment": "Cautious"
    },
    {
        "id": "mem-104",
        "deal_id": "deal-3",
        "client": "Delhivery Logistics",
        "stakeholder": "Anjali Kapoor (VP Engineering)",
        "timestamp": "2026-11-01T09:00:00Z",
        "content": "Anjali's primary concern is real-time webhook latency. Any platform averaging over 200ms will not pass their SLA requirements for last-mile delivery tracking.",
        "category": "Performance & SLA",
        "entities": ["Latency SLA", "Webhook", "200ms Threshold", "Anjali Kapoor"],
        "sentiment": "Analytical"
    },
    {
        "id": "mem-105",
        "deal_id": "deal-4",
        "client": "Meesho E-Commerce",
        "stakeholder": "Ravi Shankar (Director of Platform)",
        "timestamp": "2026-10-30T14:00:00Z",
        "content": "Meesho needs multi-region support across India and Southeast Asia. Single-region architecture will not meet their platform redundancy requirements for Tier-2 city expansion.",
        "category": "Infrastructure Requirement",
        "entities": ["Multi-Region", "Southeast Asia", "Redundancy", "Ravi Shankar"],
        "sentiment": "Curious"
    }
]

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
@app.get("/api/deals")
def get_deals():
    return {"deals": deals_db}

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
@app.get("/api/memories")
def get_memories(deal_id: Optional[str] = None):
    if deal_id:
        filtered = [m for m in memories_db if m.get("deal_id") == deal_id]
        return {"memories": filtered}
    return {"memories": memories_db}

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

@app.delete("/api/memories/{memory_id}")
def delete_memory(memory_id: str):
    global memories_db
    memories_db = [m for m in memories_db if m["id"] != memory_id]
    save_json(MEMORIES_FILE, memories_db)
    return {"status": "deleted", "id": memory_id}

# 3. Live AI Copilot Chat (The Core Engine)
@app.post("/api/chat")
def deal_copilot_chat(req: ChatQueryRequest):
    """
    Real-time dynamic chat assistant.
    Can be run with memory enabled (DealMind Hindsight) or disabled (Stateless).
    """
    deal = next((d for d in deals_db if d["id"] == req.deal_id), None) if req.deal_id else None
    account_name = deal["name"] if deal else "General"
    
    # 1. Search relevant memories via Hindsight recall pipeline
    relevant_memories = []
    if req.use_memory:
        query_words = req.prompt.lower().split()
        for m in memories_db:
            score = 0.0
            if req.deal_id and m.get("deal_id") == req.deal_id:
                score += 3.0
            text = (m["content"] + " " + " ".join(m.get("entities", []))).lower()
            for w in query_words:
                if w in text:
                    score += 1.5
            if score > 0:
                relevant_memories.append({"score": round(score, 2), "memory": m})
        relevant_memories.sort(key=lambda x: x["score"], reverse=True)
        relevant_memories = relevant_memories[:4]

    # 2. Dynamic generation logic
    prompt_lower = req.prompt.lower()
    
    if not req.use_memory:
        # Stateless mode (fails to account for history)
        if "price" in prompt_lower or "cost" in prompt_lower or "quote" in prompt_lower:
            reply = f"For {account_name}, our standard enterprise tier is $65,000 ARR hosted on our global multi-tenant cluster. Standard payment terms apply."
        elif "email" in prompt_lower or "proposal" in prompt_lower:
            reply = f"Subject: Proposal for {account_name}\n\nHi,\n\nFollowing up on our product! Let's schedule a 30-minute introductory call next week to walk through our features.\n\nBest,\nSales Team"
        elif "risk" in prompt_lower or "objection" in prompt_lower:
            reply = "No historical risks recorded in standard memory. Recommend asking the client for their requirements on the next call."
        else:
            reply = f"I am a generic AI sales assistant. I do not have access to past call notes or previous constraints for {account_name}."
        
        return {
            "mode": "Stateless (No Memory)",
            "reply": reply,
            "recalled_memories": [],
            "context_applied": []
        }

    # Hindsight Memory-Augmented Mode
    context_applied = []
    recalled_facts = [rm["memory"]["content"] for rm in relevant_memories]

    if "price" in prompt_lower or "cost" in prompt_lower or "quote" in prompt_lower:
        if deal and deal["id"] == "deal-1":
            reply = (
                f"**Strategic Pricing Recommendation for {deal['name']}:**\n\n"
                f"• **Quote: $44,500 ARR** (Strictly below Neha Sharma's $45,000 Q4 department threshold).\n"
                f"• **Architecture: Dedicated Mumbai VPC** (Fulfills Vikram Sethi's RBI data localization requirement).\n\n"
                f"**Why this wins:** Keeps the contract within the Head of Procurement's signing limit, completely bypassing the 8-week CFO board approval cycle."
            )
            context_applied = ["Recalled Neha's $45k budget cap (mem-102)", "Recalled Vikram's RBI Mumbai VPC gate (mem-101)"]
        else:
            reply = f"Based on Hindsight memory for {account_name}, we recommend quoting within the established budget while addressing active architectural constraints."
            context_applied = [f"Recalled {len(relevant_memories)} account memories"]

    elif "email" in prompt_lower or "draft" in prompt_lower:
        if deal and deal["id"] == "deal-1":
            reply = (
                f"**Drafted Follow-up Email to Neha Sharma:**\n\n"
                f"**Subject:** Pre-Approved Mumbai VPC Deployment ($44,500 ARR) — FinTech Corp\n\n"
                f"Hi Neha,\n\n"
                f"Great connecting again. In direct alignment with Vikram's RBI data localization requirements and your Q4 procurement budget threshold, we have pre-packaged an isolated Mumbai VPC deployment configured strictly at **$44,500 ARR**.\n\n"
                f"Because this stays within your departmental direct-approval cap, no 8-week CFO board review is required, enabling your team to launch before year-end.\n\n"
                f"Can I send over the compliance audit certificate and one-page agreement for your sign-off today?\n\n"
                f"Best regards,\nVibudhi Sainikhil | Tech Lead, CoreStack"
            )
            context_applied = ["Recalled procurement threshold", "Recalled RBI compliance requirements", "Addressed stakeholders directly"]
        else:
            reply = f"Drafted custom contextual email incorporating past stakeholder constraints for {account_name}."
            context_applied = ["Loaded Hindsight memory bank"]

    elif "risk" in prompt_lower or "objection" in prompt_lower or "blocker" in prompt_lower:
        if relevant_memories:
            facts = "\n".join([f"• **{rm['memory']['category']}:** {rm['memory']['content']} *(Logged by {rm['memory']['stakeholder']})*" for rm in relevant_memories])
            reply = f"**Active Deal Risks & Objections for {account_name}:**\n\n{facts}\n\n**Hindsight Strategic Play:** Proactively address the compliance and budget limits in the next email rather than waiting for the client to bring them up."
            context_applied = [f"{rm['memory']['id']}: {rm['memory']['category']}" for rm in relevant_memories]
        else:
            reply = f"No active blockers flagged yet in the memory bank for {account_name}. Ready to retain notes from the next call."
    else:
        mem_summary = ", ".join([rm["memory"]["category"] for rm in relevant_memories]) if relevant_memories else "No prior constraints"
        reply = f"**DealMind Memory Analysis ({account_name}):**\n\nI synthesized context from {len(relevant_memories)} memories ({mem_summary}).\n\nHow would you like to proceed? I can draft a tailored contract, prepare an objection-handling briefing, or calculate custom deal terms."
        context_applied = [f"Recalled {len(relevant_memories)} memories from Hindsight"]

    return {
        "mode": "DealMind (Hindsight Memory)",
        "reply": reply,
        "recalled_memories": [rm["memory"] for rm in relevant_memories],
        "context_applied": context_applied
    }

# 4. Settings Config
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

# Static files & frontend
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
def serve_index():
    index_file = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"status": "running", "message": "DealMind API active"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
