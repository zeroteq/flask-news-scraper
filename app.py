import requests
import random
import html
import re
import feedparser
import json
import os
import base64
from flask import Flask, jsonify
from bs4 import BeautifulSoup
from datetime import datetime
import pytz

# Initialize Flask app
app = Flask(__name__)

# List of user agents for rotation
user_agents = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
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

def fetch_rss_feed(rss_url, max_articles=10):
    """Fetch URLs, descriptions, titles, and other metadata from the RSS feed."""
    feed = feedparser.parse(rss_url)
    articles = []
    for entry in feed.entries[:max_articles]:
        if 'link' in entry and 'summary' in entry:
            article = {
                "title": entry.title,
                "url": entry.link,
                "description": html.unescape(entry.summary),  # Decode HTML entities in the description
                "time": datetime.now(pytz.timezone("Africa/Harare")).strftime('%Y-%m-%d %H:%M:%S')  # CAT time
            }
            articles.append(article)
    return articles

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

def scrape_and_save_to_github(rss_url, content_class, image_class, json_file, custom_image_url=None, max_articles=10):
    """Scrape articles from an RSS feed and save to GitHub."""
    articles_to_scrape = fetch_rss_feed(rss_url, max_articles)
    news_content = {"news": []}

    for article in articles_to_scrape:
        url = article["url"]
        description = article["description"]
        title = article["title"]
        time = article["time"]
        print(f"Scraping {url}...")
        data = scrape_article_content(url, content_class, image_class, custom_image_url)
        if data:
            news_content["news"].append({
                "title": title,
                "url": url,
                "content": data["content"],
                "image_url": data["image_url"],
                "description": description,
                "time": time
            })
        else:
            print(f"Failed to scrape {url}")

    # Using the GitHub API to update the file
    github_token = os.getenv("GITHUB_TOKEN")
    repo_owner = "zeroteq"  # Replace with your GitHub username
    repo_name = "flask-news-scraper"  # Replace with your GitHub repository name
    branch = "main"

    # Prepare data for commit
    file_content = json.dumps(news_content, indent=4)
    encoded_content = base64.b64encode(file_content.encode('utf-8')).decode('utf-8')

    # Get file information from GitHub
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{json_file}?ref={branch}"
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        file_info = response.json()
        sha = file_info['sha']
    else:
        sha = None  # If file doesn't exist, no sha needed

    data = {
        "message": f"Update {json_file} with latest scraped articles",
        "content": encoded_content,
        "branch": branch
    }
    if sha:
        data["sha"] = sha  # Add sha for existing file update

    response = requests.put(url, headers=headers, json=data)
    if response.status_code in (200, 201):
        print(f"{json_file} updated successfully on GitHub")
    else:
        print(f"Failed to update {json_file} on GitHub: {response.status_code}, {response.text}")

@app.route('/scrape/category/<category>', methods=['GET'])
def scrape_category(category):
    """Scrape a specific category page and save data to GitHub."""
    urls = {
        "business": "https://www.zbcnews.co.zw/category/business/",
        "local": "https://www.zbcnews.co.zw/category/local-news/",
        "sport": "https://www.zbcnews.co.zw/category/sport/"
    }
    json_files = {
        "business": "custom-rss/business.json",
        "local": "custom-rss/local.json",
        "sport": "custom-rss/sport.json"
    }

    if category in urls:
        url = urls[category]
        headers = {"User-Agent": random.choice(user_agents)}
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            # Parse the HTML content using BeautifulSoup
            soup = BeautifulSoup(response.content, "html.parser")

            # Find all relevant div elements (same as the original code)
            articles = soup.find_all("div", class_="td-module-meta-info")

            # Extract title and link
            data = []
            for article in articles:
                category_tag = article.find("a", class_="td-post-category")
                if category_tag and category_tag.text.strip() == category.capitalize():
                    title = article.find("p", class_="entry-title td-module-title").find("a").text.strip()
                    href = article.find("p", class_="entry-title td-module-title").find("a")["href"]
                    data.append({"title": title, "href": href})

            # Save the scraped data to GitHub directly using the scrape_and_save_to_github function
            scrape_and_save_to_github(
                rss_url=url,
                content_class="td-module-meta-info",
                image_class=None,
                json_file=json_files[category],  # File path for GitHub
                custom_image_url=None,
                max_articles=len(data)
            )

            return jsonify({"message": f"Scraped {len(data)} articles for {category} and saved to GitHub."}), 200
        else:
            return jsonify({"error": f"Failed to scrape {category}. Status code: {response.status_code}"}), 500
    return jsonify({"error": "Category not found"}), 404

if __name__ == "__main__":
    app.run(debug=True)
