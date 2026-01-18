import machine
import time
import network
import socket
import struct
from machine import I2S, Pin, I2C
# Try to import ssd1306, handle if missing
try:
    import ssd1306
except ImportError:
    ssd1306 = None

# -------------------------------
# CONFIGURATION
# -------------------------------
# WIFI
WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
SERVER_IP = "192.168.1.100"  # Update this with your computer's IP
SERVER_PORT = 5000

# PINS
SCK_PIN = 16   # I2S Serial Clock
WS_PIN = 17    # I2S Word Select
SD_PIN = 18    # I2S Serial Data
SCL_PIN = 1    # I2C Clock
SDA_PIN = 0    # I2C Data

# AUDIO
SAMPLE_RATE = 16000
BITS_PER_SAMPLE = 16
BUFFER_LENGTH = 1600  # 0.1s chunks

# -------------------------------
# HARDWARE SETUP
# -------------------------------
# LED
try:
    led = Pin("LED", Pin.OUT)
except:
    led = Pin(25, Pin.OUT) # Fallback for non-W Pico

# OLED
i2c = I2C(0, scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=400000)
oled = None
try:
    if ssd1306:
        oled = ssd1306.SSD1306_I2C(128, 64, i2c)
except Exception as e:
    print(f"OLED Init Error: {e}")

# I2S Microphone
audio_in = I2S(
    0,
    sck=Pin(SCK_PIN),
    ws=Pin(WS_PIN),
    sd=Pin(SD_PIN),
    mode=I2S.RX,
    bits=BITS_PER_SAMPLE,
    format=I2S.MONO,
    rate=SAMPLE_RATE,
    ibuf=20000
)

# -------------------------------
# HELPER FUNCTIONS
# -------------------------------
def display_text(text):
    """Display text on OLED with word wrapping"""
    print(f"Display: {text}")
    if not oled:
        return
        
    oled.fill(0)
    words = text.split()
    lines = []
    current_line = ""
    
    for word in words:
        test_line = current_line + " " + word if current_line else word
        if len(test_line) <= 16:
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word
    
    if current_line:
        lines.append(current_line)
    
    for i, line in enumerate(lines[:8]):
        oled.text(line, 0, i * 8)
    
    oled.show()

def blink_led(times, delay=0.2):
    for _ in range(times):
        led.on()
        time.sleep(delay)
        led.off()
        time.sleep(delay)

def connect_wifi():
    """Connect to WiFi with power management disabled for performance"""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    # Disable power saving mode (improves latency/throughput)
    # 0xa11140 is a magic value/standard for 'performance' on cyw43
    try:
        wlan.config(pm=0xa11140)
    except:
        pass # Not all firmwares/boards support this
    
    if not wlan.isconnected():
        display_text(f"Connecting to {WIFI_SSID}...")
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        
        timeout = 20
        while not wlan.isconnected() and timeout > 0:
            time.sleep(1)
            timeout -= 1
            print(".")
            
    if wlan.isconnected():
        status = wlan.ifconfig()
        print(f"Connected: {status[0]}")
        display_text(f"WiFi Connected\n{status[0]}")
        blink_led(3, 0.1)
        return True
    else:
        display_text("WiFi Failed")
        return False

def recv_exact(sock, n):
    """Receive exactly n bytes from socket"""
    data = b''
    while len(data) < n:
        try:
            chunk = sock.recv(n - len(data))
            if not chunk:
                return None
            data += chunk
        except OSError:
            return None
    return data

