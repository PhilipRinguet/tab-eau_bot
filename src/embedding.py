from sentence_transformers import SentenceTransformer
import faiss
import os
import json
from pathlib import Path

# Initialize the embedding model
model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')

# Define paths
processed_dir = Path("data/processed")
vector_db_path = processed_dir / "vector_index.faiss"

# Function to load preprocessed data
def load_preprocessed_data():
    """
    Load preprocessed data from the processed directory.

    Returns:
        list: A list of dictionaries containing preprocessed text data.
    """
    data = []
    for file in processed_dir.glob("*.json"):
        with open(file, "r", encoding="utf-8") as f:
            data.extend(json.load(f))
    return data

# Function to generate embeddings
def generate_embeddings(data):
    """
    Generate embeddings for the given text data.

    Args:
        data (list): A list of dictionaries containing text data.

    Returns:
        tuple: A tuple containing the embeddings and metadata.
    """
    texts = [entry["text"] for entry in data]
    embeddings = model.encode(texts, show_progress_bar=True)
    metadata = [{"page_number": entry.get("page_number"), "source_file": entry.get("source_file")} for entry in data]
    return embeddings, metadata

# Function to store embeddings in FAISS with metadata
def store_embeddings_faiss(embeddings, metadata):
    """
    Store embeddings and metadata in a FAISS index.

    Args:
        embeddings (ndarray): The embeddings to store.
        metadata (list): The metadata associated with the embeddings.
    """
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatL2(dimension)
    index.add(embeddings)

    # Save the index
    faiss.write_index(index, str(vector_db_path))

    # Save metadata
    metadata_path = vector_db_path.with_suffix(".json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=4)

    print(f"FAISS index and metadata saved to {vector_db_path} and {metadata_path}")

# Function to query FAISS and retrieve metadata
def query_faiss(query_text, k=5):
    """
    Query the FAISS index and retrieve the nearest neighbors along with their metadata.

    Args:
        query_text (str): The text to query.
        k (int): The number of nearest neighbors to retrieve.

    Returns:
        list: A list of dictionaries containing the metadata of the nearest neighbors.
    """
    # Load the FAISS index
    index = faiss.read_index(str(vector_db_path))

    # Load the metadata
    metadata_path = vector_db_path.with_suffix(".json")
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    # Generate the query embedding
    query_embedding = model.encode([query_text])

    # Perform the search
    distances, indices = index.search(query_embedding, k)

    # Retrieve the metadata for the nearest neighbors
    results = []
    for idx in indices[0]:
        if idx < len(metadata):
            results.append(metadata[idx])

    return results

# Main script
if __name__ == "__main__":
    # Load preprocessed data
    preprocessed_data = load_preprocessed_data()

    # Generate embeddings
    embeddings, metadata = generate_embeddings(preprocessed_data)

    # Store embeddings in FAISS
    store_embeddings_faiss(embeddings, metadata)

    # Example query
    query = "What is Tableau?"
    results = query_faiss(query)
    print("Query Results:", results)