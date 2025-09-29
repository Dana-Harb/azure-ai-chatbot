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
    VectorSearchProfile, 
)
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.models import VectorizedQuery
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.storage.blob import BlobServiceClient
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()

# --- Load non-sensitive values from .env ---
KEYVAULT_NAME = os.getenv("KEYVAULT_NAME")  
AZURE_OPENAI_ENDPOINT = os.getenv("ENDPOINT_URL")
AZURE_OPENAI_DEPLOYMENT = os.getenv("DEPLOYMENT_NAME")
EMBEDDING_MODEL = "text-embedding-3-large"
SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
SEARCH_INDEX = os.getenv("AZURE_INDEX_NAME", "document-index")
TOP_K = 3
BLOB_CONTAINER = os.getenv("BLOB_CONTAINER_NAME")
DOC_INTELLIGENCE_ENDPOINT = os.getenv("DOC_INTELLIGENCE_ENDPOINT")  

# --- Cache for secrets and clients ---
_openai_key = None
_search_key = None
_doc_intelligence_key = None
_blob_connection_string = None
_openai_client = None
_search_client = None
_index_client = None
_doc_client = None
_blob_service_client = None
_container_client = None

def get_openai_key():
    global _openai_key
    if _openai_key is None:
        # Try environment variable first
        _openai_key = os.getenv("AZURE_OPENAI_API_KEY")
        if _openai_key:
            print("Using OpenAI key from environment variable")
            return _openai_key
            
        print("OpenAI key not found in environment, trying Key Vault...")
        
        # Fall back to Key Vault
        try:
            keyvault_url = f"https://{KEYVAULT_NAME}.vault.azure.net/"
            credential = DefaultAzureCredential()
            secret_client = SecretClient(vault_url=keyvault_url, credential=credential)
            _openai_key = secret_client.get_secret("AZURE-OPENAI-KEY").value
            print("Successfully fetched OpenAI key from Key Vault")
        except Exception as e:
            print(f"Error fetching OpenAI key from Key Vault: {e}")
            print("Make sure AZURE_OPENAI_KEY is set in local.settings.json")
            raise ValueError("Could not get OpenAI key from environment or Key Vault")
    return _openai_key

def get_search_key():
    global _search_key
    if _search_key is None:
        # Try environment variable first
        _search_key = os.getenv("AZURE_SEARCH_KEY")
        if _search_key:
            print("Using Search key from environment variable")
            return _search_key
            
        print("Search key not found in environment, trying Key Vault...")
        
        try:
            keyvault_url = f"https://{KEYVAULT_NAME}.vault.azure.net/"
            credential = DefaultAzureCredential()
            secret_client = SecretClient(vault_url=keyvault_url, credential=credential)
            _search_key = secret_client.get_secret("AZURE-SEARCH-KEY").value
            print("Successfully fetched Search key from Key Vault")
        except Exception as e:
            print(f"Error fetching Search key from Key Vault: {e}")
            print("Make sure AZURE_SEARCH_KEY is set in local.settings.json")
            raise ValueError("Could not get Search key from environment or Key Vault")
    return _search_key

def get_doc_intelligence_key():
    global _doc_intelligence_key
    if _doc_intelligence_key is None:
        # Try environment variable first
        _doc_intelligence_key = os.getenv("DOC_INTELLIGENCE_KEY")
        if _doc_intelligence_key:
            print("Using Document Intelligence key from environment variable")
            return _doc_intelligence_key
            
        print("Document Intelligence key not found in environment, trying Key Vault...")
        
        try:
            keyvault_url = f"https://{KEYVAULT_NAME}.vault.azure.net/"
            credential = DefaultAzureCredential()
            secret_client = SecretClient(vault_url=keyvault_url, credential=credential)
            _doc_intelligence_key = secret_client.get_secret("DOC-INTELLIGENCE-KEY").value
            print("Successfully fetched Document Intelligence key from Key Vault")
        except Exception as e:
            print(f"Error fetching Document Intelligence key from Key Vault: {e}")
            print("Make sure DOC_INTELLIGENCE_KEY is set in local.settings.json")
            raise ValueError("Could not get Document Intelligence key from environment or Key Vault")
    return _doc_intelligence_key

def get_blob_connection_string():
    global _blob_connection_string
    if _blob_connection_string is None:
        # Try environment variable first
        _blob_connection_string = os.getenv("BLOB_CONNECTION_STRING")
        if _blob_connection_string:
            print("Using Blob connection string from environment variable")
            return _blob_connection_string
            
        print("Blob connection string not found in environment, trying Key Vault...")
        
        try:
            keyvault_url = f"https://{KEYVAULT_NAME}.vault.azure.net/"
            credential = DefaultAzureCredential()
            secret_client = SecretClient(vault_url=keyvault_url, credential=credential)
            _blob_connection_string = secret_client.get_secret("BLOB-CONNECTION-STRING").value
            print("Successfully fetched Blob connection string from Key Vault")
        except Exception as e:
            print(f"Error fetching Blob connection string from Key Vault: {e}")
            print("Make sure BLOB_CONNECTION_STRING is set in local.settings.json")
            raise ValueError("Could not get Blob connection string from environment or Key Vault")
    return _blob_connection_string

def get_openai_client():
    global _openai_client
    if _openai_client is None:
        _openai_client = AzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=get_openai_key(),
            api_version="2025-01-01-preview",
        )
    return _openai_client

def get_search_client():
    global _search_client
    if _search_client is None:
        _search_client = SearchClient(
            endpoint=SEARCH_ENDPOINT,
            index_name=SEARCH_INDEX,
            credential=AzureKeyCredential(get_search_key())
        )
    return _search_client

