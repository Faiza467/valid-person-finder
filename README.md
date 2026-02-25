A FastAPI-based tool that, given a company name and a role (e.g., "CEO", "Founder"), discovers the full name of the person currently holding that position. It searches multiple   search engines, extracts   names from prgrph and web pages, validates them, and returns a structured JSON result with a confidence score.

Name Extraction Process:
The name extraction pipeline is designed to locate and verify the full name of a person holding a specific role at a given company using only available web sources. It begins by generating a set of smart search queries that expand the input role with common aliases (e.g., “CEO” → “Chief Executive Officer”). These queries are submitted to multiple search engines—primarily DuckDuckGo (no API key required) and optionally Brave Search to retrieve a diverse set of results. For each result, the tool first examines the search snippet, which often contains the name in context. If the snippet yields a candidate, the page is not fetched, saving time. Otherwise, the tool fetches the page’s HTML, removes script and style tags, and extracts the visible text. To identify names, it uses a combination of flexible regular expressions that capture patterns such as “Sundar Pichai, CEO of Google” or “Google CEO Sundar Pichai”.(optional) If spaCy is installed, a named entity recognition (NER) model is applied as a more robust alternative. Every candidate name is validated by ensuring it consists of at least two capitalized words and does not contain common job titles or stopwords. Validated names are recorded along with the source URL and a credibility score based on the domain (e.g., LinkedIn = 0.95, Wikipedia = 0.9, news sites = 0.8). When the same name appears in multiple independent sources, its confidence score is boosted. Finally, the name with the highest combined score is selected, split into first and last name, and returned in a structured JSON response together with the source URL and confidence value.

Steps to Run the Program:
1. Clone the Repository
2. Set Up a Virtual Environment 
3. Install Dependencies (fastapi uvicorn requests beautifulsoup4 duckduckgo-search)
4. Run the FastAPI Server
5. Access the Web Interface
