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
import time
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
AUDIO_TIMEOUT_SECONDS = 5  # Close recognition if no audio for this many seconds
# Set your Google Cloud API key here or use the GOOGLE_API_KEY environment variable
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "AIzaSyCzTzNFjTZt3ZNOSLBJQ-nOx0Pfk3X4k50")

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


class RecognitionSession:
    """Handles a single speech recognition session (one recording)"""
    def __init__(self, loop, transcript_queue):
        self.loop = loop
        self.transcript_queue = transcript_queue
        self.audio_queue = queue.Queue()
        self.is_running = False
        self._thread = None
        self._last_audio_time = None

    def start(self):
        self.is_running = True
        self._last_audio_time = time.time()
        self._thread = threading.Thread(target=self._process_speech, daemon=True)
        self._thread.start()
        logging.info("Recognition session started")

    def stop(self):
        self.is_running = False
        self.audio_queue.put(None)  # Sentinel to stop generator
        logging.info("Recognition session stopped")

    def add_audio(self, data):
        if self.is_running:
            self._last_audio_time = time.time()
            self.audio_queue.put(data)

    def _audio_generator(self):
        """Generate audio chunks for Google Speech API with timeout handling"""
        while self.is_running:
            try:
                # Short timeout to check for inactivity
                data = self.audio_queue.get(timeout=0.1)
                if data is None:
                    logging.info("Audio generator received stop signal")
                    return
                yield speech.StreamingRecognizeRequest(audio_content=data)
            except queue.Empty:
                # Check if we've been idle too long
                if self._last_audio_time and (time.time() - self._last_audio_time) > AUDIO_TIMEOUT_SECONDS:
                    logging.info(f"No audio for {AUDIO_TIMEOUT_SECONDS}s, ending recognition session")
                    return
                continue

    def _process_speech(self):
        if not CREDENTIALS_VALID or not client:
            self.loop.call_soon_threadsafe(
                self.transcript_queue.put_nowait,
                json.dumps({
                    "error": "Missing Google Cloud Credentials.",
                    "transcript": "[System: No Credentials]",
                    "isFinal": True
                })
            )
            return

        try:
            logging.info("Starting Google Speech recognition...")
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

                self.loop.call_soon_threadsafe(
                    self.transcript_queue.put_nowait,
                    json.dumps({
                        "transcript": transcript,
                        "isFinal": is_final
                    })
                )
                
            logging.info("Recognition stream ended normally")

        except Exception as e:
            error_msg = str(e)
            logging.error(f"Recognition error: {error_msg}")
            # Only send error to frontend if it's not a normal timeout
            if "Audio Timeout" not in error_msg:
                self.loop.call_soon_threadsafe(
                    self.transcript_queue.put_nowait,
                    json.dumps({"error": error_msg})
                )


class ConnectionHandler:
    """Handles a single WebSocket connection"""
    def __init__(self, websocket, loop):
        self.websocket = websocket
        self.loop = loop
        self.transcript_queue = asyncio.Queue()
        self.current_session = None
        self.last_stop_time = 0  # Track when recording was stopped
        self.STOP_GRACE_PERIOD = 0.5  # Ignore audio for this many seconds after STOP
        
    async def handle(self):
        logging.info(f"Client connected: {self.websocket.remote_address}")
        
        # Task to send transcripts back to client
        sender_task = asyncio.create_task(self._sender())

        try:
            async for message in self.websocket:
                if isinstance(message, bytes):
                    # Audio data received
                    current_time = time.time()
                    
                    # Ignore audio during grace period after stop
                    if current_time - self.last_stop_time < self.STOP_GRACE_PERIOD:
                        logging.debug("Ignoring audio during grace period")
                        continue
                    
                    if self.current_session is None:
                        # Start new recognition session on first audio
                        logging.info("Creating new recognition session...")
                        self.current_session = RecognitionSession(self.loop, self.transcript_queue)
                        self.current_session.start()
                    elif not self.current_session.is_running:
                        # Previous session ended, start a new one
                        logging.info("Previous session ended, creating new one...")
                        self.current_session = RecognitionSession(self.loop, self.transcript_queue)
                        self.current_session.start()
                    
                    self.current_session.add_audio(message)
                else:
                    # Text message - could be control commands
                    logging.info(f"Received text message: {message}")
                    if message == "STOP_RECORDING":
                        self.last_stop_time = time.time()  # Start grace period
                        if self.current_session:
                            self.current_session.stop()
                            self.current_session = None  # Clear the session so next audio creates new one
                            logging.info("Session cleared, ready for new recording")

        except websockets.exceptions.ConnectionClosed:
            logging.info("Client disconnected")
        except Exception as e:
            logging.error(f"Handler error: {e}")
        finally:
            if self.current_session:
                self.current_session.stop()
            sender_task.cancel()
            logging.info("Cleaned up connection")

    async def _sender(self):
        try:
            while True:
                msg = await self.transcript_queue.get()
                await self.websocket.send(msg)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logging.error(f"Sender error: {e}")


async def handler(websocket):
    connection = ConnectionHandler(websocket, asyncio.get_running_loop())
    await connection.handle()


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
