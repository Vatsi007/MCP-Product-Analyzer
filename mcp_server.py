import asyncio
import re
import urllib.parse
from playwright.async_api import async_playwright
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("PriceCompare")

def clean_price(price_str: str) -> float:
    try:
        cleaned = re.sub(r'[^\d]', '', price_str)
        return float(cleaned) if cleaned else float('inf')
    except:
        return float('inf')

def get_match_score(card_text: str, original_prompt: str) -> int:
    """
    The Scoring Engine: Proximity and exact phrase matching.
    """
    text_lower = card_text.lower()
    prompt_lower = original_prompt.lower()
    words = prompt_lower.split()
    
    score = 0
    
    # 0. Accessory Penalties (Extremely Important)
    accessories = ["cover", "case", "protector", "screen guard", "skin", "cable", "charger", "compatible", "adapter", "glass", "bumper", "stand"]
    for acc in accessories:
        if acc in text_lower:
            score -= 50 # massive penalty to prevent picking accessories
            
    # 0.5 Variant/Upsell Penalties
    # Prevent base model searches from pulling "Pro" or "Plus" models
    variants = ["plus", "pro", "max", "ultra", "mini", "lite", "fe"]
    for var in variants:
        # Check for word boundary so "promax" or "protection" doesn't falsely trigger "pro"
        if re.search(rf'\b{var}\b', text_lower) and var not in words:
            score -= 30 # Heavy penalty for 'category bleed' (e.g. found Pro when asking for base)
        elif var in words and not re.search(rf'\b{var}\b', text_lower):
            score -= 50 # Massive penalty for missing a requested variant (e.g. asked for Ultra, but found base model)
            
    # 1. Exact phrase match bonus
    # If "iphone 15" is in the text as an exact phrase, huge bonus
    for i in range(len(words) - 1):
        phrase = f"{words[i]} {words[i+1]}"
        if phrase in text_lower:
            score += 15 # Huge bonus for finding adjacent words like "iphone 15" or "15 256gb"
            
    # 2. Individual word/number matching
    critical_numbers = [w for w in words if any(c.isdigit() for c in w)]
    keywords = [w for w in words if not any(c.isdigit() for c in w)]
    
    # Numbers
    for num in critical_numbers:
        # Strip ONLY common units so '256gb' becomes '256' but '3a' remains '3a'
        clean_num = re.sub(r'(gb|mb|tb|hz|k|inch)$', '', num)
        if clean_num and clean_num in text_lower:
            # check if it's not a decimal like 15.9
            if f"{clean_num}." not in text_lower:
                score += 5
            else:
                score += 1 # matched but it seems to be a decimal
        else:
            score -= 50 # Massive penalty if a requested number (like exactly '16' or '128') is missing
                
    # Keywords
    for kw in keywords:
        if kw in text_lower:
            score += 2
            
    return score


