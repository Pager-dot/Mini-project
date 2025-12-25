from playwright.sync_api import sync_playwright
import time

profile_url = "https://faculty.kiit.ac.in/manoj-ukamanal/"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    page.goto(profile_url, timeout=60000)

    page.wait_for_selector("div.tab-content", timeout=15000)
    time.sleep(2)

    tabs = page.query_selector_all("div.tab-content")

    print(f"Total tab-content blocks found: {len(tabs)}")
    print("=" * 80)

    for tab_index, tab in enumerate(tabs, start=1):
        print(f"\nTAB {tab_index}")
        print("-" * 80)

        sections = tab.evaluate("""
        (tab) => {
            const results = [];
            const labels = tab.querySelectorAll("p span");

            labels.forEach(span => {
                const labelP = span.closest("p");
                const label = labelP.innerText.trim();

                let content = [];
                let el = labelP.nextElementSibling;

                while (el) {
                    // stop at next labeled section
                    if (el.tagName.toLowerCase() === "p" && el.querySelector("span")) {
                        break;
                    }

                    const text = el.innerText?.trim();
                    if (text) content.push(text);

                    el = el.nextElementSibling;
                }

                results.push({
                    label,
                    content
                });
            });

            return results;
        }
        """)

        for section in sections:
            print(f"\n▶ {section['label']}")
            for line in section["content"]:
                print(f"  {line}")

    browser.close()
