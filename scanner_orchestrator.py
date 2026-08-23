import os
import sys
import traceback
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import Client, create_client

from discovery import run_discovery
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
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------
# Scanner control helpers
# ---------------------------------------------------------

def get_scanner_control() -> dict:
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
# Scanner start checks
# ---------------------------------------------------------

def scanner_can_start(
    control: dict,
    trigger_type: str,
) -> bool:
    if control.get("status") == "running":
        print("")
        print("A scanner run is already active.")
        print("No duplicate scan was started.")
        return False

    if (
        trigger_type == "scheduled"
        and control.get("enabled") is False
    ):
        print("")
        print("Automatic scanning is disabled.")
        print("Scheduled scan skipped.")
        return False

    return True


# ---------------------------------------------------------
# Result helpers
# ---------------------------------------------------------

def get_run_status(
    result: dict,
) -> str:
    failed_count = result.get(
        "failed",
        0,
    )

    if failed_count > 0:
        return "partial"

    return "success"


def merge_results(
    discovery_result: dict,
    scanner_result: dict,
) -> dict:
    """
    Combine discovery statistics with Scanner V4 statistics.

    NEW_LISTING events come from discovery.

    Price reductions, relisted and off-market events
    come from Scanner V4.

    SOLD events are also created during discovery, but
    scan_runs currently has no sold_properties column,
    so sold count is logged separately for now.
    """

    return {
        "total_properties": scanner_result.get(
            "total_properties",
            0,
        ),

        "processed": scanner_result.get(
            "processed",
            0,
        ),

        "failed": (
            scanner_result.get(
                "failed",
                0,
            )
            +
            discovery_result.get(
                "errors",
                0,
            )
        ),

        "events_created": (
            scanner_result.get(
                "events_created",
                0,
            )
            +
            discovery_result.get(
                "events_created",
                0,
            )
        ),

        "new_listings": (
            scanner_result.get(
                "new_listings",
                0,
            )
            +
            discovery_result.get(
                "new_listings",
                0,
            )
        ),

        "price_reductions": scanner_result.get(
            "price_reductions",
            0,
        ),

        "relisted_properties": scanner_result.get(
            "relisted_properties",
            0,
        ),

        "off_market_properties": scanner_result.get(
            "off_market_properties",
            0,
        ),

        "sold_properties": discovery_result.get(
            "sold_properties",
            0,
        ),

        "discovery_errors": discovery_result.get(
            "errors",
            0,
        ),
    }


def save_successful_run(
    run_id: str,
    result: dict,
) -> str:
    run_status = get_run_status(
        result
    )

    update_scan_run(
        run_id=run_id,
        values={
            "status": run_status,
            "finished_at": utc_now_iso(),

            "properties_checked": result.get(
                "total_properties",
                0,
            ),

            "new_listings": result.get(
                "new_listings",
                0,
            ),

            "price_reductions": result.get(
                "price_reductions",
                0,
            ),

            "relisted_properties": result.get(
                "relisted_properties",
                0,
            ),

            "off_market_properties": result.get(
                "off_market_properties",
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
    run_id = None
    control_id = None

    try:
        control = get_scanner_control()
        control_id = control["id"]

        print("")
        print("Scanner control row found.")
        print(f"ID: {control_id}")

        print(
            f"Automatic scanning enabled: "
            f"{control.get('enabled')}"
        )

        print(
            f"Engine status: "
            f"{control.get('status')}"
        )

        print(
            f"Trigger type: "
            f"{trigger_type}"
        )

        if not scanner_can_start(
            control=control,
            trigger_type=trigger_type,
        ):
            return

        run_id = create_scan_run(
            control_id=control_id,
            trigger_type=trigger_type,
        )

        update_scanner_control(
            control_id=control_id,
            values={
                "status": "running",
                "last_started_at": utc_now_iso(),
                "last_error": None,
            },
        )

        print("")
        print("Nyro scanner run started.")
        print(f"Run ID: {run_id}")
        print(f"Trigger type: {trigger_type}")

        # -------------------------------------------------
        # Phase 1 — discovery
        # -------------------------------------------------

        print("")
        print(
            "========================================"
        )
        print(
            "PHASE 1: PROPERTY DISCOVERY"
        )
        print(
            "========================================"
        )

        discovery_result = run_discovery(
            supabase=supabase,
            headless=True,
        )

        print("")
        print(
            "Discovery phase complete."
        )

        print(
            f"New listings discovered: "
            f"{discovery_result.get('new_listings', 0)}"
        )

        print(
            f"Sold properties detected: "
            f"{discovery_result.get('sold_properties', 0)}"
        )

        print(
            f"Discovery events created: "
            f"{discovery_result.get('events_created', 0)}"
        )

        print(
            f"Discovery errors: "
            f"{discovery_result.get('errors', 0)}"
        )

        # -------------------------------------------------
        # Phase 2 — monitoring
        # -------------------------------------------------

        print("")
        print(
            "========================================"
        )
        print(
            "PHASE 2: PROPERTY MONITORING"
        )
        print(
            "========================================"
        )

        scanner_result = run_scanner_v4(
            supabase=supabase,
            headless=True,
        )

        # -------------------------------------------------
        # Merge both phases
        # -------------------------------------------------

        result = merge_results(
            discovery_result=discovery_result,
            scanner_result=scanner_result,
        )

        run_status = save_successful_run(
            run_id=run_id,
            result=result,
        )

        update_scanner_control(
            control_id=control_id,
            values={
                "status": "idle",
                "last_completed_at": utc_now_iso(),
                "last_error": None,
            },
        )

        # -------------------------------------------------
        # Final summary
        # -------------------------------------------------

        print("")
        print(
            "========================================"
        )
        print(
            "NYRO SCANNER RUN FINISHED"
        )
        print(
            "========================================"
        )

        print(
            f"Properties checked: "
            f"{result.get('total_properties', 0)}"
        )

        print(
            f"Processed successfully: "
            f"{result.get('processed', 0)}"
        )

        print(
            f"New listings: "
            f"{result.get('new_listings', 0)}"
        )

        print(
            f"Sold properties: "
            f"{result.get('sold_properties', 0)}"
        )

        print(
            f"Price reductions: "
            f"{result.get('price_reductions', 0)}"
        )

        print(
            f"Relisted properties: "
            f"{result.get('relisted_properties', 0)}"
        )

        print(
            f"Off market properties: "
            f"{result.get('off_market_properties', 0)}"
        )

        print(
            f"Events created: "
            f"{result.get('events_created', 0)}"
        )

        print(
            f"Errors: "
            f"{result.get('failed', 0)}"
        )

        print(
            f"Run status: "
            f"{run_status}"
        )

        print(
            "Final scanner status: idle"
        )

    except Exception as exc:
        error_message = str(exc)

        print("")
        print(
            "Scanner orchestrator failed."
        )

        print(
            f"Error: "
            f"{error_message}"
        )

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