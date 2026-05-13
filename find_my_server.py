# find_my_server.py
import json
from sentence_transformers import SentenceTransformer
from supabase import create_client
from openai import OpenAI

# Load credentials
with open("private/db_env_sample.json") as f:
    config = json.load(f)

supabase = create_client(
    config["supabase_url"],
    config["supabase_key"]
)

client = OpenAI(
    api_key=config["openai_api_key"],
    base_url=config["openai_base_url"]
)

model = SentenceTransformer('all-MiniLM-L6-v2')

def find_my_server(user_query: str):
    print(f"\nFinding servers for: '{user_query}'\n")
    
    # Step 1: Embed user query
    query_embedding = model.encode(user_query).tolist()
    
    # Step 2: Find similar servers via pgvector
    results = supabase.rpc("match_servers", {
        "query_embedding": query_embedding,
        "match_count": 5
    }).execute()
    
    if not results.data:
        print("No matches found!")
        return []
    
    # Step 3: LLM generates explanation for each server
    recommendations = []
    
    for server in results.data:
        prompt = f"""A user is looking for a Mastodon server to join.

User interests: {user_query}

Server profile:
{server['profile_text']}

Write 2-3 sentences explaining why this server is a good match.
Be specific about the topics and community.
Then give a match score 0-100%.

Format exactly like this:
EXPLANATION: <your explanation>
MATCH: <number>%"""

        response = client.chat.completions.create(
            model=config["openai_model"],
            messages=[{"role": "user", "content": prompt}]
        )
        
        result_text = response.choices[0].message.content
        
        # Parse response
        explanation = result_text.split("MATCH:")[0]\
            .replace("EXPLANATION:", "").strip()
        match_pct = result_text.split("MATCH:")[1].strip() \
            if "MATCH:" in result_text else "N/A"
        
        recommendations.append({
            "instance_id": server["instance_id"],
            "similarity_score": round(server["similarity"] * 100, 1),
            "match_score": match_pct,
            "explanation": explanation
        })
        
        # Print results
        print(f"Server: {server['instance_id']}")
        print(f"Similarity: {round(server['similarity'] * 100, 1)}%")
        print(f"Match: {match_pct}")
        print(f"Explanation: {explanation}")
        print("-" * 50)
    
    return recommendations

if __name__ == "__main__":
    query = input("What are your interests? ")
    find_my_server(query)