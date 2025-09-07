import os
from openai import AzureOpenAI
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.models import VectorizedQuery

from dotenv import load_dotenv


load_dotenv()


AZURE_OPENAI_ENDPOINT = os.getenv("ENDPOINT_URL")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("DEPLOYMENT_NAME") 
EMBEDDING_MODEL = "text-embedding-3-small"  


SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
SEARCH_INDEX = os.getenv("AZURE_INDEX_NAME")
TOP_K = 3  



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



def retrieve_similar_docs(query: str, top_k: int = TOP_K):
    query_vector = embed_query(query)

    vector_query = VectorizedQuery(
        kind="vector",
        vector=query_vector,
        fields = "text_vector",
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

