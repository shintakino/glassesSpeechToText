"""
Test 7: Full Audio Streaming Test
---------------------------------
Tests the full pipeline:
Microphone -> I2S -> Pico -> ESP8285 -> WiFi -> TCP -> Server

This script will:
1. Connect to WiFi and Server
2. Record audio from the microphone
3. Stream it to the server for 10 seconds
4. Check if server acknowledges receipt (TCP ACK)

Run 'server_speech_recognition.py' on your computer first!
"""

from machine import UART, Pin, I2S
import utime
import time
import struct

# ==========================================
# CONFIGURATION
# ==========================================
# WiFi Credentials
WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
SERVER_IP = "192.168.1.100"  # Update with your PC's IP
SERVER_PORT = 5000

# Pins
SCK_PIN = 16   # I2S SCK
WS_PIN = 17    # I2S WS
SD_PIN = 18    # I2S SD
BUTTON_PIN = 14

# Audio
SAMPLE_RATE = 16000
BITS_PER_SAMPLE = 16
BUFFER_LENGTH = 1600  # 0.1s chunks

# UART
UART_ID = 0
UART_BAUD = 115200
# ==========================================

# Hardware Init
esp_uart = UART(UART_ID, UART_BAUD)
led = Pin("LED", Pin.OUT) if "LED" in dir(Pin) else Pin(25, Pin.OUT)

print("Audio Streaming Test")
print("--------------------")

# -------------------------------
# ESP8285 Functions
# -------------------------------
def send_cmd(cmd, ack="OK", timeout=5000):
    if esp_uart.any():
        esp_uart.read()
    print(f">> {cmd}")
    esp_uart.write(cmd + '\r\n')
    
    start = utime.ticks_ms()
    response = ""
    while utime.ticks_diff(utime.ticks_ms(), start) < timeout:
        if esp_uart.any():
            chunk = esp_uart.read()
            if chunk:
                response += chunk.decode('utf-8', 'ignore')
                if ack in response:
                    print("<< OK")
                    return True
                if "ERROR" in response:
                    print(f"<< ERROR: {response}")
                    return False
        time.sleep_ms(10)
    print("<< TIMEOUT")
    return False

def connect_wifi():
    print("Initializing ESP8285...")
    esp_uart.write('+++')
    time.sleep(1)
    
    if not send_cmd("AT", "OK", 2000): return False
    send_cmd("AT+CWMODE=1", "OK")
    
    print(f"Connecting to {WIFI_SSID}...")
    if not send_cmd(f'AT+CWJAP="{WIFI_SSID}","{WIFI_PASSWORD}"', "OK", 20000):
        print("WiFi Connection Failed!")
        return False
        
    print("WiFi Connected!")
    # Use single connection mode for simple test
    send_cmd("AT+CIPMUX=0", "OK")
    return True

def connect_server():
    print(f"Connecting to {SERVER_IP}:{SERVER_PORT}...")
    if not send_cmd(f'AT+CIPSTART="TCP","{SERVER_IP}",{SERVER_PORT}', "OK", 10000):
        print("Server Connection Failed!")
        return False
    print("Server Connected!")
    
    # Send AUDIO identifier
    msg = b"AUDIO"
    return send_data(msg)

def send_data(data):
    cmd = f"AT+CIPSEND={len(data)}"
    if not send_cmd(cmd, ">", 2000):
        return False
    
    esp_uart.write(data)
    
    # Wait for SEND OK
    start = utime.ticks_ms()
    while utime.ticks_diff(utime.ticks_ms(), start) < 5000:
        if esp_uart.any():
            chunk = esp_uart.read()
            if chunk and b"SEND OK" in chunk:
                return True
        time.sleep_ms(5)
    return False

# -------------------------------
# I2S Setup
# -------------------------------
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
# Main Test
# -------------------------------
try:
    if not connect_wifi():
        raise Exception("WiFi Failed")
        
    if not connect_server():
        raise Exception("Server Failed")
        
    print("\nStarting Stream for 10 seconds...")
    print("Speak into microphone!")
    
    audio_buffer = bytearray(BUFFER_LENGTH * 2)
    start_time = time.time()
    
    packet_count = 0
    
    while time.time() - start_time < 10:
        # 1. Read Mic
        n = audio_in.readinto(audio_buffer)
        
        if n > 0:
            # 2. Add Length Header
            header = struct.pack('<I', n)
            packet = header + audio_buffer[:n]
            
            # 3. Send to Server
            if send_data(packet):
                packet_count += 1
                if packet_count % 10 == 0:
                    print(f"Sent {packet_count} packets...", end='\r')
                led.toggle()
            else:
                print("\nSend failed!")
                break
                
    print(f"\n\nTest Finished! Sent {packet_count} packets.")
    print("Check server logs to see if it received the audio.")

except Exception as e:
    print(f"\nTest Error: {e}")

finally:
    send_cmd("AT+CIPCLOSE", "OK")
    audio_in.deinit()
    led.off()