async def get_best_price(product_name: str) -> dict:
    words = product_name.lower().split()
    amazon_data = {"price": float('inf'), "url": "", "title": "Not found"}
    flipkart_data = {"price": float('inf'), "url": "", "title": "Not found"}

    print(f"\n🚀 Initiating Scoring Engine Scraper for: '{product_name}'")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1920, "height": 1080}
        )

        # --- 1. AMAZON ---
        try:
            print("🕵️ [AMAZON] 1. Searching...")
            page_amazon = await context.new_page()
            await page_amazon.goto(f"https://www.amazon.in/s?k={urllib.parse.quote_plus(product_name)}", timeout=15000)
            
            await page_amazon.wait_for_selector('div[data-asin]:not([data-asin=""])', timeout=10000)
            products = await page_amazon.locator('div[data-asin]:not([data-asin=""])').all()
            print(f"🕵️ [AMAZON] Found {len(products)} products on page")
            best_amazon_score = 0
            
            for product in products[:25]: 
                # Read all text inside the product card
                card_text = await product.inner_text()
                if not card_text: continue
                
                score = get_match_score(card_text, product_name)
                
                # Update if score is strictly better OR if score is tied but we currently have no valid price
                is_better = score > best_amazon_score
                is_tie_breaker = (score == best_amazon_score) and (amazon_data["price"] == float('inf'))
                
                if is_better or is_tie_breaker:
                    best_amazon_score = score
                    # Extract full title from card text instead of relying on brittle h2 tags
                    card_lines = [line.strip() for line in card_text.split('\n') if line.strip()]
                    title = "Not found"
                    for line in card_lines:
                        if len(line) > 10 and words[0] in line.lower() and "₹" not in line:
                            title = line
                            break
                            
                    link_el = product.locator('a.a-link-normal').first
                    link = await link_el.get_attribute('href') if await link_el.count() > 0 else ""
                            
                    if title == "Not found":
                        # Pure fallback
                        for line in card_lines:
                            if len(line) > 15 and "₹" not in line:
                                title = line
                                break
                    
                    price_el = product.locator('.a-price-whole').first
                    current_raw_price = "inf"
                    if await price_el.count() > 0:
                        current_raw_price = await price_el.inner_text()
                        
                    full_link = link if link.startswith('http') else f"https://www.amazon.in{link}"
                    amazon_data.update({
                        "price": clean_price(current_raw_price),
                        "url": full_link,
                        "title": title.strip()
                    })
                    print(f"✅ [AMAZON] Found Match (Score {score}): {amazon_data['title'][:40]}... (₹{amazon_data['price']})")
                    
                    if score == len([w for w in product_name.split() if not any(c.isdigit() for c in w)]):
                        break # Perfect score found!

        except Exception as e:
            print(f"⚠️ [AMAZON] Error: {e}")

        # --- 2. FLIPKART ---
        try:
            print("🕵️ [FLIPKART] 1. Searching...")
            page_flipkart = await context.new_page()
            # Clean the prompt for Flipkart search
            clean_query = " ".join(product_name.split()[:5])
            
            await page_flipkart.goto(f"https://www.flipkart.com/search?q={urllib.parse.quote_plus(clean_query)}", timeout=15000)
            await page_flipkart.wait_for_selector('a[href*="/p/itm"]', timeout=10000)
            
            product_links = await page_flipkart.locator('a[href*="/p/itm"]').all()
            print(f"🕵️ [FLIPKART] Found {len(product_links)} product links on page")
            best_flipkart_score = 0
            
            for link_node in product_links[:15]:
                card = link_node.locator('xpath=../../..') 
                card_text = await card.inner_text()
                if not card_text: continue
                
                score = get_match_score(card_text, product_name)
                
                is_better = score > best_flipkart_score
                is_tie_breaker = (score == best_flipkart_score) and (flipkart_data["price"] == float('inf'))
                
                if is_better or is_tie_breaker:
                    best_flipkart_score = score
                    lines = [line.strip() for line in card_text.split('\n') if line.strip()]
                    title_text = ""
                    # 1. Try to find the line containing the primary keyword (usually the exact title)
                    for line in lines:
                        if len(line) > 10 and words[0] in line.lower() and "₹" not in line:
                            title_text = line
                            break
                    
                    # 2. Fallback
                    if not title_text:
                        for line in lines:
                            if len(line) > 15 and "₹" not in line and "off" not in line.lower():
                                title_text = line
                                break
                    
                    price_match = re.search(r'₹\s*([0-9,]+)', card_text)
                    if not price_match: continue
                    raw_price = price_match.group(1)
                    
                    link_href = await link_node.get_attribute('href')
                    
                    best_flipkart_score = score
                    full_link = link_href if link_href.startswith('http') else f"https://www.flipkart.com{link_href}"
                    flipkart_data.update({
                        "price": clean_price(raw_price),
                        "url": full_link,
                        "title": title_text
                    })
                    print(f"✅ [FLIPKART] Found Match (Score {score}): {flipkart_data['title'][:40]}... (₹{flipkart_data['price']})")
                    
                    if score == len([w for w in product_name.split() if not any(c.isdigit() for c in w)]):
                        break

        except Exception as e:
            print(f"❌ [FLIPKART] Error: {e}")

        await browser.close()

    # --- FINAL REPORT ---
    winner = "Amazon" if amazon_data["price"] <= flipkart_data["price"] else "Flipkart"
    if amazon_data["price"] == float('inf'): winner = "Flipkart"
    if flipkart_data["price"] == float('inf'): winner = "Amazon"
    if amazon_data["price"] == float('inf') and flipkart_data["price"] == float('inf'):
        winner = "Neither (Extraction Failed)"

    best_data = amazon_data if winner == "Amazon" else flipkart_data

    return {
        "winner": winner,
        "best_price": best_data.get('price', float('inf')),
        "amazon_data": amazon_data,
        "flipkart_data": flipkart_data
    }

