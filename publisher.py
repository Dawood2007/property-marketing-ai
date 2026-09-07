import argparse
import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import Client, create_client


# ---------------------------------------------------------
# Environment
# ---------------------------------------------------------

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
PUBLISHER_POLL_SECONDS = int(os.getenv("PUBLISHER_POLL_SECONDS", "60"))

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL is missing from the environment.")

if not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY is missing from the environment.")

if PUBLISHER_POLL_SECONDS < 10:
    raise RuntimeError("PUBLISHER_POLL_SECONDS must be at least 10 seconds.")

supabase: Client = create_client(
    SUPABASE_URL.strip(),
    SUPABASE_KEY.strip(),
)


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------
# Find jobs ready for publishing
# ---------------------------------------------------------

def get_due_jobs() -> list[dict]:
    now = utc_now_iso()

    queued_response = (
        supabase
        .table("publishing_jobs")
        .select("*")
        .eq("status", "Queued")
        .execute()
    )

    scheduled_response = (
        supabase
        .table("publishing_jobs")
        .select("*")
        .eq("status", "Scheduled")
        .lte("scheduled_for", now)
        .execute()
    )

    queued_jobs = queued_response.data or []
    scheduled_jobs = scheduled_response.data or []

    return queued_jobs + scheduled_jobs


# ---------------------------------------------------------
# Job status helpers
# ---------------------------------------------------------

def mark_publishing(job_id: int) -> None:
    (
        supabase
        .table("publishing_jobs")
        .update(
            {
                "status": "Publishing",
                "error_message": None,
                "updated_at": utc_now_iso(),
            }
        )
        .eq("id", job_id)
        .execute()
    )


def mark_published(job_id: int, external_post_id: str) -> None:
    now = utc_now_iso()

    (
        supabase
        .table("publishing_jobs")
        .update(
            {
                "status": "Published",
                "published_at": now,
                "external_post_id": external_post_id,
                "error_message": None,
                "updated_at": now,
            }
        )
        .eq("id", job_id)
        .execute()
    )


def mark_failed(job_id: int, error_message: str) -> None:
    (
        supabase
        .table("publishing_jobs")
        .update(
            {
                "status": "Failed",
                "error_message": error_message,
                "updated_at": utc_now_iso(),
            }
        )
        .eq("id", job_id)
        .execute()
    )


# ---------------------------------------------------------
# Mock social publisher
# ---------------------------------------------------------

def mock_publish(job: dict) -> str:
    platform = job.get("platform", "unknown")
    draft_id = job.get("marketing_draft_id")
    job_id = job.get("id")

    print(
        f"[MOCK PUBLISH] "
        f"platform={platform} "
        f"draft_id={draft_id} "
        f"job_id={job_id}"
    )

    return f"mock-{platform.lower()}-{job_id}"


# ---------------------------------------------------------
# Process one job
# ---------------------------------------------------------

def process_job(job: dict) -> None:
    job_id = job["id"]

    try:
        print("")
        print(f"Processing publishing job {job_id}")

        mark_publishing(job_id)

        external_post_id = mock_publish(job)

        mark_published(
            job_id=job_id,
            external_post_id=external_post_id,
        )

        print(f"Publishing job {job_id} completed.")

    except Exception as exc:
        error_message = str(exc)

        print(
            f"Publishing job "
            f"{job_id} failed: "
            f"{error_message}"
        )

        try:
            mark_failed(
                job_id=job_id,
                error_message=error_message,
            )
        except Exception as update_error:
            print("Warning: failed job could not be updated.")
            print(f"Update error: {update_error}")


# ---------------------------------------------------------
# Publisher worker
# ---------------------------------------------------------

def run_publisher() -> None:
    print("")
    print("========================================")
    print("NYRO PUBLISHER")
    print("========================================")

    print("")
    print("Checking for publishing jobs...")

    jobs = get_due_jobs()

    if not jobs:
        print("No publishing jobs ready.")
        return

    print(f"Found {len(jobs)} publishing job(s).")

    for job in jobs:
        process_job(job)

    print("")
    print("Publisher run finished.")


def run_publisher_loop() -> None:
    print("")
    print("========================================")
    print("NYRO PUBLISHER WORKER STARTED")
    print("========================================")
    print(f"Polling every {PUBLISHER_POLL_SECONDS} seconds.")

    while True:
        try:
            run_publisher()
        except Exception as exc:
            print("")
            print("Publisher cycle failed:")
            print(str(exc))

        print("")
        print(f"Waiting {PUBLISHER_POLL_SECONDS} seconds...")
        time.sleep(PUBLISHER_POLL_SECONDS)


# ---------------------------------------------------------
# Entry point
# ---------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Nyro publishing worker"
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one publishing check and exit.",
    )

    args = parser.parse_args()

    if args.once:
        run_publisher()
    else:
        run_publisher_loop()
