import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
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
    raise RuntimeError(
        "SUPABASE_URL is missing from the environment."
    )

if not SUPABASE_KEY:
    raise RuntimeError(
        "SUPABASE_KEY is missing from the environment."
    )

if not SCANNER_API_KEY:
    raise RuntimeError(
        "SCANNER_API_KEY is missing from the environment."
    )

if not ORCHESTRATOR_FILE.exists():
    raise RuntimeError(
        f"scanner_orchestrator.py was not found at: "
        f"{ORCHESTRATOR_FILE}"
    )


supabase: Client = create_client(
    SUPABASE_URL.strip(),
    SUPABASE_KEY.strip(),
)


# ---------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------

app = FastAPI(
    title="Nyro Scanner API",
    version="1.1.0",
)


# During development, allow Lovable and browser testing.
# This should be restricted to known frontend domains later.
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


def verify_api_key(
    x_api_key: str = Header(None),
) -> None:
    """
    Verify that the request contains the correct scanner API key.
    """

    if x_api_key != SCANNER_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key.",
        )


def get_scanner_control() -> dict:
    """
    Return the scanner_control record.
    """

    response = (
        supabase
        .table("scanner_control")
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


def update_scanner_control(
    values: dict,
) -> dict:
    """
    Update the scanner_control record.
    """

    control = get_scanner_control()

    update_values = dict(values)
    update_values["updated_at"] = utc_now_iso()

    response = (
        supabase
        .table("scanner_control")
        .update(update_values)
        .eq("id", control["id"])
        .execute()
    )

    if not response.data:
        raise HTTPException(
            status_code=500,
            detail="scanner_control could not be updated.",
        )

    return response.data[0]


def get_latest_scan_run() -> dict | None:
    """
    Return the most recent scan_runs record.
    """

    response = (
        supabase
        .table("scan_runs")
        .select("*")
        .order("started_at", desc=True)
        .limit(1)
        .execute()
    )

    if not response.data:
        return None

    return response.data[0]


def get_recent_scan_runs(
    limit: int = 5,
) -> list:
    """
    Return recent scanner runs in reverse chronological order.
    """

    response = (
        supabase
        .table("scan_runs")
        .select("*")
        .order("started_at", desc=True)
        .limit(limit)
        .execute()
    )

    return response.data or []


def launch_scanner_process() -> None:
    """
    Start scanner_orchestrator.py as a separate process.

    The orchestrator remains responsible for:

    - checking whether scanning is enabled
    - preventing duplicate runs
    - creating scan_runs
    - setting status to running
    - completing the full portfolio scan
    - storing statistics
    - returning to idle or paused
    """

    subprocess.Popen(
        [
            sys.executable,
            str(ORCHESTRATOR_FILE),
        ],
        cwd=str(BASE_DIR),
        creationflags=(
            subprocess.CREATE_NEW_PROCESS_GROUP
            if os.name == "nt"
            else 0
        ),
    )


# ---------------------------------------------------------
# Health
# ---------------------------------------------------------

@app.get("/")
def health_check():
    return {
        "success": True,
        "service": "Nyro Scanner API",
        "version": "1.1.0",
        "message": "Scanner API is online.",
    }


# ---------------------------------------------------------
# Scanner status
# ---------------------------------------------------------

@app.get("/scanner/status")
def scanner_status():
    control = get_scanner_control()
    latest_run = get_latest_scan_run()

    return {
        "success": True,
        "scanner": control,
        "latest_run": latest_run,
    }


# ---------------------------------------------------------
# Scanner history
# ---------------------------------------------------------

@app.get("/scanner/history")
def scanner_history():
    runs = get_recent_scan_runs(
        limit=5,
    )

    return {
        "success": True,
        "runs": runs,
    }


# ---------------------------------------------------------
# Today's / latest scan summary
# ---------------------------------------------------------

@app.get("/scanner/today")
def scanner_today():
    """
    Return statistics from the most recent scanner run.

    For now this endpoint uses the latest run rather than
    aggregating multiple runs from the same calendar day.
    That matches the Scanner dashboard's current purpose:
    show the results of the latest completed scan.
    """

    latest_run = get_latest_scan_run()

    if not latest_run:
        return {
            "success": True,
            "run": None,
            "summary": {
                "properties_scanned": 0,
                "new_listings": 0,
                "price_reductions": 0,
                "relisted_properties": 0,
                "off_market_properties": 0,
                "events_created": 0,
                "drafts_created": 0,
                "errors": 0,
            },
        }

    return {
        "success": True,
        "run": latest_run,
        "summary": {
            "properties_scanned": (
                latest_run.get("properties_checked", 0)
            ),
            "new_listings": (
                latest_run.get("new_listings", 0)
            ),
            "price_reductions": (
                latest_run.get("price_reductions", 0)
            ),
            "relisted_properties": (
                latest_run.get("relisted_properties", 0)
            ),
            "off_market_properties": (
                latest_run.get("off_market_properties", 0)
            ),
            "events_created": (
                latest_run.get("events_created", 0)
            ),
            "drafts_created": (
                latest_run.get("drafts_created", 0)
            ),
            "errors": (
                latest_run.get("errors_count", 0)
            ),
        },
    }


# ---------------------------------------------------------
# Manual scanner run
# ---------------------------------------------------------

@app.post("/scanner/run")
def run_scanner(
    x_api_key: str = Header(None),
):
    verify_api_key(x_api_key)

    control = get_scanner_control()

    if not control.get("enabled", False):
        raise HTTPException(
            status_code=409,
            detail=(
                "The scanner is paused. "
                "Resume it before starting a scan."
            ),
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


# ---------------------------------------------------------
# Pause scanner
# ---------------------------------------------------------

@app.post("/scanner/pause")
def pause_scanner(
    x_api_key: str = Header(None),
):
    verify_api_key(x_api_key)

    control = get_scanner_control()
    current_status = control.get("status")

    # Important:
    # Pause NEVER interrupts an active scanner run.
    # It only prevents future runs.
    if current_status == "running":
        updated = update_scanner_control(
            {
                "enabled": False,
            }
        )

        message = (
            "Scanner paused for future runs. "
            "The current scan will continue until completion."
        )

    else:
        updated = update_scanner_control(
            {
                "enabled": False,
                "status": "paused",
            }
        )

        message = (
            "Scanner paused. "
            "Future scans are disabled."
        )

    return {
        "success": True,
        "message": message,
        "scanner": updated,
    }


# ---------------------------------------------------------
# Resume scanner
# ---------------------------------------------------------

@app.post("/scanner/resume")
def resume_scanner(
    x_api_key: str = Header(None),
):
    verify_api_key(x_api_key)

    control = get_scanner_control()

    if control.get("status") == "running":
        updated = update_scanner_control(
            {
                "enabled": True,
            }
        )

        message = (
            "Future scans have been enabled. "
            "The current scan is still running."
        )

    else:
        updated = update_scanner_control(
            {
                "enabled": True,
                "status": "idle",
                "last_error": None,
            }
        )

        message = (
            "Scanner resumed and is ready to run."
        )

    return {
        "success": True,
        "message": message,
        "scanner": updated,
    }