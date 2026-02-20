"""
WiFi Speech Recognition Server (Session-Based)
------------------------------------------------
This server receives audio from Raspberry Pi Pico W via WiFi,
processes it with Google Speech-to-Text API, and sends back transcripts.

Features:
- Session-based recognition (starts on first audio, ends on STOP or timeout)
- Compatible with button-controlled Pico W
- Handles STOP_RECORDING message from Pico

Requirements:
- pip install google-cloud-speech
- Google Cloud Speech-to-Text API enabled
- Service account JSON key file OR API key

Usage:
1. Update credentials path or API key below
2. Run: python server_speech_recognition.py
3. Note the IP address shown
4. Update Pico code with this IP address
5. Power on Pico W
"""

import os
import socket
import struct
import threading
import queue
import time

# Try importing google.cloud.speech, handle failure gracefully
try:
    from google.cloud import speech
    from google.api_core.client_options import ClientOptions
    GOOGLE_IMPORT_SUCCESS = True
except ImportError:
    GOOGLE_IMPORT_SUCCESS = False
    print("WARNING: google-cloud-speech not installed.")

# -------------------------------
# CREDENTIALS SETUP
# -------------------------------
current_dir = os.path.dirname(os.path.abspath(__file__))
cred_path = os.path.join(current_dir, "speech_key.json")

# Try service account first, then API key
CREDENTIALS_VALID = False
client = None
streaming_config = None

# Option 1: Service Account (JSON file)
if os.path.exists(cred_path):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path
    try:
        client = speech.SpeechClient()
        CREDENTIALS_VALID = True
        print(f"Using service account: {cred_path}")
    except Exception as e:
        print(f"Service account error: {e}")

# Option 2: API Key (set via environment variable or below)
if not CREDENTIALS_VALID:
    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "Your-API-Key")
    if GOOGLE_API_KEY and GOOGLE_API_KEY != "YOUR_API_KEY_HERE":
        try:
            client_options = ClientOptions(api_key=GOOGLE_API_KEY)
            client = speech.SpeechClient(client_options=client_options)
            CREDENTIALS_VALID = True
            print("Using API key")
        except Exception as e:
            print(f"API key error: {e}")

if CREDENTIALS_VALID and GOOGLE_IMPORT_SUCCESS:
    # Configure for LINEAR16 (raw PCM from Pico)
    streaming_config = speech.StreamingRecognitionConfig(
        config=speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code="en-US",
            enable_automatic_punctuation=True
        ),
        interim_results=True
    )
else:
    print("WARNING: No valid credentials found. Speech recognition will not work.")

# -------------------------------
# CONFIGURATION
# -------------------------------
RATE = 16000
HOST = "0.0.0.0"  # Listen on all network interfaces
AUDIO_PORT = 5000
TRANSCRIPT_PORT = 5001
AUDIO_TIMEOUT_SECONDS = 5  # End session if no audio for this long

# -------------------------------
# SESSION MANAGEMENT
# -------------------------------
class RecognitionSession:
    """Handles a single speech recognition session"""
    def __init__(self, send_transcript_callback):
        self.audio_queue = queue.Queue()
        self.send_transcript = send_transcript_callback
        self.is_running = False
        self._thread = None
        self._last_audio_time = None

    def start(self):
        self.is_running = True
        self._last_audio_time = time.time()
        self._thread = threading.Thread(target=self._process_speech, daemon=True)
        self._thread.start()
        print("Recognition session started")

    def stop(self):
        self.is_running = False
        self.audio_queue.put(None)  # Sentinel to stop generator
        print("Recognition session stopped")

    def add_audio(self, data):
        if self.is_running:
            self._last_audio_time = time.time()
            self.audio_queue.put(data)

    def _audio_generator(self):
        """Generate audio chunks for Google Speech API with timeout handling"""
        while self.is_running:
            try:
                data = self.audio_queue.get(timeout=0.1)
                if data is None:
                    print("Audio generator received stop signal")
                    return
                yield speech.StreamingRecognizeRequest(audio_content=data)
            except queue.Empty:
                # Check if we've been idle too long
                if self._last_audio_time and (time.time() - self._last_audio_time) > AUDIO_TIMEOUT_SECONDS:
                    print(f"No audio for {AUDIO_TIMEOUT_SECONDS}s, ending session")
                    return
                continue

    def _process_speech(self):
        if not CREDENTIALS_VALID or not client:
            self.send_transcript("[No credentials - recognition disabled]")
            return

        try:
            print("Starting Google Speech recognition...")
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

                if is_final:
                    self.send_transcript(transcript)
                else:
                    self.send_transcript(transcript + "...")
                    
            print("Recognition stream ended normally")

        except Exception as e:
            print(f"Recognition error: {e}")


# -------------------------------
# CLIENT HANDLER
# -------------------------------
class PicoHandler:
    """Handles connection from a Pico W"""
    def __init__(self):
        self.audio_sock = None
        self.transcript_sock = None
        self.current_session = None
        self.last_stop_time = 0
        self.STOP_GRACE_PERIOD = 0.5
        
    def set_sockets(self, audio_sock, transcript_sock):
        self.audio_sock = audio_sock
        self.transcript_sock = transcript_sock
        
    def send_transcript(self, text):
        """Send transcript to Pico"""
        if self.transcript_sock:
            try:
                data = text.encode('utf-8')
                length = len(data)
                self.transcript_sock.send(struct.pack('<I', length))
                self.transcript_sock.send(data)
                print(f"Sent to Pico: {text}")
            except Exception as e:
                print(f"Error sending transcript: {e}")
    
    def handle_audio(self, audio_data):
        """Process incoming audio data"""
        current_time = time.time()
        
        # Ignore audio during grace period after stop
        if current_time - self.last_stop_time < self.STOP_GRACE_PERIOD:
            return
        
        # Start new session if needed
        if self.current_session is None:
            print("Creating new recognition session...")
            self.current_session = RecognitionSession(self.send_transcript)
            self.current_session.start()
        elif not self.current_session.is_running:
            print("Previous session ended, creating new one...")
            self.current_session = RecognitionSession(self.send_transcript)
            self.current_session.start()
        
        self.current_session.add_audio(audio_data)
    
    def handle_stop(self):
        """Handle STOP_RECORDING message"""
        print("Received STOP_RECORDING")
        self.last_stop_time = time.time()
        if self.current_session:
            self.current_session.stop()
            self.current_session = None
            print("Session cleared, ready for new recording")
    
    def cleanup(self):
        if self.current_session:
            self.current_session.stop()


