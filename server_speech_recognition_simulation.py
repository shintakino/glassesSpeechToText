"""
WebSocket Speech Recognition Server
--------------------------------
This server receives audio from a Web Browser via WebSockets,
processes it with Google Speech-to-Text API, and sends back transcripts.

Requirements:
- pip install google-cloud-speech websockets google-api-core
- Google Cloud Speech-to-Text API enabled
- API Key from Google Cloud Console

Usage:
1. Set your API key in the GOOGLE_API_KEY variable below (or use environment variable)
2. Run: python server_speech_recognition_simulation.py
3. Open the web simulation app
"""

import os
import asyncio
import queue
import threading
import json
import logging
import websockets
# Try importing google.cloud.speech, handle failure gracefully
try:
    from google.cloud import speech
    from google.api_core.client_options import ClientOptions
    GOOGLE_IMPORT_SUCCESS = True
except ImportError:
    GOOGLE_IMPORT_SUCCESS = False
    logging.warning("google-cloud-speech not installed.")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# -------------------------------
# CONFIGURATION
# -------------------------------
RATE = 16000
HOST = "0.0.0.0"
PORT = 8000
# Set your Google Cloud API key here or use the GOOGLE_API_KEY environment variable
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "YOUR_API_KEY_HERE")

# -------------------------------
# CLIENT SETUP
# -------------------------------
client = None
streaming_config = None
CREDENTIALS_VALID = False

def setup_google_client():
    global client, streaming_config, CREDENTIALS_VALID
    
    if not GOOGLE_IMPORT_SUCCESS:
        logging.error("Google Cloud Speech library not found.")
        return

    api_key = GOOGLE_API_KEY
    
    if api_key and api_key != "YOUR_API_KEY_HERE":
        try:
            # Create client with API key
            client_options = ClientOptions(api_key=api_key)
            client = speech.SpeechClient(client_options=client_options)
            streaming_config = speech.StreamingRecognitionConfig(
                config=speech.RecognitionConfig(
                    encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
                    sample_rate_hertz=48000,
                    language_code="en-US",
                    enable_automatic_punctuation=True,
                ),
                interim_results=True
            )
            CREDENTIALS_VALID = True
            logging.info("Google Cloud Speech Client successfully initialized with API key.")
        except Exception as e:
            logging.error(f"Failed to initialize Google Cloud Speech Client: {e}")
            CREDENTIALS_VALID = False
    else:
        logging.warning("Google Cloud API key not configured. Set GOOGLE_API_KEY environment variable or update the script.")
        CREDENTIALS_VALID = False

# Initialize client on module load
setup_google_client()

class SpeechProcessor:
    def __init__(self, loop):
        self.loop = loop
        self.audio_queue = queue.Queue()
        self.transcript_queue = asyncio.Queue()
        self.is_running = False
        self._thread = None
        self._sent_error = False

    def start(self):
        self.is_running = True
        self._thread = threading.Thread(target=self._process_speech, daemon=True)
        self._thread.start()

    def stop(self):
        self.is_running = False
        self.audio_queue.put(None)  # Sentinel to stop generator

    def add_audio(self, data):
        if self.is_running:
            self.audio_queue.put(data)

    def _audio_generator(self):
        while self.is_running:
            data = self.audio_queue.get()
            if data is None:
                return
            yield speech.StreamingRecognizeRequest(audio_content=data)

    def _process_speech(self):
        logging.info("Speech recognition thread started")
        
        # If no credentials, just drain queue and send error once
        if not CREDENTIALS_VALID or not client:
            if not self._sent_error:
                # Notify frontend of missing credentials
                self.loop.call_soon_threadsafe(
                    self.transcript_queue.put_nowait,
                    json.dumps({
                        "error": "Missing Google Cloud Credentials. Server is running in simulation mode (no STT).",
                        "transcript": "[System: No Credentials - Speech Recognition Disabled]",
                        "isFinal": True
                    })
                )
                self._sent_error = True
            
            # Drain queue to prevent memory leak
            while self.is_running:
                data = self.audio_queue.get()
                if data is None: 
                    break
            return

        try:
            responses = client.streaming_recognize(
                streaming_config,
                self._audio_generator()
            )

            for response in responses:
                if not self.is_running:
                    break
                    
                if not response.results:
                    continue

                result = response.results[0]
                if not result.alternatives:
                    continue
                    
                transcript = result.alternatives[0].transcript
                is_final = result.is_final

                # Send back to main loop via thread-safe call
                self.loop.call_soon_threadsafe(
                    self.transcript_queue.put_nowait,
                    json.dumps({
                        "transcript": transcript,
                        "isFinal": is_final
                    })
                )

        except Exception as e:
            logging.error(f"Recognition error: {e}")
            # Notify frontend of error
            self.loop.call_soon_threadsafe(
                self.transcript_queue.put_nowait,
                json.dumps({"error": str(e)})
            )
        finally:
            logging.info("Speech recognition thread stopped")


async def handler(websocket):
    logging.info(f"Client connected: {websocket.remote_address}")
    loop = asyncio.get_running_loop()
    processor = SpeechProcessor(loop)
    processor.start()

    # Task to send transcripts back to client
    async def sender():
        try:
            while True:
                msg = await processor.transcript_queue.get()
                await websocket.send(msg)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logging.error(f"Sender error: {e}")

    sender_task = asyncio.create_task(sender())

    try:
        async for message in websocket:
            # Assume binary message is audio
            if isinstance(message, bytes):
                processor.add_audio(message)
            else:
                logging.info(f"Received text message: {message}")

    except websockets.exceptions.ConnectionClosed:
        logging.info("Client disconnected")
    except Exception as e:
        logging.error(f"Handler error: {e}")
    finally:
        processor.stop()
        sender_task.cancel()
        logging.info("Cleaned up connection")

async def main():
    logging.info(f"Starting WebSocket server on {HOST}:{PORT}")
    if not CREDENTIALS_VALID:
        logging.warning("!!! RUNNING WITHOUT GOOGLE CREDENTIALS !!!")
        logging.warning("Speech recognition will not work. Clients will receive an error message.")

    async with websockets.serve(handler, HOST, PORT):
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopping server...")
