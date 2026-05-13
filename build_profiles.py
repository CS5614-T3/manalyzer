# build_profiles.py
import json
from supabase import create_client

# Load credentials from private/db_env.json
with open("private/db_env_sample.json") as f:
    config = json.load(f)

supabase = create_client(
    config["supabase_url"],
    config["supabase_key"]
)

def build_server_profiles():
    # Get all instances
    instances = supabase.table("instances_raw")\
        .select("id, name, short_description, topic, languages, categories, active_users")\
        .execute()
    
    print(f"Found {len(instances.data)} instances")
    
    success_count = 0
    skip_count = 0

    for instance in instances.data:
        instance_name = instance.get("name", "")
        
        if not instance_name:
            skip_count += 1
            continue
        
        # Get trending hashtags for this instance
        trends = supabase.table("trends_raw")\
            .select("name")\
            .eq("base_url", instance_name)\
            .execute()
        
        hashtags = [t["name"] for t in trends.data]
        
        # Build languages string
        languages = instance.get("languages") or []
        languages_str = ", ".join(languages) if languages else "Not specified"
        
        # Build categories string
        categories = instance.get("categories") or []
        categories_str = ", ".join(categories) if categories else "General"
        
        # Build profile text
        profile_text = f"""
Server: {instance_name}
Description: {instance.get('short_description') or 'No description available'}
Topic: {instance.get('topic') or 'General'}
Languages: {languages_str}
Categories: {categories_str}
Active Users: {instance.get('active_users') or 0}
Trending hashtags: {', '.join(hashtags) if hashtags else 'No trends available'}
        """.strip()
        
        # Store in server_profiles
        supabase.table("server_profiles").upsert({
            "instance_id": instance.get("id"),
            "profile_text": profile_text,
            "top_hashtags": hashtags
        }).execute()
        
        success_count += 1
        print(f"✓ Built profile for {instance_name} ({len(hashtags)} hashtags)")
    
    print(f"\nDone! Built {success_count} profiles, skipped {skip_count}")

if __name__ == "__main__":
    build_server_profiles()