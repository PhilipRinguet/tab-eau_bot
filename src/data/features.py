"""
Feature engineering for Tableau data
"""
import re
import numpy as np
from typing import List, Dict, Any, Set, Optional, Tuple
from loguru import logger
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

try:
    import spacy
    from spacy.lang.en import English
    SPACY_AVAILABLE = True
except ImportError:
    SPACY_AVAILABLE = False
    logger.warning("spaCy not available. Using simplified entity extraction.")


def normalize_text(text: str) -> str:
    """
    Advanced text normalization specifically for Tableau terminology.
    """
    # Handle None values
    if text is None:
        return ""
        
    # Normalize Tableau version references
    text = re.sub(r'tableau\s+(\d{4})\.(\d+)', r'tableau \1.\2', text, flags=re.IGNORECASE)
    
    # Normalize common abbreviations
    tableau_abbreviations = {
        r'\bLOD\b': 'level of detail',
        r'\bTDE\b': 'tableau data extract',
        r'\bTBM\b': 'tableau bookmark',
        r'\bTWB\b': 'tableau workbook',
        r'\bTWBX\b': 'packaged tableau workbook'
    }
    
    for abbr, full in tableau_abbreviations.items():
        text = re.sub(abbr, full, text, flags=re.IGNORECASE)
    
    # Remove HTML artifacts
    text = re.sub(r'<[^>]+>', ' ', text)
    
    # Convert Unicode characters to ASCII equivalents
    text = text.replace('–', '-').replace('—', '-').replace('"', '"').replace('"', '"')
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text


def extract_tableau_entities(text: str) -> Dict[str, List[str]]:
    """
    Extract Tableau-specific entities from text.
    """
    # Handle None values
    if text is None:
        return {"measures": [], "dimensions": [], "functions": [], "chart_types": [], "general_terms": []}
        
    tableau_entities = {
        "measures": [],
        "dimensions": [],
        "functions": [],
        "chart_types": [],
        "general_terms": []
    }
    
    if SPACY_AVAILABLE:
        try:
            nlp = spacy.load("en_core_web_sm")
            doc = nlp(text)
            # Advanced NER processing could be added here
        except:
            nlp = English()
    
    # Custom rule-based extraction for Tableau concepts
    measure_patterns = [r'\bsum\(\w+\)', r'\bavg\(\w+\)', r'\bcount\(\w+\)']
    for pattern in measure_patterns:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        if matches:
            tableau_entities["measures"].extend(matches)
    
    # Extract function references
    function_matches = re.findall(r'\b(FIXED|INCLUDE|EXCLUDE|WINDOW_\w+|IF|ELSE|THEN|END|DATE|DATEADD)\b', 
                                 text, flags=re.IGNORECASE)
    if function_matches:
        tableau_entities["functions"] = list(set(function_matches))
    
    # Extract chart types
    chart_patterns = [r'\b(bar chart|line chart|pie chart|scatter plot|histogram|box plot|treemap|heatmap)\b']
    for pattern in chart_patterns:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        if matches:
            tableau_entities["chart_types"].extend(matches)
    
    # Extract general Tableau terms
    general_terms = re.findall(
        r'\b(dashboard|visualization|worksheet|filter|calculated field|parameter|dimension|measure|workbook|data source)\b', 
        text.lower()
    )
    tableau_entities["general_terms"] = list(set(general_terms))
    
    return tableau_entities