@mcp.tool()
async def compare_prices(product_name: str) -> str:
    """
    Compares the price of a product on Amazon and Flipkart to find the cheapest option.
    """
    result = await get_best_price(product_name)
    winner = result["winner"]
    amazon_data = result["amazon_data"]
    flipkart_data = result["flipkart_data"]
    best_data = amazon_data if winner == "Amazon" else flipkart_data

    return (
        f"🏆 CHEAPEST OPTION FOUND: {winner}\n"
        f"Price: ₹{best_data.get('price', 'N/A')}\n\n"
        f"🔗 VERIFY ON AMAZON: {amazon_data['url'] if amazon_data['url'] else 'N/A'}\n"
        f"🔗 VERIFY ON FLIPKART: {flipkart_data['url'] if flipkart_data['url'] else 'N/A'}\n\n"
        f"--- Cross-Platform Spec Verification ---\n"
        f"Amazon Found: {amazon_data['title']}\n"
        f"Flipkart Found: {flipkart_data['title']}\n\n"
        f"--- Price Data ---\n"
        f"Amazon: ₹{amazon_data['price']}\n"
        f"Flipkart: ₹{flipkart_data['price']}"
    )

@mcp.tool()
async def set_price_alert(product_name: str, target_price: float) -> str:
    """
    Sets a background alert to monitor the price of a product. 
    You will be notified via email/SMS when the price drops below the target_price.
    """
    import db
    db.init_db()
    db.add_alert(product_name, target_price)
    return f"✅ Alert set! You will be notified when '{product_name}' drops below ₹{target_price}."

