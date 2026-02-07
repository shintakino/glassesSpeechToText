# Glasses Speech-to-Text Schematic

This document outlines the hardware connections for the Glasses Speech-to-Text system.

## System Overview

- **MCU**: Raspberry Pi Pico (RP2040)
- **WiFi**: ESP8285 (via UART)
- **Audio Input**: INMP441 MEMS Microphone (I2S)
- **Display**: SSD1306 OLED 0.96" (I2C)
- **Input**: Push Button (GPIO)
- **Status**: LED (GPIO)

## Pinout Table

| Component | Pin Name | Pico Pin | Description |
|-----------|----------|----------|-------------|
| **ESP8285** | TX | GPIO 1 (UART0 RX) | UART Receive |
| | RX | GPIO 0 (UART0 TX) | UART Transmit |
| | VCC | 3.3V (OUT) | Power |
| | GND | GND | Ground |
| **INMP441** | SCK | GPIO 16 | I2S Serial Clock (BCLK) |
| | WS | GPIO 17 | I2S Word Select (LRCLK) |
| | SD | GPIO 18 | I2S Serial Data (DOUT) |
| | VCC | 3.3V (OUT) | Power |
| | GND | GND | Ground |
| | L/R | GND | Channel Select (Left) |
| **SSD1306** | SCL | GPIO 5 | I2C Clock (SoftI2C) |
| | SDA | GPIO 4 | I2C Data (SoftI2C) |
| | VCC | 3.3V (OUT) | Power |
| | GND | GND | Ground |
| **Button** | Signal | GPIO 14 | Active LOW (Pull-up) |
| | GND | GND | Ground |
| **LED** | Anode | GPIO 25 | Status Indicator |
| | Cathode | GND | Ground |

> **Note:** The ESP8285 on some Pico clones is internally connected to UART0 (GPIO 0/1). If using an external ESP8285 module, wire as above.

## Schematic Diagram

```mermaid
graph TD
    subgraph IntegratedBoard [Pico + ESP8285 Board]
        direction TB
        
        subgraph Internal [Internal Connections]
            Pico_UART_TX[GPIO 0 - UART0 TX] --> ESP_RX[ESP8285 RX]
            ESP_TX[ESP8285 TX] --> Pico_UART_RX[GPIO 1 - UART0 RX]
            Regulator[3.3V Regulator] --> ESP_VCC[ESP Power]
        end

        VSYS[VSYS Pin]
        GND[GND Pin]
        Pico3V3[3.3V OUT Pin]
        
        Pico_I2C_SDA[GPIO 4 - SDA]
        Pico_I2C_SCL[GPIO 5 - SCL]
        
        Pico_I2S_SCK[GPIO 16 - SCK]
        Pico_I2S_WS[GPIO 17 - WS]
        Pico_I2S_SD[GPIO 18 - SD]
        
        Pico_BTN[GPIO 14]
        Pico_LED[GPIO 25]
    end

    subgraph PowerSource [Power System]
        Battery[LiPo Battery 3.7V]
        Charger[TP4056 Charger Module]
        Switch[Power Switch]
        USB[USB Charging]
        
        USB --> Charger
        Battery --> Charger
        Charger -- OUT+ --> Switch
        Charger -- OUT- --> GND
        Switch --> VSYS
    end

    subgraph ExternalComponents [External Components]
        subgraph OLED [SSD1306 OLED Display]
            OLED_SDA[SDA]
            OLED_SCL[SCL]
            OLED_VCC[VCC]
            OLED_GND[GND]
        end

        subgraph Mic [INMP441 Microphone]
            Mic_SCK[SCK]
            Mic_WS[WS]
            Mic_SD[SD]
            Mic_LR[L/R]
            Mic_VCC[VCC]
            Mic_GND[GND]
        end

        subgraph UserInterface [User Interface]
            Button[Push Button]
            StatusLED[Status LED]
        end
    end

    %% External Connections
    Pico3V3 --> OLED_VCC
    GND --> OLED_GND
    Pico3V3 --> Mic_VCC
    GND --> Mic_GND
    GND --> Mic_LR

    Pico_I2C_SDA --> OLED_SDA
    Pico_I2C_SCL --> OLED_SCL

    Pico_I2S_SCK --> Mic_SCK
    Pico_I2S_WS --> Mic_WS
    Mic_SD --> Pico_I2S_SD

    Pico_BTN --> Button
    Button --> GND
    
    Pico_LED --> StatusLED
    StatusLED --> GND
```

## Wiring Notes

1.  **I2C Pull-ups**: The SSD1306 OLED usually has built-in pull-up resistors. If not, add 4.7kΩ resistors from SDA and SCL to 3.3V.
2.  **Microphone Channel**: Connecting L/R to GND selects the Left channel. Connecting to VCC selects Right. Our code uses Mono (Left).
3.  **Power Supply**: Ensure your 3.3V source can supply enough current (~300mA peak) for the ESP8285 WiFi transmission. The Pico's onboard regulator is usually sufficient.
