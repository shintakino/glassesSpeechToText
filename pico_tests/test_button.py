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

# Debounce and State
last_press_time = 0
DEBOUNCE_MS = 300
press_count = 0
button_was_pressed = False 

print(f"Button Test - GPIO {BUTTON_PIN}")
print("Press the button to test. Press Ctrl+C to exit.")
print("-" * 40)

try:
    while True:
        current_value = button.value()
        current_time = utime.ticks_ms()
        
        # Check for button press (active LOW)
        if current_value == 0:
            # Only trigger if button wasn't already pressed and debounce time passed
            if not button_was_pressed and utime.ticks_diff(current_time, last_press_time) > DEBOUNCE_MS:
                last_press_time = current_time
                press_count += 1
                button_was_pressed = True
                print(f"Button pressed! Count: {press_count}")
                
                # Toggle LED
                led.toggle()
        else:
            # Button released
            button_was_pressed = False
        
        time.sleep_ms(10)
        
except KeyboardInterrupt:
    print("\nButton test ended.")
    print(f"Total presses detected: {press_count}")
    led.off()