@mcp.tool()
async def find_active_coupons(product_url: str) -> str:
    """
    Visits the actual product page on Amazon or Flipkart and extracts the real bank offers and cashback details available right now.
    Example: find_active_coupons("https://www.amazon.in/dp/B0CHX1W1XY")
    """
    from playwright.async_api import async_playwright
    import asyncio
    import re
    
    if not product_url or not product_url.startswith("http"):
        return "❌ Please provide a valid product URL (starting with http/https)."
        
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            await page.goto(product_url, timeout=30000)
            await asyncio.sleep(3) # Wait for dynamic offers to load
            
            offers_text = []
            
            # --- AMAZON LOGIC ---
            if "amazon.in" in product_url:
                try:
                    headers = await page.locator('.a-color-base.a-text-bold').all()
                    for header in headers:
                        header_text = await header.inner_text()
                        if header_text and any(x in header_text.lower() for x in ['cashback', 'bank offer', 'partner offer']):
                            parent = header.locator('xpath=./ancestor::div[contains(@class, "a-carousel-card") or contains(@class, "a-box")]').first
                            if await parent.count() > 0:
                                text = await parent.inner_text()
                                if text and len(text) < 400: # Ignore massive tables
                                    clean_text = re.sub(r'\s+', ' ', text).strip()
                                    if clean_text not in offers_text:
                                        offers_text.append(clean_text)
                except:
                    pass
                    
            # --- FLIPKART LOGIC ---
            elif "flipkart.com" in product_url:
                try:
                    # Give it a bit more time to load
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except:
                        pass
                    await asyncio.sleep(2)
                    
                    body_text = await page.locator('body').inner_text()
                    lines = [line.strip() for line in body_text.split('\n') if line.strip()]
                    
                    capturing = False
                    temp_offers = []
                    
                    for i, line in enumerate(lines):
                        lower_line = line.lower()
                        
                        # Stop if we hit related products or reviews
                        if lower_line in ["similar products", "you might be interested in", "ratings & reviews", "product description", "specifications", "frequently bought together"]:
                            break
                            
                        # Detect headers
                        if lower_line in ["apply offers for maximum savings", "lowest price for you", "bank offers", "exchange offer", "available offers"]:
                            capturing = True
                            if line not in temp_offers:
                                temp_offers.append(f"[{line}]")
                            continue
                            
                        if capturing:
                            if lower_line == "view emi offers" or lower_line.startswith("t&c") or lower_line.startswith("know more"):
                                continue
                            
                            # If we hit random text that indicates the end of offers
                            # Remove strict capturing=False as it might trigger prematurely.
                            # Just continue, but rely on the main loop break for Similar Products
                            # to stop the extraction.
                            if lower_line == "highlights" or lower_line == "easy payment options":
                                capturing = False
                                continue
                                
                            # Avoid appending exact duplicate consecutive lines
                            if not temp_offers or temp_offers[-1] != line:
                                temp_offers.append(line)
                                
                    if temp_offers:
                        # Join elements. 
                        # We limit to first 30 elements to avoid dumping massive text if parsing fails to stop
                        joined = " ".join(temp_offers[:30])
                        offers_text.append(joined)
                        
                except Exception as e:
                    print(f"Error extracting Flipkart offers: {e}")

            # --- GENERIC FALLBACK ---
            if not offers_text:
                elements = await page.locator('text=/Bank Offer|Cashback|Partner Offer/i').all()
                for el in elements:
                    try:
                        text = await el.inner_text()
                        # Avoid matching short related product strings like "₹88,999 with Bank offer"
                        if text and 15 < len(text) < 400 and '\nEMI' not in text:
                            if not re.search(r'₹[0-9,]+\s+with Bank offer', text):
                                clean_text = re.sub(r'\s+', ' ', text).strip()
                                if clean_text not in offers_text:
                                    offers_text.append(clean_text)
                    except:
                        pass
            
            await browser.close()
            
            if offers_text:
                result = f"✅ Found Real Offers on Product Page:\n"
                for i, text in enumerate(offers_text[:8]):
                    result += f"  {i+1}. {text}\n"
                return result.strip()
            else:
                return f"❌ No explicit bank offers or cashback sections found on this product page. Make sure the URL is correct or try again."
                
    except Exception as e:
        return f"⚠️ Error visiting product page: {e}"

