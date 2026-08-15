import os
import sys
import traceback
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import Client, create_client

from scanner_v4 import run_scanner_v4


# ---------------------------------------------------------
# Environment
# ---------------------------------------------------------

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


if not SUPABASE_URL:
    raise RuntimeError(
        "SUPABASE_URL is missing from the environment."
    )

if not SUPABASE_KEY:
    raise RuntimeError(
        "SUPABASE_KEY is missing from the environment."
    )


supabase: Client = create_client(
    SUPABASE_URL.strip(),
    SUPABASE_KEY.strip(),
)


# ---------------------------------------------------------
# Time helpers
# ---------------------------------------------------------

def utc_now_iso() -> str:
    """
    Return the current UTC time as an ISO formatted string.
    """

    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------
# Scanner control helpers
# ---------------------------------------------------------

def get_scanner_control() -> dict:
    """
    Retrieve the scanner control record.

    For the current BM Estates version of Nyro there is
    one scanner_control row.
    """

    response = (
        supabase
        .table("scanner_control")
        .select("*")
        .limit(1)
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "No scanner_control row was returned."
        )

    return response.data[0]


def update_scanner_control(
    control_id: str,
    values: dict,
) -> None:
    """
    Update scanner_control with the supplied values.
    """

    update_values = dict(values)
    update_values["updated_at"] = utc_now_iso()

    response = (
        supabase
        .table("scanner_control")
        .update(update_values)
        .eq("id", control_id)
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "The scanner_control row could not be updated."
        )


# ---------------------------------------------------------
# Scan run helpers
# ---------------------------------------------------------

def create_scan_run(
    control_id: str,
    trigger_type: str,
) -> str:
    """
    Create a scan_runs record when a new scan begins.
    """

    response = (
        supabase
        .table("scan_runs")
        .insert(
            {
                "scanner_control_id": control_id,
                "trigger_type": trigger_type,
                "status": "running",
                "started_at": utc_now_iso(),
            }
        )
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "The scan_runs record could not be created."
        )

    return response.data[0]["id"]


def update_scan_run(
    run_id: str,
    values: dict,
) -> None:
    """
    Update an existing scan_runs record.
    """

    response = (
        supabase
        .table("scan_runs")
        .update(values)
        .eq("id", run_id)
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "The scan_runs record could not be updated."
        )


# ---------------------------------------------------------
# Scanner checks
# ---------------------------------------------------------

def scanner_can_start(control: dict) -> bool:
    """
    Determine whether a new scanner run is allowed.

    Pause never interrupts an existing scan.
    It only prevents future scans from starting.
    """

    if control.get("enabled") is False:
        print("")
        print("Scanner is paused.")
        print("No scan was started.")

        return False

    if control.get("status") == "paused":
        print("")
        print("Scanner is paused.")
        print("No scan was started.")

        return False

    if control.get("status") == "running":
        print("")
        print("A scanner run is already active.")
        print("No duplicate scan was started.")

        return False

    return True


def determine_final_control_status() -> str:
    """
    Determine what state the scanner should enter
    after the current full scan has completed.

    If the user pressed Pause while the scan was running,
    enabled will now be False and the completed scanner
    moves into the paused state.

    Otherwise it returns to idle.
    """

    latest_control = get_scanner_control()

    if latest_control.get("enabled") is False:
        return "paused"

    return "idle"


# ---------------------------------------------------------
# Scanner result helpers
# ---------------------------------------------------------

def get_run_status(result: dict) -> str:
    """
    Determine the final scan_runs status.

    A completely successful scan is marked success.

    If one or more individual properties failed but the
    scanner still completed the portfolio, mark the run
    partial rather than failed.
    """

    failed_count = result.get("failed", 0)

    if failed_count > 0:
        return "partial"

    return "success"


def save_successful_run(
    run_id: str,
    result: dict,
) -> str:
    """
    Save the real results returned by scanner_v4
    into scan_runs.

    This is the data Nyro will later use for:
    - Today's scan summary
    - Recent scan history
    - Scanner analytics
    """

    run_status = get_run_status(result)

    update_scan_run(
        run_id=run_id,
        values={
            "status": run_status,
            "finished_at": utc_now_iso(),
            "properties_checked": result.get(
                "processed",
                0,
            ),
            "events_created": result.get(
                "events_created",
                0,
            ),
            "errors_count": result.get(
                "failed",
                0,
            ),
            "error_message": None,
        },
    )

    return run_status


