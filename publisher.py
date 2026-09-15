import argparse
import json
import os
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from supabase import Client, create_client


# ---------------------------------------------------------
# Environment
# ---------------------------------------------------------

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv(
    "SUPABASE_SERVICE_ROLE_KEY"
)

PUBLISHER_POLL_SECONDS = int(
    os.getenv("PUBLISHER_POLL_SECONDS", "60")
)

META_GRAPH_BASE = "https://graph.facebook.com"

MAX_FACEBOOK_IMAGES = 10
MAX_INSTAGRAM_IMAGES = 10

INSTAGRAM_CONTAINER_TIMEOUT_SECONDS = 120
INSTAGRAM_CONTAINER_POLL_SECONDS = 3


if not SUPABASE_URL:
    raise RuntimeError(
        "SUPABASE_URL is missing from the environment."
    )

if not SUPABASE_KEY:
    raise RuntimeError(
        "SUPABASE_KEY is missing from the environment."
    )

if not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError(
        "SUPABASE_SERVICE_ROLE_KEY is missing from the environment."
    )

if PUBLISHER_POLL_SECONDS < 10:
    raise RuntimeError(
        "PUBLISHER_POLL_SECONDS must be at least 10 seconds."
    )


supabase: Client = create_client(
    SUPABASE_URL.strip(),
    SUPABASE_KEY.strip(),
)

supabase_admin: Client = create_client(
    SUPABASE_URL.strip(),
    SUPABASE_SERVICE_ROLE_KEY.strip(),
)


# ---------------------------------------------------------
# General helpers
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

def mark_publishing(
    job_id: int,
) -> None:
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


def mark_published(
    job_id: int,
    external_post_id: str,
) -> None:
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


def mark_failed(
    job_id: int,
    error_message: str,
) -> None:
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
# Draft helpers
# ---------------------------------------------------------

def get_marketing_draft(
    draft_id: int,
) -> dict:
    response = (
        supabase_admin
        .table("marketing_drafts")
        .select("*")
        .eq("id", draft_id)
        .limit(1)
        .execute()
    )

    rows = response.data or []

    if not rows:
        raise RuntimeError(
            f"Marketing draft {draft_id} was not found."
        )

    return rows[0]


def get_draft_text(
    draft_id: int,
) -> str:
    draft = get_marketing_draft(
        draft_id
    )

    draft_text = draft.get(
        "draft_text"
    )

    if not isinstance(
        draft_text,
        str,
    ):
        raise RuntimeError(
            f"Marketing draft {draft_id} has no draft_text."
        )

    draft_text = draft_text.strip()

    if not draft_text:
        raise RuntimeError(
            f"Marketing draft {draft_id} has empty draft_text."
        )

    return draft_text


# ---------------------------------------------------------
# Property image helpers
# ---------------------------------------------------------

def get_property_images(
    property_listing_id: int,
    max_images: int,
) -> list[str]:
    response = (
        supabase_admin
        .table("property_images")
        .select(
            "stored_image_url,"
            "image_order"
        )
        .eq(
            "property_listing_id",
            property_listing_id,
        )
        .order(
            "image_order"
        )
        .execute()
    )

    rows = response.data or []

    image_urls = []

    for row in rows:
        stored_image_url = row.get(
            "stored_image_url"
        )

        if not stored_image_url:
            continue

        stored_image_url = str(
            stored_image_url
        ).strip()

        if stored_image_url:
            image_urls.append(
                stored_image_url
            )

    return image_urls[:max_images]


# ---------------------------------------------------------
# Social connection helpers
# ---------------------------------------------------------

def get_connected_social_account(
    platform: str,
) -> dict:
    response = (
        supabase_admin
        .table("social_connections")
        .select(
            "id,"
            "platform,"
            "account_name,"
            "external_account_id,"
            "access_token,"
            "token_expires_at,"
            "is_connected,"
            "updated_at"
        )
        .eq(
            "platform",
            platform,
        )
        .eq(
            "is_connected",
            True,
        )
        .order(
            "updated_at",
            desc=True,
        )
        .limit(1)
        .execute()
    )

    rows = response.data or []

    if not rows:
        raise RuntimeError(
            f"No connected {platform} account was found."
        )

    connection = rows[0]

    external_account_id = connection.get(
        "external_account_id"
    )

    access_token = connection.get(
        "access_token"
    )

    if not external_account_id:
        raise RuntimeError(
            f"Connected {platform} account has "
            "no external_account_id."
        )

    if not access_token:
        raise RuntimeError(
            f"Connected {platform} account has "
            "no access token."
        )

    return connection


