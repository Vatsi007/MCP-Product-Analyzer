## PriceCompareVenv 

from playwright.sync_api import sync_playwright

def get_product_data(url):
    print("Starting the scraper...")
    # 1. The Context Manager: This ensures Playwright cleans up after itself
    with sync_playwright() as p:

        # 2. Launch the Browser
        # headless=False means you will actually see the browser pop up!
        # In production, we set this to True so it runs invisibly.
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        print(f"Navigating to: {url}")

        # 3. Go to the URL
        page.goto(url)
        
        # 4. Extract the Data (The "Scraping" part)
        # We use CSS selectors to find the exact HTML elements holding our data
        title = page.locator("h1").inner_text()
        price_text = page.locator("p.price_color").inner_text()
        
        print("--- Data Extracted ---")
        print(f"Product: {title}")
        print(f"Price: {price_text}")
        print("----------------------")
        
        # 5. Clean up
        browser.close()

test_url = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
get_product_data(test_url)