"""
Speech Recognition Client for Pico with ESP8285 WiFi
-----------------------------------------------------
This script runs on a Pico clone with ESP8285 WiFi chip.
Uses UART AT commands for WiFi communication.
Features button-controlled recording with I2S microphone.
"""

from machine import UART, Pin, I2S, I2C
import utime
import time
import struct

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
SERVER_IP = "192.168.1.100"  # Update with your computer's IP
SERVER_PORT = 5000

# UART for ESP8285
UART_ID = 0
UART_BAUD = 115200

# PINS
SCK_PIN = 16   # I2S Serial Clock
WS_PIN = 17    # I2S Word Select
SD_PIN = 18    # I2S Serial Data
SCL_PIN = 1    # I2C Clock for OLED
SDA_PIN = 0    # I2C Data for OLED
BUTTON_PIN = 14  # Button to start/stop recording

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
    led = Pin(25, Pin.OUT)  # Fallback

# Button with internal pull-up
button = Pin(BUTTON_PIN, Pin.IN, Pin.PULL_UP)

# UART for ESP8285
esp_uart = UART(UART_ID, UART_BAUD)

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
# STATE MANAGEMENT
# -------------------------------
is_recording = False
last_button_time = 0
DEBOUNCE_MS = 300
audio_connected = False
transcript_connected = False

# -------------------------------
# HELPER FUNCTIONS
# -------------------------------
def display_status(line1, line2="", line3=""):
    """Display status on OLED"""
    print(f"Display: {line1} | {line2} | {line3}")
    if not oled:
        return
    oled.fill(0)
    oled.text(line1[:16], 0, 0)
    if line2:
        oled.text(line2[:16], 0, 16)
    if line3:
        oled.text(line3[:16], 0, 32)
    oled.show()

def display_transcript(text):
    """Display transcript with word wrapping"""
    print(f"Transcript: {text}")
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

def check_button():
    """Check if button was pressed with debounce"""
    global last_button_time
    if button.value() == 0:  # Active low
        current_time = utime.ticks_ms()
        if utime.ticks_diff(current_time, last_button_time) > DEBOUNCE_MS:
            last_button_time = current_time
            return True
    return False

# -------------------------------
# ESP8285 AT COMMAND FUNCTIONS
# -------------------------------
def esp_send_cmd(cmd, ack="OK", timeout=5000):
    """Send AT command and wait for acknowledgment"""
    # Clear any pending data
    if esp_uart.any():
        esp_uart.read()
    
    esp_uart.write(cmd + '\r\n')
    start = utime.ticks_ms()
    response = ""
    
    while utime.ticks_diff(utime.ticks_ms(), start) < timeout:
        if esp_uart.any():
            chunk = esp_uart.read()
            if chunk:
                response += chunk.decode('utf-8', 'ignore')
                if ack in response:
                    return True, response
                if "ERROR" in response:
                    return False, response
        time.sleep_ms(10)
    
    return False, response

def esp_init():
    """Initialize ESP8285 and connect to WiFi"""
    display_status("Init ESP8285...")
    
    # Exit transparent mode if stuck
    esp_uart.write('+++')
    time.sleep(1)
    if esp_uart.any():
        esp_uart.read()
    
    # Test AT
    ok, _ = esp_send_cmd("AT", "OK", 2000)
    if not ok:
        display_status("ESP8285 Error", "Not responding")
        return False
    
    # Set WiFi mode to station
    ok, _ = esp_send_cmd("AT+CWMODE=1", "OK")
    if not ok:
        display_status("ESP8285 Error", "Mode failed")
        return False
    
    # Connect to WiFi
    display_status("Connecting WiFi", WIFI_SSID[:16])
    ok, _ = esp_send_cmd(f'AT+CWJAP="{WIFI_SSID}","{WIFI_PASSWORD}"', "OK", 20000)
    if not ok:
        display_status("WiFi Failed!")
        return False
    
    # Set normal mode (not passthrough)
    esp_send_cmd("AT+CIPMODE=0", "OK")
    
    # Enable multiple connections
    esp_send_cmd("AT+CIPMUX=1", "OK")
    
    display_status("WiFi Connected!")
    blink_led(3, 0.1)
    return True

def esp_connect_tcp(link_id, host, port, timeout=10000):
    """Connect to TCP server"""
    cmd = f'AT+CIPSTART={link_id},"TCP","{host}",{port}'
    ok, response = esp_send_cmd(cmd, "OK", timeout)
    return ok

def esp_send_data(link_id, data, timeout=5000):
    """Send data over TCP connection"""
    length = len(data)
    cmd = f'AT+CIPSEND={link_id},{length}'
    
    ok, response = esp_send_cmd(cmd, ">", 2000)
    if not ok:
        return False
    
    # Send the actual data
    esp_uart.write(data)
    
    # Wait for SEND OK
    start = utime.ticks_ms()
    while utime.ticks_diff(utime.ticks_ms(), start) < timeout:
        if esp_uart.any():
            chunk = esp_uart.read()
            if chunk and b"SEND OK" in chunk:
                return True
        time.sleep_ms(10)
    
    return False

def esp_close_tcp(link_id):
    """Close TCP connection"""
    esp_send_cmd(f"AT+CIPCLOSE={link_id}", "OK", 2000)

def esp_check_data():
    """Check for incoming data from ESP8285"""
    if esp_uart.any():
        data = esp_uart.read()
        if data:
            return data
    return None

