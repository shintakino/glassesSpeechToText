"""
Test 4: ESP8285 WiFi (AT Commands)
----------------------------------
Tests the ESP8285 WiFi module via UART AT commands.
"""

from machine import UART, Pin
import utime
import time

# WiFi credentials - UPDATE THESE!
WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"

# UART settings
UART_ID = 0
UART_BAUD = 115200

print("ESP8285 WiFi Test (AT Commands)")
print(f"UART: {UART_ID} at {UART_BAUD} baud")
print("-" * 40)

# Initialize UART
esp_uart = UART(UART_ID, UART_BAUD)

def send_cmd(cmd, ack="OK", timeout=5000):
    """Send AT command and wait for response"""
    # Clear buffer
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
                    print(f"<< {response.strip()}")
                    return True, response
                if "ERROR" in response:
                    print(f"<< ERROR: {response.strip()}")
                    return False, response
        time.sleep_ms(10)
    
    print(f"<< TIMEOUT: {response.strip()}")
    return False, response

# Test sequence
print("\n1. Exit transparent mode (if stuck)...")
esp_uart.write('+++')
time.sleep(1)
if esp_uart.any():
    esp_uart.read()

print("\n2. Testing AT command...")
ok, _ = send_cmd("AT", "OK", 2000)
if not ok:
    print("FAILED: ESP8285 not responding!")
    print("Check UART wiring and baud rate.")
else:
    print("SUCCESS: ESP8285 responding!")
    
    print("\n3. Getting firmware version...")
    send_cmd("AT+GMR", "OK", 2000)
    
    print("\n4. Setting WiFi mode to Station...")
    send_cmd("AT+CWMODE=1", "OK")
    
    print("\n5. Scanning for networks...")
    ok, response = send_cmd("AT+CWLAP", "OK", 15000)
    if ok:
        print("Networks found!")
    
    print(f"\n6. Connecting to WiFi: {WIFI_SSID}...")
    ok, _ = send_cmd(f'AT+CWJAP="{WIFI_SSID}","{WIFI_PASSWORD}"', "OK", 20000)
    if ok:
        print("SUCCESS: Connected to WiFi!")
        
        print("\n7. Getting IP address...")
        send_cmd("AT+CIFSR", "OK", 2000)
        
        print("\n8. Testing internet connection (ping Google DNS)...")
        # Note: AT+PING may not be available on all firmware
        send_cmd('AT+PING="8.8.8.8"', "OK", 5000)
    else:
        print("FAILED: Could not connect to WiFi")
        print("Check SSID and password")

print("\n" + "-" * 40)
print("ESP8285 test complete!")
