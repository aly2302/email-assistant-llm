# Personalized LLM Email Assistant

**A Context-Aware Email Automation System using Google Gemini & Ontology-Based Retrieval.**

This repository contains the source code for a Bachelor's Final Project in Computer Engineering. The system implements a Retrieval-Augmented Generation (RAG) architecture tailored for hyper-personalized email drafting. It moves beyond generic prompt engineering by utilizing a structured "Personalization Ontology" to enforce stylistic consistency, social awareness, and factual accuracy.

## Project Status & Disclaimer

**Status:** Academic Prototype / Archived

This software was developed for research and demonstration purposes as part of an academic thesis. It is **not** a production-ready application. The codebase is provided "as is" for educational value, code review, and architectural reference.

## System Architecture

The core innovation of this system is its ability to learn and adapt to a user's specific writing style through three distinct components:

### 1. Personalization Ontology
Unlike standard LLM wrappers, this system relies on a JSON-based ontology (`personas2.0.json`) that acts as the user's "digital twin." It structures:
* **Style Profiles:** Definitions of tone, verbosity, and key principles.
* **Interlocutor Profiles:** Social context rules specific to different contacts (e.g., "Always formal with Client X," "Casual with Team Y").
* **Fact Memory:** A persistent store of personal and professional details.

### 2. Hybrid Retrieval Engine (RAG)
To ensure context window efficiency and factual accuracy, the system employs a dual-retrieval strategy before calling the LLM:
* **Semantic Search:** Uses `SentenceTransformers` (`paraphrase-multilingual-MiniLM-L12-v2`) to generate vector embeddings of incoming emails and retrieve contextually relevant memories.
* **Keyword Matching:** Filters knowledge based on direct token overlap to capture specific entities.
* **Rule Injection:** Dynamically injects "Learned Corrections" into the prompt based on similarity scores.

### 3. Mobile "Human-in-the-Loop" Workflow
The system runs a background agent (Celery worker) that proactively drafts replies to incoming emails. To ensure safety and control, it integrates with **Pushover** for real-time mobile management:
* **Instant Notification:** When a draft is ready, a push notification is sent to the user's phone containing a summary and the proposed response.
* **One-Tap Actions:** The notification includes actionable links (`Approve` / `Reject`). Clicking "Approve" instantly sends the email via the Gmail API without opening a laptop.

### 4. Feedback & Learning Loop
The system implements a continuous improvement mechanism. When a user manually edits a generated draft in the dashboard:
1.  The system compares the **AI Generation** vs. **User Correction**.
2.  An inference call (via Gemini) identifies the underlying rule change (e.g., "Prefer direct answers for scheduling").
3.  This new rule is written back to the Ontology, refining future outputs.

## Technical Stack

* **Core Logic:** Python 3.x
* **Web Framework:** Flask
* **LLM Provider:** Google Gemini API (`gemini-2.5-flash-lite`)
* **Vector Embeddings:** PyTorch + SentenceTransformers
* **Task Queue:** Celery + Redis (for background email processing)
* **Mobile Notifications:** Pushover API
* **Database:** SQLite + SQLAlchemy
* **Integrations:** Gmail API (OAuth 2.0)

## Configuration & Prerequisites

**Note:** This application requires active API credentials which are not included in the repository. To run this system locally, you must provide your own keys.

1.  **Google Cloud Project:** Enable the Gmail API and download `client_secret.json` to the root directory.
2.  **Gemini API:** Set the `GEMINI_API_KEY` environment variable.
3.  **Pushover:** Create an application on Pushover.net to get your `PUSHOVER_USER_KEY` and `PUSHOVER_API_TOKEN`.
4.  **Environment Variables:** Create a `.env` file with the following:
    ```bash
    APP_HOST=127.0.0.1
    APP_PORT=5001
    FLASK_DEBUG=True
    FLASK_SECRET_KEY=your_secret_key
    FLASK_BASE_URL=[http://your-public-url.com](http://your-public-url.com)  # Required for Pushover links (e.g., ngrok)
    
    # AI Configuration
    GEMINI_API_KEY=your_gemini_key
    GEMINI_MODEL=gemini-2.5-flash-lite

    # Mobile Notifications
    PUSHOVER_USER_KEY=your_pushover_user_key
    PUSHOVER_API_TOKEN=your_pushover_app_token
    ```
5.  **Redis:** Ensure a Redis server is running locally for Celery tasks.

## Installation

```bash
# Clone the repository
git clone [https://github.com/aly2302/email-assistant-llm.git](https://github.com/aly2302/email-assistant-llm.git)

# Install dependencies
pip install -r requirements.txt

# Run the application
python app.py

# Run the background worker (separate terminal)
celery -A automation.celery_worker.celery worker --loglevel=info
```

Related Publications
This project is the practical implementation of the research presented in: https://www.mdpi.com/1999-5903/17/12/536