# -------------------------------
# SPEECH CLIENT
# -------------------------------
class SpeechClient:
    def __init__(self):
        self.audio_link = 0
        self.transcript_link = 1
        self.connected = False
        self.recv_buffer = b""
        
    def connect(self):
        """Connect to speech recognition server"""
        global audio_connected, transcript_connected
        
        display_status("Connecting to", "server...")
        
        # Connect audio socket (link 0)
        if not esp_connect_tcp(self.audio_link, SERVER_IP, SERVER_PORT):
            display_status("Audio connect", "failed!")
            return False
        
        # Send AUDIO identifier
        if not esp_send_data(self.audio_link, b"AUDIO"):
            display_status("Audio init", "failed!")
            return False
        audio_connected = True
        
        time.sleep_ms(500)
        
        # Connect transcript socket (link 1)
        if not esp_connect_tcp(self.transcript_link, SERVER_IP, SERVER_PORT + 1):
            display_status("Transcript", "connect failed!")
            return False
        
        # Send TRANSCRIPT identifier
        if not esp_send_data(self.transcript_link, b"TRANSCRIPT"):
            display_status("Transcript init", "failed!")
            return False
        transcript_connected = True
        
        self.connected = True
        display_status("Server OK!", "Press button", "to record")
        blink_led(2, 0.1)
        return True
    
    def disconnect(self):
        """Disconnect from server"""
        esp_close_tcp(self.audio_link)
        esp_close_tcp(self.transcript_link)
        self.connected = False
        
    def send_audio(self, data):
        """Send audio data with length header"""
        if not self.connected:
            return False
        
        # Create packet: 4-byte length header + audio data
        header = struct.pack('<I', len(data))
        packet = header + bytes(data)
        
        return esp_send_data(self.audio_link, packet, 2000)
    
    def send_stop(self):
        """Send STOP_RECORDING message"""
        if not self.connected:
            return False
        
        msg = b"STOP_RECORDING"
        # Special marker (0xFFFFFFFF) + text length + text
        header = struct.pack('<I', 0xFFFFFFFF)
        text_header = struct.pack('<I', len(msg))
        packet = header + text_header + msg
        
        return esp_send_data(self.audio_link, packet, 2000)
    
    def check_transcript(self):
        """Check for incoming transcript"""
        data = esp_check_data()
        if not data:
            return None
        
        # Add to buffer
        self.recv_buffer += data
        
        # Look for +IPD pattern: +IPD,<link_id>,<len>:<data>
        while b"+IPD" in self.recv_buffer:
            try:
                idx = self.recv_buffer.find(b"+IPD")
                # Find the colon
                colon_idx = self.recv_buffer.find(b":", idx)
                if colon_idx < 0:
                    break
                
                # Parse header: +IPD,<link>,<len>
                header = self.recv_buffer[idx:colon_idx].decode()
                parts = header.replace("+IPD,", "").split(",")
                if len(parts) >= 2:
                    link_id = int(parts[0])
                    data_len = int(parts[1])
                    
                    # Check if we have enough data
                    data_start = colon_idx + 1
                    data_end = data_start + data_len
                    
                    if len(self.recv_buffer) >= data_end:
                        payload = self.recv_buffer[data_start:data_end]
                        # Remove processed data from buffer
                        self.recv_buffer = self.recv_buffer[data_end:]
                        
                        # If this is from transcript link, parse it
                        if link_id == self.transcript_link:
                            return self._parse_transcript(payload)
                    else:
                        # Not enough data yet
                        break
                else:
                    # Malformed, skip this +IPD
                    self.recv_buffer = self.recv_buffer[idx+4:]
            except Exception as e:
                print(f"Parse error: {e}")
                # Clear buffer on error
                self.recv_buffer = b""
                break
        
        return None
    
    def _parse_transcript(self, data):
        """Parse transcript packet"""
        if len(data) < 4:
            return None
        
        length = struct.unpack('<I', data[:4])[0]
        
        # Keepalive packet
        if length == 0:
            return None
        
        # Extract transcript text
        if len(data) >= 4 + length:
            text = data[4:4+length].decode('utf-8', 'ignore')
            return text
        
        return None

# -------------------------------
# MAIN PROGRAM
# -------------------------------
def main():
    global is_recording
    
    display_status("Starting...")
    time.sleep(1)
    
    # Initialize ESP8285 and WiFi
    if not esp_init():
        while True:
            blink_led(5, 0.1)
            time.sleep(2)
    
    # Connect to server
    client = SpeechClient()
    while not client.connect():
        time.sleep(2)
    
    # Main loop
    audio_buffer = bytearray(BUFFER_LENGTH * 2)
    last_transcript = ""
    
    print("Ready! Press button to start/stop recording.")
    
    while True:
        try:
            # Check button press
            if check_button():
                if is_recording:
                    # Stop recording
                    is_recording = False
                    led.off()
                    client.send_stop()
                    display_status("Stopped", "Press button", "to record")
                    print("Recording stopped")
                else:
                    # Start recording
                    is_recording = True
                    led.on()
                    last_transcript = ""
                    display_status("Recording...", "Speak now")
                    print("Recording started")
            
            # If recording, capture and send audio
            if is_recording:
                n = audio_in.readinto(audio_buffer)
                if n > 0:
                    if not client.send_audio(audio_buffer[:n]):
                        print("Send failed, reconnecting...")
                        is_recording = False
                        led.off()
                        client.disconnect()
                        while not client.connect():
                            time.sleep(2)
            
            # Check for transcripts
            transcript = client.check_transcript()
            if transcript and transcript != last_transcript:
                display_transcript(transcript)
                last_transcript = transcript
            
            time.sleep_ms(10)
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(1)
    
    # Cleanup
    client.disconnect()
    audio_in.deinit()
    led.off()
    display_status("Stopped")

if __name__ == "__main__":
    main()