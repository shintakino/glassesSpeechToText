"""
WiFi Speech Recognition Server
--------------------------------
This server receives audio from Raspberry Pi Pico W via WiFi,
processes it with Google Speech-to-Text API, and sends back transcripts.

Requirements:
- pip install google-cloud-speech
- Google Cloud Speech-to-Text API enabled
- Service account JSON key file

Usage:
1. Update GOOGLE_APPLICATION_CREDENTIALS path below
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
from google.cloud import speech

# Set your credentials
# Set your credentials
# START_USER_EDIT
# Make sure to place your 'service_account.json' in the same folder or update the path
current_dir = os.path.dirname(os.path.abspath(__file__))
cred_path = os.path.join(current_dir, "speech_key.json")
if os.path.exists(cred_path):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path
else:
    # Fallback to hardcoded or environment variable if set manually
    # os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"path\to\your\speech_key.json"
    print(f"WARNING: Google Cloud credentials file not found at {cred_path}")
# END_USER_EDIT

# -------------------------------
# CONFIGURATION
# -------------------------------
RATE = 16000
HOST = "0.0.0.0"  # Listen on all network interfaces
AUDIO_PORT = 5000
TRANSCRIPT_PORT = 5001

# Audio queue for streaming
audio_queue = queue.Queue()

# Connected clients
audio_client = None
transcript_client = None

# -------------------------------
# GOOGLE SPEECH CLIENT
# -------------------------------
client = speech.SpeechClient()
streaming_config = speech.StreamingRecognitionConfig(
    config=speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE,
        language_code="en-US",
        enable_automatic_punctuation=True
    ),
    interim_results=True
)

# -------------------------------
# SOCKET SERVERS
# -------------------------------
def send_transcript(text):
    """Send transcript to Pico"""
    global transcript_client
    if transcript_client:
        try:
            data = text.encode('utf-8')
            length = len(data)
            # Send length header + data
            transcript_client.send(struct.pack('<I', length))
            transcript_client.send(data)
            print(f"Sent to Pico: {text}")
        except Exception as e:
            print(f"Error sending transcript: {e}")
            transcript_client = None

def audio_server():
    """Server to receive audio from Pico"""
    global audio_client
    
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((HOST, AUDIO_PORT))
    server_sock.listen(1)
    
    print(f"Audio server listening on port {AUDIO_PORT}")
    
    while True:
        try:
            conn, addr = server_sock.accept()
            
            # Check client type
            client_type = conn.recv(10).decode('utf-8')
            if client_type.startswith("AUDIO"):
                print(f"Audio client connected from {addr}")
                audio_client = conn
                
                # Receive audio data
                while True:
                    try:
                        # Read length header (4 bytes)
                        length_bytes = audio_client.recv(4)
                        if len(length_bytes) != 4:
                            break
                        
                        length = struct.unpack('<I', length_bytes)[0]
                        
                        # Read audio data
                        audio_data = b''
                        while len(audio_data) < length:
                            chunk = audio_client.recv(length - len(audio_data))
                            if not chunk:
                                break
                            audio_data += chunk
                        
                        if len(audio_data) == length:
                            audio_queue.put(audio_data)
                    except Exception as e:
                        print(f"Error receiving audio: {e}")
                        break
                
                print("Audio client disconnected")
                audio_client = None
        except Exception as e:
            print(f"Audio server error: {e}")

def transcript_server():
    """Server to send transcripts to Pico"""
    global transcript_client
    
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((HOST, TRANSCRIPT_PORT))
    server_sock.listen(1)
    
    print(f"Transcript server listening on port {TRANSCRIPT_PORT}")
    
    while True:
        try:
            conn, addr = server_sock.accept()
            
            # Check client type
            client_type = conn.recv(15).decode('utf-8')
            if client_type.startswith("TRANSCRIPT"):
                print(f"Transcript client connected from {addr}")
                transcript_client = conn
                
                # Keep connection alive
                while transcript_client:
                    try:
                        # Send keepalive every 30 seconds (send 0 length packet)
                        import time
                        time.sleep(30)
                        if transcript_client:
                            # Send 0 length packet as keepalive
                            transcript_client.send(struct.pack('<I', 0))
                    except Exception as e:
                        print(f"Keepalive error: {e}")
                        break
                
                print("Transcript client disconnected")
                transcript_client = None
        except Exception as e:
            print(f"Transcript server error: {e}")

# -------------------------------
# AUDIO STREAM GENERATOR
# -------------------------------
def audio_stream_generator():
    """Generate audio stream for Google Speech API"""
    while True:
        audio_data = audio_queue.get()
        yield speech.StreamingRecognizeRequest(audio_content=audio_data)

# -------------------------------
# SPEECH RECOGNITION THREAD
# -------------------------------
def recognize_speech():
    """Process audio with Google Speech-to-Text"""
    print("Speech recognition thread started")
    
    while True:
        try:
            # Wait for audio client to connect
            while not audio_client:
                import time
                time.sleep(1)
            
            print("Starting speech recognition stream...")
            responses = client.streaming_recognize(
                streaming_config, 
                audio_stream_generator()
            )
            
            for response in responses:
                if not response.results:
                    continue
                
                result = response.results[0]
                transcript = result.alternatives[0].transcript
                
                if result.is_final:
                    # Send final transcript
                    print(f"Final: {transcript}")
                    send_transcript(transcript)
                else:
                    # Send interim transcript with indicator
                    print(f"Interim: {transcript}")
                    send_transcript(transcript + "...")
                    
        except Exception as e:
            print(f"Recognition error: {e}")
            # Restart recognition after error
            import time
            time.sleep(2)
            continue

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
# START THREADS
# -------------------------------
print("=" * 50)
print("WiFi Speech Recognition Server")
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

audio_thread = threading.Thread(target=audio_server, daemon=True)
transcript_thread = threading.Thread(target=transcript_server, daemon=True)
recognition_thread = threading.Thread(target=recognize_speech, daemon=True)

audio_thread.start()
transcript_thread.start()
recognition_thread.start()

# Keep main thread alive
try:
    while True:
        import time
        time.sleep(1)
except KeyboardInterrupt:
    print("\n\nStopping server...")
    print("Goodbye!")