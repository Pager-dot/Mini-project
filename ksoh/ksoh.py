import requests
from bs4 import BeautifulSoup
import time
import random
import json
from playwright.sync_api import sync_playwright

FACULTY_LIST_URL = "https://ksoh.kiit.ac.in/faculty/"

OUTPUT_FILE = "ksoh_kiit_profiles.json"
RAG_OUTPUT_FILE = "ksoh_kiit_rag_ready.json"


# -------------------------------------------------
# SAVE DATA (RAW + RAG)
# -------------------------------------------------
def save_data(all_profiles):

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_profiles, f, indent=4, ensure_ascii=False)

    rag_documents = []

    for profile in all_profiles:
        sidebar_text = ", ".join(
            [f"{k}: {v}" for k, v in profile.get("sidebar_details", {}).items() if v]
        )

        tab_text_list = []
        for section, values in profile.get("tab_details", {}).items():
            if values:
                tab_text_list.append(f"{section}: {' '.join(values)}")

        summary_text = (
            f"Profile: {profile['name']}. "
            f"Role: {profile.get('role', 'Unknown')}. "
            f"Bio: {profile.get('bio', '')}. "
            f"Details: {sidebar_text}. "
            f"Additional Info: {' '.join(tab_text_list)}"
        )

        rag_documents.append({
            "page_content": summary_text,
            "metadata": {
                "source": profile["profile_url"],
                "type": "profile_summary",
                "name": profile["name"]
            }
        })

    with open(RAG_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(rag_documents, f, indent=4, ensure_ascii=False)

    print(f" Data saved to {OUTPUT_FILE} and {RAG_OUTPUT_FILE}")


# -------------------------------------------------
# 1. FAST REQUESTS SESSION
# -------------------------------------------------
session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://mechanical.kiit.ac.in/"
})


# -------------------------------------------------
# 2. GET FACULTY LINKS (BS)
# -------------------------------------------------
resp = session.get(FACULTY_LIST_URL, timeout=15)
resp.raise_for_status()

soup = BeautifulSoup(resp.text, "html.parser")

faculty_links = sorted({
    a["href"]
    for a in soup.find_all("a", href=True)
    if "faculty.kiit.ac.in/" in a["href"]
})

print(f"Total faculty found: {len(faculty_links)}")
print("=" * 80)


all_profiles = []


# -------------------------------------------------
# 3. PLAYWRIGHT (ONE BROWSER)
# -------------------------------------------------
with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"]
    )
    page = browser.new_page()

    for idx, profile_url in enumerate(faculty_links, start=1):
        print(f"\n[{idx}/{len(faculty_links)}] Fetching: {profile_url}")

        page.goto(profile_url, timeout=60000)

        try:
            page.wait_for_selector("div.fusion-social-links", timeout=8000)
        except:
            pass

        time.sleep(random.uniform(0.9, 1.6))

        html = page.content()
        psoup = BeautifulSoup(html, "html.parser")

        # -------------------------
        # BASIC INFO
        # -------------------------
        name = psoup.select_one("h1.entry-title")
        name = name.get_text(strip=True) if name else "N/A"

        role_div = psoup.select_one(
            "div.fusion-title-size-four"
        )
        role = role_div.get_text(" ", strip=True) if role_div else "N/A"

        bio_div = psoup.select_one("div.fusion-text-1")
        bio = bio_div.get_text(" ", strip=True) if bio_div else "N/A"

        # -------------------------
        # EMAIL + SOCIAL
        # -------------------------
        email = None
        socials = []

        for a in psoup.select("div.fusion-social-links a[href]"):
            href = a["href"]
            if href.startswith("mailto:"):
                email = href.replace("mailto:", "")
            elif href.startswith("http"):
                socials.append(href)

        # -------------------------
        # ACADEMIC LINKS
        # -------------------------
        academic = {"Scopus": None, "Google Scholar": None, "ORCID": None}

        for a in psoup.find_all("a", href=True):
            h = a["href"].lower()
            if "scopus.com" in h:
                academic["Scopus"] = a["href"]
            elif "scholar.google" in h:
                academic["Google Scholar"] = a["href"]
            elif "orcid.org" in h:
                academic["ORCID"] = a["href"]

        # -------------------------
        # TAB CONTENT (SAFE JS)
        # -------------------------
        tab_data = page.evaluate("""
        () => {
            const result = {};
            document.querySelectorAll("div.tab-content").forEach(tab => {
                tab.querySelectorAll("p span").forEach(span => {
                    const label = span.innerText.trim();
                    let p = span.closest("p");
                    let el = p.nextElementSibling;
                    let content = [];

                    while (el) {
                        if (el.tagName === "P" && el.querySelector("span")) break;
                        if (el.innerText?.trim()) content.push(el.innerText.trim());
                        el = el.nextElementSibling;
                    }
                    result[label] = content;
                });
            });
            return result;
        }
        """)

        profile = {
            "profile_url": profile_url,
            "name": name,
            "role": role,
            "bio": bio,
            "email": email,
            "social_links": socials,
            "academic_profiles": academic,
            "sidebar_details": {
                "Email": email,
                **academic
            },
            "tab_details": tab_data
        }

        all_profiles.append(profile)

        print(f" {name} scraped")

        time.sleep(random.uniform(0.8, 1.8))

    browser.close()


# -------------------------------------------------
# SAVE EVERYTHING
# -------------------------------------------------
save_data(all_profiles)
