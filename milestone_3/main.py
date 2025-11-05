# ivr_simulator_backend_with_twilio.py
# Full backend with Twilio adapter endpoints
from fastapi import FastAPI, HTTPException, Query, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import random

app = FastAPI(title="Harshvardhan IVR Backend + Twilio", version="1.0.0")

# CORS (frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- CONFIG ----------------
# If you run ngrok and want to hardcode the public URL for Twilio action URLs,
# set NGROK_HOST to something like "tendenciously-nonhostile-letha.ngrok-free.dev"
# Leave empty "" to use Host header (works in many setups but sometimes fragile).
NGROK_HOST = ""  # e.g. "abcd-1234.ngrok-free.app"

# ---------------- Models ----------------
class CallStart(BaseModel):
    caller_number: str
    call_id: Optional[str] = None

class DTMFInput(BaseModel):
    call_id: str
    digit: str
    current_menu: str

# ---------------- In-memory ----------------
active_calls = {}
call_history = []

# ---------------- MENU (same as your Harsh version) ----------------
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
    "booking": {
        "prompt": "Booking — Press 1 New booking, 2 Modify booking, 3 Cancel booking, 0 Back to main.",
        "options": {
            "1": {"action": "end", "msg": "New booking selected. Our booking team will call you."},
            "2": {"action": "end", "msg": "Modify booking selected. We will email details."},
            "3": {"action": "end", "msg": "Cancel booking selected. Refund policy explained via email."},
            "0": {"action": "goto", "target": "main", "msg": "Returning to main menu."}
        }
    },
    "flight_status": {
        "prompt": "Please type your 6-digit PNR followed by the hash.",
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

# ---------------- helpers ----------------
def create_session(caller_number: str):
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
    print(f"[SESSION] {cid} from {caller_number}")
    return cid

# ---------- existing endpoints (same behavior) ----------
@app.get("/")
def root():
    return {"status":"HarshIVR Running","active_calls":len(active_calls),"total_calls":len(call_history)}

@app.post("/ivr/start")
def ivr_start(payload: CallStart):
    cid = create_session(payload.caller_number)
    return {"call_id":cid,"status":"connected","prompt":MENU["main"]["prompt"]}

@app.post("/ivr/dtmf")
def ivr_dtmf(data: DTMFInput):
    call_id = data.call_id
    digit = data.digit
    if call_id not in active_calls:
        raise HTTPException(status_code=404,detail="session missing")
    session = active_calls[call_id]
    menu_key = session["current_menu"]
    session["inputs"].append(digit)
    print(f"[DTMF] {call_id} @ {menu_key} -> {digit}")
    menu = MENU.get(menu_key)
    if not menu:
        return {"status":"error","message":"bad menu"}
    # PNR collecting
    if menu_key == "flight_status" and digit != "#":
        if digit.isdigit():
            session["pnr_buffer"] += digit
            if len(session["pnr_buffer"]) < 6:
                return {"status":"collecting","prompt":f"Digit received. Enter more digits.","collected":session["pnr_buffer"]}
            else:
                return {"status":"collecting","prompt":"6 digits received. Press # to confirm or * to restart.","collected":session["pnr_buffer"]}
        else:
            return {"status":"invalid","prompt":"Please enter digits only for PNR."}
    options = menu.get("options",{})
    if digit not in options:
        return {"status":"invalid","prompt":"Invalid option. Try again.","valid":list(options.keys())}
    opt = options[digit]; action = opt["action"]; msg = opt.get("msg","")
    if action == "goto":
        target = opt["target"]; session["current_menu"] = target; session["menu_path"].append(target)
        return {"status":"processed","message":msg,"prompt":MENU[target]["prompt"],"current_menu":target}
    if action == "end":
        session["end_time"] = datetime.now().isoformat(); call_history.append(session.copy()); del active_calls[call_id]
        return {"status":"call_ended","message":msg,"call_action":"hangup"}
    if action == "transfer":
        session["end_time"] = datetime.now().isoformat(); call_history.append(session.copy()); del active_calls[call_id]
        return {"status":"transferring","message":msg,"call_action":"transfer"}
    if action == "lookup_pnr":
        pnr = session.get("pnr_buffer","")
        if len(pnr)==6:
            info = {"pnr":pnr,"flight":"HS123","status":"Confirmed","route":"Pune->Mumbai"}
            session["end_time"] = datetime.now().isoformat(); call_history.append(session.copy()); del active_calls[call_id]
            return {"status":"pnr_found","message":f"PNR {pnr} confirmed. Flight {info['flight']} {info['route']}"}
        else:
            session["pnr_buffer"] = ""; return {"status":"invalid_pnr","message":"PNR incomplete. Returning to main.","call_action":"hangup"}
    return {"status":"error","message":"unhandled"}

@app.post("/ivr/end")
def ivr_end(call_id: str = Query(...)):
    if call_id in active_calls:
        s = active_calls[call_id]; s["end_time"] = datetime.now().isoformat(); call_history.append(s.copy()); del active_calls[call_id]
        return {"status":"ended","call_id":call_id}
    return {"status":"not_found","call_id":call_id}

# ---------------- Twilio adapter ----------------
@app.post("/voice")
async def voice_for_twilio(request: Request):
    """
    Twilio calls this URL (A Call Comes In).
    We create internal session mapped to caller number and return TwiML with Gather -> /twilio/dtmf
    """
    form = await request.form()
    caller = form.get("From","unknown")
    cid = create_session(caller)
    # build action_url: prefer hardcoded NGROK_HOST if set (safer during testing)
    if NGROK_HOST:
        action_url = f"https://{NGROK_HOST}/twilio/dtmf"
    else:
        host = request.headers.get("host","")
        action_url = f"https://{host}/twilio/dtmf" if host else "/twilio/dtmf"
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice">{MENU['main']['prompt']}</Say>
  <Gather action="{action_url}" method="POST" numDigits="1" timeout="8">
    <!-- waiting for one DTMF digit -->
  </Gather>
  <Say voice="alice">No input received. Goodbye.</Say>
  <Hangup/>
</Response>"""
    print(f"[TWILIO] New call mapped to {cid} from {caller}")
    return PlainTextResponse(content=twiml, media_type="application/xml")

@app.post("/twilio/dtmf")
async def twilio_dtmf(request: Request, Digits: Optional[str] = Form(None), From: Optional[str] = Form(None), CallSid: Optional[str] = Form(None)):
    """
    Twilio POSTs here after Gather. We find internal session by 'From' number and relay to our ivr_dtmf logic.
    Then return TwiML based on result.
    """
    form = await request.form()
    digits = form.get("Digits") or Digits or ""
    caller = form.get("From") or From or ""
    print(f"[TWILIO] Digits={digits} From={caller} CallSid={CallSid}")

    # find session by caller (last created wins) — fine for testing
    matched = None
    for cid, sess in active_calls.items():
        if sess.get("caller_number") == caller:
            matched = cid
            break
    if not matched:
        # fallback: create one
        matched = create_session(caller)
        print(f"[TWILIO] Fallback session {matched}")

    # call internal handler
    payload = DTMFInput(call_id=matched, digit=str(digits), current_menu=active_calls[matched]["current_menu"])
    result = ivr_dtmf(payload)  # call internal function directly

    # Build TwiML based on result
    if result.get("status") in ("call_ended",) or result.get("call_action")=="hangup":
        content = result.get("message","Thank you. Goodbye.")
        twiml = f"<?xml version='1.0' encoding='UTF-8'?><Response><Say voice='alice'>{content}</Say><Hangup/></Response>"
        return PlainTextResponse(content=twiml, media_type="application/xml")

    if result.get("status") in ("processed",):
        prompt = result.get("prompt") or result.get("message") or ""
        if NGROK_HOST:
            action_url = f"https://{NGROK_HOST}/twilio/dtmf"
        else:
            host = request.headers.get("host","")
            action_url = f"https://{host}/twilio/dtmf" if host else "/twilio/dtmf"
        twiml = f"<?xml version='1.0' encoding='UTF-8'?><Response><Say voice='alice'>{prompt}</Say><Gather action='{action_url}' method='POST' numDigits='1' timeout='8'></Gather><Say voice='alice'>No input received. Goodbye.</Say><Hangup/></Response>"
        return PlainTextResponse(content=twiml, media_type="application/xml")

    if result.get("status") in ("collecting","invalid"):
        prompt = result.get("prompt") or result.get("message") or "Please enter digits."
        if NGROK_HOST:
            action_url = f"https://{NGROK_HOST}/twilio/dtmf"
        else:
            host = request.headers.get("host","")
            action_url = f"https://{host}/twilio/dtmf" if host else "/twilio/dtmf"
        twiml = f"<?xml version='1.0' encoding='UTF-8'?><Response><Say voice='alice'>{prompt}</Say><Gather action='{action_url}' method='POST' numDigits='1' timeout='8'></Gather></Response>"
        return PlainTextResponse(content=twiml, media_type="application/xml")

    if result.get("status") == "pnr_found":
        twiml = f"<?xml version='1.0' encoding='UTF-8'?><Response><Say voice='alice'>{result.get('message')}</Say><Hangup/></Response>"
        return PlainTextResponse(content=twiml, media_type="application/xml")

    # fallback error
    twiml = "<?xml version='1.0' encoding='UTF-8'?><Response><Say voice='alice'>Sorry, something went wrong. Goodbye.</Say><Hangup/></Response>"
    return PlainTextResponse(content=twiml, media_type="application/xml")