# Global handler instance
pico_handler = PicoHandler()

# -------------------------------
# SOCKET SERVERS
# -------------------------------
def audio_server():
    """Server to receive audio from Pico"""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((HOST, AUDIO_PORT))
    server_sock.listen(1)
    
    print(f"Audio server listening on port {AUDIO_PORT}")
    
    while True:
        try:
            conn, addr = server_sock.accept()
            conn.settimeout(5.0) # Set timeout to detect dead connections
            
            # Check client type
            try:
                client_type = conn.recv(10).decode('utf-8')
                if client_type.startswith("AUDIO"):
                    print(f"Audio client connected from {addr}")
                    pico_handler.audio_sock = conn
                    
                    # Receive audio data
                    while True:
                        try:
                            # Read length header (4 bytes)
                            length_bytes = conn.recv(4)
                            if not length_bytes:
                                break
                            if len(length_bytes) != 4:
                                break
                            
                            length = struct.unpack('<I', length_bytes)[0]
                            
                            # Check for special text message marker
                            if length == 0xFFFFFFFF:
                                # Read text message length
                                text_len_bytes = conn.recv(4)
                                if len(text_len_bytes) != 4:
                                    break
                                text_len = struct.unpack('<I', text_len_bytes)[0]
                                
                                # Read text message
                                text_data = b''
                                while len(text_data) < text_len:
                                    chunk = conn.recv(text_len - len(text_data))
                                    if not chunk:
                                        break
                                    text_data += chunk
                                
                                message = text_data.decode('utf-8')
                                if message == "STOP_RECORDING":
                                    pico_handler.handle_stop()
                                continue
                            
                            # Read audio data
                            audio_data = b''
                            while len(audio_data) < length:
                                chunk = conn.recv(length - len(audio_data))
                                if not chunk:
                                    break
                                audio_data += chunk
                            
                            if len(audio_data) == length:
                                pico_handler.handle_audio(audio_data)
                                
                        except socket.timeout:
                            # Timeout is fine, just loop back and check if we should still run
                            continue
                        except Exception as e:
                            print(f"Error receiving audio: {e}")
                            break
                    
                    print("Audio client disconnected")
                    pico_handler.cleanup()
                    pico_handler.audio_sock = None
                    conn.close()
                else:
                    conn.close()

            except Exception as e:
                print(f"Handshake error: {e}")
                conn.close()
                
        except Exception as e:
            print(f"Audio server error: {e}")
            time.sleep(1)

def transcript_server():
    """Server to send transcripts to Pico"""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((HOST, TRANSCRIPT_PORT))
    server_sock.listen(1)
    
    print(f"Transcript server listening on port {TRANSCRIPT_PORT}")
    
    while True:
        try:
            conn, addr = server_sock.accept()
            conn.settimeout(5.0)
            
            try:
                # Check client type
                client_type = conn.recv(15).decode('utf-8')
                if client_type.startswith("TRANSCRIPT"):
                    print(f"Transcript client connected from {addr}")
                    pico_handler.transcript_sock = conn
                    
                    # Keep connection alive
                    while pico_handler.transcript_sock:
                        try:
                            time.sleep(5) # Send keepalive more frequently
                            if pico_handler.transcript_sock:
                                # Send 0 length packet as keepalive
                                pico_handler.transcript_sock.send(struct.pack('<I', 0))
                        except Exception as e:
                            print(f"Keepalive error: {e}")
                            break
                    
                    print("Transcript client disconnected")
                    pico_handler.transcript_sock = None
                    conn.close()
                else:
                    conn.close()
            except Exception as e:
                print(f"Transcript handshake error: {e}")
                conn.close()
                
        except Exception as e:
            print(f"Transcript server error: {e}")
            time.sleep(1)

# -------------------------------
# GET LOCAL IP ADDRESS
# -------------------------------
def get_local_ip():
    """Get local IP address"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

# -------------------------------
# MAIN
# -------------------------------
if __name__ == "__main__":
    print("=" * 50)
    print("WiFi Speech Recognition Server (Session-Based)")
    print("=" * 50)
    
    local_ip = get_local_ip()
    print(f"\nServer IP Address: {local_ip}")
    print(f"Audio Port: {AUDIO_PORT}")
    print(f"Transcript Port: {TRANSCRIPT_PORT}")
    print(f"\nUpdate Pico code with:")
    print(f'  SERVER_IP = "{local_ip}"')
    print(f"  SERVER_PORT = {AUDIO_PORT}")
    print("\nWaiting for Pico to connect...")
    print("Press Ctrl+C to stop\n")
    
    # Start server threads
    audio_thread = threading.Thread(target=audio_server, daemon=True)
    transcript_thread = threading.Thread(target=transcript_server, daemon=True)
    
    audio_thread.start()
    transcript_thread.start()
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nStopping server...")
        pico_handler.cleanup()
        print("Goodbye!")