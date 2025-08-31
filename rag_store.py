import os
import pdfplumber
import pandas as pd
from azure.cosmos import CosmosClient
from azure.search.documents import SearchClient
from azure.search.documents.models import QueryType
from azure.core.credentials import AzureKeyCredential

COSMOS_URI = os.getenv("COSMOS_URI")
COSMOS_KEY = os.getenv("COSMOS_KEY")
COSMOS_DB_NAME = os.getenv("COSMOS_DB_NAME")
COSMOS_DOCS_CONTAINER = os.getenv("COSMOS_DOCS_CONTAINER")

COGNITIVE_SEARCH_ENDPOINT = os.getenv("COGNITIVE_SEARCH_ENDPOINT")
COGNITIVE_SEARCH_KEY = os.getenv("COGNITIVE_SEARCH_KEY")
COGNITIVE_SEARCH_INDEX = os.getenv("COGNITIVE_SEARCH_INDEX")

cosmos_client = CosmosClient(COSMOS_URI, COSMOS_KEY)
database = cosmos_client.get_database_client(COSMOS_DB_NAME)
docs_container = database.get_container_client(COSMOS_DOCS_CONTAINER)

search_client = None
if COGNITIVE_SEARCH_ENDPOINT and COGNITIVE_SEARCH_KEY and COGNITIVE_SEARCH_INDEX:
    search_client = SearchClient(
        endpoint=COGNITIVE_SEARCH_ENDPOINT,
        index_name=COGNITIVE_SEARCH_INDEX,
        credential=AzureKeyCredential(COGNITIVE_SEARCH_KEY)
    )

def read_file(file_path):
    if file_path.endswith(".txt"):
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    elif file_path.endswith(".pdf"):
        text = ""
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text += page.extract_text() + "\n"
        return text
    elif file_path.endswith(".csv"):
        df = pd.read_csv(file_path)
        if 'content' not in df.columns:
            raise ValueError("CSV must have a 'content' column")
        return "\n".join(df['content'].astype(str).tolist())
    else:
        raise ValueError("Unsupported file type")

def upload_document(file_path, doc_id, title="", topic="General"):
    content = read_file(file_path)
    doc = {
        "id": doc_id,
        "title": title,
        "content": content,
        "topic": topic
    }
    docs_container.upsert_item(doc)
    return doc

def search_documents(query, top_k=3):
    if search_client:
        results = search_client.search(
            search_text=query,
            top=top_k,
            include_total_count=True,
            query_type=QueryType.SIMPLE
        )
        return [{"content": r["content"], "title": r.get("title", "")} for r in results]
    else:
        # fallback: simple cosine similarity could be implemented if embeddings exist
        docs = list(docs_container.read_all_items())
        return docs[:top_k]  # naive top_k return
