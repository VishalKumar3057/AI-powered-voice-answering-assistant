import json
import os
import httpx
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from config import Config
import openai

class BookingService:
    def __init__(self):
        # Mock database of appointments
        # Format: {"datetime": "2023-10-27T10:00:00", "name": "John Doe", "type": "Checkup"}
        self.appointments = []

    def get_availability(self, date_str: str) -> List[str]:
        """
        Mock function to return available slots for a given date.
        Returns a list of time strings.
        """
        # In a real app, this would query a DB
        # For demo, assume 9 AM, 10 AM, 2 PM are always open
        return ["09:00", "10:00", "14:00", "15:00"]

    def book_appointment(self, name: str, date_time_str: str, reason: str = "General") -> Dict:
        """
        Books an appointment and saves to JSON.
        """
        appointment = {
            "id": len(self.appointments) + 1,
            "name": name,
            "datetime": date_time_str,
            "reason": reason,
            "status": "confirmed",
            "timestamp": datetime.now().isoformat()
        }
        self.appointments.append(appointment)
        self.save_to_json(appointment)
        return appointment

    def save_to_json(self, booking_data: Dict):
        """
        Appends booking data to a local JSON file.
        """
        file_path = "bookings.json"
        existing_data = []
        try:
            if os.path.exists(file_path):
                with open(file_path, "r") as f:
                    existing_data = json.load(f)
        except Exception as e:
            print(f"Error reading bookings.json: {e}")

        existing_data.append(booking_data)
        
        try:
            with open(file_path, "w") as f:
                json.dump(existing_data, f, indent=4)
            print(f"Booking saved to {file_path}")
        except Exception as e:
            print(f"Error writing to bookings.json: {e}")

class LLMService:
    def __init__(self):
        self.client = openai.AsyncOpenAI(api_key=Config.OPENAI_API_KEY)
        self.booking_service = BookingService()
        self.booking_flag = False   # Set when a booking is confirmed
        self.terminate_flag = False # Set when the call should end

    async def get_response(self, conversation_history: List[Dict]):
        """
        Generates a streaming response from the LLM.
        """
        self.booking_flag = False
        self.terminate_flag = False
        
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "check_availability",
                    "description": "Check available appointment slots for a specific date",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string", "description": "YYYY-MM-DD format"},
                        },
                        "required": ["date"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "book_appointment",
                    "description": "Book a new appointment",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Patient name"},
                            "datetime": {"type": "string", "description": "YYYY-MM-DD HH:MM format"},
                            "reason": {"type": "string", "description": "Reason for visit"},
                        },
                        "required": ["name", "datetime"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "terminate_call",
                    "description": "Ends the call when the user is finished and no more assistance is needed.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            }
        ]

        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=conversation_history,
            tools=tools,
            tool_choice="auto",
            stream=True
        )

        full_content = ""
        tool_calls = []
        
        async for chunk in response:
            delta = chunk.choices[0].delta
            
            # Handle tool calls
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    if len(tool_calls) <= tc_delta.index:
                        tool_calls.append({
                            "id": tc_delta.id,
                            "type": "function",
                            "function": {"name": tc_delta.function.name, "arguments": ""}
                        })
                    if tc_delta.function.arguments:
                        tool_calls[tc_delta.index]["function"]["arguments"] += tc_delta.function.arguments
            
            # Handle content
            if delta.content:
                full_content += delta.content
                yield delta.content

        # If tool calls were made, we need to execute them and get a second response
        if tool_calls:
            # Construct a message object compatible with OpenAI's expected format for tool_calls
            # Converting dict to a simple object for history injection if needed, 
            # but usually OpenAI client handles dicts in messages list.
            
            # For simplicity in this async generator, if a tool is called, we wait, execute, 
            # and then stream the final response.
            
            # 1. Add assistant message with tool calls
            assistant_message = {
                "role": "assistant",
                "content": full_content or None,
                "tool_calls": tool_calls
            }
            conversation_history.append(assistant_message)
            
            # 2. Execute tools
            for tc in tool_calls:
                function_name = tc["function"]["name"]
                arguments = json.loads(tc["function"]["arguments"])
                
                tool_result = None
                if function_name == "check_availability":
                    tool_result = self.booking_service.get_availability(arguments.get("date"))
                elif function_name == "book_appointment":
                    tool_result = self.booking_service.book_appointment(
                        arguments.get("name"), 
                        arguments.get("datetime"), 
                        arguments.get("reason")
                    )
                    self.booking_flag = True
                elif function_name == "terminate_call":
                    self.terminate_flag = True
                    tool_result = {"status": "Call termination initiated."}

                conversation_history.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(tool_result)
                })

            # 3. Get final streaming response
            second_response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=conversation_history,
                stream=True
            )
            
            async for chunk in second_response:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

class TTSService:
    def __init__(self):
        self.api_key = Config.DEEPGRAM_API_KEY
        # Correct Deepgram URL for TTS
        self.url = "https://api.deepgram.com/v1/speak?model=aura-asteria-en&encoding=mulaw&sample_rate=8000"
        self.client = httpx.AsyncClient(timeout=10.0)

    async def generate_audio(self, text: str) -> Optional[bytes]:
        """
        Generates mulaw 8000Hz audio from text using Deepgram Speak API.
        Returns raw bytes if successful.
        """
        header = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "text": text
        }
        
        try:
            response = await self.client.post(self.url, headers=header, json=payload)
            if response.status_code == 200:
                return response.content
            else:
                print(f"[TTS] Error: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"[TTS] Exception: {e}")
            return None

    async def close(self):
        await self.client.aclose()
