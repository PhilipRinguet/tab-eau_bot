import sys
import fitz  # PyMuPDF
import json
from loguru import logger
from pathlib import Path

# Add the project root to sys.path
project_root = Path(__file__).resolve().parents[1]  # Adjusted to include the correct root
sys.path.append(str(project_root))

from src.dataset import extract_and_clean_text_with_sections

def test_extraction_and_cleaning():
    """
    Test the extraction and cleaning functionality with a sample PDF.
    """
    pdf_dir = "data/raw/"  # Path to the raw PDF files
    output_dir = "data/interim/test_output/"  # Temporary output directory for testing

    # Call the extraction function
    extract_and_clean_text_with_sections(pdf_dir, output_dir)

    print(f"Test completed. Check the output in {output_dir}")

if __name__ == "__main__":
    test_extraction_and_cleaning()