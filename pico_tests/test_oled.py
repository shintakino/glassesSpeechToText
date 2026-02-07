"""
Test 1: OLED Display
--------------------
Tests the SSD1306 OLED display via I2C.
If working, you should see text on the display.
"""

from machine import Pin, SoftI2C
import time

# Try to import ssd1306
try:
    import ssd1306
except ImportError:
    print("ERROR: ssd1306 module not found!")
    print("Upload ssd1306.py to your Pico first.")
    raise

# PINS - adjust if needed
SCL_PIN = 5
SDA_PIN = 4

print("Initializing SoftI2C...")
# Use SoftI2C for better compatibility, lower freq for stability
i2c = SoftI2C(scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=200000)

# Scan for I2C devices
devices = i2c.scan()
print(f"I2C devices found: {[hex(d) for d in devices]}")

if not devices:
    print("ERROR: No I2C devices found!")
    print("Check wiring: SCL -> GPIO 1, SDA -> GPIO 0")
else:
    print("Initializing OLED...")
    try:
        oled = ssd1306.SSD1306_I2C(128, 64, i2c)
        
        # Clear screen
        oled.fill(0)
        
        # Display "Hello World"
        oled.text("Hello", 30, 10)
        oled.text("World!", 30, 25)
        
        # Draw a rectangle box around it
        oled.rect(10, 5, 108, 40, 1)
        
        oled.show()
        
        print("SUCCESS: You should see 'Hello World' on the OLED now!")
        
        # Keep it on screen for 5 seconds
        time.sleep(5)
        
        oled.fill(0)
        oled.text("Test Complete", 10, 30)
        oled.show()
        print("OLED test complete!")
        
    except Exception as e:
        print(f"ERROR: OLED init failed: {e}")
