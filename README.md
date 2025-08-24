# azure-ai-chatbot
A basic chatbot using Azure OpenAI GPT-4o.

Key features: Welcome message, Conversation flow with AI, Exit/quit commands


### ** Setup Instructions (Local)**

1. Clone the repository:

```
git clone https://github.com/Dana-Harb/azure-ai-chatbot.git
cd azure-ai-chatbot
```

2. Create a virtual environment:

```
python -m venv venv
venv\Scripts\activate   # Windows
# source venv/bin/activate  # macOS/Linux
```

3. Set environment variables locally (or create `.env` for testing):

```
$env:ENDPOINT_URL="https://your-resource.openai.azure.com/"
$env:DEPLOYMENT_NAME="gpt-4o"
$env:AZURE_OPENAI_API_KEY="your_api_key_here"
```

4. Run the chatbot locally:

```
python chatbot.py
```

---

### **. API Configuration**

* Chatbot uses Azure OpenAI GPT-4o via **Azure endpoint** and **API key**.
* Required environment variables:

  * `ENDPOINT_URL` → your Azure OpenAI resource URL
  * `DEPLOYMENT_NAME` → GPT-4o deployment name
  * `AZURE_OPENAI_API_KEY` → API key

---

### **. Usage Examples**

**CLI example:**

```
You: Hello
Chatbot: Hi! How can I help you today?
You: How are you?
Chatbot: I’m an AI, so I don’t have feelings, but I’m ready to assist you!
You: exit
Chatbot: Goodbye! Have a great day! 👋
```

<img width="1346" height="647" alt="image" src="https://github.com/user-attachments/assets/b3aec4fd-23cb-467e-8e49-17e137f7bd46" />

<img width="1200" height="570" alt="image" src="https://github.com/user-attachments/assets/6d088214-4eaa-42a3-8f6c-29403dcd81df" />



