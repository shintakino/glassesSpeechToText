"""
Test 2: Button Input
--------------------
Tests button input with debounce.
Press the button and watch the console output.
"""

from machine import Pin, SoftI2C
import utime
import time

try:
    import ssd1306
    HAS_OLED = True
except ImportError:
    print("WARNING: ssd1306 module not found. OLED will be disabled.")
    HAS_OLED = False

# PINS - adjust if needed
BUTTON_PIN = 14
SCL_PIN = 5
SDA_PIN = 4

# Button with internal pull-up (active LOW)
button = Pin(BUTTON_PIN, Pin.IN, Pin.PULL_UP)

# LED for visual feedback
try:
    led = Pin("LED", Pin.OUT)
except:
    led = Pin(25, Pin.OUT)

# Initialize OLED
oled = None
if HAS_OLED:
    try:
        i2c = SoftI2C(scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=200000)
        devices = i2c.scan()
        if devices:
            oled = ssd1306.SSD1306_I2C(128, 64, i2c)
            oled.fill(0)
            oled.text("Button Test", 0, 0)
            oled.text("Waiting...", 0, 20)
            oled.show()
        else:
            print("WARNING: No I2C devices found for OLED.")
    except Exception as e:
        print(f"OLED Init Error: {e}")

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
                
                if oled:
                    oled.fill(0)
                    oled.text("Button Test", 0, 0)
                    oled.text("Pressed!", 0, 20)
                    oled.text(f"Count: {press_count}", 0, 40)
                    oled.show()
                
                # Toggle LED
                led.toggle()
        else:
            # Button released
            button_was_pressed = False
        
        time.sleep_ms(10)
        
except KeyboardInterrupt:
    print("\nButton test ended.")
    print(f"Total presses detected: {press_count}")
    if oled:
        oled.fill(0)
        oled.text("Test ended", 0, 0)
        oled.text(f"Total: {press_count}", 0, 20)
        oled.show()
    led.off()
