from config import SoPConfig
import requests

JELLYFIN_URL = SoPConfig.JELLYFIN_URL
API_KEY = SoPConfig.JELLYFIN_API_KEY
USER_ID = SoPConfig.JELLYFIN_USER

params = {
    "SearchTerm": "Kardashians",
    "IncludeItemTypes": "Movie,Series",
    "Recursive": "true",
    "UserId": USER_ID,
    "Limit": 100,
}

headers = {
    "Authorization": f'MediaBrowser Token="{API_KEY}"'
}

response = requests.get(
    f"{JELLYFIN_URL}/Items",
    params=params,
    headers=headers
)

response.raise_for_status()

data = response.json()

print(f"Found {data['TotalRecordCount']} result(s):\n")

for item in data["Items"]:
    print(
        f"{item['Type']:6} | "
        f"{item['Name']} | "
        f"ID: {item['Id']}"
    )