# ---------------------------------------------------------
# Main scanner orchestrator
# ---------------------------------------------------------

def run_scanner(
    trigger_type: str = "manual",
) -> None:
    """
    Run the complete Nyro property scanning process.

    Responsibilities:

    1. Read scanner_control.
    2. Confirm scanning is enabled.
    3. Prevent duplicate scanner runs.
    4. Create a scan_runs record.
    5. Mark scanner_control as running.
    6. Run scanner_v4 in headless mode.
    7. Store real scan statistics.
    8. Return the scanner to idle or paused.
    9. Record failures safely.
    """

    run_id = None
    control_id = None

    try:
        # -------------------------------------------------
        # Load scanner state
        # -------------------------------------------------

        control = get_scanner_control()
        control_id = control["id"]

        print("")
        print("Scanner control row found.")
        print(f"ID: {control_id}")
        print(
            f"Enabled: "
            f"{control.get('enabled')}"
        )
        print(
            f"Status: "
            f"{control.get('status')}"
        )

        # -------------------------------------------------
        # Check whether a scan may start
        # -------------------------------------------------

        if not scanner_can_start(control):
            return

        # -------------------------------------------------
        # Create scan run
        # -------------------------------------------------

        run_id = create_scan_run(
            control_id=control_id,
            trigger_type=trigger_type,
        )

        # -------------------------------------------------
        # Mark scanner as running
        # -------------------------------------------------

        update_scanner_control(
            control_id=control_id,
            values={
                "status": "running",
                "last_started_at": utc_now_iso(),
                "last_error": None,
            },
        )

        print("")
        print("Real scanner run started.")
        print(f"Run ID: {run_id}")
        print(
            f"Trigger type: "
            f"{trigger_type}"
        )

        # -------------------------------------------------
        # Run the actual scanner
        # -------------------------------------------------

        result = run_scanner_v4(
            supabase=supabase,
            headless=True,
        )

        # -------------------------------------------------
        # Save real scanner statistics
        # -------------------------------------------------

        run_status = save_successful_run(
            run_id=run_id,
            result=result,
        )

        # -------------------------------------------------
        # Determine final engine state
        # -------------------------------------------------

        final_control_status = (
            determine_final_control_status()
        )

        # -------------------------------------------------
        # Update scanner control
        # -------------------------------------------------

        update_scanner_control(
            control_id=control_id,
            values={
                "status": final_control_status,
                "last_completed_at": utc_now_iso(),
                "last_error": None,
            },
        )

        # -------------------------------------------------
        # Terminal summary
        # -------------------------------------------------

        print("")
        print("Scanner run finished.")

        print(
            f"Total properties: "
            f"{result.get('total_properties', 0)}"
        )

        print(
            f"Processed successfully: "
            f"{result.get('processed', 0)}"
        )

        print(
            f"Failed: "
            f"{result.get('failed', 0)}"
        )

        print(
            f"Events created: "
            f"{result.get('events_created', 0)}"
        )

        print(
            f"Run status: "
            f"{run_status}"
        )

        print(
            f"Final scanner status: "
            f"{final_control_status}"
        )

    except Exception as exc:
        error_message = str(exc)

        print("")
        print("Scanner orchestrator failed.")
        print(f"Error: {error_message}")
        print("")

        # -------------------------------------------------
        # Mark scan run as failed
        # -------------------------------------------------

        if run_id:
            try:
                update_scan_run(
                    run_id=run_id,
                    values={
                        "status": "failed",
                        "finished_at": utc_now_iso(),
                        "errors_count": 1,
                        "error_message": error_message,
                    },
                )

            except Exception as update_error:
                print(
                    "Warning: The failed scan run "
                    "could not be updated."
                )

                print(
                    f"Update error: "
                    f"{update_error}"
                )

        # -------------------------------------------------
        # Mark scanner engine as failed
        # -------------------------------------------------

        if control_id:
            try:
                update_scanner_control(
                    control_id=control_id,
                    values={
                        "status": "failed",
                        "last_error": error_message,
                    },
                )

            except Exception as update_error:
                print(
                    "Warning: scanner_control "
                    "could not be updated."
                )

                print(
                    f"Update error: "
                    f"{update_error}"
                )

        traceback.print_exc()
        sys.exit(1)


# ---------------------------------------------------------
# Entry point
# ---------------------------------------------------------

if __name__ == "__main__":
    run_scanner(
        trigger_type="manual",
    )