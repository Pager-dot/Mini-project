import requests
from bs4 import BeautifulSoup
import json
import re
import time

# -------------------------------------------------
# CONFIGURATION
# -------------------------------------------------
BASE_URL = "https://ksoft.kiit.ac.in/faculty/"
OUTPUT_FILE = "ksoft_kiit_profiles.json"
RAG_OUTPUT_FILE = "ksoft_kiit_rag_ready.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# -------------------------------------------------
# 1. HELPER: Decode Cloudflare Emails
# -------------------------------------------------
def decode_cfemail(cf_hex):
    try:
        r = int(cf_hex[:2], 16)
        email = ''.join([chr(int(cf_hex[i:i+2], 16) ^ r) for i in range(2, len(cf_hex), 2)])
        return email
    except:
        return ""

# -------------------------------------------------
# 2. SAVE DATA FUNCTION
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
            f"Phone: {profile.get('phone', 'Not available')}. "
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
# 3. DYNAMIC PROFILE SCRAPER (UPDATED FOR YOUR HTML)
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
    
    # Target the Main Container
    main_container = soup.find("main", id="main")
    if not main_container:
        main_container = soup # Fallback if ID is missing

    # --- A. Extract Name ---
    name = "Unknown"
    
    # Strategy 1: Look for the specific 'fusion-title-2' div as seen in your HTML
    # The first fusion-title is "FACULTY", the second (fusion-title-2) is the Name.
    title_div = main_container.find("div", class_="fusion-title-2")
    if title_div:
        name_tag = title_div.find("h2")
        if name_tag:
            name = name_tag.get_text(strip=True)
    
    # Strategy 2: Fallback to the standard WP entry-title H1 if Strategy 1 failed
    if name == "Unknown":
        h1_tag = main_container.find("h1", class_="entry-title")
        if h1_tag:
            name = h1_tag.get_text(strip=True)

    # --- B. Extract Role ---
    role = "Faculty"
    
    # Strategy: Your HTML shows the role is in 'fusion-text-2'
    role_div = main_container.find("div", class_="fusion-text-2")
    if role_div:
        role_text = role_div.get_text(strip=True)
        if role_text:
            role = role_text

    # --- C. Extract Email & Phone ---
    email = "Not available"
    phone = "Not available"

    # In your HTML, Email is in 'fusion-text-3', but we search all text divs to be safe
    text_divs = main_container.find_all("div", class_="fusion-text")
    
    for div in text_divs:
        html_content = str(div)
        text_content = div.get_text(separator=" ", strip=True)

        # 1. Email Detection
        if email == "Not available":
            # Cloudflare check
            if "data-cfemail" in html_content:
                try:
                    cf_tag = div.find(attrs={"data-cfemail": True})
                    if cf_tag:
                        email = decode_cfemail(cf_tag["data-cfemail"])
                except:
                    pass
            
            # Regex fallback
            if email == "Not available":
                email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text_content)
                if email_match:
                    email = email_match.group(0)

        # 2. Phone Detection
        if phone == "Not available" and ("Phone" in text_content or "Mobile" in text_content):
            phone_match = re.search(r'[\+\d\s\-]{10,}', text_content)
            if phone_match:
                phone = phone_match.group(0).strip()

    # --- D. Dynamic Bio/Research Sections ---
    dynamic_sections = {}
    current_section = "Biography" # Default bucket
    dynamic_sections[current_section] = []

    # Strategy: Find the main content div.
    # In your HTML, this is 'fusion-text-4'. 
    # To be robust, we find the fusion-text div with the *longest* text length
    # that ISN'T the role (text-2) or email (text-3).
    
    target_content_div = None
    max_len = 0
    
    for div in text_divs:
        # Skip the Role and Email divs based on class if possible, or length
        classes = div.get("class", [])
        if "fusion-text-2" in classes or "fusion-text-3" in classes:
            continue
            
        txt_len = len(div.get_text(strip=True))
        if txt_len > max_len:
            max_len = txt_len
            target_content_div = div
    
    # If we found the content div (likely fusion-text-4)
    if target_content_div:
        # Iterate over immediate children (p, ul, ol, h3, h4)
        elements = target_content_div.find_all(['p', 'ul', 'ol', 'h3', 'h4', 'div'])
        
        for el in elements:
            text = el.get_text(separator=" ", strip=True)
            if not text: continue
            
            # --- HEADER DETECTION LOGIC ---
            is_new_header = False
            header_text = ""
            body_text = ""

            # Check 1: <p><strong>Header</strong></p> OR <p><strong>Header :</strong> content</p>
            strong_tag = el.find("strong")
            
            if strong_tag:
                strong_text = strong_tag.get_text(strip=True)
                
                # If the paragraph *starts* with the bold text
                if text.startswith(strong_text):
                    clean_header = strong_text.replace(":", "").replace("-", "").strip()
                    
                    # Valid headers are usually short (e.g., "Research Interest", "Publications")
                    if len(clean_header) < 50 and len(clean_header) > 2:
                        is_new_header = True
                        header_text = clean_header
                        
                        # The body is the text *after* the header
                        # We use simple string replacement for the first occurrence
                        body_text = text[len(strong_text):].strip()
                        
                        # Remove leading colons/hyphens from the body text
                        if body_text.startswith(":") or body_text.startswith("-"):
                            body_text = body_text[1:].strip()

            # Check 2: Explicit H3/H4 tags
            if el.name in ['h3', 'h4']:
                 is_new_header = True
                 header_text = text
                 body_text = ""

            # --- APPEND TO SECTIONS ---
            if is_new_header:
                current_section = header_text
                if current_section not in dynamic_sections:
                    dynamic_sections[current_section] = []
                
                if body_text:
                    dynamic_sections[current_section].append(body_text)
            else:
                # Regular text -> append to current section
                dynamic_sections[current_section].append(text)

    # Clean up sections (join lists to strings)
    final_sections = {k: "\n".join(v) for k, v in dynamic_sections.items() if v}

    return {
        "name": name,
        "role": role,
        "email": email,
        "phone": phone,
        "profile_url": url,
        "dynamic_sections": final_sections
    }

# -------------------------------------------------
# 4. MAIN CRAWLER
# -------------------------------------------------
def main():
    print(f"Step 1: Crawling Directory: {BASE_URL}")
    
    try:
        response = requests.get(BASE_URL, headers=HEADERS, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Error fetching directory: {e}")
        return

    soup = BeautifulSoup(response.text, "html.parser")
    profile_links = set()
    anchors = soup.find_all("a", href=True)
    
    for a in anchors:
        href = a['href']
        if BASE_URL in href and href != BASE_URL:
            clean_link = href.split("?")[0].rstrip("/") + "/"
            profile_links.add(clean_link)

    print(f"Found {len(profile_links)} unique profiles.")
    
    all_profiles = []
    
    for i, link in enumerate(profile_links):
        print(f"[{i+1}/{len(profile_links)}] Processing...", end="")
        data = scrape_profile(link)
        if data:
            all_profiles.append(data)
        time.sleep(0.5) 

    save_data(all_profiles)

if __name__ == "__main__":
    main()