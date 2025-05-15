"""
Functions for text chunking and embedding preparation
"""
from typing import List, Dict, Any
from loguru import logger
from pathlib import Path
import json
import numpy as np

# Vector database imports
from sentence_transformers import SentenceTransformer
import faiss

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    logger.warning("LangChain splitters not available. Using basic chunking.")


def chunk_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> List[str]:
    """
    Split text into semantically meaningful chunks suitable for embedding.
    """
    if LANGCHAIN_AVAILABLE:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
        return splitter.split_text(text)
    else:
        # Fallback to basic chunking
        chunks = []
        words = text.split()
        current_chunk = []
        current_size = 0
        
        for word in words:
            current_chunk.append(word)
            current_size += len(word) + 1  # +1 for space
            
            if current_size >= chunk_size:
                chunks.append(" ".join(current_chunk))
                # Keep overlap words
                overlap_words = current_chunk[-int(chunk_overlap/5):]  # Approximate words for overlap chars
                current_chunk = overlap_words
                current_size = len(" ".join(current_chunk))
        
        # Add the last chunk if it has content
        if current_chunk:
            chunks.append(" ".join(current_chunk))
            
        return chunks


def create_embedding_template(entry: Dict[str, Any]) -> str:
    """
    Create a structured template for better embedding context.
    
    The template format helps the LLM understand the structure and source
    of the information, which improves retrieval quality.
    """
    template = []
    
    # Add source information
    if "source_file" in entry:
        template.append(f"SOURCE: Tableau Documentation - {entry['source_file']}")
        if "page_number" in entry:
            template.append(f"PAGE: {entry['page_number']}")
    else:
        template.append(f"SOURCE: Tableau Community Forum")
        if "title" in entry:
            template.append(f"TITLE: {entry['title']}")
    
    # Add metadata
    if entry.get("entities"):
        template.append(f"TOPICS: {', '.join(entry['entities'])}")
    
    # Add tableau-specific entities if available
    entities = entry.get("tableau_entities", {})
    if entities.get("functions"):
        template.append(f"FUNCTIONS: {', '.join(entities['functions'])}")
    if entities.get("chart_types"):
        template.append(f"CHART TYPES: {', '.join(entities['chart_types'])}")
    
    # Add the main content
    template.append(f"CONTENT: {entry['text']}")
    
    # Add chunking information if applicable
    if entry.get("is_chunked", False):
        template.append(f"CHUNK: {entry['chunk_id']+1} of {entry['total_chunks']}")
    
    return "\n".join(template)


async def prepare_for_embedding(enhanced_data: List[Dict[str, Any]], 
                               chunk_long_texts: bool = True) -> List[Dict[str, Any]]:
    """
    Prepare data for embedding by chunking and creating templates.
    
    Args:
        enhanced_data: Data with extracted features
        chunk_long_texts: Whether to chunk texts longer than the threshold
        
    Returns:
        Data ready for embedding
    """
    embedding_ready_data = []
    
    for entry in enhanced_data:
        # Skip empty entries
        if not entry.get("text"):
            continue
        
        # Chunk longer texts if requested
        if chunk_long_texts and len(entry["text"]) > 600:
            chunks = chunk_text(entry["text"])
            for i, chunk in enumerate(chunks):
                chunk_entry = entry.copy()
                chunk_entry["text"] = chunk
                chunk_entry["chunk_id"] = i
                chunk_entry["is_chunked"] = True
                chunk_entry["total_chunks"] = len(chunks)
                
                # Create embedding template
                chunk_entry["embedding_template"] = create_embedding_template(chunk_entry)
                
                embedding_ready_data.append(chunk_entry)
        else:
            entry["is_chunked"] = False
            
            # Create embedding template
            entry["embedding_template"] = create_embedding_template(entry)
            
            embedding_ready_data.append(entry)
    
    logger.info(f"Prepared {len(embedding_ready_data)} entries for embedding")
    return embedding_ready_data