def get_index_client():
    global _index_client
    if _index_client is None:
        _index_client = SearchIndexClient(
            endpoint=SEARCH_ENDPOINT,
            credential=AzureKeyCredential(get_search_key())
        )
    return _index_client

def get_doc_client():
    global _doc_client
    if _doc_client is None:
        _doc_client = DocumentIntelligenceClient(
            endpoint=DOC_INTELLIGENCE_ENDPOINT,
            credential=AzureKeyCredential(get_doc_intelligence_key())
        )
    return _doc_client

def get_blob_service_client():
    global _blob_service_client
    if _blob_service_client is None:
        _blob_service_client = BlobServiceClient.from_connection_string(get_blob_connection_string())
    return _blob_service_client

def get_container_client():
    global _container_client
    if _container_client is None:
        _container_client = get_blob_service_client().get_container_client(BLOB_CONTAINER)
    return _container_client

# --- Utility functions ---

def create_search_index(index_name: str):
    existing_indexes = [idx.name for idx in get_index_client().list_indexes()]
    if index_name in existing_indexes:
        print(f"[INFO] Index '{index_name}' already exists. Skipping creation.")
        return

    fields = [
        SimpleField(name="chunk_id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="title", type=SearchFieldDataType.String, searchable=True),
        SearchableField(name="chunk", type=SearchFieldDataType.String, searchable=True),
        SearchField(
            name="text_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=3072,
            vector_search_profile_name="my-hnsw-profile"
        )
    ]

    vector_search = VectorSearch(
        profiles=[
            VectorSearchProfile(
                name="my-hnsw-profile",
                algorithm_configuration_name="my-hnsw-algorithm"
            )
        ],
        algorithms=[
            HnswAlgorithmConfiguration(
                name="my-hnsw-algorithm",
            )
        ]
    )

    index = SearchIndex(
        name=index_name,
        fields=fields,
        vector_search=vector_search
    )

    print(f"[INFO] Creating index '{index_name}'...")
    get_index_client().create_index(index)
    print(f"[SUCCESS] Index '{index_name}' created!")

def embed_query(query: str):
    resp = get_openai_client().embeddings.create(
        model=EMBEDDING_MODEL,
        input=query
    )
    return resp.data[0].embedding

def make_safe_id(file_name: str, chunk_idx: int) -> str:
    clean = re.sub(r'[^A-Za-z0-9_\-=:]', '_', file_name)
    clean = clean.lstrip("_")
    if not clean:
        clean = "doc"
    return f"doc_{clean}_chunk_{chunk_idx}"

def index_all_blobs_stream(chunk_size: int = 400):
    print("[INFO] Indexing all documents from Blob Storage (if not already indexed)...")
    create_search_index(SEARCH_INDEX)

    for blob in get_container_client().list_blobs():
        blob_name = blob.name

        results = get_search_client().search(
            search_text=f"title:{blob_name}",
            select=["title"],
            top=1
        )
        if any(True for _ in results):
            print(f"[SKIP] Already indexed: {blob_name}")
            continue

        blob_client = get_container_client().get_blob_client(blob)
        blob_data = blob_client.download_blob().readall()
        ext = os.path.splitext(blob_name)[1].lower()

        if ext == ".txt":
            text = blob_data.decode("utf-8")
        elif ext in [".pdf", ".png", ".jpg", ".jpeg", ".tiff"]:
            poller = get_doc_client().begin_analyze_document("prebuilt-read", body=blob_data)
            result = poller.result()
            text = "\n".join([line.content for page in result.pages for line in page.lines])
        else:
            print(f"[SKIP] Unsupported file type: {blob_name}")
            continue

        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            print(f"[SKIP] No text extracted from {blob_name}")
            continue

        words = text.split()
        for i in range(0, len(words), chunk_size):
            chunk = " ".join(words[i:i + chunk_size])
            chunk_id = make_safe_id(blob_name, i)
            vector = embed_query(chunk)

            get_search_client().merge_or_upload_documents(documents=[{
                "title": blob_name,
                "chunk_id": chunk_id,
                "chunk": chunk,
                "text_vector": vector
            }])
            print(f"[INDEXED] {chunk_id} from {blob_name}")

def retrieve_similar_docs(query: str, top_k: int = TOP_K):
    query_vector = embed_query(query)
    vector_query = VectorizedQuery(
        kind="vector",
        vector=query_vector,
        fields="text_vector",
        k_nearest_neighbors=top_k
    )
    results = get_search_client().search(
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
    "Your goal is to provide concise, helpful answers: "
    "- Keep responses brief and to the point (2-3 sentences maximum)"
    "- If the documents contain relevant information, use it briefly. "
    "- Supplement with your own knowledge if it adds value. "
    "- Cite sources used, either from the documents or external knowledge. "
    "- Provide references if the information comes from the documents. "
    "- Provide a link to reliable resources if available. "
    "- Answer in the same language as the query (Arabic or English). "
    "- Do not fabricate references."
    "- Be concise and avoid unnecessary details."
)

    messages = [
            {
        "role": "user",
        "content": f"""
    Reference documents (use them if relevant):

    {context_text}

    Question: {query}

    Instructions: Please provide a concise answer (2-3 sentences maximum). Focus on the key information.

    Answer:"""
    }
    ]

    completion = get_openai_client().chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=messages,
        max_tokens=150,
        temperature=0.7
    )

    answer_text = completion.choices[0].message.content.strip()
    used_references = [d["title"] for d in docs if d["title"] in answer_text]

    return {"answer": answer_text, "references": used_references}