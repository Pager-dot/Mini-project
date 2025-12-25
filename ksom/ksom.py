import requests
from bs4 import BeautifulSoup
import json
import re
import time

# -------------------------------------------------
# CONFIGURATION
# -------------------------------------------------
DIRECTORY_URL = "https://ksom.ac.in/faculty-and-research/faculty/regular-faculty-directory/"
BASE_DOMAIN = "https://ksom.ac.in"
OUTPUT_FILE = "ksom_kiit_profiles.json"
RAG_OUTPUT_FILE = "ksom_kiit_rag_ready.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# -------------------------------------------------
# 1. SAVE DATA FUNCTION
# -------------------------------------------------
def save_data(all_profiles):
    """Saves data in Raw and RAG formats."""
    
    # 1. Raw Data
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_profiles, f, indent=4, ensure_ascii=False)

    # 2. RAG-Optimized Data
    rag_documents = []
    for profile in all_profiles:
        # Flatten the dynamic sections for the RAG context
        dynamic_sections = []
        for section_title, section_content in profile.get("dynamic_sections", {}).items():
            if section_content and section_content.strip():
                clean_content = section_content.replace("\n", " ").strip()
                dynamic_sections.append(f"{section_title}: {clean_content}")
        
        dynamic_text = " | ".join(dynamic_sections)

        summary_text = (
            f"Profile: {profile['name']}. "
            f"Role: {profile.get('role', 'Unknown')}. "
            f"Email: {profile.get('email', 'Not available')}. "
            f"Bio: {profile.get('bio', '')}. "
            f"Info: {dynamic_text}"
        )

        rag_documents.append({
            "page_content": summary_text,
            "metadata": {
                "source": profile['profile_url'],
                "type": "profile_summary",
                "name": profile['name']
            }
        })

    with open(RAG_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(rag_documents, f, indent=4, ensure_ascii=False)
    
    print(f"✅ Data saved to {OUTPUT_FILE} and {RAG_OUTPUT_FILE}")

# -------------------------------------------------
# 2. PROFILE SCRAPER
# -------------------------------------------------
def scrape_profile(url):
    print(f"   -> Scraping: {url}")
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    
    # --- A. Basic Info (Name, Role, Email) ---
    # Located in <div class="faculty-profile-info entry-content">
    info_div = soup.find("div", class_="faculty-profile-info")
    
    name = "Unknown"
    role = "Unknown"
    email = "Not available"

    if info_div:
        # 1. Name
        name_div = info_div.find("div", class_="name")
        if name_div:
            # Remove the icon <i> tag to get clean text
            if name_div.find("i"):
                name_div.find("i").decompose()
            name = name_div.get_text(strip=True)

        # 2. Role (Position)
        role_div = info_div.find("div", class_="position")
        if role_div:
            if role_div.find("i"):
                role_div.find("i").decompose()
            role = role_div.get_text(strip=True)

        # 3. Email
        email_div = info_div.find("div", class_="email")
        if email_div:
            if email_div.find("i"):
                email_div.find("i").decompose()
            email = email_div.get_text(strip=True)

    # --- B. Content Section (Bio & Tabs) ---
    # Located in <section class="faculty-profile-content entry-content">
    content_section = soup.find("section", class_="faculty-profile-content")
    
    bio_text = ""
    dynamic_sections = {}

    if content_section:
        # 1. Extract Bio
        # The bio is usually in the first <div class="wpb_wrapper"> BEFORE the tabs container
        # We find the tabs container first to know where to stop or ignore
        tabs_container = content_section.find("div", class_="vc_tta-panels-container")
        
        # Find all wpb_wrappers
        all_wrappers = content_section.find_all("div", class_="wpb_wrapper")
        
        # Heuristic: The first wrapper is usually the Bio. 
        # If tabs exist, the Bio is the wrapper that is NOT inside the tabs.
        for wrapper in all_wrappers:
            # Check if this wrapper is inside the tabs container
            if tabs_container and tabs_container in wrapper.parents:
                continue # Skip wrappers that are inside tabs for now
            
            # If we are here, this is likely the Bio wrapper
            # Get text from p tags
            bio_paras = [p.get_text(strip=True) for p in wrapper.find_all("p")]
            bio_text = " ".join(bio_paras)
            if bio_text:
                break # Stop after finding the first valid bio wrapper

        # 2. Extract Tabs (Research, Books, etc.)
        if tabs_container:
            # Iterate through each panel
            panels = tabs_container.find_all("div", class_="vc_tta-panel")
            
            for panel in panels:
                # Get Title (e.g., Research Publication)
                # Usually in heading -> h4 -> a -> span.vc_tta-title-text
                title_text = "Section"
                heading = panel.find("div", class_="vc_tta-panel-heading")
                if heading:
                    title_span = heading.find("span", class_="vc_tta-title-text")
                    if title_span:
                        title_text = title_span.get_text(strip=True)
                
                # Get Body Content
                body = panel.find("div", class_="vc_tta-panel-body")
                if body:
                    # Content is usually in wpb_wrapper inside body
                    inner_wrapper = body.find("div", class_="wpb_wrapper")
                    if inner_wrapper:
                        # Extract text from common tags
                        content_items = []
                        for tag in inner_wrapper.find_all(['p', 'li', 'h4', 'h5']):
                            txt = tag.get_text(strip=True)
                            if txt:
                                content_items.append(txt)
                        
                        if content_items:
                            dynamic_sections[title_text] = "\n".join(content_items)

    return {
        "name": name,
        "role": role,
        "email": email,
        "profile_url": url,
        "bio": bio_text,
        "dynamic_sections": dynamic_sections
    }

# -------------------------------------------------
# 3. MAIN CRAWLER
# -------------------------------------------------
def main():
    print(f"Step 1: Crawling Directory: {DIRECTORY_URL}")
    
    try:
        response = requests.get(DIRECTORY_URL, headers=HEADERS, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Error fetching directory: {e}")
        return

    soup = BeautifulSoup(response.text, "html.parser")
    
    profile_links = set()
    
    # Find all anchors
    anchors = soup.find_all("a", href=True)
    
    for a in anchors:
        href = a['href']
        # Filter for KSOM staff links
        if "ksom.ac.in/staff/" in href:
            # Clean URL
            clean_link = href.split("?")[0].rstrip("/") + "/"
            profile_links.add(clean_link)

    print(f"Found {len(profile_links)} unique profiles.")
    
    all_profiles = []
    
    # Step 2: Visit each unique link
    for i, link in enumerate(profile_links):
        print(f"[{i+1}/{len(profile_links)}] Processing...", end="")
        data = scrape_profile(link)
        if data:
            all_profiles.append(data)
        time.sleep(0.5) # Polite delay

    save_data(all_profiles)

if __name__ == "__main__":
    main()