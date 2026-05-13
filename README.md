##Supabase config

Save resources to connect supabase db:
private/db_env.json

Example:
{
  "supabase_url": "https://your-project.supabase.co",
  "supabase_key": "your-key"
}

## Files
| File | Description |
|------|-------------|
| `build_profiles.py` | Builds server profiles from DB |
| `embed_profiles.py` | Embeds profiles using sentence-transformers |
| `find_my_server.py` | RAG-based server recommendation |