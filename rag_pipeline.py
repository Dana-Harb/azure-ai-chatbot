import os
import re
from openai import AzureOpenAI
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.models import VectorizedQuery
from azure.ai.formrecognizer import DocumentAnalysisClient
from dotenv import load_dotenv

load_dotenv()

AZURE_OPENAI_ENDPOINT = os.getenv("ENDPOINT_URL")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("DEPLOYMENT_NAME") 
EMBEDDING_MODEL = "text-embedding-3-small"  

SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
SEARCH_INDEX = os.getenv("AZURE_INDEX_NAME")
TOP_K = 15

FORM_RECOGNIZER_ENDPOINT = os.getenv("FORM_RECOGNIZER_ENDPOINT") 
FORM_RECOGNIZER_KEY = os.getenv("FORM_RECOGNIZER_KEY")           

doc_client = DocumentAnalysisClient(
    endpoint=FORM_RECOGNIZER_ENDPOINT,
    credential=AzureKeyCredential(FORM_RECOGNIZER_KEY)
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

def embed_query(query: str):
    resp = openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query
    )
    return resp.data[0].embedding

def extract_text_from_file(file_path: str):
    ext = os.path.splitext(file_path)[1].lower()
    if ext in [".pdf", ".txt"]:
        if ext == ".txt":
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
        else:
            with open(file_path, "rb") as f:
                poller = doc_client.begin_analyze_document("prebuilt-read", document=f)
                result = poller.result()
                text = "\n".join([line.content for page in result.pages for line in page.lines])
    elif ext in [".png", ".jpg", ".jpeg", ".tiff"]:
        with open(file_path, "rb") as f:
            poller = doc_client.begin_analyze_document("prebuilt-read", document=f)
            result = poller.result()
            text = "\n".join([line.content for page in result.pages for line in page.lines])
    else:
        text = ""
    # Clean extracted text
    text = re.sub(r"\s+", " ", text).strip()
    return text

def process_and_index_doc(file_path: str, chunk_size: int = 400):
    title = os.path.basename(file_path)
    safe_title = re.sub(r'[^A-Za-z0-9_\-=:]', '_', title)
    text = extract_text_from_file(file_path)
    if not text:
        print(f"[SKIP] No text extracted from {title}")
        return
    words = text.split()
    if not words:
        print(f"[SKIP] No valid words in {title}")
        return
    for i in range(0, len(words), chunk_size):
        chunk = " ".join(words[i:i + chunk_size])
        chunk_id = f"{safe_title}_chunk_{i}"
        vector = embed_query(chunk)
        search_client.upload_documents(documents=[{
            "title": title,
            "chunk_id": chunk_id,
            "chunk": chunk,
            "text_vector": vector
        }])
        print(f"[INDEXED] {chunk_id} from {title}")

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
        select=["title", "chunk", "chunk_id"],
    )
    docs = []
    for r in results:
        docs.append({
            "title": r["title"],
            "chunk": r["chunk"],
            "chunk_id": r["chunk_id"],
        })
    return docs

def generate_response_with_context(query: str, top_k: int = TOP_K):
    docs = retrieve_similar_docs(query, top_k=top_k)
    context_text = ""
    references = []
    for d in docs:
        context_text += f"\nTitle: {d['title']}\nContent: {d['chunk']}\n"
        references.append(d["title"])
    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert barista with deep knowledge of coffee. "
                "Answer questions related to coffee, brewing, beans, or recipes. "
                "If the question is unrelated to coffee, politely decline to answer."
            )
        },
        {
            "role": "user",
            "content": f"""
You have access to the following reference documents. Use them when they contain relevant information, but you may also draw on your general knowledge as a coffee expert if needed.

Documents:
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
    answer = completion.choices[0].message.content.strip()
    return {"answer": answer, "references": references}