@mcp.tool()
async def calculate_review_trust_score(product_url: str) -> str:
    """
    Scrapes the first page of reviews and runs a quick heuristic check to detect potential fake reviews.
    Returns a Trust Score and warning if suspicious.
    """
    from playwright.async_api import async_playwright
    import asyncio
    import re
    from collections import Counter
    
    if not product_url or not product_url.startswith("http"):
        return "❌ Please provide a valid product URL."

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--disable-blink-features=AutomationControlled']
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={'width': 1920, 'height': 1080}
            )
            page = await context.new_page()
            
            # Additional evasion script
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            await page.goto(product_url, timeout=30000)
            
            # Scroll slowly to trigger lazy loading of reviews
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
            await asyncio.sleep(1)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 2 / 3)")
            await asyncio.sleep(1)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except:
                pass
            await asyncio.sleep(3)

            reviews = []

            # Grab entire body text
            body_text = await page.locator('body').inner_text()
            if "Something went wrong!" in body_text and ("E002" in body_text or "Retry" in body_text):
                await browser.close()
                return "⚠️ Flipkart actively blocked the request (Bot Protection). Cannot extract reviews."

            lines = [line.strip() for line in body_text.split('\n') if line.strip()]

            # --- AMAZON ---
            if "amazon" in product_url:
                current_review = None
                for line in lines:
                    rating_m = re.search(r'^([0-9.]+)\s*out of 5 stars$', line)
                    if rating_m:
                        if current_review and current_review.get('date'):
                            current_review['text'] = " ".join(current_review['text']).strip()
                            reviews.append(current_review)
                        current_review = {"rating": float(rating_m.group(1)), "date": "", "text": []}
                        continue
                        
                    if current_review:
                        date_m = re.search(r'Reviewed in .*? on (.*)$', line)
                        if date_m:
                            current_review['date'] = date_m.group(1).strip()
                            continue
                            
                        # Skip typical non-review text lines
                        if line in ["Verified Purchase", "Helpful", "Report", "See more reviews"] or re.search(r'people found this helpful', line):
                            if line == "Report":
                                if current_review and current_review.get('date'):
                                    current_review['text'] = " ".join(current_review['text']).strip()
                                    reviews.append(current_review)
                                current_review = None
                            continue
                            
                        if current_review.get('date'):
                            current_review['text'].append(line)
                            
                if current_review and current_review.get('date'):
                    current_review['text'] = " ".join(current_review['text']).strip()
                    reviews.append(current_review)

            # --- FLIPKART ---
            elif "flipkart.com" in product_url:
                await page.evaluate("window.scrollTo(0, 1500)")
                await asyncio.sleep(2)
                
                # Check for bot block
                body_text = await page.locator('body').inner_text()
                if "Something went wrong!" in body_text and ("E002" in body_text or "Retry" in body_text):
                    await browser.close()
                    return "⚠️ Flipkart actively blocked the request (Bot Protection). Cannot extract reviews."
                    
                # Look for the deepest elements containing the buyer tag
                buyer_tags = await page.locator('text=/Verified Buyer|Certified Buyer/i').all()
                
                # Extract text from their ancestors
                raw_review_blocks = []
                for tag in buyer_tags:
                    try:
                        # Grab the text of the container 3 levels up, which typically holds the whole review card
                        block_text = await tag.evaluate("el => el.parentElement && el.parentElement.parentElement && el.parentElement.parentElement.parentElement ? el.parentElement.parentElement.parentElement.innerText : ''")
                        if block_text and block_text not in raw_review_blocks:
                            raw_review_blocks.append(block_text)
                    except:
                        pass
                        
                for block in raw_review_blocks:
                    lines = [line.strip() for line in block.split('\n') if line.strip()]
                    if not lines: continue
                    
                    # Rating is usually the first line with a digit
                    rating_val = 0
                    for line in lines[:3]:
                        # Look for a digit/float 1-5, or a digit followed by a star
                        m = re.search(r'^([0-9.]+)(\s*★)?', line)
                        if m:
                            rating_val = float(m.group(1))
                            break
                            
                    date_val = "Unknown date"
                    text_lines = []
                    for line in lines:
                        if re.search(r'^[0-9.]+(\s*★)?(.*)$', line):
                            # Usually the title is on the same line or rating line
                            title_m = re.search(r'^[0-9.]+(\s*★)?(.*)$', line)
                            if title_m and title_m.group(2).strip():
                                text_lines.append(title_m.group(2).strip())
                            continue
                            
                        if re.search(r'ago|\d{4}', line) and len(line) < 25:
                            date_val = line
                            continue
                            
                        if line in ["Certified Buyer", "Verified Buyer", "READ MORE", "Permalink", "Report Abuse", "Like", "Dislike"] or re.search(r'\d+\s+people found this helpful', line):
                            continue
                            
                        if len(text_lines) < 10 or len(line) > 5:
                            text_lines.append(line)
                            
                    if rating_val > 0 or text_lines:
                        reviews.append({
                            "rating": rating_val,
                            "date": date_val,
                            "text": " ".join(text_lines).strip()
                        })

            await browser.close()
            
            if not reviews:
                return "⚠️ Could not extract any reviews from the page. The product might not have reviews or the page structure is unsupported."

            # --- CALCULATE TRUST SCORE ---
            score = 100
            penalties = []
            
            total_reviews = len(reviews)
            five_star_reviews = [r for r in reviews if r['rating'] >= 4.0]
            
            # 1. Textless / Short 5-Star Reviews
            textless_5_stars = 0
            for r in five_star_reviews:
                # Flipkart raw text includes the rating "5★" and date, so we strip those out or just check length
                # A generic review might just be "Good" (4 chars). Let's say < 25 chars of actual unique text is suspicious.
                if len(r['text']) < 25: 
                    textless_5_stars += 1
            
            if len(five_star_reviews) > 0:
                percent_textless = (textless_5_stars / len(five_star_reviews)) * 100
                if percent_textless > 40:
                    penalty = int((percent_textless - 40) * 0.8) # up to 48 penalty
                    score -= penalty
                    penalties.append(f"-{penalty} pts: {int(percent_textless)}% of high-rating reviews lack substantive text.")
            
            # 2. Review Velocity (Date Clustering)
            # Exclude relative dates like "months ago" or "days ago" from velocity checks 
            # since they naturally cluster over broad periods and cause false positives.
            dates = [r['date'] for r in reviews if r['date'] and r['date'] != "Unknown date" and "ago" not in r['date'].lower()]
            if dates:
                date_counts = Counter(dates)
                most_common_date, count = date_counts.most_common(1)[0]
                percent_same_date = (count / total_reviews) * 100
                
                # If more than 30% of reviews are on the exact same date
                if percent_same_date > 30 and count > 2:
                    penalty = int((percent_same_date - 30) * 0.6) # up to 42 penalty
                    score -= penalty
                    penalties.append(f"-{penalty} pts: Suspicious velocity ({int(percent_same_date)}% of reviews posted on '{most_common_date}').")

            # 3. Low Average Rating Penalty
            valid_ratings = [r['rating'] for r in reviews if r['rating'] > 0]
            if valid_ratings:
                average_rating = sum(valid_ratings) / len(valid_ratings)
                if average_rating < 3.8:
                    penalty = int((3.8 - average_rating) * 25) # e.g. 2.3 -> 37 penalty
                    score -= penalty
                    penalties.append(f"-{penalty} pts: Poor average rating ({average_rating:.1f} ★). Product has highly negative feedback.")

            # Format the output
            score = max(0, score)
            trust_level = "HIGH TRUST"
            if score < 50:
                trust_level = "LOW TRUST 🚨"
            elif score < 80:
                trust_level = "MEDIUM TRUST ⚠️"
                
            report = f"🛡️ Review Trust Score: {score} / 100 ({trust_level})\n"
            report += f"Analyzed {total_reviews} reviews from the first page.\n\n"
            
            if penalties:
                report += "Penalties Applied:\n"
                for p in penalties:
                    report += f"  {p}\n"
            else:
                report += "✅ No suspicious review patterns detected.\n"
                
            if score < 50:
                report += "\nAgent Action: Consider warning the user before recommending this product."
                
            return report

    except Exception as e:
        return f"⚠️ Error calculating trust score: {e}"

