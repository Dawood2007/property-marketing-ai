from datetime import datetime, UTC


def load_live_properties(supabase):
    return (
        supabase.table("property_listings")
        .select("*")
        .eq("currently_live", True)
        .execute()
        .data
    )


def update_property(supabase, property_id, new):
    now = datetime.now(UTC).isoformat()

    if new.get("currently_live") is False:
        update_data = {
            "currently_live": False,
            "listing_status": "Off Market",
            "detail_extracted": False,
            "title": None,
            "price": None,
            "bedrooms": None,
            "property_type": None,
            "description": None,
            "main_image_url": None,
            "last_seen_at": now,
        }
    else:
        update_data = {
            "currently_live": True,
            "listing_status": new.get("listing_status"),
            "title": new.get("title"),
            "price": new.get("price"),
            "bedrooms": new.get("bedrooms"),
            "property_type": new.get("property_type"),
            "description": new.get("description"),
            "main_image_url": new.get("main_image_url"),
            "bm_reference": new.get("bm_reference"),
            "detail_extracted": True,
            "last_seen_at": now,
        }

    supabase.table("property_listings").update(update_data).eq("id", property_id).execute()


def refresh_property_images(supabase, property_id, image_urls):
    supabase.table("property_images").delete().eq("property_listing_id", property_id).execute()

    for index, image_url in enumerate(image_urls or []):
        supabase.table("property_images").insert({
            "property_listing_id": property_id,
            "image_url": image_url,
            "image_order": index + 1,
        }).execute()