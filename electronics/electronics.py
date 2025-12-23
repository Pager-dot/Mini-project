from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import re
import time
import json
import os
BASE_URL = "https://electronics.kiit.ac.in"
PEOPLE_URL = f"{BASE_URL}/faculty/"
OUTPUT_FILE = "electronics_kiit_profiles.json"
RAG_OUTPUT_FILE = "electronics_kiit_rag_ready.json"

def clean_name_to_slug(name):
    slug = name.lower()
    titles = ["dr.", "prof.", "mr.", "ms.", "er.", "ar."]
    for title in titles:
        if slug.startswith(title):
            slug = slug.replace(title, "").strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = slug.strip().replace(" ", "-")
    return slug

def derive_name_from_url(url):
    """
    Extracts a readable name from the URL for manual entries.
    e.g. .../profiles/abinash-tripathy/ -> Abinash Tripathy
    """
    # Remove trailing slash and split
    clean_url = url.strip().rstrip('/')
    slug = clean_url.split('/')[-1]
    # Replace hyphens with spaces and title case
    return slug.replace('-', ' ').title()

def extract_listing_page():
    print(f"Scraping Listing Page: {PEOPLE_URL}...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(PEOPLE_URL, wait_until="networkidle", timeout=30000)
            html = page.content()
        except Exception as e:
            print(f"Error fetching listing page: {e}")
            return []
        finally:
            browser.close()

    soup = BeautifulSoup(html, "html.parser")
    people = []

    for h2 in soup.find_all("h2"):
        name = h2.text.strip()
        slug = clean_name_to_slug(name)
        profile_url = f"{BASE_URL}/profiles/{slug}/"
        people.append({"name": name, "profile_url": profile_url})
    return people

def extract_key_value_pairs(container, target_dict):
    """Scans a container for <strong>Label:</strong> Value patterns."""
    strong_tags = container.find_all("strong")
    found_any = False

    for strong in strong_tags:
        label = strong.get_text(strip=True).rstrip(" :")
        if not label or re.match(r'^\d+\.', label): continue
        
        value_parts = []
        next_node = strong.next_sibling
        while next_node:
            if hasattr(next_node, 'name') and next_node.name in ['strong', 'h1', 'h2', 'h3', 'h4']:
                break 
            
            if hasattr(next_node, 'get_text'):
                text_val = next_node.get_text(strip=True)
                if text_val: value_parts.append(text_val)
            elif isinstance(next_node, str):
                text_val = next_node.strip()
                if text_val: value_parts.append(text_val)
            
            next_node = next_node.next_sibling
        
        if value_parts:
            target_dict[label] = " ".join(value_parts)
            found_any = True

    if not found_any:
        full_text = container.get_text(" ", strip=True)
        if len(full_text) > 5 and not any(x in full_text.lower() for x in ["journal", "conference"]):
            target_dict["Info"] = full_text

def extract_publications_from_container(container, data_list, seen_set):
    list_items = container.find_all("li")
    if list_items:
        for li in list_items:
            text = li.get_text(strip=True)
            if len(text) > 15 and text not in seen_set:
                seen_set.add(text)
                data_list.append(text)
        return

    full_text = container.get_text(separator="\n", strip=True)
    lines = full_text.split("\n")
    current_buffer = ""
    
    for line in lines:
        line = line.strip()
        if len(line) < 10: continue
        if any(x in line.lower() for x in ["journals/conferences", "recent publications"]): continue

        is_numbered = re.match(r'^\[?\d+\]?[\.\)\s]', line)
        
        if is_numbered:
            if current_buffer and current_buffer not in seen_set:
                seen_set.add(current_buffer)
                data_list.append(current_buffer)
            current_buffer = line
        else:
            if current_buffer:
                if not re.search(r'20\d\d', line): 
                    current_buffer += " " + line
                else:
                    if current_buffer not in seen_set:
                        seen_set.add(current_buffer)
                        data_list.append(current_buffer)
                    current_buffer = line
            else:
                current_buffer = line

    if current_buffer and current_buffer not in seen_set:
        seen_set.add(current_buffer)
        data_list.append(current_buffer)

def scrape_profile_page(profile_url, browser):
    print(f"   -> Visiting: {profile_url}")
    page = browser.new_page()
    try:
        response = page.goto(profile_url, wait_until="domcontentloaded", timeout=15000)
        if response.status == 404:
            page.close()
            return {"error": "Page not found (404)"}
        page.wait_for_timeout(1500) # Give it a moment for JS rendering
        html = page.content()
        page.close()
    except Exception as e:
        page.close()
        return {"error": f"Failed to load: {e}"}

    soup = BeautifulSoup(html, "html.parser")
    data = {
        "role": "Not available",
        "bio": "Not available",
        "sidebar_details": {},
        "socials": [],
        "tab_details": {},
        "publications": []
    }
    seen_pubs = set()

    # 1. Role
    role_tag = soup.find("h3", class_="fusion-title-heading")
    if role_tag:
        text = role_tag.get_text(strip=True)
        if "Links" not in text: data["role"] = text

    # 2. Bio
    main_content = soup.find("div", class_="post-content")
    if main_content:
        bio_div = soup.find("div", class_="fusion-text-2")
        if bio_div:
            data["bio"] = bio_div.get_text(" ", strip=True)
        else:
            for div in main_content.find_all("div", class_="fusion-text"):
                text = div.get_text(strip=True)
                if len(text) > 100 and "Scopus" not in text and "Email" not in text and "Interests" not in text:
                    data["bio"] = text.strip()
                    break

    # 3. Sidebar (Dynamic Key-Values)
    profile_links_header = soup.find("h3", string=re.compile("Profile Links", re.I))
    if profile_links_header:
        header_wrapper = profile_links_header.find_parent("div", class_="fusion-title")
        if header_wrapper:
            curr = header_wrapper.next_sibling
            while curr:
                if hasattr(curr, 'name') and curr.name == 'div' and 'fusion-text' in curr.get('class', []):
                    extract_key_value_pairs(curr, data["sidebar_details"])
                    # Fallback for website
                    if "Website" not in data["sidebar_details"]:
                         for a in curr.find_all("a", href=True):
                             if "mailto" not in a['href']:
                                 data["sidebar_details"]["Website"] = a['href']
                    break 
                curr = curr.next_sibling

    # 4. Socials
    social_header = soup.find("h3", string=re.compile("Social Links", re.I))
    if social_header:
        header_wrapper = social_header.find_parent("div", class_="fusion-title")
        if header_wrapper:
            curr = header_wrapper.next_sibling
            while curr:
                if hasattr(curr, 'name') and curr.name == 'div' and 'fusion-social-links' in curr.get('class', []):
                    social_inner = curr.find("div", class_="fusion-social-networks-wrapper")
                    if social_inner:
                        for a in social_inner.find_all("a", href=True):
                            if a['href'] not in data["socials"]:
                                data["socials"].append(a['href'])
                    break
                curr = curr.next_sibling

    # 5. Tabs
    tab_panes = soup.find_all("div", class_="tab-pane")
    for pane in tab_panes:
        pane_text = pane.get_text(" ", strip=True).lower()
        if any(x in pane_text for x in ["journal", "conference", "publication", "selected paper"]):
            extract_publications_from_container(pane, data["publications"], seen_pubs)
        else:
            extract_key_value_pairs(pane, data["tab_details"])

    # 6. Accordions
    if not data["publications"] and not data["tab_details"]:
        accordions = soup.find_all("div", class_="fusion-accordian")
        for acc in accordions:
            title_node = acc.find("div", class_="panel-heading")
            if title_node:
                t_text = title_node.get_text(strip=True).lower()
                body = acc.find("div", class_="panel-body")
                if body:
                    if any(x in t_text for x in ["publication", "journal"]):
                         extract_publications_from_container(body, data["publications"], seen_pubs)
                    else:
                        data["tab_details"][title_node.get_text(strip=True)] = body.get_text(" ", strip=True)

    return data

def save_data(all_profiles):
    """Saves data in two formats."""
    
    # 1. Raw Data
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_profiles, f, indent=4, ensure_ascii=False)

    # 2. RAG-Optimized Data
    rag_documents = []
    for profile in all_profiles:
        # Document 1: Profile Summary
        sidebar_text = ", ".join([f"{k}: {v}" for k, v in profile.get("sidebar_details", {}).items()])
        tab_text_list = []
        for k, v in profile.get("tab_details", {}).items():
            if v and v != "Not available":
                tab_text_list.append(f"{k}: {v}")
        tab_text_str = ". ".join(tab_text_list)

        summary_text = (
            f"Profile: {profile['name']}. "
            f"Role: {profile.get('role', 'Unknown')}. "
            f"Bio: {profile.get('bio', '')} "
            f"Details: {sidebar_text}. "
            f"Additional Info: {tab_text_str}"
        )

        rag_documents.append({
            "page_content": summary_text,
            "metadata": {
                "source": profile['profile_url'],
                "type": "profile_summary",
                "name": profile['name']
            }
        })

        # Document 2: Publications
        pubs = profile.get('publications', [])
        if pubs:
            pubs_text = "\n".join(pubs)
            rag_documents.append({
                "page_content": f"Publications by {profile['name']}:\n{pubs_text}",
                "metadata": {
                    "source": profile['profile_url'],
                    "type": "publications",
                    "name": profile['name']
                }
            })

    with open(RAG_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(rag_documents, f, indent=4, ensure_ascii=False)
    
    print(f"✅ Data saved to {OUTPUT_FILE} and {RAG_OUTPUT_FILE}")

def main():
    print("--- Starting KIIT Scraper ---")
    
    # 1. Initial Scrape from Listing
    try:
        people_listing = extract_listing_page()
    except:
        people_listing = []
    
    print(f"\nFound {len(people_listing)} people initially.\n")

    all_profiles = []
    # If you want to append to existing file instead of overwrite, load it here:
    # if os.path.exists(OUTPUT_FILE):
    #     with open(OUTPUT_FILE, 'r') as f: all_profiles = json.load(f)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        # --- Batch Processing ---
        for person in people_listing:
            print("-" * 60)
            print(f"Processing: {person['name']}")
            
            profile_data = scrape_profile_page(person["profile_url"], browser)
            full_profile = {**person, **profile_data}
            
            if "error" not in profile_data:
                all_profiles.append(full_profile)
                print(f"   -> Success. {len(profile_data.get('publications', []))} pubs found.")
            else:
                print(f"   -> Skipped (Error: {profile_data['error']}).")

            time.sleep(1)

        # Save batch results
        save_data(all_profiles)

        # --- Interactive Mode for Missed URLs ---
        print("\n" + "="*60)
        print(" INITIAL BATCH COMPLETE. ENTER MANUAL URLs BELOW.")
        print("="*60)

        while True:
            print("\nDid any URLs fail? Or do you have specific URLs to add?")
            user_url = input("Enter URL (or press Enter/Type 'q' to finish): ").strip()
            
            if not user_url or user_url.lower() == 'q':
                print("Exiting scraper. Goodbye!")
                break
            
            # Simple validation
            if "ksca.kiit.ac.in" not in user_url:
                print("⚠️  Warning: That doesn't look like a valid KIIT URL. Trying anyway...")

            # Derive name and structure basic object
            manual_name = derive_name_from_url(user_url)
            print(f"\nManually Scraping: {manual_name}")
            print(f"Link: {user_url}")

            # Scrape using the same logic
            manual_data = scrape_profile_page(user_url, browser)
            
            if "error" in manual_data:
                print(f"❌ Failed to scrape manual URL: {manual_data['error']}")
            else:
                # Construct full profile object
                manual_profile = {
                    "name": manual_name,
                    "profile_url": user_url,
                    **manual_data
                }
                
                # Check for duplicates before adding
                existing = next((item for item in all_profiles if item["profile_url"] == user_url), None)
                if existing:
                    print("⚠️  URL already exists in data. Updating it.")
                    all_profiles.remove(existing)
                
                all_profiles.append(manual_profile)
                
                # Immediate Save
                save_data(all_profiles)
                
                print(f"✅ Successfully added {manual_name}. Data re-saved.")
                print(f"   Details found: {list(manual_data.get('sidebar_details', {}).keys())}")
                print(f"   Pubs found: {len(manual_data.get('publications', []))}")

        browser.close()

if __name__ == "__main__":
    main()