def get_connected_facebook_page() -> dict:
    return get_connected_social_account(
        "Facebook"
    )


def get_connected_instagram_account() -> dict:
    return get_connected_social_account(
        "Instagram"
    )


# ---------------------------------------------------------
# Meta API helpers
# ---------------------------------------------------------

def parse_meta_error(
    error_body: str,
) -> str:
    try:
        payload = json.loads(
            error_body
        )

        error = payload.get(
            "error",
            {}
        )

        message = error.get(
            "message"
        )

        code = error.get(
            "code"
        )

        subcode = error.get(
            "error_subcode"
        )

        if message:
            details = (
                f"Meta API error: {message}"
            )

            if code is not None:
                details += (
                    f" (code {code}"
                )

                if subcode is not None:
                    details += (
                        f", subcode {subcode}"
                    )

                details += ")"

            return details

    except Exception:
        pass

    return "Meta API request failed."


def meta_post(
    path: str,
    form_data: dict,
) -> dict:
    url = (
        f"{META_GRAPH_BASE}"
        f"/{path.lstrip('/')}"
    )

    encoded_data = urlencode(
        form_data
    ).encode("utf-8")

    request = Request(
        url=url,
        data=encoded_data,
        method="POST",
        headers={
            "Content-Type":
                "application/x-www-form-urlencoded",
            "Accept":
                "application/json",
        },
    )

    try:
        with urlopen(
            request,
            timeout=60,
        ) as response:
            body = response.read().decode(
                "utf-8"
            )

    except HTTPError as exc:
        error_body = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        raise RuntimeError(
            parse_meta_error(
                error_body
            )
        ) from exc

    except URLError as exc:
        raise RuntimeError(
            f"Unable to contact Meta API: "
            f"{exc.reason}"
        ) from exc

    try:
        payload = json.loads(
            body
        )

    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Meta returned invalid JSON."
        ) from exc

    if "error" in payload:
        raise RuntimeError(
            parse_meta_error(
                body
            )
        )

    return payload


def meta_get(
    path: str,
    query_data: dict,
) -> dict:
    query_string = urlencode(
        query_data
    )

    url = (
        f"{META_GRAPH_BASE}"
        f"/{path.lstrip('/')}?"
        f"{query_string}"
    )

    request = Request(
        url=url,
        method="GET",
        headers={
            "Accept":
                "application/json",
        },
    )

    try:
        with urlopen(
            request,
            timeout=60,
        ) as response:
            body = response.read().decode(
                "utf-8"
            )

    except HTTPError as exc:
        error_body = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        raise RuntimeError(
            parse_meta_error(
                error_body
            )
        ) from exc

    except URLError as exc:
        raise RuntimeError(
            f"Unable to contact Meta API: "
            f"{exc.reason}"
        ) from exc

    try:
        payload = json.loads(
            body
        )

    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Meta returned invalid JSON."
        ) from exc

    if "error" in payload:
        raise RuntimeError(
            parse_meta_error(
                body
            )
        )

    return payload


# ---------------------------------------------------------
# Facebook photo helpers
# ---------------------------------------------------------

def upload_facebook_photo(
    page_id: str,
    access_token: str,
    image_url: str,
) -> str:
    payload = meta_post(
        f"{page_id}/photos",
        {
            "url":
                image_url,

            "published":
                "false",

            "access_token":
                access_token,
        },
    )

    photo_id = payload.get(
        "id"
    )

    if not photo_id:
        raise RuntimeError(
            "Meta uploaded a Facebook photo "
            "but returned no photo ID."
        )

    return str(
        photo_id
    )


def create_facebook_multi_photo_post(
    page_id: str,
    access_token: str,
    message: str,
    photo_ids: list[str],
) -> str:
    form_data = {
        "message":
            message,

        "access_token":
            access_token,
    }

    for index, photo_id in enumerate(
        photo_ids
    ):
        form_data[
            f"attached_media[{index}]"
        ] = json.dumps(
            {
                "media_fbid":
                    photo_id
            }
        )

    payload = meta_post(
        f"{page_id}/feed",
        form_data,
    )

    external_post_id = payload.get(
        "id"
    )

    if not external_post_id:
        raise RuntimeError(
            "Meta created the Facebook post "
            "but returned no post ID."
        )

    return str(
        external_post_id
    )


