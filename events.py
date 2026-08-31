from datetime import datetime, UTC


# ---------------------------------------------------------
# Pending draft invalidation
# ---------------------------------------------------------

def reject_pending_drafts(
    supabase,
    property_id,
):
    """
    Reject any marketing drafts that are still awaiting
    approval when a property goes off market.

    This prevents outdated marketing such as NEW_LISTING,
    PRICE_REDUCED or RELISTED content from being approved
    after the property is no longer available.
    """

    response = (
        supabase
        .table("marketing_drafts")
        .update(
            {
                "approval_status":
                    "Rejected",
            }
        )
        .eq(
            "property_listing_id",
            property_id,
        )
        .eq(
            "approval_status",
            "Pending Approval",
        )
        .execute()
    )

    rejected_count = len(
        response.data or []
    )

    if rejected_count > 0:
        print(
            f"Rejected {rejected_count} pending "
            f"marketing draft(s) for off-market property."
        )

    return rejected_count


# ---------------------------------------------------------
# Event creation
# ---------------------------------------------------------

def create_event(
    supabase,
    property_id,
    change,
    property_url,
):
    event_type = change["event_type"]

    old_value = (
        str(change["old_value"])
        if change.get("old_value") is not None
        else None
    )

    new_value = (
        str(change["new_value"])
        if change.get("new_value") is not None
        else None
    )

    existing = (
        supabase
        .table("listing_events")
        .select("id")
        .eq(
            "property_listing_id",
            property_id,
        )
        .eq(
            "event_type",
            event_type,
        )
        .eq(
            "new_value",
            new_value,
        )
        .eq(
            "processed",
            False,
        )
        .execute()
    )

    if existing.data:
        print(
            f"Skipped duplicate event: "
            f"{event_type}"
        )
        return False

    response = (
        supabase
        .table("listing_events")
        .insert(
            {
                "property_listing_id":
                    property_id,

                "event_type":
                    event_type,

                "old_value":
                    old_value,

                "new_value":
                    new_value,

                "metadata": {
                    "field":
                        change.get("field"),

                    "property_url":
                        property_url,

                    "scan_time":
                        datetime.now(
                            UTC
                        ).isoformat(),

                    "trigger":
                        "scanner_v4",
                },

                "processed":
                    False,
            }
        )
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            f"Could not create event: "
            f"{event_type}"
        )

    print(
        f"Created event: "
        f"{event_type}"
    )

    # -----------------------------------------------------
    # OFF_MARKET safety rule
    # -----------------------------------------------------
    #
    # OFF_MARKET itself does not generate marketing.
    #
    # Any marketing that was waiting for approval for this
    # property is now stale and must no longer be publishable.
    # -----------------------------------------------------

    if event_type == "OFF_MARKET":
        reject_pending_drafts(
            supabase,
            property_id,
        )

    return True