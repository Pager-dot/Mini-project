from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import re

URL = "https://ksca.kiit.ac.in/people/"

email_regex = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)

people = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(URL, wait_until="networkidle")
    page.wait_for_timeout(3000)  # ensure JS-rendered content
    html = page.content()
    browser.close()

soup = BeautifulSoup(html, "html.parser")

# Each person is identified by <h2> (confirmed)
for h2 in soup.find_all("h2"):
    name = h2.text.strip()

    container = h2.find_parent("div")
    if not container:
        continue

    # ---------- EMAIL ----------
    email = "Not available"
    text = container.get_text(" ", strip=True)
    match = email_regex.search(text)
    if match:
        email = match.group()

    # ---------- SOCIAL LINKS ----------
    socials = {
        "linkedin": None,
        "github": None,
        "x": None,
        "facebook": None
    }

    for a in container.find_all("a", href=True):
        href = a["href"].strip()

        if "linkedin.com" in href:
            socials["linkedin"] = href

        elif "github.com" in href or "github.io" in href:
            socials["github"] = href

        elif "twitter.com" in href or "x.com" in href:
            socials["x"] = href.replace("twitter.com", "x.com")

        elif "facebook.com" in href:
            socials["facebook"] = href

    people.append({
        "name": name,
        "email": email,
        "linkedin": socials["linkedin"],
        "github": socials["github"],
        "x": socials["x"],
        "facebook": socials["facebook"]
    })

# ---------- OUTPUT ----------
print(f"\nFound {len(people)} people\n")

for p in people:
    print("=" * 80)
    print("Name     :", p["name"])
    print("Email    :", p["email"])
    print("LinkedIn :", p["linkedin"] or "Not available")
    print("GitHub   :", p["github"] or "Not available")
    print("X        :", p["x"] or "Not available")
    print("Facebook :", p["facebook"] or "Not available")
