import hashlib
from datetime import datetime, UTC


# ---------------------------------------------------------
# General helpers
# ---------------------------------------------------------

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
# Property images
# ---------------------------------------------------------

def refresh_property_images(
    supabase,
    property_id,
    image_urls,
):
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

    for index, image_url in enumerate(
        image_urls or []
    ):
        (
            supabase
            .table("property_images")
            .insert(
                {
                    "property_listing_id":
                        property_id,

                    "image_url":
                        image_url,

                    "image_order":
                        index + 1,
                }
            )
            .execute()
        )