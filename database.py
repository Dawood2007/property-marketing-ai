import hashlib
import mimetypes
import os
import ssl
from datetime import datetime, UTC
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import certifi


# ---------------------------------------------------------
# General helpers
# ---------------------------------------------------------

PROPERTY_IMAGES_BUCKET = "property-images"


def utc_now_iso():
    return datetime.now(UTC).isoformat()


def make_property_fingerprint(property_url):
    normalized_url = (
        property_url
        .lower()
        .strip()
    )

    return hashlib.sha256(
        normalized_url.encode()
    ).hexdigest()


# ---------------------------------------------------------
# Property lookup
# ---------------------------------------------------------

def load_live_properties(supabase):
    return (
        supabase
        .table("property_listings")
        .select("*")
        .eq("currently_live", True)
        .execute()
        .data
    )


def find_property_by_fingerprint(
    supabase,
    property_fingerprint,
):
    response = (
        supabase
        .table("property_listings")
        .select("*")
        .eq(
            "property_fingerprint",
            property_fingerprint,
        )
        .limit(1)
        .execute()
    )

    if not response.data:
        return None

    return response.data[0]


def find_property_by_url(
    supabase,
    property_url,
):
    fingerprint = make_property_fingerprint(
        property_url
    )

    return find_property_by_fingerprint(
        supabase,
        fingerprint,
    )


# ---------------------------------------------------------
# Insert brand-new property
# ---------------------------------------------------------

def insert_property(
    supabase,
    property_url,
    category,
    listing_type,
    extracted_property,
):
    now = utc_now_iso()

    fingerprint = make_property_fingerprint(
        property_url
    )

    insert_data = {
        "property_url":
            property_url,

        "property_fingerprint":
            fingerprint,

        "title":
            extracted_property.get(
                "title"
            ),

        "price":
            extracted_property.get(
                "price"
            ),

        "bedrooms":
            extracted_property.get(
                "bedrooms"
            ),

        "main_image_url":
            extracted_property.get(
                "main_image_url"
            ),

        "first_seen_at":
            now,

        "last_seen_at":
            now,

        "post_generated":
            False,

        "social_posted":
            False,

        "category":
            category,

        "currently_live":
            True,

        "listing_type":
            listing_type,

        "listing_status":
            extracted_property.get(
                "listing_status"
            ) or "Live",

        "description":
            extracted_property.get(
                "description"
            ),

        "property_type":
            extracted_property.get(
                "property_type"
            ),

        "detail_extracted":
            True,

        "bm_reference":
            extracted_property.get(
                "bm_reference"
            ),
    }

    response = (
        supabase
        .table("property_listings")
        .insert(insert_data)
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "New property could not be inserted."
        )

    return response.data[0]


# ---------------------------------------------------------
# Existing property updates
# ---------------------------------------------------------

def update_property(
    supabase,
    property_id,
    new,
):
    """
    Update an existing property.

    If a property goes off market, preserve its last known
    property details. Only its live state and listing status
    should change.

    This ensures historical property data remains available
    inside Nyro and prevents useful information such as the
    title, price, description and images from being erased.
    """

    now = utc_now_iso()

    if new.get("currently_live") is False:

        update_data = {
            "currently_live":
                False,

            "listing_status":
                "Off Market",

            "last_seen_at":
                now,
        }

    else:

        update_data = {
            "currently_live":
                True,

            "listing_status":
                new.get(
                    "listing_status"
                ),

            "title":
                new.get(
                    "title"
                ),

            "price":
                new.get(
                    "price"
                ),

            "bedrooms":
                new.get(
                    "bedrooms"
                ),

            "property_type":
                new.get(
                    "property_type"
                ),

            "description":
                new.get(
                    "description"
                ),

            "main_image_url":
                new.get(
                    "main_image_url"
                ),

            "bm_reference":
                new.get(
                    "bm_reference"
                ),

            "detail_extracted":
                True,

            "last_seen_at":
                now,
        }

    (
        supabase
        .table("property_listings")
        .update(update_data)
        .eq(
            "id",
            property_id,
        )
        .execute()
    )


# ---------------------------------------------------------
# Sold property update
# ---------------------------------------------------------

def mark_property_sold(
    supabase,
    property_id,
):
    """
    Mark a known property as sold without deleting its
    extracted details.

    Sold properties are removed from normal live monitoring,
    but their property data remains available for the SOLD
    marketing event and historical records.
    """

    now = utc_now_iso()

    response = (
        supabase
        .table("property_listings")
        .update(
            {
                "currently_live":
                    False,

                "listing_status":
                    "Sold",

                "last_seen_at":
                    now,
            }
        )
        .eq(
            "id",
            property_id,
        )
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "Property could not be marked as sold."
        )

    return response.data[0]


