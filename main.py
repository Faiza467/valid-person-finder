from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
import requests
from bs4 import BeautifulSoup
import re
from ddgs import DDGS
import logging
import traceback
from collections import defaultdict
from typing import List, Dict, Optional
import time
import os
from urllib.parse import urlparse
import hashlib
import json

 
try:
    import spacy
    nlp = spacy.load("en_core_web_sm")
    USE_NER = True
except:
    USE_NER = False
    nlp = None

 
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
USE_BRAVE = bool(BRAVE_API_KEY)

app = FastAPI()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
 
cache = {
    "search": {},     
    "page": {}          
}

def cache_key(*args):
    return hashlib.md5("|".join(str(a) for a in args).encode()).hexdigest()

 
def build_queries(company: str, role: str) -> List[str]:
     
    aliases = {
        "CEO": ["Chief Executive Officer", "Chief Executive"],
        "CTO": ["Chief Technology Officer", "Chief Technical Officer"],
        "CFO": ["Chief Financial Officer"],
        "CMO": ["Chief Marketing Officer", "Marketing Director"],
        "COO": ["Chief Operating Officer"],
        "Founder": ["Co-Founder", "Founding Partner"],
        "Director": ["Managing Director", "Executive Director"],
        "Manager": ["General Manager", "Senior Manager"],
        "President": ["President & CEO"],
    } 
    role_upper = role.upper()
    role_variants = [role] + aliases.get(role_upper, [])
 
    if "&" in role:
        parts = [p.strip() for p in role.split("&")]
        for p in parts:
            role_variants.extend(aliases.get(p.upper(), []))
    
    queries = []
    for r in role_variants:
        queries.append(f"{company} {r}")
        queries.append(f"Who is the {r} of {company}")
        queries.append(f"{company} {r} LinkedIn")
        queries.append(f"{company} leadership {r}")   
        queries.append(f"{company} about {r}")        
    return list(set(queries))  
 
def search_duckduckgo(query: str, max_results: int = 20) -> List[Dict]:
    key = cache_key("ddg", query)
    if key in cache["search"]:
        logger.info(f"Cache hit for DDG query: {query}")
        return cache["search"][key]
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            cache["search"][key] = results
            return results
    except Exception as e:
        logger.error(f"DuckDuckGo search failed: {e}")
        return []

def search_brave(query: str, max_results: int = 20) -> List[Dict]:
    if not USE_BRAVE:
        return []
    key = cache_key("brave", query)
    if key in cache["search"]:
        logger.info(f"Cache hit for Brave query: {query}")
        return cache["search"][key]
    try:
        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY}
        params = {"q": query, "count": max_results}
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            results = []
            for item in data.get("web", {}).get("results", []):
                results.append({
                    "title": item.get("title"),
                    "href": item.get("url"),
                    "body": item.get("description")
                })
            cache["search"][key] = results
            return results
        else:
            logger.error(f"Brave search error {resp.status_code}")
            return []
    except Exception as e:
        logger.error(f"Brave search exception: {e}")
        return []

def search_all_engines(query: str) -> List[Dict]:
    """Combine results from all enabled engines."""
    results = []
    results.extend(search_duckduckgo(query))
    if USE_BRAVE:
        results.extend(search_brave(query))
    
    seen = set()
    unique = []
    for r in results:
        url = r.get("href") or r.get("url")
        if url and url not in seen:
            seen.add(url)
            unique.append(r)
    return unique
 
def is_likely_name(candidate: str) -> bool:
    words = candidate.split()
    if len(words) < 2:
        return False 
    for w in words:
        if not re.match(r'^[A-Z][a-zA-Z.]*$', w):
            return False 
    blacklist = {"Chief", "Executive", "Officer", "Founder", "Director", "Manager",
                 "Google", "Company", "Inc", "Ltd", "Corporation", "The", "And", "Of",
                 "President", "Chairman", "Board", "Member", "Head", "Lead"}
    if any(w in blacklist for w in words):
        return False
    return True

def extract_name_with_ner(text: str, company: str, role: str) -> Optional[str]:
    if not USE_NER:
        return None
    doc = nlp(text[:10000])   
    company_lower = company.lower()
    role_lower = role.lower()
    for ent in doc.ents:
        if ent.label_ == "PERSON": 
            sent = ent.sent.text.lower()
            if company_lower in sent and role_lower in sent:
                name = ent.text.strip()
                if is_likely_name(name):
                    return name
    return None

