import os
import sys
import traceback
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import Client, create_client

from scanner_v4 import run_scanner_v4


load_dotenv()


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


if not SUPABASE_URL:
    raise RuntimeError(
        "SUPABASE_URL is missing from the .env file."
    )

if not SUPABASE_KEY:
    raise RuntimeError(
        "SUPABASE_KEY is missing from the .env file."
    )


supabase: Client = create_client(
    SUPABASE_URL.strip(),
    SUPABASE_KEY.strip(),
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    values["updated_at"] = utc_now_iso()

    response = (
        supabase
        .table("scanner_control")
        .update(values)
        .eq("id", control_id)
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "The scanner_control row could not be updated."
        )


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
        print(f"Enabled: {control.get('enabled')}")
        print(f"Status: {control.get('status')}")

        if control.get("enabled") is False:
            print("")
            print(
                "Scanner is paused. "
                "No scan was started."
            )
            return

        if control.get("status") == "paused":
            print("")
            print(
                "Scanner is paused. "
                "No scan was started."
            )
            return

        if control.get("status") == "running":
            print("")
            print(
                "A scanner run is already active. "
                "No duplicate run was started."
            )
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
        print("Real scanner run started.")
        print(f"Run ID: {run_id}")
        print(f"Trigger type: {trigger_type}")

        result = run_scanner_v4(
            supabase=supabase,
            headless=True,
        )

        latest_control = get_scanner_control()

        if latest_control.get("enabled") is False:
            final_control_status = "paused"
        else:
            final_control_status = "idle"

        update_scan_run(
            run_id=run_id,
            values={
                "status": "success",
                "finished_at": utc_now_iso(),
            },
        )

        update_scanner_control(
            control_id=control_id,
            values={
                "status": final_control_status,
                "last_completed_at": utc_now_iso(),
                "last_error": None,
            },
        )

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
            f"Final scanner status: "
            f"{final_control_status}"
        )

    except Exception as exc:
        error_message = str(exc)

        print("")
        print("Scanner orchestrator failed.")
        print(f"Error: {error_message}")
        print("")

        if run_id:
            try:
                update_scan_run(
                    run_id=run_id,
                    values={
                        "status": "failed",
                        "finished_at": utc_now_iso(),
                    },
                )
            except Exception as update_error:
                print(
                    "Warning: The failed scan run "
                    "could not be updated."
                )
                print(f"Update error: {update_error}")

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
                print(f"Update error: {update_error}")

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    run_scanner(
        trigger_type="manual",
    )