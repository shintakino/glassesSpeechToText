"""
Test 5: TCP Connection via ESP8285
----------------------------------
Tests TCP socket connection to the speech recognition server.
Run server_speech_recognition.py on your computer first!
"""

from machine import UART, Pin
import utime
import time
import struct

# Server settings - UPDATE THESE!
SERVER_IP = "192.168.1.100"  # Your computer's IP
SERVER_PORT = 5000

# WiFi credentials - UPDATE THESE!
WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"

# UART
UART_ID = 0
UART_BAUD = 115200

esp_uart = UART(UART_ID, UART_BAUD)

print("TCP Connection Test (via ESP8285)")
print(f"Target: {SERVER_IP}:{SERVER_PORT}")
print("-" * 40)

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
                    print(f"<< OK")
                    return True, response
                if "ERROR" in response:
                    print(f"<< ERROR")
                    return False, response
        time.sleep_ms(10)
    print(f"<< TIMEOUT")
    return False, response

def send_data(data, timeout=5000):
    """Send raw data after AT+CIPSEND"""
    esp_uart.write(data)
    
    start = utime.ticks_ms()
    while utime.ticks_diff(utime.ticks_ms(), start) < timeout:
        if esp_uart.any():
            chunk = esp_uart.read()
            if chunk and b"SEND OK" in chunk:
                return True
        time.sleep_ms(10)
    return False

# Initialize
print("\n1. Initializing ESP8285...")
esp_uart.write('+++')
time.sleep(1)
if esp_uart.any():
    esp_uart.read()

send_cmd("AT", "OK", 2000)
send_cmd("AT+CWMODE=1", "OK")

print("\n2. Connecting to WiFi...")
ok, _ = send_cmd(f'AT+CWJAP="{WIFI_SSID}","{WIFI_PASSWORD}"', "OK", 20000)
if not ok:
    print("FAILED: WiFi connection failed!")
else:
    print("WiFi connected!")
    
    # Use single connection mode
    send_cmd("AT+CIPMUX=0", "OK")
    
    print(f"\n3. Connecting to server {SERVER_IP}:{SERVER_PORT}...")
    ok, _ = send_cmd(f'AT+CIPSTART="TCP","{SERVER_IP}",{SERVER_PORT}', "OK", 10000)
    
    if not ok:
        print("FAILED: Could not connect to server!")
        print("Make sure server_speech_recognition.py is running.")
    else:
        print("Connected to server!")
        
        print("\n4. Sending AUDIO identifier...")
        msg = b"AUDIO"
        ok, _ = send_cmd(f"AT+CIPSEND={len(msg)}", ">", 2000)
        if ok:
            if send_data(msg):
                print("SUCCESS: AUDIO identifier sent!")
            else:
                print("FAILED: Send failed")
        
        print("\n5. Sending test audio packet (zeros)...")
        # Create a fake audio packet: 4-byte length header + audio data
        fake_audio = bytes(320)  # 160 samples of silence
        header = struct.pack('<I', len(fake_audio))
        packet = header + fake_audio
        
        ok, _ = send_cmd(f"AT+CIPSEND={len(packet)}", ">", 2000)
        if ok:
            if send_data(packet):
                print("SUCCESS: Test audio packet sent!")
            else:
                print("FAILED: Send failed")
        
        print("\n6. Closing connection...")
        send_cmd("AT+CIPCLOSE", "OK", 2000)

print("\n" + "-" * 40)
print("TCP test complete!")
print("\nIf everything passed, your Pico can communicate with the server!")
