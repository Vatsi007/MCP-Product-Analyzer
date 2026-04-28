import asyncio
import os
import yagmail
from dotenv import load_dotenv

import db
from mcp_server import get_best_price

# Load environment variables from .env file
load_dotenv()

EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD") # Use App Password for Gmail
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER") # Usually the same as sender for self-alerts

async def check_alerts():
    print("🔄 Waking up to check active alerts...")
    active_alerts = db.get_active_alerts()
    
    if not active_alerts:
        print("📭 No active alerts found.")
        return

    # Initialize email client
    try:
        yag = yagmail.SMTP(EMAIL_SENDER, EMAIL_PASSWORD)
    except Exception as e:
        print(f"❌ Failed to initialize yagmail. Check your .env credentials. Error: {e}")
        return

    for alert in active_alerts:
        product_name = alert['product_name']
        target_price = alert['target_price']
        alert_id = alert['id']

        print(f"🔎 Checking '{product_name}' (Target: ₹{target_price})")
        
        try:
            result = await get_best_price(product_name)
            current_price = result['best_price']
            winner = result['winner']
            
            if current_price == float('inf'):
                print(f"⚠️ Could not extract a valid price for '{product_name}'. Skipping.")
                continue

            print(f"💰 Current Best Price: ₹{current_price} on {winner}")

            if current_price <= target_price:
                print(f"🎉 TARGET HIT! Notifying via email...")
                
                subject = f"Price Drop Alert: {product_name} is now ₹{current_price}!"
                
                best_data = result['amazon_data'] if winner == "Amazon" else result['flipkart_data']
                url = best_data['url']
                
                body = f"""
                <h2>Great News!</h2>
                <p>The price for <strong>{product_name}</strong> has dropped to your target!</p>
                <ul>
                    <li><strong>Target Price:</strong> ₹{target_price}</li>
                    <li><strong>Current Price:</strong> ₹{current_price}</li>
                    <li><strong>Store:</strong> {winner}</li>
                    <li><strong>Link:</strong> <a href="{url}">{url}</a></li>
                </ul>
                <p>Happy Shopping!</p>
                """
                
                yag.send(
                    to=EMAIL_RECEIVER,
                    subject=subject,
                    contents=[body]
                )
                
                # Mark as triggered so we don't spam
                db.mark_alert_triggered(alert_id)
                print(f"✅ Alert {alert_id} marked as triggered.")
            else:
                print(f"📉 Still too high. Will check again later.")
                
        except Exception as e:
            print(f"❌ Error checking price for {product_name}: {e}")

async def main():
    print("🚀 Starting Price Alert Worker...")
    db.init_db()
    
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER]):
        print("⚠️ WARNING: Email credentials missing in .env file.")
        print("Please set EMAIL_SENDER, EMAIL_PASSWORD, and EMAIL_RECEIVER in a .env file.")
    
    while True:
        await check_alerts()
        
        # The 6-hour cycle
        sleep_hours = 6
        print(f"💤 Sleeping for {sleep_hours} hours...")
        await asyncio.sleep(sleep_hours * 3600)

if __name__ == "__main__":
    asyncio.run(main())