def create_facebook_text_post(
    page_id: str,
    access_token: str,
    message: str,
) -> str:
    payload = meta_post(
        f"{page_id}/feed",
        {
            "message":
                message,

            "access_token":
                access_token,
        },
    )

    external_post_id = payload.get(
        "id"
    )

    if not external_post_id:
        raise RuntimeError(
            "Meta created the Facebook post "
            "but returned no post ID."
        )

    return str(
        external_post_id
    )


# ---------------------------------------------------------
# Real Facebook publisher
# ---------------------------------------------------------

def publish_facebook(
    job: dict,
) -> str:
    draft_id = job.get(
        "marketing_draft_id"
    )

    property_listing_id = job.get(
        "property_listing_id"
    )

    if not draft_id:
        raise RuntimeError(
            "Publishing job has no marketing_draft_id."
        )

    if not property_listing_id:
        raise RuntimeError(
            "Publishing job has no property_listing_id."
        )

    message = get_draft_text(
        int(draft_id)
    )

    connection = (
        get_connected_facebook_page()
    )

    page_id = str(
        connection[
            "external_account_id"
        ]
    )

    access_token = str(
        connection[
            "access_token"
        ]
    )

    account_name = (
        connection.get(
            "account_name"
        )
        or "Facebook Page"
    )

    print(
        f"Publishing to Facebook Page: "
        f"{account_name}"
    )

    print(
        f"Facebook Page ID: "
        f"{page_id}"
    )

    image_urls = get_property_images(
        int(property_listing_id),
        MAX_FACEBOOK_IMAGES,
    )

    print(
        f"Found {len(image_urls)} "
        f"stored property image(s)."
    )

    if not image_urls:
        print(
            "No stored property images found."
        )

        print(
            "Publishing text-only Facebook post."
        )

        external_post_id = (
            create_facebook_text_post(
                page_id=page_id,
                access_token=access_token,
                message=message,
            )
        )

        print(
            f"Facebook post created: "
            f"{external_post_id}"
        )

        return external_post_id

    photo_ids = []

    for index, image_url in enumerate(
        image_urls,
        start=1,
    ):
        print(
            f"Uploading Facebook photo "
            f"{index}/{len(image_urls)}..."
        )

        photo_id = (
            upload_facebook_photo(
                page_id=page_id,
                access_token=access_token,
                image_url=image_url,
            )
        )

        photo_ids.append(
            photo_id
        )

        print(
            f"Facebook photo "
            f"{index} uploaded."
        )

    print(
        f"Creating Facebook post with "
        f"{len(photo_ids)} photo(s)..."
    )

    external_post_id = (
        create_facebook_multi_photo_post(
            page_id=page_id,
            access_token=access_token,
            message=message,
            photo_ids=photo_ids,
        )
    )

    print(
        f"Facebook multi-photo post created: "
        f"{external_post_id}"
    )

    return external_post_id


# ---------------------------------------------------------
# Instagram container helpers
# ---------------------------------------------------------

def create_instagram_image_container(
    instagram_account_id: str,
    access_token: str,
    image_url: str,
    is_carousel_item: bool,
) -> str:
    form_data = {
        "image_url":
            image_url,

        "access_token":
            access_token,
    }

    if is_carousel_item:
        form_data[
            "is_carousel_item"
        ] = "true"

    payload = meta_post(
        f"{instagram_account_id}/media",
        form_data,
    )

    creation_id = payload.get(
        "id"
    )

    if not creation_id:
        raise RuntimeError(
            "Meta created an Instagram media "
            "container but returned no ID."
        )

    return str(
        creation_id
    )


def create_instagram_carousel_container(
    instagram_account_id: str,
    access_token: str,
    caption: str,
    child_ids: list[str],
) -> str:
    payload = meta_post(
        f"{instagram_account_id}/media",
        {
            "media_type":
                "CAROUSEL",

            "children":
                ",".join(child_ids),

            "caption":
                caption,

            "access_token":
                access_token,
        },
    )

    creation_id = payload.get(
        "id"
    )

    if not creation_id:
        raise RuntimeError(
            "Meta created an Instagram carousel "
            "container but returned no ID."
        )

    return str(
        creation_id
    )


def get_instagram_container_status(
    container_id: str,
    access_token: str,
) -> str:
    payload = meta_get(
        container_id,
        {
            "fields":
                "status_code",

            "access_token":
                access_token,
        },
    )

    status_code = payload.get(
        "status_code"
    )

    if not status_code:
        return "UNKNOWN"

    return str(
        status_code
    ).upper()


