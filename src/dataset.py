import sys
import os
import asyncio
import json
from pathlib import Path

# Add the src directory to sys.path to resolve imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Add the project root to sys.path to resolve the 'src' module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger
from tqdm import tqdm
import typer

from src.config import PROCESSED_DATA_DIR, RAW_DATA_DIR
from src.data.download import extract_pdf_data, extract_web_data
from src.data.preprocess import preprocess_data_async, integrate_translations
from src.data.features import feature_engineering
from src.data.embedding import prepare_for_embedding

app = typer.Typer()


async def main_async(input_path, output_path):
    """
    Main asynchronous function to orchestrate the data processing pipeline.
    
    Args:
        input_path: Path to raw data directory
        output_path: Path to processed data directory
    """
    # Create output directories if they don't exist
    pdf_output_dir = output_path / "cleaned_text_with_sections"
    pdf_output_dir.mkdir(parents=True, exist_ok=True)
    
    interim_dir = output_path.parent / "interim"
    interim_dir.mkdir(parents=True, exist_ok=True)
    
    web_data_output = output_path / "tableau_forum_threads.json"

    # Extract PDF and web data concurrently
    logger.info(f"Extracting data from PDFs at path: {input_path}")
    raw_pdf_data, raw_web_data = await asyncio.gather(
        asyncio.to_thread(extract_pdf_data, input_path),
        asyncio.to_thread(extract_web_data)
    )
    
    logger.info(f"Extracted {len(raw_pdf_data)} PDF blocks and {len(raw_web_data)} web entries")
    
    if len(raw_pdf_data) == 0:
        logger.warning(f"No PDF data extracted! Check if PDF files exist in {input_path}")

    # Save raw data to interim directory
    with open(interim_dir / "raw_pdf_data.json", "w", encoding="utf-8") as f:
        json.dump(raw_pdf_data, f, ensure_ascii=False, indent=4)
    
    with open(interim_dir / "raw_web_data.json", "w", encoding="utf-8") as f:
        json.dump(raw_web_data, f, ensure_ascii=False, indent=4)

    # Combine all raw data
    combined_data = raw_pdf_data + raw_web_data
    logger.info(f"Combined {len(raw_pdf_data)} PDF blocks and {len(raw_web_data)} web entries")

    # Preprocess data
    logger.info("Preprocessing data...")
    preprocessed_data, texts_to_translate, metadata, seen_texts = await preprocess_data_async(combined_data)
    
    # Translate and integrate non-English texts
    if texts_to_translate:
        logger.info(f"Translating {len(texts_to_translate)} non-English texts...")
        preprocessed_data = await integrate_translations(
            preprocessed_data, texts_to_translate, metadata, seen_texts
        )

    # Add the enhanced processing steps
    logger.info("Applying feature engineering...")
    enhanced_data = await feature_engineering(preprocessed_data)
    
    # Prepare for embeddings
    logger.info("Preparing data for embeddings...")
    embedding_ready_data = await prepare_for_embedding(enhanced_data)

    # Group data by source (using the enhanced data for better organization)
    pdf_data = [entry for entry in enhanced_data if "source_file" in entry]
    web_data = [entry for entry in enhanced_data if "source_file" not in entry]
    
    # Save preprocessed PDF data grouped by source file
    pdf_files = {entry["source_file"] for entry in pdf_data}
    for pdf_file in pdf_files:
        file_entries = [entry for entry in pdf_data if entry["source_file"] == pdf_file]
        output_file = pdf_output_dir / f"{pdf_file.replace('.pdf', '')}_paragraphs.json"
        with open(output_file, "w", encoding="utf-8") as json_file:
            json.dump(file_entries, json_file, ensure_ascii=False, indent=4)
        logger.info(f"Saved {len(file_entries)} entries to {output_file}")

    # Save preprocessed web data
    if web_data:
        with open(web_data_output, "w", encoding="utf-8") as json_file:
            json.dump(web_data, json_file, ensure_ascii=False, indent=4)
        logger.info(f"Saved {len(web_data)} web entries to {web_data_output}")

    # Save combined preprocessed data
    with open(output_path / "combined_preprocessed_data.json", "w", encoding="utf-8") as f:
        json.dump(preprocessed_data, f, ensure_ascii=False, indent=4)
    
    logger.info(f"Successfully processed {len(preprocessed_data)} entries")

    # Save the embedding-ready data (fixed indentation)
    with open(output_path / "rag_ready_data.json", "w", encoding="utf-8") as f:
        json.dump(embedding_ready_data, f, ensure_ascii=False, indent=4)
    logger.info(f"Saved {len(embedding_ready_data)} entries ready for embedding")
    
    return embedding_ready_data  # Return the embedding-ready data


@app.command()
def main(
    input_path: str = typer.Option(str(RAW_DATA_DIR), "--input", "-i", help="Path to raw data directory"),
    output_path: str = typer.Option(str(PROCESSED_DATA_DIR), "--output", "-o", help="Path to processed data directory")
):
    """
    Process the dataset: download raw data and preprocess it.
    """
    logger.info("Starting dataset processing...")
    input_path_obj = Path(input_path)
    output_path_obj = Path(output_path)
    asyncio.run(main_async(input_path_obj, output_path_obj))
    logger.success("Dataset processing complete.")


if __name__ == "__main__":
    app()