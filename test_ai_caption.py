from dotenv import load_dotenv
from openai import OpenAI
from supabase import create_client
import os

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

PROPERTY_ID = 20
PLATFORM = "Instagram"
EVENT_TYPE = "NEW_LISTING"


def format_price(price):
    if price is None:
        return "Price on application"

    return f"£{price:,.0f}"


def load_marketing_brain():
    file_path = os.path.join("ai", "marketing_brain.txt")

    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()


property_response = (
    supabase.table("property_listings")
    .select("*")
    .eq("id", PROPERTY_ID)
    .single()
    .execute()
)

property_data = property_response.data
marketing_brain = load_marketing_brain()

instructions = f"""
{marketing_brain}

INSTAGRAM-SPECIFIC INSTRUCTIONS

Create an engaging Instagram property caption for BM Estates.

Before writing, silently analyse the property and decide:

1. What is genuinely most appealing about this specific property?
2. What is the strongest truthful marketing angle?
3. What opening would make a relevant buyer or tenant stop scrolling?
4. Which two or three facts best support that opening?
5. What clear action should the reader take?

The first line must earn attention.

Avoid generic openings such as:
- New to the market
- We are delighted to present
- Discover this stunning property
- This beautiful home
- Looking for your dream home?

Do not force drama or use fake urgency.

Do not claim:
- the property will sell quickly,
- it is perfect for a particular group,
- it is ready to move into,
- it is newly renovated,
unless the supplied data clearly supports that claim.

Use natural UK English.

Use emojis selectively, not on every line.

Keep the caption polished, interesting and easy to scan.

Include:
- a distinctive opening hook,
- the strongest property benefits,
- location,
- bedroom count where available,
- price,
- a clear viewing enquiry call to action,
- the property URL,
- 4 to 7 relevant hashtags.

Do not explain your strategy.
Return only the final caption.
"""

property_input = f"""
EVENT TYPE
{EVENT_TYPE}

PLATFORM
{PLATFORM}

PROPERTY TITLE
{property_data.get("title")}

PRICE
{format_price(property_data.get("price"))}

BEDROOMS
{property_data.get("bedrooms")}

PROPERTY TYPE
{property_data.get("property_type")}

DESCRIPTION
{property_data.get("description")}

PROPERTY URL
{property_data.get("property_url")}

AGENCY
BM Estates
"""

response = client.responses.create(
    model="gpt-5.5",
    instructions=instructions,
    input=property_input
)

caption = response.output_text

print("\nAI CAPTION:\n")
print(caption)