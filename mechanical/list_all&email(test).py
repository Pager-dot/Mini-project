import requests
from bs4 import BeautifulSoup

url = "https://mechanical.kiit.ac.in/faculty/"

# Fetch the webpage
response = requests.get(url)
response.raise_for_status()  # stops if request fails

# Parse HTML
soup = BeautifulSoup(response.text, "html.parser")

# Find all <a> tags with the required class
links = soup.find_all(
    "a",
    class_="fusion-no-lightbox",
    href=True
)

print("Faculty profile links:\n")

# Create a set to store unique faculty links
unique_faculty_links = set()

for a in links:
    href = a.get("href")
    # Check if link exists and belongs to the faculty domain
    if href and href.startswith("https://faculty.kiit.ac.in/"):
        unique_faculty_links.add(href)

print("Total Faculty found: ",len(unique_faculty_links))

# Sort the unique links alphabetically and print them
for link in sorted(unique_faculty_links):
    print(link)



from playwright.sync_api import sync_playwright
import time

profile_url = "https://faculty.kiit.ac.in/abhilas-swain/"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    page.goto(profile_url, timeout=60000)

    # wait for social icons to load
    page.wait_for_selector("div.fusion-social-links", timeout=10000)

    # give Cloudflare JS time to decode email
    time.sleep(2)

    # get all social <a> elements
    links = page.query_selector_all(
        "div.fusion-social-links a"
    )

    email = None
    social_links = []

    for a in links:
        href = a.get_attribute("href")

        if not href:
            continue

        if href.startswith("mailto:"):
            email = href.replace("mailto:", "")
        elif href.startswith("http"):
            social_links.append(href)

    print("Email:", email)
    print("Social Links:", social_links)

    browser.close()
