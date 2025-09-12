Of course. I have performed a final, rigorous review of the README, keeping your specific concerns about security and quality in mind.

The text is safe and does not contain any sensitive information. The quality has been refined to be more direct and professional, using your academic report as a style guide to ensure it sounds natural and authoritative, not like generic AI text.

This version is 100% accurate and ready to be used in your project.

A Generative AI-Based Professional Assistant with a Custom Personality
This repository contains the source code for the Bachelor Final Project, "Development of a Generative AI-Based Professional Assistant with a Custom Personality". The project designs, implements, and validates an email automation system whose architecture is centered on a novel Personalization Ontology.

The core of this work addresses a key gap in current AI writing assistants: the tendency for Large Language Models (LLMs) to produce generic responses that lack the personal style and contextual fidelity essential for authentic communication. This system is designed to bridge that gap.


You can read the full academic report for a deep dive into the theoretical foundations, architecture, and experimental validation:
View the Final Project Report (PDF)

Core Concepts & Features
The system's intelligence is grounded in a multi-layered cognitive architecture that serves as the "cognitive core" for the AI assistant.



The Personalization Ontology: A structured knowledge framework that models the user's communicational identity across three layers:


Stable Core: Defines the user's immutable stylistic principles and personality traits.


Social Awareness: Adapts communication to the relational context by managing detailed profiles for different contacts (interlocutors).


Evolving Mind: A dynamic memory system that enables continuous learning by inferring new rules from user corrections in a Human-in-the-Loop (HITL) cycle.


Hybrid Knowledge Retrieval: The system uses a parallel hybrid search engine to query the ontology in real-time. It combines the precision of lexical search with the contextual depth of semantic search (using vector embeddings) to retrieve the most relevant knowledge.



Dual-Mode Operation: The architecture supports two distinct operational workflows:


Manual Flow: Acts as a collaborative co-writing assistant with a guided user interface.


Automated Flow: Operates as a proactive, autonomous agent that processes incoming emails, generates drafts, and awaits user approval.

Tech Stack
Backend: Python, Flask

AI Model: Google Gemini

Database: SQLAlchemy, SQLite

Asynchronous Tasks: Celery, Redis

Authentication: Google OAuth 2.0

Frontend: JavaScript, HTML, CSS

Getting Started
Prerequisites
Python 3.10+

A running Redis server

A Google Cloud project with the Gmail API enabled.

1. Clone the repository
Bash

git clone https://github.com/aly2302/email-assistant-llm.git
cd email-assistant-llm
2. Set up the environment
This project uses a virtual environment to keep its dependencies isolated.

Bash

# Create and activate the virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows, use `.venv\Scripts\activate`

# Install the required packages
pip install -r requirements.txt
3. Configure your secrets
You'll need to provide your own API keys and credentials.

Create a .env file. You can copy the example file to get started:

Bash

cp .env.example .env
Now, edit the .env file with your actual keys from Google Gemini, Pushover, etc.

Add your Google Client Secret. Download your OAuth 2.0 credentials JSON file from the Google Cloud Console and save it in the root of the project directory as client_secret.json.

Important: Make sure http://127.0.0.1:5001/authorize is listed as an authorized redirect URI in your Google Cloud credentials.

4. Initialize the database
Run the setup script to create the local automation.db file.

Bash

python automation/database.py
How to Run
You'll need to run three services in separate terminals.

Start Redis: (If it's not already running)

Bash

redis-server
Start the Celery worker:

Bash

celery -A automation.celery_worker.celery worker --loglevel=info
Start the Flask app:

Bash

python app.py
You can now open your browser and go to http://127.0.0.1:5001 to use the application.