def enrich_metadata(entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add useful metadata to improve RAG context and retrieval.
    """
    # Skip if no text
    if not entry.get("text"):
        return entry
        
    # Create a simplified title for web content
    if "title" in entry and not entry.get("simplified_title"):
        # Remove special characters and limit length
        simplified = re.sub(r'[^\w\s]', '', entry["title"].lower())
        entry["simplified_title"] = simplified[:100]
    
    # Extract key entities if not already extracted
    if "text" in entry and not entry.get("entities"):
        tableau_terms = extract_tableau_entities(entry["text"])
        entry["entities"] = tableau_terms["general_terms"]
    
    # Add content type and source classification
    if "source_file" in entry:
        entry["content_type"] = "documentation"
        entry["source"] = "official_docs"
    else:
        entry["content_type"] = "community_question"
        entry["source"] = "forum"
    
    # If there's translated text, ensure it's normalized too
    if entry.get("translated", False):
        entry["text"] = normalize_text(entry["text"])
    
    return entry


async def deduplicate_semantic_content(entries: List[Dict[str, Any]], threshold: float = 0.85) -> List[Dict[str, Any]]:
    """
    Remove semantically duplicate content using TF-IDF and cosine similarity.
    """
    if len(entries) <= 1:
        return entries
        
    # Extract text from entries, handling None values
    texts = [entry.get("text", "") for entry in entries]
    texts = [t if t is not None else "" for t in texts]
    
    try:
        # Create TF-IDF vectors
        vectorizer = TfidfVectorizer(stop_words="english")
        tfidf_matrix = vectorizer.fit_transform(texts)
        
        # Compute similarities
        similarities = cosine_similarity(tfidf_matrix)
    except Exception as e:
        logger.error(f"TF-IDF vectorization failed: {e}")
        return entries  # Return original entries if vectorization fails
    
    # Track which entries to keep
    keep_indices = []
    
    for i in range(len(entries)):
        # Skip if already processed
        if i in keep_indices:
            continue
            
        # Mark this entry as keeper
        keep_indices.append(i)
        
        # Find similar entries and exclude them
        for j in range(i+1, len(entries)):
            if j not in keep_indices and similarities[i, j] > threshold:
                # Entry j is too similar to i, don't add to keep_indices
                pass
    
    # Return only the unique entries
    return [entries[i] for i in keep_indices]


async def feature_engineering(preprocessed_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Apply feature engineering to preprocessed data.
    
    Args:
        preprocessed_data: List of preprocessed entries
        
    Returns:
        Enhanced data with extracted features
    """
    enhanced_data = []
    
    for entry in preprocessed_data:
        # Skip empty entries
        if not entry.get("text"):
            continue
            
        # Normalize text
        entry["text"] = normalize_text(entry["text"])
        
        # Extract Tableau-specific entities
        entry["tableau_entities"] = extract_tableau_entities(entry["text"])
        
        # Enrich metadata
        entry = enrich_metadata(entry)
        
        enhanced_data.append(entry)
    
    # Semantic deduplication
    logger.info(f"Deduplicating {len(enhanced_data)} entries...")
    enhanced_data = await deduplicate_semantic_content(enhanced_data)
    logger.info(f"After deduplication: {len(enhanced_data)} entries")
    
    return enhanced_data


if __name__ == "__main__":
    # Test code
    import asyncio
    import json
    from pathlib import Path
    
    async def test_feature_engineering():
        # Sample data
        sample_data = [
            {"text": "How to create a dashboard in Tableau?", "title": "Dashboard Creation Help"},
            {"text": "Using LOD expressions with filters in Tableau", "title": "LOD Filter Issue"}
        ]
        
        enhanced = await feature_engineering(sample_data)
        logger.info(f"Enhanced {len(enhanced)} entries")
        logger.info(f"Sample entities: {enhanced[0].get('tableau_entities')}")
        
        # Try to load real data if available
        processed_dir = Path("data/processed")
        combined_path = processed_dir / "combined_preprocessed_data.json"
        
        if combined_path.exists():
            with open(combined_path, 'r', encoding='utf-8') as f:
                real_data = json.load(f)
                
            logger.info(f"Loaded {len(real_data)} entries from {combined_path}")
            # Process just a few items for testing
            test_items = real_data[:5] if len(real_data) > 5 else real_data
            
            enhanced_real = await feature_engineering(test_items)
            logger.info(f"Enhanced {len(enhanced_real)} real entries")
            
            # Show sample output
            if enhanced_real:
                logger.info(f"Sample output: {json.dumps(enhanced_real[0], indent=2)[:500]}...")
    
    asyncio.run(test_feature_engineering())