import uvicorn
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from fastapi.websockets import WebSocketDisconnect
import json
import asyncio
import base64
import traceback
from deepgram import AsyncDeepgramClient
from config import Config
from services import LLMService, TTSService
from twilio.rest import Client

app = FastAPI()
llm_service = LLMService()
tts_service = TTSService()
twilio_client = Client(Config.TWILIO_ACCOUNT_SID, Config.TWILIO_AUTH_TOKEN)

# In-memory storage for active call contexts
# Key: streamSid, Value: list of message dictionaries
call_contexts = {}

@app.get("/")
async def get():
    return HTMLResponse(content="<h1>HealthCenter One Voice Assistant</h1><p>Server is running.</p>")


@app.post("/")
async def post_root(request: Request):
    """
    Handles POST requests to the root endpoint and returns valid TwiML for Twilio.
    """
    response = f"""
    <Response>
        <Say>Welcome to HealthCenter One administrative services. How may I assist you with your appointment today?</Say>
        <Connect>
            <Stream url=\"wss://{request.url.hostname}/ws/call\" />
        </Connect>
    </Response>
    """
    return HTMLResponse(content=response, media_type="application/xml")

@app.post("/incoming")
async def incoming_call(request: Request):
    """
    Twilio Webhook URL. Returns TwiML to connect the call to the Media Stream.
    """
    response = f"""
    <Response>
        <Say>Welcome to HealthCenter One administrative services. How may I assist you with your appointment today?</Say>
        <Connect>
            <Stream url="wss://{request.url.hostname}/ws/call" />
        </Connect>
    </Response>
    """
    return HTMLResponse(content=response, media_type="application/xml")

