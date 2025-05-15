import sys
import os
import re
import asyncio
import time
from pathlib import Path
from loguru import logger

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from langdetect import detect
# Replace googletrans with deep-translator
from deep_translator import GoogleTranslator


async def translate_texts_async(texts, batch_size=5, max_retries=3):
    """
    Asynchronously translate a list of texts to English in batches using deep-translator.

    Args:
        texts (list): List of texts to translate.
        batch_size (int): Number of texts to translate in each batch.
        max_retries (int): Maximum number of retries for failed translations.

    Returns:
        list: List of translated texts.
    """
    translated_texts = []
    translator = GoogleTranslator(source='auto', target='en')
    
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                # Run translation in a separate thread since it's blocking
                translations = await asyncio.to_thread(
                    lambda b=batch: [translator.translate(text) for text in b]
                )
                translated_texts.extend(translations)
                logger.debug(f"Translated batch {i//batch_size + 1}")
                
                # Add a small delay to avoid rate limiting
                if i + batch_size < len(texts):
                    await asyncio.sleep(1)
                    
                break  # Success - exit retry loop
                
            except Exception as e:
                retry_count += 1
                logger.warning(f"Batch translation failed (attempt {retry_count}): {e}")
                if retry_count >= max_retries:
                    # If all retries failed, use original texts
                    logger.error(f"Translation failed after {max_retries} attempts. Using original texts.")
                    translated_texts.extend(batch)
                else:
                    # Wait before retrying
                    await asyncio.sleep(2 * retry_count)  # Exponential backoff
    
    return translated_texts


async def preprocess_data_async(data):
    """
    Preprocess raw text data by normalizing text, ensuring web data is in English (translating if necessary),
    and deduplicating entries. PDF data is assumed to be in English and is only preprocessed.

    Args:
        data (list): A list of dictionaries containing raw text data and metadata.

    Returns:
        tuple: (preprocessed_data, texts_to_translate, metadata, seen_texts)
    """
    preprocessed_data = []
    seen_texts = set()
    texts_to_translate = []
    metadata = []

    # Normalize and prepare texts for translation
    for entry in data:
        if "text" not in entry:
            logger.warning(f"Skipping entry without text field: {entry}")
            continue
            
        text = entry["text"].lower()
        text = re.sub(r"[^\w\s\u3000-\u9FFF\u3040-\u30FF\u31F0-\u31FF]", "", text)  # Remove special characters
        text = re.sub(r"\s+", " ", text).strip()  # Normalize whitespace

        # Skip empty or non-linguistic texts
        if not any(char.isalpha() for char in text) or len(text) < 10:
            logger.warning(f"Skipping non-linguistic or too short text: {text}")
            continue

        # Determine if this is PDF data (has source_file field) or web data
        is_pdf_data = "source_file" in entry
        
        if is_pdf_data:
            # For PDF data: assume it's English, just apply preprocessing
            if text not in seen_texts:
                seen_texts.add(text)
                preprocessed_data.append({**entry, "text": text})
        else:
            # For web data: check language and translate if needed
            try:
                # Use more text for more accurate detection (up to 200 chars)
                detect_sample = text[:200] if len(text) > 200 else text
                detected_language = detect(detect_sample)
                logger.debug(f"Detected language: {detected_language} for text: {text[:30]}...")
                
                # Add translation logic here
                if detected_language != "en" and detected_language != "non-en":
                    texts_to_translate.append(text)
                    metadata.append(entry)
                else:
                    if text not in seen_texts:
                        seen_texts.add(text)
                        preprocessed_data.append({**entry, "text": text})
            except Exception as e:
                logger.warning(f"Language detection failed: {e}")
                # If detection fails on non-Latin text, assume it's non-English
                if any(ord(c) > 127 for c in text):
                    detected_language = "non-en"
                    texts_to_translate.append(text)
                    metadata.append(entry)
                else:
                    detected_language = "en"
                    if text not in seen_texts:
                        seen_texts.add(text)
                        preprocessed_data.append({**entry, "text": text})
    
    return preprocessed_data, texts_to_translate, metadata, seen_texts


async def integrate_translations(preprocessed_data, texts_to_translate, metadata, seen_texts):
    """
    Translate non-English texts and integrate them with preprocessed data.
    
    Args:
        preprocessed_data (list): Already preprocessed English data
        texts_to_translate (list): Non-English texts to translate
        metadata (list): Metadata for texts to translate
        seen_texts (set): Set of already seen texts to avoid duplication
        
    Returns:
        list: Combined preprocessed data with translations
    """
    # Translate non-English texts in bulk
    if not texts_to_translate:
        return preprocessed_data
        
    logger.info(f"Translating {len(texts_to_translate)} non-English entries...")
    translated_texts = await translate_texts_async(texts_to_translate)

    translations_added = 0
    for entry, translated_text in zip(metadata, translated_texts):
        if translated_text and translated_text not in seen_texts:
            seen_texts.add(translated_text)
            entry_with_translation = {**entry, "text": translated_text, "translated": True}
            preprocessed_data.append(entry_with_translation)
            translations_added += 1
    
    logger.info(f"Added {translations_added} translated entries")
    return preprocessed_data


if __name__ == "__main__":
    # Test with sample data including both PDF and web content
    sample_data = [
        # PDF-like entry (has source_file)
        {"text": "This is a sample PDF text.", "source_file": "sample.pdf", "page_number": 1},
        # Web-like entry (no source_file)
        {"text": "This is a sample web text.", "title": "Web Sample", "link": "https://example.com"},
        # Non-English web content
        {"text": "Ceci est un exemple de texte français du web.", "title": "French Sample", "link": "https://example.fr"},
    ]
    
    async def test_preprocessing():
        logger.info("Testing preprocessing with sample data...")
        preprocessed, to_translate, meta, seen = await preprocess_data_async(sample_data)
        
        logger.info(f"\nPreprocessed English entries ({len(preprocessed)}):")
        for i, entry in enumerate(preprocessed):
            source_type = "PDF" if "source_file" in entry else "Web"
            logger.info(f"{i+1}. [{source_type}] {entry['text'][:50]}...")
        
        logger.info(f"\nNon-English entries to translate ({len(to_translate)}):")
        for i, text in enumerate(to_translate):
            logger.info(f"{i+1}. {text[:50]}...")
        
        if to_translate:
            logger.info("\nTranslating non-English content...")
            final_data = await integrate_translations(preprocessed, to_translate, meta, seen)
            
            logger.info(f"\nFinal dataset after translation ({len(final_data)} entries):")
            pdf_entries = sum(1 for entry in final_data if "source_file" in entry)
            web_entries = sum(1 for entry in final_data if "source_file" not in entry)
            translated = sum(1 for entry in final_data if entry.get("translated", False))
            
            logger.info(f"PDF entries: {pdf_entries}")
            logger.info(f"Web entries: {web_entries} (including {translated} translated)")
        else:
            logger.info("No texts to translate")
    
    asyncio.run(test_preprocessing())