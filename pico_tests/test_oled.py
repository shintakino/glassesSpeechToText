"""
Test 1: OLED Display
--------------------
Tests the SSD1306 OLED display via I2C.
If working, you should see text on the display.
"""

from machine import Pin, I2C
import time

# Try to import ssd1306
try:
    import ssd1306
except ImportError:
    print("ERROR: ssd1306 module not found!")
    print("Upload ssd1306.py to your Pico first.")
    raise

# PINS - adjust if needed
SCL_PIN = 1
SDA_PIN = 0

print("Initializing I2C...")
i2c = I2C(0, scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=400000)

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
        
        # Display test text
        oled.text("OLED Test OK!", 0, 0)
        oled.text("Line 2", 0, 16)
        oled.text("Line 3", 0, 32)
        oled.text("Line 4", 0, 48)
        oled.show()
        
        print("SUCCESS: OLED should display text now!")
        
        # Animation test
        print("Running animation test...")
        for i in range(5):
            oled.fill(0)
            oled.text(f"Count: {i}", 0, 0)
            oled.show()
            time.sleep(0.5)
        
        oled.fill(0)
        oled.text("Test Complete!", 0, 0)
        oled.show()
        print("OLED test complete!")
        
    except Exception as e:
        print(f"ERROR: OLED init failed: {e}")
