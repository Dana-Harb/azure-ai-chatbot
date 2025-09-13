import os
import re
from openai import AzureOpenAI
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SearchField,
    SearchFieldDataType,
    SearchableField,
    SimpleField,
    VectorSearch,
    HnswAlgorithmConfiguration,
    VectorSearchProfile,  # Import the VectorSearchProfile class
)
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.models import VectorizedQuery
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv


load_dotenv()

# -------------------------------
# ENV VARIABLES
# -------------------------------
AZURE_OPENAI_ENDPOINT = os.getenv("ENDPOINT_URL")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("DEPLOYMENT_NAME")
EMBEDDING_MODEL = "text-embedding-3-small"

SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")

# Use env var if set, otherwise default to "document-index"
SEARCH_INDEX = os.getenv("AZURE_INDEX_NAME", "document-index")
TOP_K = 3

DOC_INTELLIGENCE_ENDPOINT = os.getenv("DOC_INTELLIGENCE_ENDPOINT")
DOC_INTELLIGENCE_KEY = os.getenv("DOC_INTELLIGENCE_KEY")

BLOB_CONNECTION_STRING = os.getenv("BLOB_CONNECTION_STRING")
BLOB_CONTAINER = os.getenv("BLOB_CONTAINER_NAME")

# -------------------------------
# CLIENTS
# -------------------------------
doc_client = DocumentIntelligenceClient(
    endpoint=DOC_INTELLIGENCE_ENDPOINT,
    credential=AzureKeyCredential(DOC_INTELLIGENCE_KEY)
)

openai_client = AzureOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_KEY,
    api_version="2025-01-01-preview",
)

search_client = SearchClient(
    endpoint=SEARCH_ENDPOINT,
    index_name=SEARCH_INDEX,
    credential=AzureKeyCredential(SEARCH_KEY)
)

index_client = SearchIndexClient(
    endpoint=SEARCH_ENDPOINT,
    credential=AzureKeyCredential(SEARCH_KEY)
)

blob_service_client = BlobServiceClient.from_connection_string(BLOB_CONNECTION_STRING)
container_client = blob_service_client.get_container_client(BLOB_CONTAINER)

# -------------------------------
# INDEX CREATION
# -------------------------------
def create_search_index(index_name: str):
    """Create the search index if it does not already exist."""
    existing_indexes = [idx.name for idx in index_client.list_indexes()]
    if index_name in existing_indexes:
        print(f"[INFO] Index '{index_name}' already exists. Skipping creation.")
        return

    # Define fields
    fields = [
        SimpleField(name="chunk_id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="title", type=SearchFieldDataType.String, searchable=True),
        SearchableField(name="chunk", type=SearchFieldDataType.String, searchable=True),
        SearchField(
            name="text_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=1536,
            vector_search_profile_name="my-hnsw-profile"  # ✅ new param name
        )
    ]

    # Define vector search (new style)
    vector_search = VectorSearch(
        profiles=[
            VectorSearchProfile(
                name="my-hnsw-profile",  # Profile name
                algorithm_configuration_name="my-hnsw-algorithm"  # Reference algorithm
            )
        ],
        algorithms=[
            HnswAlgorithmConfiguration(
                name="my-hnsw-algorithm",  # Algorithm name
            )
        ]
    )

    # Create the index object
    index = SearchIndex(
        name=index_name,
        fields=fields,
        vector_search=vector_search
    )

    print(f"[INFO] Creating index '{index_name}'...")
    index_client.create_index(index)
    print(f"[SUCCESS] Index '{index_name}' created!")



# -------------------------------
# EMBEDDINGS
# -------------------------------
def embed_query(query: str):
    resp = openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query
    )
    return resp.data[0].embedding

# -------------------------------
# BLOB STORAGE STREAMING & INDEXING
# -------------------------------
def make_safe_id(file_name: str, chunk_idx: int) -> str:
    # Replace invalid characters with "_"
    clean = re.sub(r'[^A-Za-z0-9_\-=:]', '_', file_name)

    # Remove leading underscores
    clean = clean.lstrip("_")

    # Ensure it’s not empty after cleaning
    if not clean:
        clean = "doc"

    # Always prepend a prefix so it never starts invalid
    return f"doc_{clean}_chunk_{chunk_idx}"