# Define paths for vector database
processed_dir = Path("data/processed")
vector_db_path = processed_dir / "vector_index.faiss"

# Initialize the embedding model
try:
    model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    EMBEDDING_MODEL_AVAILABLE = True
except ImportError:
    EMBEDDING_MODEL_AVAILABLE = False
    logger.warning("SentenceTransformer not available. Install with: pip install sentence-transformers")


def generate_embeddings(data):
    """
    Generate embeddings for the given text data.

    Args:
        data (list): A list of dictionaries containing text data with embedding_template field

    Returns:
        tuple: A tuple containing the embeddings and the original data
    """
    if not EMBEDDING_MODEL_AVAILABLE:
        logger.error("Cannot generate embeddings: SentenceTransformer not available")
        return None, data
        
    # Use the embedding template if available, otherwise use plain text
    texts = [entry.get("embedding_template", entry.get("text", "")) for entry in data]
    logger.info(f"Generating embeddings for {len(texts)} texts")
    
    embeddings = model.encode(texts, show_progress_bar=True)
    # Convert to numpy float32 array for FAISS
    embeddings = np.array(embeddings).astype('float32')
    
    return embeddings, data


def store_embeddings_faiss(embeddings, data, output_path=None):
    """
    Store embeddings and data in a FAISS index.

    Args:
        embeddings (ndarray): The embeddings to store
        data (list): The original data entries
        output_path (Path): Where to save the index (default: vector_db_path)
    """
    if output_path is None:
        output_path = vector_db_path
    
    # Create directory if it doesn't exist
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create the FAISS index
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatL2(dimension)
    index.add(embeddings)

    # Save the index
    faiss.write_index(index, str(output_path))
    
    # Save data alongside index
    metadata_path = output_path.with_suffix(".json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    logger.info(f"FAISS index and data saved to {output_path} and {metadata_path}")


def query_faiss(query_text, k=5, index_path=None):
    """
    Query the FAISS index and retrieve the nearest entries.

    Args:
        query_text (str): The text to query
        k (int): Number of results to retrieve
        index_path (Path): Path to the FAISS index

    Returns:
        list: List of relevant entries with distances
    """
    if index_path is None:
        index_path = vector_db_path
    
    if not EMBEDDING_MODEL_AVAILABLE:
        logger.error("Cannot query: SentenceTransformer not available")
        return []
        
    # Check if index exists
    if not index_path.exists():
        logger.error(f"FAISS index not found at {index_path}")
        return []
        
    # Load the FAISS index
    index = faiss.read_index(str(index_path))
    
    # Load the data
    metadata_path = index_path.with_suffix(".json")
    with open(metadata_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Generate query embedding
    query_embedding = model.encode([query_text])[0].reshape(1, -1).astype('float32')
    
    # Search
    distances, indices = index.search(query_embedding, k)
    
    # Format results
    results = []
    for i, idx in enumerate(indices[0]):
        if idx < len(data):
            entry = data[idx].copy()
            entry["distance"] = float(distances[0][i])
            results.append(entry)
    
    return results


if __name__ == "__main__":
    # Example code for testing
    from pathlib import Path
    import json
    
    # Load prepared data
    rag_ready_path = processed_dir / "rag_ready_data.json"
    if rag_ready_path.exists():
        with open(rag_ready_path, "r", encoding="utf-8") as f:
            rag_data = json.load(f)
            
        # Generate and store embeddings
        embeddings, _ = generate_embeddings(rag_data)
        if embeddings is not None:
            store_embeddings_faiss(embeddings, rag_data)
            
            # Test query
            results = query_faiss("How to create a dashboard in Tableau?", k=3)
            for i, result in enumerate(results, 1):
                logger.info(f"Result {i}: {result.get('embedding_template', '')[:100]}... (distance: {result['distance']:.4f})")
    else:
        logger.warning(f"No RAG-ready data found at {rag_ready_path}")