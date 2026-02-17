from product_validator_search.sources.brave_search.search_tool import search_brave
import json
import os
from dotenv import load_dotenv


def test_brave():
    # Load .env file
    load_dotenv()

    print(
        f"Checking API Key: {'Set' if os.environ.get('BRAVE_SEARCH_API_KEY') else 'MISSING'}"
    )

    print("Running Brave Search query: 'OpenAI vs Google Gemini'...")
    result = search_brave("OpenAI vs Google Gemini", num_results=3)

    if result.get("error"):
        print(f"\n❌ Error: {result['error']}")
    else:
        print(f"\n✅ Success! Found {len(result['results'])} results:\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    test_brave()
