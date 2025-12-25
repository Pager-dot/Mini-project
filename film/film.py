import requests
from bs4 import BeautifulSoup
import json
import re

FACULTY_LIST_URL = "https://film.kiit.ac.in/faculty/"
OUTPUT_FILE = "film_kiit_profiles.json"
RAG_OUTPUT_FILE = "film_kiit_rag_ready.json"

# -------------------------------------------------
# SAVE DATA FUNCTION
# -------------------------------------------------
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

    with open(RAG_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(rag_documents, f, indent=4, ensure_ascii=False)
    
    print(f"✅ Data saved to {OUTPUT_FILE} and {RAG_OUTPUT_FILE}")

# -------------------------------------------------
# HELPER: Decode Cloudflare Emails
# -------------------------------------------------
def decode_cfemail(cfemail):
    try:
        r = int(cfemail[:2], 16)
        email = ''.join([chr(int(cfemail[i:i+2], 16) ^ r) for i in range(2, len(cfemail), 2)])
        return email
    except:
        return ""

# -------------------------------------------------
# MAIN SCRAPER
# -------------------------------------------------
def main():
    print(f"Fetching: {FACULTY_LIST_URL}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        response = requests.get(FACULTY_LIST_URL, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Error fetching URL: {e}")
        return

    soup = BeautifulSoup(response.text, "html.parser")
    
    all_profiles = []

    # Find columns that look like faculty cards
    content_columns = soup.find_all("div", class_="fusion-layout-column")
    
    for col in content_columns:
        text_div = col.find("div", class_="fusion-text")
        if not text_div:
            continue
            
        name_tag = text_div.find("h3")
        if not name_tag:
            continue
            
        # 1. EXTRACT NAME
        name = name_tag.get_text(strip=True)
        
        # 2. EXTRACT DETAILS (Role, Phone, Email)
        # Find the <p> immediately after the <h3> Name
        # This paragraph usually contains Role <br> Phone <br> Email
        details_p = name_tag.find_next_sibling("p")
        bio_text = ""
        
        # If details_p exists, extract lines. 
        # Also look for Bio in subsequent paragraphs
        if not details_p:
            # Fallback if structure is nested differently
             ps = text_div.find_all("p")
             if ps: details_p = ps[0] # Assume first P is details
             if len(ps) > 1: bio_text = ps[1].get_text(strip=True)
        else:
             # Look for next P for bio
             bio_p = details_p.find_next_sibling("p")
             if bio_p:
                 bio_text = bio_p.get_text(strip=True)

        role = "Unknown"
        phone = "Not available"
        email = "Not available"

        if details_p:
            # 1. Decode Email first (since it's encoded)
            cf_emails = details_p.find_all("a", href=True)
            email_list = []
            for link in cf_emails:
                if "email-protection" in link['href']:
                    span = link.find("span", class_="__cf_email__")
                    if span and span.get("data-cfemail"):
                        email_list.append(decode_cfemail(span.get("data-cfemail")))
            if email_list:
                email = ", ".join(email_list)

            # 2. Extract Text Lines (separating by <br> or newline)
            # using separator="\n" splits text nodes cleanly
            clean_text = details_p.get_text(separator="\n", strip=True)
            lines = clean_text.split("\n")
            
            # --- FIXED LOGIC HERE ---
            # The FIRST line is the Role. 
            # Subsequent lines are checked for Phone/Email.
            if len(lines) > 0:
                role = lines[0].strip() # First line is always Role
            
            for line in lines[1:]: # Check remaining lines
                if "Phone" in line:
                    phone = line.replace("Phone:", "").replace("Phone :", "").strip()
                # Email is already handled by CF decoder above, but if plain text exists:
                elif "Email" in line and email == "Not available":
                     email = line.replace("Email:", "").replace("Email :", "").strip()

        # 3. SOCIAL MEDIA
        socials = {}
        social_div = col.find("div", class_="fusion-social-links")
        if social_div:
            links = social_div.find_all("a", href=True)
            for link in links:
                href = link['href']
                title = link.get('title') or link.get('data-original-title') or "Social"
                if href and href != "#":
                    socials[title] = href

        # 4. Construct Profile Object
        profile = {
            "name": name,
            "role": role,
            "bio": bio_text,
            "profile_url": FACULTY_LIST_URL,
            "sidebar_details": {
                "Phone": phone,
                "Email": email,
                **socials
            },
            "tab_details": {
                "Biography": bio_text
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
        print("No profiles found. Check selector logic.")

if __name__ == "__main__":
    main()