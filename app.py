import requests
import random
import html
import re
import feedparser
import json
import os
import base64
import aiohttp
import asyncio
from flask import Flask, jsonify
from bs4 import BeautifulSoup

# Initialize Flask app
app = Flask(__name__)

# List of user agents for rotation
user_agents = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.88 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.97 Safari/537.36",
]

# Feed configuration
feeds = {
    "chronicle": {
        "rss_url": "https://www.chronicle.co.zw/feed/",
        "content_class": "post--content",
        "image_class": "s-post-thumbnail",
        "json_file": "news/chronicle.json"
    },
    "newzimbabwe": {
        "rss_url": "https://www.newzimbabwe.com/feed/",
        "content_class": "post-body",
        "image_class": "post-media",
        "json_file": "news/newzimbabwe.json"
    },
    "zimeye": {
        "rss_url": "https://www.zimeye.net/feed/",
        "content_class": "page-content",
        "image_class": None,  # No image for ZimEye
        "json_file": "news/zimeye.json",
        "custom_image_url": "https://example.com/default-image.jpg"  # Replace with your default image URL
    },
    "herald": {
        "rss_url": "https://www.herald.co.zw/feed/",
        "content_class": "post--content",
        "image_class": "s-post-thumbnail",
        "json_file": "news/herald.json"
    }
}

AI_API_URL = "https://api.paxsenix.biz.id/ai/gpt4omini?text="

async def send_to_ai_api(content):
    """Send content to the AI API for rephrasing."""
    prompt = f'''
    Rephrase the following content and generate a title and description based on it. Return the result in JSON format as shown below without any commentary or additional text:
    {{
        "title": "Rephrased title here",
        "description": "Rephrased description here",
        "rephrased_content": "Rephrased article content here"
    }}

    Content: {content}
    '''
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(AI_API_URL + prompt) as response:
                if response.status == 200:
                    data = await response.json()
                    message = data.get("message", "{}")
                    rephrased_data = json.loads(message)
                    return rephrased_data
                else:
                    print(f"AI API request failed with status: {response.status}")
                    return None
        except Exception as e:
            print(f"Error connecting to AI API: {str(e)}")
            return None

def fetch_rss_feed(rss_url, max_articles=3):
    """Fetch URLs from the RSS feed."""
    feed = feedparser.parse(rss_url)
    urls = []
    for entry in feed.entries[:max_articles]:
        if 'link' in entry:
            urls.append(entry.link)
    return urls

def scrape_article_content(url, content_class, image_class=None, custom_image_url=None):
    """Scrape article content and image URL from a URL."""
    headers = {"User-Agent": random.choice(user_agents)}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")

            # Extract content
            post_data_div = soup.find("div", class_=content_class)
            if not post_data_div:
                return None
            paragraphs = post_data_div.find_all("p")
            processed_paragraphs = []
            for p in paragraphs:
                clean_text = html.unescape(p.get_text(strip=True))
                clean_text = re.sub(r'[^\x20-\x7E\n]', '', clean_text)
                if clean_text:
                    processed_paragraphs.append(clean_text)
            main_content = "\n\n".join(processed_paragraphs) + "\n\n"

            # Extract image
            if image_class:
                image_div = soup.find("div", class_=image_class)
                if image_div and image_div.img and image_div.img.get("src"):
                    image_url = image_div.img["src"]
                else:
                    image_url = custom_image_url
            else:
                image_url = custom_image_url  # Use default for ZimEye or missing images

            return {"content": main_content, "image_url": image_url}
        else:
            return None
    except Exception as e:
        print(f"Error scraping {url}: {str(e)}")
        return None

async def process_article(url, content_class, image_class=None, custom_image_url=None):
    """Scrape article content, rephrase it via AI API, and return formatted data."""
    data = scrape_article_content(url, content_class, image_class, custom_image_url)
    if data:
        rephrased = await send_to_ai_api(data["content"])
        if rephrased and "rephrased_content" in rephrased:
            return {
                "url": url,
                "title": rephrased["title"],
                "description": rephrased["description"],
                "content": rephrased["rephrased_content"],
                "image_url": data["image_url"],
            }
        else:
            print("AI failed to return valid JSON, falling back to original content.")
            return {
                "url": url,
                "title": "Original Title",
                "description": "Original Description",
                "content": data["content"],
                "image_url": data["image_url"],
            }
    else:
        print(f"Failed to scrape {url}")
        return None

async def scrape_and_process(rss_url, content_class, image_class, json_file, custom_image_url=None, max_articles=3):
    """Fetch, scrape, rephrase, and save articles asynchronously."""
    urls = fetch_rss_feed(rss_url, max_articles)
    tasks = [process_article(url, content_class, image_class, custom_image_url) for url in urls]
    results = await asyncio.gather(*tasks)
    news_content = {"news": [res for res in results if res]}

    save_to_github(news_content, json_file)

def save_to_github(news_content, json_file):
    """Save the processed news content to GitHub."""
    github_token = os.getenv("GITHUB_TOKEN")
    repo_owner = "zeroteq"  # Replace with your GitHub username
    repo_name = "flask-news-scraper"  # Replace with your GitHub repository name
    branch = "main"

    # Prepare data for commit
    file_content = json.dumps(news_content, indent=4)
    encoded_content = base64.b64encode(file_content.encode('utf-8')).decode('utf-8')

    # GitHub API URL
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{json_file}?ref={branch}"
    response = requests.get(url, headers=headers)

    sha = response.json().get('sha') if response.status_code == 200 else None
    data = {
        "message": f"Update {json_file} with latest scraped articles",
        "content": encoded_content,
        "branch": branch,
        "sha": sha,
    }

    response = requests.put(url, headers=headers, json=data)
    if response.status_code in (200, 201):
        print(f"{json_file} updated successfully on GitHub")
    else:
        print(f"Failed to update {json_file} on GitHub: {response.status_code}, {response.text}")

@app.route('/scrape/<feed_name>', methods=['GET'])
def scrape_feed(feed_name):
    """Initiate asynchronous scraping for the selected feed."""
    if feed_name in feeds:
        feed_data = feeds[feed_name]
        asyncio.run(scrape_and_process(
            rss_url=feed_data["rss_url"],
            content_class=feed_data["content_class"],
            image_class=feed_data.get("image_class"),
            json_file=feed_data["json_file"],
            custom_image_url=feed_data.get("custom_image_url"),
        ))
        return jsonify({"message": f"Scraping completed for {feed_name}!"}), 200
    else:
        return jsonify({"error": "Feed not found"}), 404

if __name__ == "__main__":
    app.run(debug=True)
