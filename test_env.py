from dotenv import load_dotenv
import os

load_dotenv()

print("OpenAI key loaded:", bool(os.getenv("OPENAI_API_KEY")))
print("Supabase URL loaded:", os.getenv("SUPABASE_URL"))
print("Supabase key loaded:", bool(os.getenv("SUPABASE_KEY")))