# ---------------------------------------------------------
# Property image storage helpers
# ---------------------------------------------------------

def get_existing_property_images(
    supabase,
    property_id,
):
    response = (
        supabase
        .table("property_images")
        .select(
            "id,"
            "property_listing_id,"
            "image_url,"
            "stored_image_url,"
            "image_order"
        )
        .eq(
            "property_listing_id",
            property_id,
        )
        .execute()
    )

    return response.data or []


def get_existing_stored_image_map(
    existing_images,
):
    stored_map = {}

    for image in existing_images:
        source_url = image.get(
            "image_url"
        )

        stored_url = image.get(
            "stored_image_url"
        )

        if source_url and stored_url:
            stored_map[source_url] = stored_url

    return stored_map


def download_property_image(
    image_url,
):
    request = Request(
        image_url,
        headers={
            "User-Agent":
                "Mozilla/5.0 Nyro/1.0"
        },
    )

    ssl_context = ssl.create_default_context(
        cafile=certifi.where()
    )

    with urlopen(
        request,
        timeout=30,
        context=ssl_context,
    ) as response:
        image_bytes = response.read()

        content_type = (
            response
            .headers
            .get_content_type()
        )

    if not image_bytes:
        raise RuntimeError(
            "Downloaded property image was empty."
        )

    if not content_type.startswith(
        "image/"
    ):
        raise RuntimeError(
            "Property image URL did not return "
            f"an image. Content type: {content_type}"
        )

    return image_bytes, content_type


def get_image_extension(
    image_url,
    content_type,
):
    extension = mimetypes.guess_extension(
        content_type
    )

    if not extension:
        parsed_url = urlparse(
            image_url
        )

        extension = os.path.splitext(
            parsed_url.path
        )[1]

    if not extension:
        extension = ".jpg"

    if extension == ".jpe":
        extension = ".jpg"

    return extension


def store_property_image(
    supabase,
    property_id,
    image_order,
    image_url,
):
    image_bytes, content_type = (
        download_property_image(
            image_url
        )
    )

    extension = get_image_extension(
        image_url,
        content_type,
    )

    storage_path = (
        f"{property_id}/"
        f"{image_order}{extension}"
    )

    (
        supabase
        .storage
        .from_(PROPERTY_IMAGES_BUCKET)
        .upload(
            path=storage_path,
            file=image_bytes,
            file_options={
                "content-type":
                    content_type,

                "upsert":
                    "true",
            },
        )
    )

    public_url = (
        supabase
        .storage
        .from_(PROPERTY_IMAGES_BUCKET)
        .get_public_url(
            storage_path
        )
    )

    return public_url


# ---------------------------------------------------------
# Property images
# ---------------------------------------------------------

def refresh_property_images(
    supabase,
    property_id,
    image_urls,
):
    """
    Refresh a property's image records.

    The original agency/CRM image URL is retained in
    image_url.

    Nyro also stores its own copy in Supabase Storage and
    records that public URL in stored_image_url.

    If an original source URL has already been stored by
    Nyro, the existing stored copy is reused instead of
    downloading and uploading it again.
    """

    image_urls = image_urls or []

    existing_images = (
        get_existing_property_images(
            supabase,
            property_id,
        )
    )

    stored_image_map = (
        get_existing_stored_image_map(
            existing_images
        )
    )

    new_image_rows = []

    for index, image_url in enumerate(
        image_urls
    ):
        image_order = index + 1

        stored_image_url = (
            stored_image_map.get(
                image_url
            )
        )

        if stored_image_url:
            print(
                f"Reusing stored image "
                f"{image_order} for "
                f"property {property_id}"
            )

        else:
            print(
                f"Storing image "
                f"{image_order} for "
                f"property {property_id}"
            )

            stored_image_url = (
                store_property_image(
                    supabase,
                    property_id,
                    image_order,
                    image_url,
                )
            )

        new_image_rows.append(
            {
                "property_listing_id":
                    property_id,

                "image_url":
                    image_url,

                "stored_image_url":
                    stored_image_url,

                "image_order":
                    image_order,
            }
        )

    # Only replace the database rows after all new images
    # have been prepared successfully.
    (
        supabase
        .table("property_images")
        .delete()
        .eq(
            "property_listing_id",
            property_id,
        )
        .execute()
    )

    if new_image_rows:
        (
            supabase
            .table("property_images")
            .insert(
                new_image_rows
            )
            .execute()
        )