"""
Test 6: LED Control
-------------------
Simple LED blink test to verify the board is working.
"""

from machine import Pin
import time

# Try to get the onboard LED
try:
    led = Pin("LED", Pin.OUT)
    print("Using Pin('LED') for onboard LED")
except:
    led = Pin(25, Pin.OUT)
    print("Using Pin(25) for onboard LED")

print("LED Blink Test")
print("LED should blink 5 times...")
print("-" * 40)

for i in range(5):
    print(f"Blink {i+1}")
    led.on()
    time.sleep(0.5)
    led.off()
    time.sleep(0.5)

print("\nLED test complete!")
print("If you saw 5 blinks, the LED is working.")
