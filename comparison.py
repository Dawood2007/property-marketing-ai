def compare_status(old, new):
    if new.get("currently_live") is False:
        if old.get("currently_live") is False:
            return None

        return {
            "event_type": "OFF_MARKET",
            "field": "listing_status",
            "old_value": old.get("listing_status"),
            "new_value": "Off Market",
        }

    if old.get("currently_live") is False and new.get("currently_live") is True:
        return {
            "event_type": "RELISTED",
            "field": "currently_live",
            "old_value": "false",
            "new_value": "true",
        }

    return None


def compare_price(old, new):
    old_price = old.get("price")
    new_price = new.get("price")

    if old_price is None or new_price is None:
        return None

    if old_price == new_price:
        return None

    return {
        "event_type": "PRICE_REDUCED" if new_price < old_price else "PRICE_INCREASED",
        "field": "price",
        "old_value": old_price,
        "new_value": new_price,
    }


def compare_main_image(old, new):
    if old.get("main_image_url") == new.get("main_image_url"):
        return None

    return {
        "event_type": "MAIN_IMAGE_CHANGED",
        "field": "main_image_url",
        "old_value": old.get("main_image_url"),
        "new_value": new.get("main_image_url"),
    }


def compare_bedrooms(old, new):
    if old.get("bedrooms") == new.get("bedrooms"):
        return None

    return {
        "event_type": "BEDROOMS_CHANGED",
        "field": "bedrooms",
        "old_value": old.get("bedrooms"),
        "new_value": new.get("bedrooms"),
    }


def compare_property(old, new):
    status_change = compare_status(old, new)

    if status_change:
        return [status_change]

    rules = [
        compare_price,
        compare_main_image,
        compare_bedrooms,
    ]

    changes = []

    for rule in rules:
        change = rule(old, new)
        if change:
            changes.append(change)

    return changes