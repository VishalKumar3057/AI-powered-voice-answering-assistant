# AI-powered Voice Answering Assistant for Medical Centers

A high-performance, fully asynchronous voice AI system designed to handle real-time medical clinic inquiries and appointment booking. This solution bridges the gap between traditional IVR systems and human receptionists using cutting-edge Generative AI.

## 🚀 The Problem & Solution

### The Problem
Medical clinics often face high call volumes, leading to long wait times, missed appointment opportunities, and overwhelmed administrative staff. Standard chatbots lack the natural feel of a phone conversation, and traditional automated systems are frustratingly linear.

### The Solution
Our assistant provides a **voice-first** conversational experience. It handles real-time audio streams via WebSockets, transcribes speech instantly, understands complex medical intents, and responds with a natural, synthesized human voice—all with sub-second latency.

---

## 🛠️ Technical Architecture

The system is built on a non-blocking, event-driven framework using **FastAPI** and **Python asyncio**.

### 🧱 Core Components

1.  **Telephony Layer (Twilio)**:
    *   Acts as the entry point for all patient calls.
    *   Uses **Twilio Media Streams** to fork binary audio (`mulaw`, `8000Hz`) via a WebSocket.
    *   **Graceful Termination**: Implements a 5-second cancellable grace period after bookings, allowing patients to ask follow-up questions.

2.  **Speech Engine (Deepgram)**:
    *   **STT (Speech-to-Text)**: Uses the `nova-2` model for ultra-low latency transcription.
    *   **TTS (Text-to-Speech)**: Uses Deepgram's "Speak" API (`aura-asteria-en`) with a persistent HTTP connection to minimize latency.
    *   **Endpointing**: Optimized at **800ms** for a natural conversational pace.

3.  **Conversational Brain (OpenAI)**:
    *   Utilizes **GPT-4o-mini** for high-speed reasoning and intent extraction.
    *   **Non-blocking Pipeline**: AI processing is offloaded to background tasks, ensuring the listener remains responsive.
    *   **User Barge-in**: Supports immediate interruption; the AI stops speaking when the user starts a new turn.

---

## 📋 Features

*   ✅ **Real-time Voice Conversation**: Truly asynchronous pipeline (STT -> LLM -> TTS).
*   ✅ **User Barge-in (Interruption)**: Natural flow where the user can interrupt the assistant at any time.
*   ✅ **Appointment Management**: Automated checking and booking logic with full data extraction.
*   ✅ **Data Persistence**: Confirmed bookings are saved to `bookings.json` for easy clinic access.
*   ✅ **Professional Persona**: Polite closing with an offer for further assistance before termination.
*   ✅ **Smart Disconnection**: Intent-based hangup (e.g., "No thanks", "Goodbye") or automatic termination after a grace period.

---

## ⚙️ Setup & Installation

### 1. Prerequisites
*   Python 3.10+
*   [Ngrok](https://ngrok.com/) (for local testing)
*   [Twilio Account](https://www.twilio.com/) with a phone number.

### 2. Required API Keys
Create a `.env` file in the root directory:
```env
DEEPGRAM_API_KEY=your_deepgram_key
OPENAI_API_KEY=your_openai_key
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
PORT=5000
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Running the Server Locally
```bash
# Start your local server
uvicorn main:app --reload --port 5000

# In a new terminal, expose your server
ngrok http 5000
```

### 5. Twilio Configuration
1.  Copy your `ngrok` URL (e.g., `https://xxxx.ngrok-free.app`).
2.  Go to your Twilio Console -> Phone Numbers -> Active Numbers.
3.  Set the "A call comes in" Webhook to: `https://your-ngrok-url/incoming` (Method: POST).

---

## 📁 Project Structure

*   `main.py`: FastAPI application and WebSocket orchestration (Background AI tasks).
*   `services.py`: LLM reasoning, TTS synthesis, and Booking logic.
*   `config.py`: Environment variable and API configuration.
*   `bookings.json`: Local storage for confirmed patient appointments.

---

## 🛡️ Compliance & Security
*   **GDPR/Swiss Ready**: Supports data residency in Swiss-based cloud clusters.
*   **Data Minimization**: Voice data is processed in real-time and not stored for training.
*   **Encryption**: All WebSocket communication is secured via TLS 1.3.

---
**Lead Engineer:** Vishal Kumar
© 2026 AI Voice Solutions
