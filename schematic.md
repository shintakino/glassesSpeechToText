# Glasses Speech-to-Text Schematic

This document outlines the hardware connections for the Glasses Speech-to-Text system.

## System Overview

- **MCU**: Raspberry Pi Pico (RP2040)
- **WiFi**: ESP8285 (via UART)
- **Audio Input**: INMP441 MEMS Microphone (I2S)
- **Display**: SSD1306 OLED 0.96" (I2C)
- **Storage**: MicroSD Card Module (SPI)
- **Input**: Push Button (GPIO)
- **Status**: Built-in LED (GPIO 25 or 'LED')

## Bill of Materials (BOM)

| Item | Description | Quantity | Notes |
|------|-------------|----------|-------|
| **Pico + ESP8285** | Raspberry Pi Pico clone with onboard ESP8285 | 1 | "Pico W" clone style |
| **INMP441** | MEMS Microphone Module (I2S) | 1 | High quality digital audio |
| **SSD1306** | 0.96" OLED Display (I2C) | 1 | 128x64 pixels |
| **Battery** | 3.7V LiPo Battery (e.g., 600mAh+) | 1 | Connector: JST-PH 2.0 usually |
| **Charger** | TP4056 USB Charger Module | 1 | With protection circuit preferred |
| **MicroSD** | MicroSD Card Breakout Module (SPI) | 1 | 3.3V compatible, with level shifter |
| **Switch** | SPDT Slide Switch | 1 | For power On/Off |
| **Button** | Momentary Push Button | 1 | 6x6mm tactile switch |
| **Resistors** | 4.7kΩ (Optional) | 2 | For I2C Pull-ups (if OLED lacks them) |
| **Capacitor** | 100µF (Optional) | 1 | Across VSYS/GND for power stability |
| **Wires** | Jumper wires / Silicone wire | - | For connections |

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
| **MicroSD** | GND | GND | Ground (Pin 1) |
| | VCC | 3.3V (OUT) | Power (Pin 2) |
| | MISO | GPIO 12 | SPI1 RX / Data Out (Pin 4) |
| | MOSI | GPIO 11 | SPI1 TX / Data In (Pin 5) |
| | SCK | GPIO 10 | SPI1 Clock (Pin 6) |
| | CS | GPIO 13 | SPI1 Chip Select (Pin 7) |
| **Button** | Signal | GPIO 14 | Active LOW (Pull-up) |
| | GND | GND | Ground |
| **LED** | - | Built-in | Status Indicator |

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
            Pico_LED[Built-in LED]
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

        Pico_SPI_SCK[GPIO 10 - SCK]
        Pico_SPI_MOSI[GPIO 11 - MOSI]
        Pico_SPI_MISO[GPIO 12 - MISO]
        Pico_SPI_CS[GPIO 13 - CS]
    end

    subgraph PowerSource [Power System]
        Battery[LiPo Battery 3.7V]
        Charger[TP4056 Charger Module]
        Switch[Power Switch]
        USB[USB Charging]
        Capacitor[100µF Capacitor]
        
        USB --> Charger
        Battery --> Charger
        Charger -- OUT+ --> Switch
        Charger -- OUT- --> GND
        Switch --> VSYS
        VSYS --> Capacitor
        Capacitor --> GND
    end

    subgraph ExternalComponents [External Components]
        subgraph OLED [SSD1306 OLED Display]
            OLED_SDA[SDA]
            OLED_SCL[SCL]
            OLED_VCC[VCC]
            OLED_GND[GND]
            
            R1[4.7k Resistor] -- Pull-up --> OLED_SDA
            R2[4.7k Resistor] -- Pull-up --> OLED_SCL
            Pico3V3 --> R1
            Pico3V3 --> R2
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
        end

        subgraph Storage [MicroSD Card Module]
            SD_SCK[SCK]
            SD_MOSI[MOSI / DI]
            SD_MISO[MISO / DO]
            SD_CS[CS]
            SD_VCC[VCC]
            SD_GND[GND]
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

    Pico3V3 --> SD_VCC
    GND --> SD_GND
    Pico_SPI_SCK --> SD_SCK
    Pico_SPI_MOSI --> SD_MOSI
    SD_MISO --> Pico_SPI_MISO
    Pico_SPI_CS --> SD_CS
```

## Wiring Notes

1.  **I2C Pull-ups**: The SSD1306 OLED usually has built-in pull-up resistors. If not, add 4.7kΩ resistors from SDA and SCL to 3.3V.
2.  **Microphone Channel**: Connecting L/R to GND selects the Left channel. Connecting to VCC selects Right. Our code uses Mono (Left).
3.  **Power Supply**: Ensure your 3.3V source can supply enough current (~300mA peak) for the ESP8285 WiFi transmission. The Pico's onboard regulator is usually sufficient.
4.  **MicroSD Module**: Use a 3.3V-compatible module (most breakout boards include a level shifter). SPI1 is used on GPIO 10-13 to avoid conflicts with I2S (GPIO 16-18) and I2C (GPIO 4-5). Format the SD card as FAT32.
