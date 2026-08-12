import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from supabase import Client, create_client


# ---------------------------------------------------------
# Environment and paths
# ---------------------------------------------------------

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
ORCHESTRATOR_FILE = BASE_DIR / "scanner_orchestrator.py"

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SCANNER_API_KEY = os.getenv("SCANNER_API_KEY")

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL is missing from the .env file.")

if not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY is missing from the .env file.")

if not ORCHESTRATOR_FILE.exists():
    raise RuntimeError(
        f"scanner_orchestrator.py was not found at: {ORCHESTRATOR_FILE}"
    )


supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ---------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------

app = FastAPI(
    title="Nyro Scanner API",
    version="1.0.0",
)


# During development, Lovable can call the API from its preview domain.
# We will restrict this later when the production domain is known.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_scanner_control() -> dict:
    response = (
        supabase.table("scanner_control")
        .select("*")
        .limit(1)
        .execute()
    )

    if not response.data:
        raise HTTPException(
            status_code=404,
            detail="No scanner_control row was found.",
        )

    return response.data[0]


def update_scanner_control(values: dict) -> dict:
    control = get_scanner_control()

    values["updated_at"] = utc_now_iso()

    response = (
        supabase.table("scanner_control")
        .update(values)
        .eq("id", control["id"])
        .execute()
    )

    if not response.data:
        raise HTTPException(
            status_code=500,
            detail="scanner_control could not be updated.",
        )

    return response.data[0]


def launch_scanner_process() -> None:
    """
    Starts scanner_orchestrator.py as a separate Python process.

    The orchestrator itself remains responsible for:
    - checking whether scanning is enabled
    - preventing duplicate runs
    - creating scan_runs
    - changing status to running
    - completing the full scan
    - returning to idle or paused
    """

    subprocess.Popen(
        [sys.executable, str(ORCHESTRATOR_FILE)],
        cwd=str(BASE_DIR),
        creationflags=(
            subprocess.CREATE_NEW_PROCESS_GROUP
            if os.name == "nt"
            else 0
        ),
    )

def verify_api_key(x_api_key: str = Header(None)) -> None:
    """
    Verifies that the request contains the correct API key.
    """

    if x_api_key != SCANNER_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key.",
        )
# ---------------------------------------------------------
# Routes
# ---------------------------------------------------------

@app.get("/")
def health_check():
    return {
        "success": True,
        "service": "Nyro Scanner API",
        "message": "Scanner API is online.",
    }


@app.get("/scanner/status")
def scanner_status():
    control = get_scanner_control()

    return {
        "success": True,
        "scanner": control,
    }


@app.post("/scanner/run")
def run_scanner(x_api_key: str = Header(None)):
    verify_api_key(x_api_key)
    control = get_scanner_control()

    if not control.get("enabled", False):
        raise HTTPException(
            status_code=409,
            detail="The scanner is paused. Resume it before starting a scan.",
        )

    if control.get("status") == "running":
        raise HTTPException(
            status_code=409,
            detail="A scanner run is already in progress.",
        )

    launch_scanner_process()

    return {
        "success": True,
        "message": "Scanner launch requested.",
    }


@app.post("/scanner/pause")
def pause_scanner(x_api_key: str = Header(None)):
    verify_api_key(x_api_key)
    control = get_scanner_control()

    current_status = control.get("status")

    # A running scan must always finish.
    # Only future scans are disabled.
    if current_status == "running":
        updated = update_scanner_control({
            "enabled": False,
        })

        message = (
            "Scanner paused for future runs. "
            "The current scan will continue until completion."
        )

    else:
        updated = update_scanner_control({
            "enabled": False,
            "status": "paused",
        })

        message = "Scanner paused. Future scans are disabled."

    return {
        "success": True,
        "message": message,
        "scanner": updated,
    }


@app.post("/scanner/resume")
def resume_scanner(x_api_key: str = Header(None)):
    verify_api_key(x_api_key)
    control = get_scanner_control()

    if control.get("status") == "running":
        updated = update_scanner_control({
            "enabled": True,
        })

        message = (
            "Future scans have been enabled. "
            "The current scan is still running."
        )

    else:
        updated = update_scanner_control({
            "enabled": True,
            "status": "idle",
            "last_error": None,
        })

        message = "Scanner resumed and is ready to run."

    return {
        "success": True,
        "message": message,
        "scanner": updated,
    }