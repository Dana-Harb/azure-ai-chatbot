# azure-ai-chatbot
A basic chatbot using Azure OpenAI GPT-4o.


### Explanation of folders:

* **`chatbot/`**:
  Contains the console-based chatbot implementation.
  You can run this locally to test the conversation loop in the terminal.

* **`function_app/`**:
  Contains the Azure Function code (`function_app.py`).
  This is what gets deployed to Azure and runs as an HTTP endpoint.

* **`requirements.txt`**:
  Lists the Python packages required by both the console chatbot and the Azure Function.

* **`host.json`**:
  Global configuration file used by Azure Functions runtime.

---

## Running Locally

### 1. Console Chatbot

You can test the chatbot in your terminal with:

```bash
python chatbot.py
```

Features available locally:

* Welcome message
* User input processing
* AI response generation
* Conversation loop
* Graceful exit (`exit` command)

### 2. Azure Function (local test)

From the project root, run:

```
func start
```

This will start the Azure Functions Core Tools runtime.
You’ll see an endpoint like:

```
http://localhost:7071/api/ChatbotFunction
```

You can send a POST request with JSON:

```json
{
  "user_input": "Hello"
}
```


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



