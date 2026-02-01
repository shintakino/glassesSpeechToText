"""
Test 2: Button Input
--------------------
Tests button input with debounce.
Press the button and watch the console output.
"""

from machine import Pin
import utime
import time

# PINS - adjust if needed
BUTTON_PIN = 14

# Button with internal pull-up (active LOW)
button = Pin(BUTTON_PIN, Pin.IN, Pin.PULL_UP)

# LED for visual feedback
try:
    led = Pin("LED", Pin.OUT)
except:
    led = Pin(25, Pin.OUT)

# Debounce
last_press_time = 0
DEBOUNCE_MS = 300
press_count = 0

print(f"Button Test - GPIO {BUTTON_PIN}")
print("Press the button to test. Press Ctrl+C to exit.")
print("-" * 40)

try:
    while True:
        current_value = button.value()
        
        # Button pressed (active LOW with pull-up)
        if current_value == 0:
            current_time = utime.ticks_ms()
            if utime.ticks_diff(current_time, last_press_time) > DEBOUNCE_MS:
                last_press_time = current_time
                press_count += 1
                print(f"Button pressed! Count: {press_count}")
                
                # Toggle LED
                led.toggle()
        
        time.sleep_ms(10)
        
except KeyboardInterrupt:
    print("\nButton test ended.")
    print(f"Total presses detected: {press_count}")
    led.off()
