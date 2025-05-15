import sys
import os
from pathlib import Path
from loguru import logger
import time

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests
from bs4 import BeautifulSoup
import json
import fitz  # PyMuPDF

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from src.config import RAW_DATA_DIR


def extract_pdf_data(pdf_dir):
    """
    Extracts raw text data from all PDF files in the specified directory.
    
    Args:
        pdf_dir (str or Path): Directory containing PDF files
        
    Returns:
        list: List of dictionaries with extracted text and metadata
    """
    pdf_dir_path = Path(pdf_dir)
    raw_data = []
    
    # Add debug logging
    pdf_files = list(pdf_dir_path.glob("*.pdf"))
    logger.info(f"Found {len(pdf_files)} PDF files in {pdf_dir}: {[f.name for f in pdf_files]}")
    
    # If no PDF files found, check if the directory exists
    if len(pdf_files) == 0:
        logger.warning(f"No PDF files found in {pdf_dir}. Directory exists: {pdf_dir_path.exists()}")
        return raw_data
    
    # Process each PDF file
    for pdf_file in pdf_files:
        try:
            logger.info(f"Processing PDF: {pdf_file}")
            doc = fitz.open(pdf_file)
            
            # Extract text from each page
            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text()
                
                # Skip empty pages
                if not text.strip():
                    continue
                
                # Process text in blocks for better context
                blocks = page.get_text("blocks")
                for block in blocks:
                    block_text = block[4]  # Text content is at index 4
                    if len(block_text.strip()) > 20:  # Only keep meaningful blocks
                        raw_data.append({
                            "text": block_text,
                            "source_file": pdf_file.name,
                            "page_number": page_num + 1,
                            "block_id": len(raw_data)
                        })
            
            logger.info(f"Extracted {len(raw_data)} text blocks from {pdf_file.name}")
            
        except Exception as e:
            logger.error(f"Error processing PDF {pdf_file}: {e}")
    
    logger.info(f"Total extracted {len(raw_data)} text blocks from all PDFs")
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
                "content": content,
                "text": f"{title} {content}" if content else title  # Combined field for preprocessing
            })
        except AttributeError:
            continue

    return threads


if __name__ == "__main__":
    # Simple test to ensure each function works independently
    pdf_data = extract_pdf_data(RAW_DATA_DIR)
    logger.info(f"Extracted {len(pdf_data)} text blocks from PDFs")
    
    web_data = extract_web_data()
    logger.info(f"Extracted {len(web_data)} forum threads")