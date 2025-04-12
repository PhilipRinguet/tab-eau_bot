import sys
import os

# Add the src directory to sys.path to resolve imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Add the project root to sys.path to resolve the 'src' module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

from loguru import logger
from tqdm import tqdm
import typer

import requests
from bs4 import BeautifulSoup
import json

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

from config import PROCESSED_DATA_DIR, RAW_DATA_DIR

app = typer.Typer()


@app.command()
def main(
    # ---- REPLACE DEFAULT PATHS AS APPROPRIATE ----
    input_path: Path = RAW_DATA_DIR / "dataset.csv",
    output_path: Path = PROCESSED_DATA_DIR / "dataset.csv",
    # ----------------------------------------------
):
    # ---- REPLACE THIS WITH YOUR OWN CODE ----
    logger.info("Processing dataset...")
    for i in tqdm(range(10), total=10):
        if i == 5:
            logger.info("Something happened for iteration 5.")
    logger.success("Processing dataset complete.")
    # -----------------------------------------


# Updated function to ensure "Expand Post" is clicked before saving content and best answer
def scrape_tableau_forum():
    # Use Selenium to handle dynamic content
    url = "https://community.tableau.com/s/topic/0TO4T000000QF9nWAG/tableau-desktop-web-authoring"
    driver = webdriver.Chrome()  # Ensure you have the ChromeDriver installed
    driver.get(url)

    # Click "View More" button until it times out or no more pages are available
    while True:
        try:
            view_more_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CLASS_NAME, "cuf-showMore"))
            )
            ActionChains(driver).move_to_element(view_more_button).click(view_more_button).perform()
            time.sleep(2)  # Wait for new content to load
        except Exception:
            print("DEBUG: No more 'View More' button or timeout occurred.")  # Debug statement
            break  # Exit loop if "View More" button is not found or times out

    # Expand all posts to get full content
    try:
        expand_buttons = driver.find_elements(By.CLASS_NAME, "cuf-more")
        for button in expand_buttons:
            try:
                ActionChains(driver).move_to_element(button).click(button).perform()
                time.sleep(1)  # Wait for content to expand
            except Exception:
                continue  # Skip if a button cannot be clicked
    except Exception:
        pass

    # Parse the partially loaded page
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    driver.quit()

    # Extract thread data
    threads = []
    for article in soup.find_all("article", class_="cuf-feedElement cuf-feedItem"):
        try:
            title = article.find("div", class_="cuf-questionTitle").get_text(strip=True)
            link = article.find("a", class_="cuf-timestamp")['href']
            author = article.find("span", class_="cuf-entityLinkId").get_text(strip=True)
            date = article.find("a", class_="cuf-timestamp").get_text(strip=True)

            # Ensure "Expand Post" is clicked for content
            content_element = article.find("div", class_="cuf-feedBodyText")
            # Debugging: Print content and best answer after clicking "Expand Post"
            if content_element:
                expanded_content_element = content_element.find("div", class_="feedBodyInner Desktop")
                if expanded_content_element:
                    content = expanded_content_element.get_text(strip=True)
                    print(f"DEBUG: Full content after expanding: {content}")  # Debug statement
                else:
                    content = content_element.get_text(strip=True)
            else:
                content = None

            # Check for best answer and ensure "Expand Post" is clicked
            best_answer = None
            best_answer_container = article.find("div", class_="cuf-bestAnswerContainer")
            if best_answer_container:
                best_answer_element = best_answer_container.find("div", class_="feedBodyInner Desktop")
                if best_answer_element:
                    best_answer = best_answer_element.get_text(strip=True)
                    print(f"DEBUG: Full best answer after expanding: {best_answer}")  # Debug statement

            threads.append({
                "title": title,
                "link": f"https://community.tableau.com{link}",
                "author": author,
                "date": date,
                "content": content,
                "best_answer": best_answer
            })
        except AttributeError:
            continue  # Skip if any data is missing

    # Save the data to a JSON file
    with open("data/processed/tableau_forum_threads.json", "w", encoding="utf-8") as f:
        json.dump(threads, f, ensure_ascii=False, indent=4)

    print(f"Scraped {len(threads)} threads and saved to data/processed/tableau_forum_threads.json")

if __name__ == "__main__":
    scrape_tableau_forum()