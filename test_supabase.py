from supabase import create_client
from datetime import datetime

SUPABASE_URL = "https://dkbtxrinvcifnamapkip.supabase.co"
SUPABASE_KEY = "sb_publishable_fzfohIWnOVYmGld7Dhwpkg_7nEYlpqn"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

test_property = {
    "property_url": "https://test.com/python-test-property",
    "property_fingerprint": "python-test-property",
    "title": "Python Test Property",
    "price": 300000,
    "bedrooms": 3,
    "status": "For Sale",
    "main_image_url": "https://test.com/image.jpg",
    "last_seen_at": datetime.utcnow().isoformat()
}

response = supabase.table("property_listings").insert(test_property).execute()

print("Inserted property:")
print(response.data)