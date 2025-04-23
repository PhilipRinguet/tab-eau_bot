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


async def translate_texts_async(texts, translator, batch_size=10):
    """
    Asynchronously translate a list of texts to English in batches.

    Args:
        texts (list): List of texts to translate.
        translator (Translator): Google Translator instance.
        batch_size (int): Number of texts to translate in each batch.

    Returns:
        list: List of translated texts.
    """
    translated_texts = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        try:
            translations = await asyncio.to_thread(
                lambda: [translator.translate(text, dest="en").text for text in batch]
            )
            translated_texts.extend(translations)
        except Exception as e:
            logger.warning(f"Batch translation failed: {e}")
            translated_texts.extend(batch)  # Fallback to original texts

    return translated_texts


async def preprocess_data_async(data):
    """
    Preprocess raw text data by normalizing text, ensuring it is in English (translating if necessary),
    and deduplicating entries.

    Args:
        data (list): A list of dictionaries containing raw text data and metadata.

    Returns:
        list: A list of dictionaries containing preprocessed text data and metadata.
    """
    preprocessed_data = []
    seen_texts = set()
    texts_to_translate = []
    metadata = []

    # Normalize and prepare texts for translation
    for entry in data:
        text = entry["text"].lower()
        text = re.sub(r"[^a-z0-9\s]", "", text)  # Remove special characters
        text = re.sub(r"\s+", " ", text).strip()  # Normalize whitespace

        # Skip empty or non-linguistic texts
        if not any(char.isalpha() for char in text):
            logger.warning(f"Skipping non-linguistic or empty text: {text}")
            continue

        # Check if the text is in English
        try:
            detected_language = detect(text)
            if detected_language != "en":
                texts_to_translate.append(text)
                metadata.append(entry)
            else:
                if text not in seen_texts:
                    seen_texts.add(text)
                    preprocessed_data.append({**entry, "text": text})
        except Exception as e:
            logger.warning(f"Language detection failed for text: {text[:30]}... Error: {e}")

    return preprocessed_data, texts_to_translate, metadata


async def main_async():
    pdf_dir = RAW_DATA_DIR
    web_data_output = PROCESSED_DATA_DIR.parent / "interim" / "tableau_forum_threads.json"
    pdf_output_dir = PROCESSED_DATA_DIR / "cleaned_text_with_sections"

    # Extract PDF and web data concurrently
    raw_pdf_data, raw_web_data = await asyncio.gather(
        asyncio.to_thread(extract_pdf_data, pdf_dir),
        asyncio.to_thread(extract_web_data)
    )

    # Combine all raw data
    combined_data = raw_pdf_data + raw_web_data

    # Preprocess data
    preprocessed_data, texts_to_translate, metadata = await preprocess_data_async(combined_data)

    # Translate non-English texts in bulk
    if texts_to_translate:
        translator = Translator()
        translated_texts = await translate_texts_async(texts_to_translate, translator)

        for entry, translated_text in zip(metadata, translated_texts):
            if translated_text not in seen_texts:
                seen_texts.add(translated_text)
                preprocessed_data.append({**entry, "text": translated_text})

    # Save preprocessed data
    for entry in preprocessed_data:
        if "source_file" in entry:  # PDF data
            output_file = pdf_output_dir / f"{entry['source_file'].replace('.pdf', '')}_paragraphs.json"
            with open(output_file, "w", encoding="utf-8") as json_file:
                json.dump(preprocessed_data, json_file, ensure_ascii=False, indent=4)
        else:  # Web data
            with open(web_data_output, "w", encoding="utf-8") as json_file:
                json.dump(preprocessed_data, json_file, ensure_ascii=False, indent=4)


if __name__ == "__main__":
    asyncio.run(main_async())