def wait_for_instagram_container(
    container_id: str,
    access_token: str,
) -> None:
    started_at = time.monotonic()

    while True:
        status = (
            get_instagram_container_status(
                container_id,
                access_token,
            )
        )

        if status == "FINISHED":
            return

        if status in {
            "ERROR",
            "EXPIRED",
        }:
            raise RuntimeError(
                "Instagram media container "
                f"{container_id} entered "
                f"status {status}."
            )

        elapsed = (
            time.monotonic()
            - started_at
        )

        if (
            elapsed
            >= INSTAGRAM_CONTAINER_TIMEOUT_SECONDS
        ):
            raise RuntimeError(
                "Timed out waiting for Instagram "
                f"media container {container_id}. "
                f"Last status: {status}."
            )

        time.sleep(
            INSTAGRAM_CONTAINER_POLL_SECONDS
        )


def publish_instagram_container(
    instagram_account_id: str,
    access_token: str,
    creation_id: str,
) -> str:
    payload = meta_post(
        f"{instagram_account_id}/media_publish",
        {
            "creation_id":
                creation_id,

            "access_token":
                access_token,
        },
    )

    media_id = payload.get(
        "id"
    )

    if not media_id:
        raise RuntimeError(
            "Meta published Instagram media "
            "but returned no media ID."
        )

    return str(
        media_id
    )


# ---------------------------------------------------------
# Real Instagram publisher
# ---------------------------------------------------------

def publish_instagram(
    job: dict,
) -> str:
    draft_id = job.get(
        "marketing_draft_id"
    )

    property_listing_id = job.get(
        "property_listing_id"
    )

    if not draft_id:
        raise RuntimeError(
            "Publishing job has no marketing_draft_id."
        )

    if not property_listing_id:
        raise RuntimeError(
            "Publishing job has no property_listing_id."
        )

    caption = get_draft_text(
        int(draft_id)
    )

    connection = (
        get_connected_instagram_account()
    )

    instagram_account_id = str(
        connection[
            "external_account_id"
        ]
    )

    access_token = str(
        connection[
            "access_token"
        ]
    )

    account_name = (
        connection.get(
            "account_name"
        )
        or "Instagram"
    )

    print(
        f"Publishing to Instagram: "
        f"{account_name}"
    )

    print(
        f"Instagram Account ID: "
        f"{instagram_account_id}"
    )

    image_urls = get_property_images(
        int(property_listing_id),
        MAX_INSTAGRAM_IMAGES,
    )

    print(
        f"Found {len(image_urls)} "
        f"stored property image(s)."
    )

    if not image_urls:
        raise RuntimeError(
            "Instagram publishing requires "
            "at least one stored property image."
        )

    # -----------------------------------------------------
    # Single-image Instagram post
    # -----------------------------------------------------

    if len(image_urls) == 1:
        print(
            "Creating Instagram "
            "single-image container..."
        )

        creation_id = (
            create_instagram_image_container(
                instagram_account_id=
                    instagram_account_id,
                access_token=
                    access_token,
                image_url=
                    image_urls[0],
                is_carousel_item=
                    False,
            )
        )

        print(
            "Waiting for Instagram "
            "image container..."
        )

        wait_for_instagram_container(
            creation_id,
            access_token,
        )

        print(
            "Publishing Instagram post..."
        )

        media_id = (
            publish_instagram_container(
                instagram_account_id=
                    instagram_account_id,
                access_token=
                    access_token,
                creation_id=
                    creation_id,
            )
        )

        print(
            f"Instagram post created: "
            f"{media_id}"
        )

        return media_id

    # -----------------------------------------------------
    # Multi-image Instagram carousel
    # -----------------------------------------------------

    child_ids = []

    for index, image_url in enumerate(
        image_urls,
        start=1,
    ):
        print(
            f"Creating Instagram carousel item "
            f"{index}/{len(image_urls)}..."
        )

        child_id = (
            create_instagram_image_container(
                instagram_account_id=
                    instagram_account_id,
                access_token=
                    access_token,
                image_url=
                    image_url,
                is_carousel_item=
                    True,
            )
        )

        print(
            f"Waiting for carousel item "
            f"{index}..."
        )

        wait_for_instagram_container(
            child_id,
            access_token,
        )

        child_ids.append(
            child_id
        )

        print(
            f"Instagram carousel item "
            f"{index} ready."
        )

    print(
        f"Creating Instagram carousel with "
        f"{len(child_ids)} image(s)..."
    )

    carousel_id = (
        create_instagram_carousel_container(
            instagram_account_id=
                instagram_account_id,
            access_token=
                access_token,
            caption=
                caption,
            child_ids=
                child_ids,
        )
    )

    print(
        "Waiting for Instagram "
        "carousel container..."
    )

    wait_for_instagram_container(
        carousel_id,
        access_token,
    )

    print(
        "Publishing Instagram carousel..."
    )

    media_id = (
        publish_instagram_container(
            instagram_account_id=
                instagram_account_id,
            access_token=
                access_token,
            creation_id=
                carousel_id,
        )
    )

    print(
        f"Instagram carousel created: "
        f"{media_id}"
    )

    return media_id