@mcp.tool()
async def find_nearby_offline_stores(pincode: str, product_brand: str) -> str:
    """
    O2O Sensor (Online-to-Offline).
    Finds physical stores selling a specific brand near a given pincode.
    Useful when online delivery is too slow or the user prefers buying locally.
    
    Args:
        pincode (str): The postal code to search around (e.g., "560001")
        product_brand (str): The brand to search for (e.g., "ASUS", "Samsung", "Apple")
    """
    search_query = f"{product_brand} store near {pincode}"
    maps_url = f"https://www.google.com/maps/search/{search_query.replace(' ', '+')}"
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--disable-blink-features=AutomationControlled']
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={'width': 1920, 'height': 1080}
            )
            page = await context.new_page()
            
            # Additional evasion script
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            await page.goto(maps_url, timeout=30000)
            await asyncio.sleep(4)
            
            # Scroll down the feed slightly to load a few results
            try:
                feed = page.locator('div[role="feed"]')
                if await feed.count() > 0:
                    await feed.first.hover()
                    await page.mouse.wheel(0, 1000)
                    await asyncio.sleep(2)
            except:
                pass
                
            results_data = await page.evaluate('''() => {
                let res = [];
                // Individual search results in Google Maps usually have role="article"
                let cards = Array.from(document.querySelectorAll('div[role="article"]'));
                
                let seen = new Set();
                for (let card of cards) {
                    if (!card) continue;
                    let text = card.innerText;
                    // Find the overlay link to get the exact store name
                    let link = card.querySelector('a[href*="/maps/place/"]');
                    let name = link ? link.getAttribute('aria-label') : null;
                    
                    if (name && !seen.has(name)) {
                        seen.add(name);
                        res.push({ name: name, text: text });
                    }
                    if (res.length >= 15) break;
                }
                return res;
            }''')
            
            await browser.close()
            
            if not results_data:
                return f"⚠️ Could not extract offline stores from Google Maps. You can manually check: {maps_url}"
                
            report = f"🏪 Found nearby {product_brand} authorized dealers near {pincode}:\n\n"
            
            valid_stores = []
            for store in results_data:
                lines = [line.strip() for line in store['text'].split('\n') if line.strip()]
                
                address = None
                phone = "Not available"
                
                for line in lines:
                    if store['name'].lower() in line.lower() or line in ["Directions", "Website", "Save", "Call", "Share", "Results"]:
                        continue
                    if any(ord(c) > 50000 for c in line) or len(line) < 2:
                        continue
                        
                    # Phone number extraction
                    # If line has Open/Close, phone is often at the end after the dot
                    if "Open" in line or "Closes" in line or "Closed" in line:
                        parts = line.split('·')
                        if len(parts) > 1 and sum(c.isdigit() for c in parts[-1]) >= 8:
                            phone = parts[-1].strip()
                        continue
                        
                    # Fallback phone regex
                    phone_match = re.search(r'((?:(?:\+|00)91[\s-]?)?(?:0\d{2,4}[\s-]?)?\d{6,10})', line)
                    if phone_match and sum(c.isdigit() for c in phone_match.group(1)) >= 10:
                        phone = phone_match.group(1).strip()
                        
                    # Skip Rating line
                    if re.match(r'^\d\.\d', line):
                        continue
                        
                    # Address extraction
                    if address is None and len(line) > 10:
                        if "·" in line:
                            address = line.split("·")[-1].strip()
                        else:
                            address = line.strip()
                            
                if address: # Address is mandatory
                    valid_stores.append({
                        "name": store['name'],
                        "phone": phone,
                        "address": address
                    })
                    
                if len(valid_stores) == 3:
                    break
            
            if not valid_stores:
                return f"⚠️ Could not find any stores with valid addresses near {pincode}."
                
            for i, store in enumerate(valid_stores, 1):
                report += f"{i}. **Name:** {store['name']}\n   **Phone Number:** {store['phone']}\n   **Address:** {store['address']}\n\n"
                
            report += f"📍 View all on Google Maps: {maps_url}"
            return report
            
    except Exception as e:
        return f"⚠️ Failed to scrape nearby stores: {str(e)}"

if __name__ == "__main__":
    mcp.run()
