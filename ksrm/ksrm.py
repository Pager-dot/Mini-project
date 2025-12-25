import requests
from bs4 import BeautifulSoup
import json
import re

FACULTY_LIST_URL = "https://ksrm.ac.in/faculty/"
OUTPUT_FILE = "ksrm_kiit_profiles.json"
RAG_OUTPUT_FILE = "ksrm_kiit_rag_ready.json"

# -------------------------------------------------
# 1. HELPER: Decode Cloudflare Emails
# -------------------------------------------------
def decode_cfemail(cf_hex):
    """Decodes the Cloudflare protected email hex string."""
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
    """Saves data in two formats."""
    
    # 1. Raw Data
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_profiles, f, indent=4, ensure_ascii=False)

    # 2. RAG-Optimized Data
    rag_documents = []
    for profile in all_profiles:
        # Prepare text sections
        sidebar_text = ", ".join([f"{k}: {v}" for k, v in profile.get("sidebar_details", {}).items() if v])
        
        tab_text_list = []
        for k, v in profile.get("tab_details", {}).items():
            if v and v != "Not available":
                tab_text_list.append(f"{k}: {v}")
        tab_text_str = ". ".join(tab_text_list)

        # Build Summary
        summary_text = (
            f"Profile: {profile['name']}. "
            f"Role: {profile.get('role', 'Unknown')}. "
            f"Bio: {profile.get('bio', '')} "
            f"Contact: {sidebar_text}. "
            f"Details: {tab_text_str}"
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
# 3. MAIN SCRAPER
# -------------------------------------------------
def main():
    print(f"Fetching: {FACULTY_LIST_URL}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(FACULTY_LIST_URL, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Error fetching URL: {e}")
        return

    soup = BeautifulSoup(response.text, "html.parser")
    all_profiles = []

    # The KSRM site uses 'fusion-person' divs
    person_cards = soup.find_all("div", class_="fusion-person")
    
    for card in person_cards:
        # --- 1. EXTRACT NAME & ROLE ---
        name_tag = card.find("span", class_="person-name")
        title_tag = card.find("span", class_="person-title")
        
        if not name_tag:
            continue

        name = name_tag.get_text(strip=True)
        role = title_tag.get_text(strip=True) if title_tag else "Faculty"

        # --- 2. EXTRACT CONTENT (Bio, Phone, Email) ---
        content_div = card.find("div", class_="person-content")
        
        phone = "Not available"
        email = "Not available"
        bio_lines = []
        email_list = []

        if content_div:
            # A. FIND EMAILS (Cloudflare Decoding)
            # We look for ANY anchor tag with 'email-protection' in href OR class '__cf_email__'
            cf_links = content_div.select("a[href*='email-protection'], a.__cf_email__, span.__cf_email__")
            
            for link in cf_links:
                hex_data = None
                
                # Check data-cfemail attribute directly on the tag
                if link.has_attr("data-cfemail"):
                    hex_data = link["data-cfemail"]
                
                # Check inside child span (some structures differ)
                elif link.find("span", class_="__cf_email__"):
                    span = link.find("span", class_="__cf_email__")
                    hex_data = span.get("data-cfemail")
                
                # Check href hash (old fallback)
                elif link.has_attr("href") and "#" in link["href"]:
                    hex_data = link["href"].split("#")[-1]

                if hex_data:
                    decoded = decode_cfemail(hex_data)
                    if "@" in decoded and decoded not in email_list:
                        email_list.append(decoded)
            
            if email_list:
                email = ", ".join(email_list)

            # B. FIND PHONE & BIO
            # We split the text content by separator to handle <br> tags gracefully
            raw_text = content_div.get_text(separator="\n", strip=True)
            lines = raw_text.split("\n")
            
            for line in lines:
                line_clean = line.strip()
                if not line_clean: continue
                
                # Phone Logic: Look for keywords or regex patterns
                # This regex looks for 10-digit numbers often found in India (+91 or just digits)
                phone_match = re.search(r'(?:Phone|Mob|Call)\s*[:\-\.]?\s*([\+\d\s\-,]{10,})', line_clean, re.IGNORECASE)
                
                if phone_match:
                    phone = phone_match.group(1).strip()
                elif "Email" in line_clean or "[email" in line_clean:
                    continue # Skip email lines as we handled them above
                else:
                    # Collect everything else as Bio
                    bio_lines.append(line_clean)
        
        bio = " ".join(bio_lines)

        # --- 3. SOCIAL MEDIA ---
        socials = {}
        social_div = card.find("div", class_="fusion-social-networks")
        if social_div:
            links = social_div.find_all("a", href=True)
            for link in links:
                href = link['href']
                # Determine platform based on class name or tooltip
                title = "Social"
                css_classes = " ".join(link.get('class', []))
                
                if "facebook" in css_classes: title = "Facebook"
                elif "twitter" in css_classes or "x-twitter" in css_classes: title = "Twitter"
                elif "linkedin" in css_classes: title = "LinkedIn"
                elif "instagram" in css_classes: title = "Instagram"
                elif "youtube" in css_classes: title = "YouTube"
                elif link.get('data-original-title'): title = link.get('data-original-title')
                
                if href and href != "#":
                    socials[title] = href

        # --- 4. CONSTRUCT OBJECT ---
        profile = {
            "name": name,
            "role": role,
            "bio": bio,
            "profile_url": FACULTY_LIST_URL,
            "sidebar_details": {
                "Phone": phone,
                "Email": email,
                **socials
            },
            "tab_details": {
                "Biography": bio
            },
            "publications": []
        }
        
        all_profiles.append(profile)
        print(f"✔ Extracted: {name}")

    # Save
    if all_profiles:
        print(f"\nTotal profiles extracted: {len(all_profiles)}")
        save_data(all_profiles)
    else:
        print("No profiles found. Check selectors.")

if __name__ == "__main__":
    main()