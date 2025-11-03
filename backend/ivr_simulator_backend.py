# ivr_simulator_backend.py
# Harshvardhan-style IVR backend (refactored, original-looking)
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import random

app = FastAPI(title="Harshvardhan IVR Backend", version="1.0.0")

# allow frontend fetches (local dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------ Data models ------------------
class CallStart(BaseModel):
    caller_number: str
    call_id: Optional[str] = None

class DTMFInput(BaseModel):
    call_id: str
    digit: str
    current_menu: str

class CallRecord(BaseModel):
    call_id: str
    caller_number: str
    start_time: str
    end_time: Optional[str] = None
    duration: Optional[int] = None
    menu_path: List[str] = []
    inputs: List[str] = []

# ------------------ In-memory store ------------------
active_calls = {}   # call_id -> session dict
call_history = []   # archived sessions

# ------------------ Fresh menu structure (1..9 handled) ------------------
# This menu is intentionally worded differently (Harshvardhan style)
MENU = {
    "main": {
        "prompt": "Welcome to HarshAir. For quick access press:\n1 Booking\n2 Flight Status\n3 Baggage Help\n4 Refunds & Cancellations\n5 Seat Selection\n6 Loyalty & Miles\n7 Travel Advisory\n8 Feedback\n9 Talk to Agent",
        "options": {
            "1": {"action": "goto", "target": "booking", "msg": "Booking selected. Redirecting to booking options."},
            "2": {"action": "goto", "target": "flight_status", "msg": "Flight Status selected. We will ask for your PNR."},
            "3": {"action": "goto", "target": "baggage", "msg": "Baggage help. Few options coming up."},
            "4": {"action": "goto", "target": "refunds", "msg": "Refunds & cancellations. Please choose."},
            "5": {"action": "goto", "target": "seat", "msg": "Seat selection. Help coming."},
            "6": {"action": "goto", "target": "loyalty", "msg": "Loyalty program options."},
            "7": {"action": "goto", "target": "advisory", "msg": "Travel advisory and guidelines."},
            "8": {"action": "goto", "target": "feedback", "msg": "We appreciate feedback. Short survey."},
            "9": {"action": "transfer", "msg": "Connecting to an agent. Please hold."}
        }
    },

    # Booking submenu
    "booking": {
        "prompt": "Booking — Press 1 New booking, 2 Modify booking, 3 Cancel booking, 0 Back to main.",
        "options": {
            "1": {"action": "end", "msg": "New booking selected. Our booking team will call you."},
            "2": {"action": "end", "msg": "Modify booking selected. We will email details."},
            "3": {"action": "end", "msg": "Cancel booking selected. Refund policy explained via email."},
            "0": {"action": "goto", "target": "main", "msg": "Returning to main menu."}
        }
    },

    # Flight status expects 6-digit PNR then '#'
    "flight_status": {
        "prompt": "Please type your 6-digit PNR followed by the hash key.",
        "options": {
            "#": {"action": "lookup_pnr", "msg": "Checking PNR..."}
        }
    },

    "baggage": {
        "prompt": "Baggage — Press 1 Lost item, 2 Excess baggage charges, 0 Back.",
        "options": {
            "1": {"action": "end", "msg": "Lost item reported. We'll initiate tracing."},
            "2": {"action": "end", "msg": "Excess baggage info: charges apply as per fare rules."},
            "0": {"action": "goto", "target": "main", "msg": "Back to main menu."}
        }
    },

    "refunds": {
        "prompt": "Refunds — Press 1 Fare rules, 2 Request refund, 0 Back.",
        "options": {
            "1": {"action": "end", "msg": "Fare rules guided to your email."},
            "2": {"action": "end", "msg": "Refund request received. We will process it."},
            "0": {"action": "goto", "target": "main", "msg": "Back to main."}
        }
    },

    "seat": {
        "prompt": "Seat Selection — Press 1 Aisle, 2 Window, 3 Extra legroom, 0 Back.",
        "options": {
            "1": {"action": "end", "msg": "Aisle preference noted."},
            "2": {"action": "end", "msg": "Window preference noted."},
            "3": {"action": "end", "msg": "Extra legroom request recorded."},
            "0": {"action": "goto", "target": "main", "msg": "Back to main."}
        }
    },

    "loyalty": {
        "prompt": "Loyalty — Press 1 Check miles, 2 Redeem miles, 0 Back.",
        "options": {
            "1": {"action": "end", "msg": "Miles balance will be sent to your registered email."},
            "2": {"action": "end", "msg": "Redeem flow initiated. Agent will assist."},
            "0": {"action": "goto", "target": "main", "msg": "Back to main."}
        }
    },

    "advisory": {
        "prompt": "Travel advisory — Press 1 Covid rules, 2 Visa & docs, 0 Back.",
        "options": {
            "1": {"action": "end", "msg": "Covid travel guidelines: check official site."},
            "2": {"action": "end", "msg": "Visa & docs details: refer to airline website."},
            "0": {"action": "goto", "target": "main", "msg": "Back to main."}
        }
    },

    "feedback": {
        "prompt": "Feedback — Press 1 Rate 1-3, 2 Rate 4-5, 0 Back.",
        "options": {
            "1": {"action": "end", "msg": "Thanks for your feedback. We'll improve."},
            "2": {"action": "end", "msg": "Thanks! Glad you had a great experience."},
            "0": {"action": "goto", "target": "main", "msg": "Back to main."}
        }
    }
}

