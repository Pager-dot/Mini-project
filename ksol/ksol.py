import requests
from bs4 import BeautifulSoup
import json
import re

FACULTY_LIST_URL = "https://ksol.kiit.ac.in/faculties/"
OUTPUT_FILE = "ksol_kiit_profiles.json"
RAG_OUTPUT_FILE = "ksol_kiit_rag_ready.json"

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
    """Saves data in two formats."""
    
    # 1. Raw Data
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_profiles, f, indent=4, ensure_ascii=False)

    # 2. RAG-Optimized Data
    rag_documents = []
    for profile in all_profiles:
        sidebar_text = ", ".join([f"{k}: {v}" for k, v in profile.get("sidebar_details", {}).items() if v])
        tab_text_list = [f"{k}: {v}" for k, v in profile.get("tab_details", {}).items() if v and v != "Not available"]
        tab_text_str = ". ".join(tab_text_list)

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

    # Target content columns (usually 3/4 width)
    content_columns = soup.find_all("div", class_="fusion-three-fourth")
    
    for col in content_columns:
        # A. EXTRACT NAME & ROLE
        h2_tag = col.find("h2")
        if not h2_tag:
            continue

        # Get text separated by newlines to detect structure
        raw_text = h2_tag.get_text(separator="\n", strip=True)
        # Filter out empty strings
        parts = [p.strip() for p in raw_text.split("\n") if p.strip()]
        
        name = ""
        role = "Faculty"
        
        if parts:
            # Check if the first part is just an honorific (e.g., "Ms.", "Dr.", "Prof")
            # If so, join it with the second part to form the full name
            honorifics = ["Dr", "Dr.", "Mr", "Mr.", "Ms", "Ms.", "Mrs", "Mrs.", "Prof", "Prof."]
            
            if len(parts) > 1 and parts[0] in honorifics:
                name = f"{parts[0]} {parts[1]}"
                # If there are more parts after combining name, the rest is the Role
                if len(parts) > 2:
                    role = " ".join(parts[2:])
                else:
                    role = "" # No role inside H2, will check <p> later
            else:
                # Standard case: Line 1 is Name
                name = parts[0]
                if len(parts) > 1:
                    role = " ".join(parts[1:])

        # If Role wasn't found in H2 (or was just the honorific case), check the next <p> tag
        if not role or role == "Faculty":
            # Look for the next 'p' tag or 'div.fusion-text' sibling
            # Sometimes role is in a <p> immediately following
            next_p = h2_tag.find_next_sibling("p")
            if next_p:
                role_text = next_p.get_text(strip=True)
                if role_text: 
                    role = role_text
        
        # Cleanup Role (sometimes "Assistant Professor" gets stuck to "(English)")
        role = role.replace("(", " (")

        # B. EXTRACT CONTACT & BIO
        phone = "Not available"
        email = "Not available"
        bio_lines = []
        email_list = []

        text_divs = col.find_all("div", class_="fusion-text")
        
        for div in text_divs:
            # 1. Decode Cloudflare Emails
            cf_links = div.select("a[href*='email-protection'], a.__cf_email__, span.__cf_email__")
            for link in cf_links:
                hex_data = None
                if link.has_attr("data-cfemail"):
                    hex_data = link["data-cfemail"]
                elif link.find("span", class_="__cf_email__"):
                    hex_data = link.find("span", class_="__cf_email__").get("data-cfemail")
                elif link.has_attr("href") and "#" in link["href"]:
                    hex_data = link["href"].split("#")[-1]
                
                if hex_data:
                    decoded = decode_cfemail(hex_data)
                    if "@" in decoded and decoded not in email_list:
                        email_list.append(decoded)

            # 2. Extract Text
            # We want to skip the H2 we just processed
            for element in div.children:
                if element.name == 'h2': continue 
                
                text_content = element.get_text(separator=" ", strip=True) if hasattr(element, 'get_text') else str(element).strip()
                if not text_content: continue

                # Check for Phone
                phone_match = re.search(r'(?:Phone|Mob|Call)\s*[:\-\.]?\s*([\+\d\s\-,]{10,})', text_content, re.IGNORECASE)
                if phone_match:
                    phone = phone_match.group(1).strip()
                
                # Filter out lines that are just labels or contact info we already have
                if "Contact Details" in text_content or "Email Id" in text_content:
                    continue
                
                # If it looks like a role (short, contains "Professor"), and we don't have a good role yet
                if not role and ("Professor" in text_content or "Faculty" in text_content) and len(text_content) < 50:
                     role = text_content
                elif len(text_content) > 3: # Ignore tiny fragments
                    bio_lines.append(text_content)

        if email_list:
            email = ", ".join(email_list)
        
        bio = " ".join(bio_lines).strip()

        # C. SOCIAL MEDIA
        socials = {}
        social_div = col.find("div", class_="fusion-social-networks")
        if social_div:
            links = social_div.find_all("a", href=True)
            for link in links:
                href = link['href']
                title = link.get('title') or link.get('data-original-title') or "Social"
                
                if title == "Social":
                    classes = " ".join(link.get('class', []))
                    if "facebook" in classes: title = "Facebook"
                    elif "linkedin" in classes: title = "LinkedIn"
                    elif "twitter" in classes: title = "Twitter"
                    elif "instagram" in classes: title = "Instagram"
                
                if href and href != "#":
                    socials[title] = href

        # D. CONSTRUCT OBJECT
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
        print(f"✔ Extracted: {name} | Role: {role}")

    # Save
    if all_profiles:
        print(f"\nTotal profiles extracted: {len(all_profiles)}")
        save_data(all_profiles)
    else:
        print("No profiles found. Check selectors.")

if __name__ == "__main__":
    main()