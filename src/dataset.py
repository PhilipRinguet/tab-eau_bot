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

import PyPDF2
import fitz  # PyMuPDF

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


# Updated function to scrape Tableau Forum threads with expanded posts and best answers
def scrape_tableau_forum():
    # Use Selenium to handle dynamic content
    url = "https://community.tableau.com/s/topic/0TO4T000000QF9nWAG/tableau-desktop-web-authoring"
    driver = webdriver.Chrome()  # Ensure you have the ChromeDriver installed
    driver.get(url)

    # Click "View More" button
    for _ in range(10):
        try:
            view_more_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CLASS_NAME, "cuf-showMore"))
            )
            ActionChains(driver).move_to_element(view_more_button).click(view_more_button).perform()
            time.sleep(2)  # Wait for new content to load
        except Exception:
            break  # Exit loop if "View More" button is not found

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
            content_element = article.find("div", class_="cuf-feedBodyText")

            # Updated function to use the correct "feedBodyInner Desktop" class for content and best answer
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
            # Updated function to ensure the "Expand Post" button for the best answer is clicked before extracting content
            if best_answer_container:
                expand_button = best_answer_container.find("a", class_="cuf-more")
                if expand_button:
                    try:
                        # Locate and click the "Expand Post" button for the best answer
                        expand_button_element = driver.find_element(By.XPATH, f"//a[@title='Show more text' and contains(@class, 'cuf-more')]")
                        ActionChains(driver).move_to_element(expand_button_element).click(expand_button_element).perform()
                        time.sleep(1)  # Wait for the content to expand
                    except Exception as e:
                        logger.warning(f"Could not click 'Expand Post' for best answer: {e}")

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


def extract_and_clean_text_with_sections(pdf_dir, output_dir):
    """
    Extracts text from all PDF files in the specified directory, identifies sections, cleans the text,
    and saves it to JSON files with metadata including sections.

    Args:
        pdf_dir (str): Path to the directory containing PDF files.
        output_dir (str): Path to the directory where cleaned text files with metadata will be saved.
    """
    pdf_dir_path = Path(pdf_dir)
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    for pdf_file in pdf_dir_path.glob("*.pdf"):
        try:
            doc = fitz.open(pdf_file)
            extracted_data = []
            current_section = None

            for page_number, page in enumerate(doc, start=1):
                text = page.get_text("blocks")  # Extract text blocks
                for block in text:
                    block_text = block[4].strip()

                    # Identify sections based on patterns (e.g., headings)
                    if block_text.isupper() or block_text.endswith(":"):
                        current_section = block_text
                        continue

                    # Clean the extracted text
                    cleaned_text = block_text.replace("\n", " ").strip()

                    # Append metadata and cleaned text
                    if cleaned_text:
                        extracted_data.append({
                            "page_number": page_number,
                            "source_file": pdf_file.name,
                            "section": current_section,
                            "text": cleaned_text
                        })

            # Save the extracted data with metadata to a JSON file
            output_file = output_dir_path / f"{pdf_file.stem}_sections.json"
            with open(output_file, "w", encoding="utf-8") as json_file:
                json.dump(extracted_data, json_file, ensure_ascii=False, indent=4)

            logger.info(f"Processed and saved cleaned text with sections for {pdf_file.name}")
        except Exception as e:
            logger.error(f"Failed to process {pdf_file.name}: {e}")

# Example usage
if __name__ == "__main__":
    pdf_dir = RAW_DATA_DIR
    output_dir = PROCESSED_DATA_DIR / "cleaned_text_with_sections"
    extract_and_clean_text_with_sections(pdf_dir, output_dir)
    scrape_tableau_forum()