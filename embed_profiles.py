# embed_profiles.py
import json
from sentence_transformers import SentenceTransformer
from supabase import create_client

# Load credentials
with open("private/db_env_sample.json") as f:
    config = json.load(f)

supabase = create_client(
    config["supabase_url"],
    config["supabase_key"]
)

# Free local model - no API key needed
model = SentenceTransformer('all-MiniLM-L6-v2')

def embed_all_profiles():
    # Get profiles without embeddings
    profiles = supabase.table("server_profiles")\
        .select("id, profile_text")\
        .is_("embedding", "null")\
        .execute()
    
    print(f"Found {len(profiles.data)} profiles to embed")
    
    success_count = 0
    
    for profile in profiles.data:
        try:
            # Generate embedding locally
            embedding = model.encode(profile["profile_text"]).tolist()
            
            # Store embedding
            supabase.table("server_profiles")\
                .update({"embedding": embedding})\
                .eq("id", profile["id"])\
                .execute()
            
            success_count += 1
            print(f"✓ Embedded profile {profile['id']}")
            
        except Exception as e:
            print(f"✗ Failed profile {profile['id']}: {e}")
    
    print(f"\nDone! Embedded {success_count} profiles")

if __name__ == "__main__":
    embed_all_profiles()