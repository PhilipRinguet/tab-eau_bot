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

import re
from langdetect import detect
from googletrans import Translator

import asyncio

# Initialize the translator
translator = Translator()

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


def extract_pdf_data(pdf_dir):
    """
    Extracts raw text data from all PDF files in the specified directory.

    Args:
        pdf_dir (str): Path to the directory containing PDF files.

    Returns:
        list: A list of dictionaries containing raw text data and metadata for each PDF.
    """
    pdf_dir_path = Path(pdf_dir)
    raw_data = []

    for pdf_file in pdf_dir_path.glob("*.pdf"):
        try:
            logger.debug(f"Extracting data from PDF: {pdf_file.name}")
            doc = fitz.open(pdf_file)

            for page_number, page in enumerate(doc, start=1):
                text_blocks = page.get_text("blocks")
                for block in text_blocks:
                    block_text = block[4].strip()
                    raw_data.append({
                        "page_number": page_number,
                        "source_file": pdf_file.name,
                        "text": block_text
                    })
        except Exception as e:
            logger.error(f"Failed to extract data from {pdf_file.name}: {e}")

    return raw_data


def extract_web_data():
    """
    Extracts raw data from the Tableau forum threads.

    Returns:
        list: A list of dictionaries containing raw text data and metadata for each thread.
    """
    url = "https://community.tableau.com/s/topic/0TO4T000000QF9nWAG/tableau-desktop-web-authoring"
    driver = webdriver.Chrome()
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

    threads = []
    for article in soup.find_all("article", class_="cuf-feedElement cuf-feedItem"):
        try:
            title = article.find("div", class_="cuf-questionTitle").get_text(strip=True)
            link = article.find("a", class_="cuf-timestamp")["href"]
            content_element = article.find("div", class_="cuf-feedBodyText")
            content = content_element.get_text(strip=True) if content_element else None

            threads.append({
                "title": title,
                "link": f"https://community.tableau.com{link}",
                "content": content
            })
        except AttributeError:
            continue

    return threads


async def translate_text_async(text, translator):
    """
    Asynchronously translate text to English using the provided translator.

    Args:
        text (str): The text to translate.
        translator (Translator): The Google Translator instance.

    Returns:
        str: Translated text in English.
    """
    try:
        translated = await asyncio.to_thread(translator.translate, text, dest="en")
        return translated.text
    except Exception as e:
        logger.warning(f"Translation failed for text: {text[:30]}... Error: {e}")
        return text


async def preprocess_data_async(data):
    """
    Asynchronously preprocess raw text data by normalizing text, ensuring it is in English (translating if necessary),
    and deduplicating entries.

    Args:
        data (list): A list of dictionaries containing raw text data and metadata.

    Returns:
        list: A list of dictionaries containing preprocessed text data and metadata.
    """
    preprocessed_data = []
    seen_texts = set()
    translator = Translator()

    for entry in data:
        text = entry["text"].lower()
        text = re.sub(r"[^a-z0-9\s]", "", text)  # Remove special characters
        text = re.sub(r"\s+", " ", text).strip()  # Normalize whitespace

        # Check if the text is in English
        try:
            detected_language = detect(text)
            if detected_language != "en":
                # Translate to English if not already in English
                text = await translate_text_async(text, translator)
        except Exception as e:
            logger.warning(f"Language detection failed for text: {text[:30]}... Error: {e}")
            continue

        # Deduplicate entries
        if text in seen_texts:
            continue
        seen_texts.add(text)

        preprocessed_data.append({
            "page_number": entry.get("page_number"),
            "source_file": entry.get("source_file"),
            "title": entry.get("title"),
            "link": entry.get("link"),
            "text": text
        })

    return preprocessed_data


# Update the main script to use asyncio for preprocessing
if __name__ == "__main__":
    pdf_dir = RAW_DATA_DIR
    web_data_output = PROCESSED_DATA_DIR.parent / "interim" / "tableau_forum_threads.json"
    pdf_output_dir = PROCESSED_DATA_DIR / "cleaned_text_with_sections"

    # Extract and preprocess PDF data
    raw_pdf_data = extract_pdf_data(pdf_dir)
    preprocessed_pdf_data = asyncio.run(preprocess_data_async(raw_pdf_data))
    for entry in preprocessed_pdf_data:
        output_file = pdf_output_dir / f"{entry['source_file'].replace('.pdf', '')}_paragraphs.json"
        with open(output_file, "w", encoding="utf-8") as json_file:
            json.dump(preprocessed_pdf_data, json_file, ensure_ascii=False, indent=4)

    # Extract and preprocess web data
    raw_web_data = extract_web_data()
    preprocessed_web_data = asyncio.run(preprocess_data_async(raw_web_data))
    with open(web_data_output, "w", encoding="utf-8") as json_file:
        json.dump(preprocessed_web_data, json_file, ensure_ascii=False, indent=4)