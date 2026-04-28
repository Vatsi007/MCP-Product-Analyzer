# 🛍️ MCP Price Compare Chatbot

An intelligent, AI-powered shopping assistant built with the Model Context Protocol (MCP) and Chainlit. This chatbot uses Google Gemini to autonomously scrape real-time prices from Amazon and Flipkart, find active coupons, analyze review authenticity, and even locate nearby physical stores.

## 🚀 Features

- **Conversational UI**: A sleek, ChatGPT-like interface built with Chainlit.
- **Real-Time Scraping**: Uses Playwright to navigate pages and extract live data.
- **Dynamic Tools**: Powered by the Model Context Protocol (MCP), allowing the AI to seamlessly execute Python scraping and database functions locally.
- **Ephemeral Security**: Your Gemini API key is never saved to disk; it is held securely in the session memory and wiped when you close the tab.

---

## 🛠️ Installation & Setup

Follow these steps to get the project running on your local machine.

### 1. Clone the Repository
```bash
git clone <your-repo-url>
cd MCP-Project-Price
```

### 2. Create a Virtual Environment
It is highly recommended to use a virtual environment to manage dependencies and avoid conflicts.

**For Windows:**
```bash
python -m venv venv
.\venv\Scripts\activate
```

**For macOS/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
Make sure your virtual environment is activated, then run:
```bash
pip install -r requirements.txt
```

### 4. Install Playwright Browsers (CRITICAL)
The web scraper relies on Chromium to read dynamic web pages. You must install the browser binaries by running:
```bash
python -m playwright install chromium
```

### 5. Environment Variables
Copy the template environment file to create your own local `.env` file (if you plan to use background workers or email alerts):
```bash
cp .env.example .env
```
*(Note: You do not need to put your Gemini API key in the `.env` file. The Chatbot UI will ask you for it securely when you open the app.)*

---

## 🏃‍♂️ How to Run the App

Start the Chainlit Chatbot UI by running the following command in your terminal:

```bash
python -m chainlit run app.py
```

1. A new tab will automatically open in your browser at `http://localhost:8000`.
2. The bot will welcome you and prompt you for your **Google Gemini API Key**.
3. Paste the key into the chat. Once accepted, the bot will connect to the local MCP server.
4. You can click on the **Available Tools** button in the sidebar to see exactly what the AI can do. 
5. Start chatting! Ask the bot to compare a product, check reviews, or find a local store.

---

## 🧰 Available AI Tools

The AI assistant has access to the following background tools. You don't need to call these manually—just ask the AI in plain English, and it will execute the appropriate tool using the required arguments.

### 1. Compare Prices
**Tool Name:** `compare_prices`
**What it does:** Scrapes Amazon and Flipkart for a specific product, calculates the cheapest option using a sophisticated text-matching algorithm to avoid accessories, and returns the winner.
* **Required Input:** `product_name` (string) - e.g., `"iPhone 15 256gb"`

### 2. Find Active Coupons
**Tool Name:** `find_active_coupons`
**What it does:** Visits a specific product page URL and extracts real-time bank offers, cashback deals, and EMI options hidden in the UI.
* **Required Input:** `product_url` (string) - e.g., `"https://www.amazon.in/dp/B0CHX1W1XY"`

### 3. Review Trust Score
**Tool Name:** `calculate_review_trust_score`
**What it does:** Analyzes the first page of product reviews to detect bot activity, textless 5-star reviews, and suspicious rating velocity. It generates a "Trust Score" to protect you from fake reviews.
* **Required Input:** `product_url` (string) - e.g., `"https://www.flipkart.com/..."`

### 4. Find Nearby Stores
**Tool Name:** `find_nearby_offline_stores`
**What it does:** Uses Google Maps to find physical, authorized dealers near a specific location if you prefer to buy offline.
* **Required Inputs:** 
  - `pincode` (string) - e.g., `"560001"`
  - `product_brand` (string) - e.g., `"Apple"`

### 5. Set Price Alert
**Tool Name:** `set_price_alert`
**What it does:** Saves a target price to the local SQLite database so the background worker can monitor it over time.
* **Required Inputs:**
  - `product_name` (string) - e.g., `"Sony WH-1000XM5"`
  - `target_price` (float) - e.g., `25000.0`