def make_safe_id(file_name: str, chunk_idx: int) -> str:
    """Generate a safe document key for Azure Cognitive Search."""
    # Replace invalid characters with "_"
    clean = re.sub(r'[^A-Za-z0-9_\-=:]', '_', file_name)
    # Remove leading underscores
    clean = clean.lstrip("_")
    # Ensure it's not empty
    if not clean:
        clean = "doc"
    # Prepend safe prefix
    return f"doc_{clean}_chunk_{chunk_idx}"


def index_all_blobs_stream(chunk_size: int = 400):
    """
    Stream all blobs from Azure Blob Storage, extract text using Document Intelligence,
    and index them into Azure Cognitive Search only if not already indexed.
    """
    print("[INFO] Indexing all documents from Blob Storage (if not already indexed)...")

    # Ensure index exists
    create_search_index(SEARCH_INDEX)

    for blob in container_client.list_blobs():
        blob_name = blob.name

        # Check if file is already indexed
        results = search_client.search(
            search_text=f"title:{blob_name}",
            select=["title"],
            top=1
        )
        if any(True for _ in results):
            print(f"[SKIP] Already indexed: {blob_name}")
            continue

        # Download blob
        blob_client = container_client.get_blob_client(blob)
        blob_data = blob_client.download_blob().readall()
        ext = os.path.splitext(blob_name)[1].lower()

        # Extract text
        if ext == ".txt":
            text = blob_data.decode("utf-8")
        elif ext in [".pdf", ".png", ".jpg", ".jpeg", ".tiff"]:
            poller = doc_client.begin_analyze_document("prebuilt-read", body=blob_data)
            result = poller.result()
            text = "\n".join([line.content for page in result.pages for line in page.lines])
        else:
            print(f"[SKIP] Unsupported file type: {blob_name}")
            continue

        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            print(f"[SKIP] No text extracted from {blob_name}")
            continue

        # Split into chunks and index
        words = text.split()
        for i in range(0, len(words), chunk_size):
            chunk = " ".join(words[i:i + chunk_size])
            chunk_id = make_safe_id(blob_name, i)
            vector = embed_query(chunk)

            search_client.merge_or_upload_documents(documents=[{
                "title": blob_name,
                "chunk_id": chunk_id,
                "chunk": chunk,
                "text_vector": vector
            }])
            print(f"[INDEXED] {chunk_id} from {blob_name}")




# -------------------------------
# RETRIEVE & GENERATE RESPONSE
# -------------------------------
def retrieve_similar_docs(query: str, top_k: int = TOP_K):
    query_vector = embed_query(query)
    vector_query = VectorizedQuery(
        kind="vector",
        vector=query_vector,
        fields="text_vector",
        k_nearest_neighbors=top_k
    )
    results = search_client.search(
        search_text=None,
        vector_queries=[vector_query],
        select=["title", "chunk", "chunk_id"]
    )
    docs = [{"title": r["title"], "chunk": r["chunk"], "chunk_id": r["chunk_id"]} for r in results]
    return docs

def generate_response_with_context(query: str, top_k: int = TOP_K):
    docs = retrieve_similar_docs(query, top_k=top_k)

    context_text = ""
    for d in docs:
        context_text += f"\nTitle: {d['title']}\nContent: {d['chunk']}\n"

    system_prompt = (
        "You are an expert barista with deep knowledge of coffee, brewing methods, beans, and recipes. "
        "You have access to reference documents which may contain information relevant to the user's query. "
        "Your goal is to provide the best answer possible: "
        "- If the documents contain relevant information, use it. "
        "- Supplement with your own knowledge if it adds value. "
        "- Cite sources used, either from the documents or external knowledge. "
        "- Provide references if the information comes from the documents. "
        "- Provide a link to you knowlede if a relaible resource is available"
        "- Answer in the same language as the query (Arabic or English). "
        "- Do not fabricate references."
    )


    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": f"""
Reference documents (use them if relevant):

{context_text}

Question: {query}
Answer:"""
        }
    ]

    completion = openai_client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=messages,
        max_tokens=500,
        temperature=0.7
    )

    answer_text = completion.choices[0].message.content.strip()

    # Only include references if they were cited
    used_references = [d["title"] for d in docs if d["title"] in answer_text]

    return {"answer": answer_text, "references": used_references}