# ---------------------------------------------------------
# Temporary mock publisher
# ---------------------------------------------------------

def mock_publish(
    job: dict,
) -> str:
    platform = job.get(
        "platform",
        "unknown",
    )

    draft_id = job.get(
        "marketing_draft_id"
    )

    job_id = job.get(
        "id"
    )

    print(
        f"[MOCK PUBLISH] "
        f"platform={platform} "
        f"draft_id={draft_id} "
        f"job_id={job_id}"
    )

    return (
        f"mock-"
        f"{platform.lower()}-"
        f"{job_id}"
    )


# ---------------------------------------------------------
# Platform router
# ---------------------------------------------------------

def publish_job(
    job: dict,
) -> str:
    platform = str(
        job.get(
            "platform",
            "",
        )
    ).strip().lower()

    if platform == "facebook":
        return publish_facebook(
            job
        )

    if platform == "instagram":
        return publish_instagram(
            job
        )

    if platform == "tiktok":
        return mock_publish(
            job
        )

    raise RuntimeError(
        f"Unsupported publishing platform: "
        f"{platform or 'unknown'}"
    )


# ---------------------------------------------------------
# Process one job
# ---------------------------------------------------------

def process_job(
    job: dict,
) -> None:
    job_id = job["id"]

    try:
        print("")

        print(
            f"Processing publishing job "
            f"{job_id}"
        )

        print(
            f"Platform: "
            f"{job.get('platform')}"
        )

        mark_publishing(
            job_id
        )

        external_post_id = (
            publish_job(
                job
            )
        )

        mark_published(
            job_id=job_id,
            external_post_id=
                external_post_id,
        )

        print(
            f"Publishing job "
            f"{job_id} completed."
        )

    except Exception as exc:
        error_message = str(
            exc
        )

        print(
            f"Publishing job "
            f"{job_id} failed: "
            f"{error_message}"
        )

        try:
            mark_failed(
                job_id=job_id,
                error_message=
                    error_message,
            )

        except Exception as update_error:
            print(
                "Warning: failed job "
                "could not be updated."
            )

            print(
                f"Update error: "
                f"{update_error}"
            )


# ---------------------------------------------------------
# Publisher worker
# ---------------------------------------------------------

def run_publisher() -> None:
    print("")

    print(
        "========================================"
    )

    print(
        "NYRO PUBLISHER"
    )

    print(
        "========================================"
    )

    print("")

    print(
        "Checking for publishing jobs..."
    )

    jobs = get_due_jobs()

    if not jobs:
        print(
            "No publishing jobs ready."
        )
        return

    print(
        f"Found {len(jobs)} "
        f"publishing job(s)."
    )

    for job in jobs:
        process_job(
            job
        )

    print("")

    print(
        "Publisher run finished."
    )


def run_publisher_loop() -> None:
    print("")

    print(
        "========================================"
    )

    print(
        "NYRO PUBLISHER WORKER STARTED"
    )

    print(
        "========================================"
    )

    print(
        f"Polling every "
        f"{PUBLISHER_POLL_SECONDS} "
        f"seconds."
    )

    while True:
        try:
            run_publisher()

        except Exception as exc:
            print("")

            print(
                "Publisher cycle failed:"
            )

            print(
                str(exc)
            )

        print("")

        print(
            f"Waiting "
            f"{PUBLISHER_POLL_SECONDS} "
            f"seconds..."
        )

        time.sleep(
            PUBLISHER_POLL_SECONDS
        )


# ---------------------------------------------------------
# Entry point
# ---------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=
            "Nyro publishing worker"
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help=
            "Run one publishing check "
            "and exit.",
    )

    args = parser.parse_args()

    if args.once:
        run_publisher()
    else:
        run_publisher_loop()