@app.websocket("/ws/call")
async def websocket_endpoint(websocket: WebSocket):
    """
    Handles the real-time media stream from Twilio using a fully async pipeline.
    """
    await websocket.accept()
    print("WebSocket connected")
    
    deepgram = AsyncDeepgramClient(api_key=Config.DEEPGRAM_API_KEY)
    
    dg_options = {
        "model": "nova-2",
        "language": "en-US",
        "smart_format": "true",
        "encoding": "mulaw",
        "sample_rate": "8000",
        "interim_results": "true",
        "utterance_end_ms": "1000",
        "vad_events": "true",
        "endpointing": "800"
    }

    stream_sid = None
    call_sid = None
    hangup_task = None # To manage the 5-second grace period
    ai_task = None     # To manage the AI response generation
    
    async def process_ai_response(sentence: str, current_stream_sid: str):
        """Processes the LLM and TTS in a non-blocking background task."""
        nonlocal hangup_task, call_sid
        total_audio_bytes = 0
        try:
            # Initialize context if missing
            if current_stream_sid not in call_contexts:
                call_contexts[current_stream_sid] = [
                    {"role": "system", "content": """You are a professional medical administrative assistant for HealthCenter One. Your objective is to manage patient inquiries and finalize bookings.

STRICT DATA EXTRACTION RULES:
1. FULL NAME: You must extract the patient's FULL NAME (First and Last). If they say only "Vishal", ASK for their last name. DO NOT use words like "Yes", "Hello", or "Okay" as a name.
2. DETAILS: You need a Date, a Time, and a Reason for the visit.
3. CONFIRMATION: Only call the 'book_appointment' tool AFTER you have all 3 items and the FULL NAME. 
4. CLOSING: After confirming a booking, ALWAYS ask if there is anything else you can help with (e.g., "Is there anything else I can assist you with today?").
5. TERMINATION: If the user says "No", "Goodbye", "No thanks", or indicates they are finished, use the 'terminate_call' tool and give a final farewell.
6. CONCISENESS: Maintain a formal, helpful tone but keep responses very concise for voice interaction."""}
                ]
            
            call_contexts[current_stream_sid].append({"role": "user", "content": sentence})
            
            full_ai_response = ""
            sentence_buffer = ""
            
            async for chunk in llm_service.get_response(call_contexts[current_stream_sid]):
                full_ai_response += chunk
                sentence_buffer += chunk
                
                # Check for sentence boundaries for lower latency TTS
                if any(punct in sentence_buffer for punct in [".", "!", "?", "\n"]):
                    import re
                    sentences = re.split(r'(?<=[.!?\n])\s*', sentence_buffer)
                    for i in range(len(sentences) - 1):
                        segment = sentences[i].strip()
                        if segment:
                            print(f"AI (Streaming Segment): {segment}")
                            audio_chunk = await tts_service.generate_audio(segment)
                            if audio_chunk:
                                total_audio_bytes += len(audio_chunk)
                                base64_audio = base64.b64encode(audio_chunk).decode('utf-8')
                                audio_delta = {
                                    "event": "media",
                                    "streamSid": current_stream_sid,
                                    "media": {"payload": base64_audio}
                                }
                                await websocket.send_text(json.dumps(audio_delta))
                    sentence_buffer = sentences[-1]

            # Final flush
            if sentence_buffer.strip():
                segment = sentence_buffer.strip()
                print(f"AI (Streaming Final): {segment}")
                audio_chunk = await tts_service.generate_audio(segment)
                if audio_chunk:
                    total_audio_bytes += len(audio_chunk)
                    base64_audio = base64.b64encode(audio_chunk).decode('utf-8')
                    audio_delta = {
                        "event": "media",
                        "streamSid": current_stream_sid,
                        "media": {"payload": base64_audio}
                    }
                    await websocket.send_text(json.dumps(audio_delta))

            print(f"AI (Full): {full_ai_response}")
            call_contexts[current_stream_sid].append({"role": "assistant", "content": full_ai_response})
            
            # Schedule Auto-Hangup if booking or termination was detected
            if llm_service.booking_flag or llm_service.terminate_flag:
                async def delayed_hangup(sid, audio_bytes, is_termination):
                    # Estimate audio duration: bytes / 8000 Hz
                    audio_duration = audio_bytes / 8000
                    # Use a shorter grace period for intentional termination
                    grace_period = 1.0 if is_termination else 5.0
                    wait_time = audio_duration + grace_period
                    print(f"Waiting {wait_time:.1f}s (Audio: {audio_duration:.1f}s + Grace: {grace_period}s) before hangup.")
                    await asyncio.sleep(wait_time)
                    try:
                        twilio_client.calls(sid).update(status='completed')
                        print(f"[Twilio] Call {sid} terminated after grace period.")
                    except Exception as e:
                        print(f"[Twilio] Error hanging up call: {e}")

                if call_sid:
                    if hangup_task and not hangup_task.done():
                        hangup_task.cancel()
                    hangup_task = asyncio.create_task(delayed_hangup(call_sid, total_audio_bytes, llm_service.terminate_flag))
                    type_str = "Termination" if llm_service.terminate_flag else "Booking"
                    print(f"{type_str} detected. Call will hang up after assistant finishes.")
        except asyncio.CancelledError:
            print(f"[AI Task] Response generation cancelled for barge-in.")
        except Exception as e:
            print(f"[AI Task] Error: {e}")
            traceback.print_exc()

    try:
        async with deepgram.listen.v1.connect(**dg_options) as dg_connection:
            print("[Deepgram] Async connection established")

            async def receive_transcriptions():
                nonlocal stream_sid, call_sid, hangup_task, ai_task
                full_transcript = []
                try:
                    async for result in dg_connection:
                        msg_type = getattr(result, 'type', None)
                        
                        if msg_type == "Results":
                            if hasattr(result, 'channel') and result.channel.alternatives:
                                is_final = getattr(result, 'is_final', False)
                                is_speech_final = getattr(result, 'speech_final', False)
                                
                                transcript = result.channel.alternatives[0].transcript
                                if transcript:
                                    if is_final:
                                        full_transcript.append(transcript)
                                
                                if is_speech_final and full_transcript:
                                    sentence = " ".join(full_transcript).strip()
                                    full_transcript = []
                                    print(f"User (Full): {sentence}")
                                    
                                    if stream_sid:
                                        # Use the dedicated background task for AI processing
                                        if ai_task and not ai_task.done():
                                            ai_task.cancel()
                                        ai_task = asyncio.create_task(process_ai_response(sentence, stream_sid))

                        elif msg_type == "SpeechStarted":
                            print("[Deepgram] User started speaking - triggering barge-in")
                            # Immediate barge-in: cancel everything
                            if ai_task and not ai_task.done():
                                ai_task.cancel()
                            if hangup_task and not hangup_task.done():
                                hangup_task.cancel()
                                print("Auto-hangup cancelled due to barge-in.")
                                
                        elif msg_type == "Metadata":
                            pass
                            
                except Exception as e:
                    print(f"[Deepgram] Receiver error: {e}")
                    # traceback.print_exc()

            receiver_task = asyncio.create_task(receive_transcriptions())

            try:
                while True:
                    data = await websocket.receive_text()
                    message = json.loads(data)
                    event = message.get("event")
                    
                    if event == "connected":
                        print("Twilio Media Stream connected")
                    elif event == "start":
                        stream_sid = message.get('streamSid')
                        call_sid = message.get('start', {}).get('callSid')
                        print(f"Media Stream started: {stream_sid}, CallSid: {call_sid}")
                    elif event == "media":
                        payload = message['media']['payload']
                        audio_chunk = base64.b64decode(payload)
                        await dg_connection.send_media(audio_chunk)
                    elif event == "stop":
                        print(f"Media Stream stopped: {stream_sid}")
                        if stream_sid in call_contexts:
                            del call_contexts[stream_sid]
                        break
            except WebSocketDisconnect:
                print("WebSocket disconnected")
                if stream_sid in call_contexts:
                            del call_contexts[stream_sid]
            finally:
                receiver_task.cancel()
                try:
                    await receiver_task
                except asyncio.CancelledError:
                    pass
                print("[Deepgram] Connection closed")

    except Exception as e:
        print(f"Error in Voice Pipeline: {e}")
        traceback.print_exc()
    finally:
        print("WebSocket cleanup complete")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=Config.PORT)
