from datetime import datetime, UTC


def create_event(supabase, property_id, change, property_url):
    event_type = change["event_type"]
    old_value = str(change["old_value"]) if change.get("old_value") is not None else None
    new_value = str(change["new_value"]) if change.get("new_value") is not None else None

    existing = (
        supabase.table("listing_events")
        .select("id")
        .eq("property_listing_id", property_id)
        .eq("event_type", event_type)
        .eq("new_value", new_value)
        .eq("processed", False)
        .execute()
    )

    if existing.data:
        print(f"Skipped duplicate event: {event_type}")
        return False

    supabase.table("listing_events").insert({
        "property_listing_id": property_id,
        "event_type": event_type,
        "old_value": old_value,
        "new_value": new_value,
        "metadata": {
            "field": change.get("field"),
            "property_url": property_url,
            "scan_time": datetime.now(UTC).isoformat(),
            "trigger": "scanner_v4"
        },
        "processed": False
    }).execute()

    print(f"Created event: {event_type}")
    return True