def extract_name_from_text(text: str, company: str, role: str) -> Optional[str]:
 
    if USE_NER:
        name = extract_name_with_ner(text, company, role)
        if name:
            return name
 
    company_esc = re.escape(company)
    role_esc = re.escape(role)
    patterns = [
        rf'([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{1,2}})[,\s]+{role_esc}\s+of\s+{company_esc}',
        rf'{company_esc}\s+{role_esc}\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{1,2}})',
        rf'([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{1,2}})\s+is\s+(?:the\s+)?{role_esc}\s+of\s+{company_esc}',
        rf'([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{1,2}})[,\s]+who\s+is\s+{role_esc}\s+of\s+{company_esc}',
        rf'([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{1,2}})\s+[–—]\s+{role_esc}\s+of\s+{company_esc}',
        rf'{role_esc}:\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{1,2}})',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            if isinstance(match, tuple):
                candidate = match[0]
            else:
                candidate = match
            candidate = candidate.strip()
            if is_likely_name(candidate):
                return candidate
    return None

def extract_name_from_snippet(snippet: str, company: str, role: str) -> Optional[str]:
    return extract_name_from_text(snippet, company, role)
 
def fetch_page_text(url: str, max_chars: int = 5000) -> str:
 
    key = cache_key("page", url)
    if key in cache["page"]:
        logger.debug(f"Cache hit for page: {url}")
        return cache["page"][key]
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for script in soup(["script", "style"]):
                script.decompose()
            text = soup.get_text(separator=" ", strip=True)
            truncated = text[:max_chars]
            cache["page"][key] = truncated
            return truncated
    except Exception as e:
        logger.debug(f"Failed to fetch {url}: {e}")
    cache["page"][key] = ""
    return ""
 
def source_credibility(url: str) -> float:
    domain = urlparse(url).netloc.lower()
 
    if "linkedin.com" in domain:
        return 0.95
    if "wikipedia.org" in domain:
        return 0.9
    if any(x in domain for x in [".gov", ".edu"]):
        return 0.85
 
    trusted = ["bloomberg", "reuters", "wsj", "nytimes", "bbc", "forbes", "techcrunch",
               "cnbc", "ft.com", "economist", "apnews"]
    if any(t in domain for t in trusted):
        return 0.8
     
    return 0.6
 
@app.get("/search")
def search(company: str, role: str):
    try:
        queries = build_queries(company, role)
        name_candidates = defaultdict(list)   

        for query in queries:
            logger.info(f"Running query: {query}")
            results = search_all_engines(query)  # use both engines
            for res in results:
                url = res.get("href") or res.get("url")
                if not url:
                    continue

                 
                snippet = res.get("body", "")
                if snippet:
                    name = extract_name_from_snippet(snippet, company, role)
                    if name:
                        logger.info(f"Found name '{name}' in snippet of {url}")
                        name_candidates[name].append((url, source_credibility(url)))
                        continue   
                page_text = fetch_page_text(url)
                if page_text:
                    name = extract_name_from_text(page_text, company, role)
                    if name:
                        logger.info(f"Found name '{name}' in page {url}")
                        name_candidates[name].append((url, source_credibility(url)))

     
            if len(name_candidates) >= 2 and sum(len(v) for v in name_candidates.values()) >= 3:
                break

        if not name_candidates:
            return {"error": "No credible source found", "details": "Could not extract any name."}
 
        best_name = None
        best_score = 0.0
        best_url = ""

        for name, sources in name_candidates.items():
             
            base_avg = sum(score for _, score in sources) / len(sources)
 
            multiplier = 1.0 + (len(sources) * 0.1)   

         
            name_parts = name.split()
            if len(name_parts) == 2 and name_parts[0] in {"John", "Jane", "David", "Sarah"}:
                multiplier *= 0.9   
           
            if any(news in best_url for news in ["/news/", "/article/", "bloomberg", "reuters"]):
                multiplier *= 1.05

            final_score = min(base_avg * multiplier, 1.0)

            if final_score > best_score:
                best_score = final_score
                best_name = name
                best_url = max(sources, key=lambda x: x[1])[0]

        if not best_name:
            return {"error": "Could not determine a valid name."}

        # Split name
        name_parts = best_name.split()
        first = name_parts[0]
        last = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

        return {
            "first_name": first,
            "last_name": last,
            "title": role,
            "company": company,
            "source_url": best_url,
            "confidence": round(best_score, 2)
        }

    except Exception:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal server error")

# ---------- Frontend  ----------
@app.get("/", response_class=HTMLResponse)
def home():
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Company Role Finder</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            input, button { padding: 8px; margin: 5px; }
            #result { background: #f4f4f4; padding: 10px; border-radius: 5px; }
        </style>
    </head>
    <body>
        <h2>Find CEO/CTO/CFO of a Company</h2>
        <input id="company" placeholder="Company (e.g. Google)" />
        <input id="role" placeholder="Role (e.g. CEO)" />
        <button onclick="search()">Find</button>
        <pre id="result"></pre>

        <script>
            async function search() {
                const company = document.getElementById('company').value;
                const role = document.getElementById('role').value;
                const res = await fetch(`/search?company=${encodeURIComponent(company)}&role=${encodeURIComponent(role)}`);
                const data = await res.json();
                document.getElementById('result').textContent = JSON.stringify(data, null, 2);
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)