# ------------------ Helper utilities ------------------
def new_call_session(caller_number: str):
    """Create a fresh session structure for a call."""
    cid = f"CALL_{random.randint(100000,999999)}"
    active_calls[cid] = {
        "call_id": cid,
        "caller_number": caller_number,
        "start_time": datetime.now().isoformat(),
        "current_menu": "main",
        "menu_path": ["main"],
        "inputs": [],
        "pnr_buffer": ""
    }
    print(f"\n[SESSION] New call {cid} from {caller_number}")
    return cid

# ------------------ Endpoints (public) ------------------
@app.get("/")
def status():
    """Health + basic stats"""
    return {"status": "HarshIVR Running", "active_calls": len(active_calls), "total_calls": len(call_history)}

@app.post("/ivr/start")
def ivr_start(payload: CallStart):
    """Called by frontend to start a session"""
    cid = new_call_session(payload.caller_number)
    prompt_text = MENU["main"]["prompt"]
    return {"call_id": cid, "status": "connected", "prompt": prompt_text}

@app.post("/ivr/dtmf")
def ivr_dtmf(input_data: DTMFInput):
    """
    Core DTMF handling. This is the 'brain' — decides action based on current menu and digit.
    Returns a dict with status and optional prompt/current_menu info.
    """
    call_id = input_data.call_id
    digit = input_data.digit

    if call_id not in active_calls:
        raise HTTPException(status_code=404, detail="Call session not found")

    session = active_calls[call_id]
    menu_key = session["current_menu"]
    session["inputs"].append(digit)
    print(f"[DTMF] Call {call_id} at menu '{menu_key}' got digit '{digit}'")

    # menu lookup
    menu = MENU.get(menu_key)
    if not menu:
        return {"status":"error","message":"Invalid menu state"}

    # Special: flight_status collects digits until '#'
    if menu_key == "flight_status" and digit != "#":
        # accept only digits 0-9 for PNR accumulation
        if digit.isdigit():
            session["pnr_buffer"] += digit
            # if not yet 6 digits, ask to continue
            if len(session["pnr_buffer"]) < 6:
                return {"status":"collecting", "prompt": f"You entered {digit}. Enter remaining digits.", "collected": session["pnr_buffer"]}
            else:
                # we have 6 digits but wait for '#' to confirm; tell user to press hash
                return {"status":"collecting", "prompt": f"You entered 6 digits. Press # to confirm PNR or press * to restart.", "collected": session["pnr_buffer"]}
        else:
            return {"status":"invalid","prompt":"Only digits are allowed for PNR. Please enter numbers."}

    # standard option handling
    options = menu.get("options", {})
    # If digit not in options and we are not in collecting state -> invalid
    if digit not in options:
        return {"status":"invalid","prompt":"Invalid option. Please try again.", "valid": list(options.keys())}

    opt = options[digit]
    action = opt["action"]
    message = opt.get("msg", "")

    # handle actions
    if action == "goto":
        target = opt["target"]
        session["current_menu"] = target
        session["menu_path"].append(target)
        next_prompt = MENU[target]["prompt"]
        print(f"[NAV] Call {call_id} -> {target}")
        return {"status":"processed","message":message,"prompt":next_prompt,"current_menu":target}

    if action == "end":
        # finalize and remove session
        session["end_time"] = datetime.now().isoformat()
        call_history.append(session.copy())
        del active_calls[call_id]
        print(f"[END] Call {call_id} ended (by action).")
        return {"status":"call_ended","message":message,"call_action":"hangup"}

    if action == "transfer":
        # mark as transferred then remove session
        session["end_time"] = datetime.now().isoformat()
        call_history.append(session.copy())
        del active_calls[call_id]
        print(f"[TRANSFER] Call {call_id} transferred to agent.")
        return {"status":"transferring","message":message,"call_action":"transfer"}

    if action == "lookup_pnr":
        # validate collected buffer
        pnr = session.get("pnr_buffer","")
        if len(pnr) == 6:
            # mock lookup
            info = {"pnr":pnr,"flight":"HS123","status":"Confirmed","route":"Pune → Mumbai"}
            session["end_time"] = datetime.now().isoformat()
            call_history.append(session.copy()); del active_calls[call_id]
            print(f"[PNR] Call {call_id} PNR {pnr} found.")
            return {"status":"pnr_found","message":f"PNR {pnr} confirmed. Flight {info['flight']} {info['route']}."}
        else:
            session["pnr_buffer"] = ""  # reset buffer
            return {"status":"invalid_pnr","message":"PNR invalid or incomplete. Returning to main menu.","call_action":"hangup"}

    # fallback
    return {"status":"error","message":"Unhandled action"}

@app.post("/ivr/end")
def ivr_end(call_id: str = Query(...)):
    """User ended the call (frontend hangup). Archive if active."""
    if call_id in active_calls:
        session = active_calls[call_id]
        session["end_time"] = datetime.now().isoformat()
        call_history.append(session.copy())
        del active_calls[call_id]
        print(f"[HANGUP] Call {call_id} ended by user.")
        return {"status":"ended","call_id":call_id}
    return {"status":"not_found","call_id":call_id}