# -------------------------------
# SOCKET CLIENT
# -------------------------------
class SpeechClient:
    def __init__(self):
        self.audio_sock = None
        self.transcript_sock = None
        self.connected = False
        
    def connect(self):
        try:
            # Audio Socket
            self.audio_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.audio_sock.connect((SERVER_IP, SERVER_PORT))
            self.audio_sock.send(b"AUDIO")
            
            # Transcript Socket
            self.transcript_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.transcript_sock.connect((SERVER_IP, SERVER_PORT + 1))
            self.transcript_sock.send(b"TRANSCRIPT")
            self.transcript_sock.setblocking(False)
            
            self.connected = True
            display_text("Server Connected")
            blink_led(2)
            return True
        except Exception as e:
            print(f"Connection error: {e}")
            display_text("Server Failed")
            self.close()
            return False
            
    def close(self):
        self.connected = False
        if self.audio_sock:
            try: self.audio_sock.close()
            except: pass
        if self.transcript_sock:
            try: self.transcript_sock.close()
            except: pass
        self.audio_sock = None
        self.transcript_sock = None
        
    def send_audio(self, data):
        if not self.connected or not self.audio_sock:
            return False
        try:
            header = struct.pack('<I', len(data))
            self.audio_sock.send(header + data)
            return True
        except Exception as e:
            print(f"Send error: {e}")
            self.connected = False
            return False
            
    def check_transcript(self):
        """Check for influx transcript data"""
        if not self.connected or not self.transcript_sock:
            return None
            
        try:
            # First try unauthorized peek or read 4 bytes for header
            # Since we are non-blocking, recv(4) might raise EAGAIN
            header = self.transcript_sock.recv(4)
            if not header: # Connection closed
                self.connected = False
                return None
                
            if len(header) == 4:
                length = struct.unpack('<I', header)[0]
                
                # If length is 0, it's a keepalive
                if length == 0:
                    return None
                
                # Read payload - Switch to blocking temporarily to ensure full read
                self.transcript_sock.setblocking(True)
                self.transcript_sock.settimeout(2.0) # 2 sec timeout
                
                data = recv_exact(self.transcript_sock, length)
                
                # Restore non-blocking
                self.transcript_sock.setblocking(False)
                
                if data:
                    return data.decode('utf-8')
                else:
                    self.connected = False
                    return None
            else:
                # We got partial header? This is bad in non-blocking mode without buffering.
                # In a LAN environment, 4 bytes usually come together.
                # Handling partials properly requires a ring buffer, simplifying here.
                return None
                
        except OSError as e:
            # 11 = EAGAIN/EWOULDBLOCK
            if e.args[0] == 110 or e.args[0] == 11: 
                return None
            print(f"Recv error: {e}")
            self.connected = False
            return None
        except Exception as e:
            print(f"Error checking transcript: {e}")
            self.connected = False
            return None

# -------------------------------
# MAIN PROCESS
# -------------------------------
def main():
    display_text("Initializing...")
    time.sleep(1)
    
    # 1. Connect WiFi
    if not connect_wifi():
        while True:
            blink_led(5, 0.1)
            time.sleep(1)
            
    # 2. Connect Server
    client = SpeechClient()
    while not client.connect():
        time.sleep(2)
        
    # 3. Audio Loop
    audio_buffer = bytearray(BUFFER_LENGTH * 2)
    last_transcript = ""
    
    print("Starting Streaming...")
    while True:
        try:
            # Record Audio
            n = audio_in.readinto(audio_buffer)
            if n > 0:
                # Send Audio
                if not client.send_audio(audio_buffer[:n]):
                    print("Reconnecting...")
                    client.close()
                    while not client.connect():
                        time.sleep(1)
                    continue
            
            # Check Transcript
            transcript = client.check_transcript()
            if transcript:
                print(f"Transcript: {transcript}")
                # Only update display if text changed
                if transcript != last_transcript:
                    display_text(transcript)
                    last_transcript = transcript
                    
            if not client.connected:
                 print("Connection lost, reconnecting...")
                 client.close()
                 while not client.connect():
                     time.sleep(1)
                     
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(1)

    # Cleanup
    client.close()
    audio_in.deinit()
    oled.fill(0)
    oled.text("Stopped", 0, 0)
    oled.show()

if __name__ == "__main__":
    main()