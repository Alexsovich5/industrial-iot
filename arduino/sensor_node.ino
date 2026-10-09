/*
 * Industrial IoT Sensor Node
 *
 * Arduino sensor node that reads temperature (DHT22),
 * humidity, and vibration (ADXL345) data, sending
 * readings to Raspberry Pi gateway via serial.
 *
 * Output format: SENSOR_ID,TEMPERATURE,HUMIDITY,VIBRATION
 */

#include <DHT.h>
#include <Wire.h>

#include "sensor_logic.h"

// Pin definitions
#define DHT_PIN 2
#define DHT_TYPE DHT22
#define LED_STATUS 13

// ADXL345 I2C address and registers
#define ADXL345_ADDR 0x53
#define ADXL345_POWER_CTL 0x2D
#define ADXL345_DATA_FORMAT 0x31
#define ADXL345_DATAX0 0x32

// Configuration
const char* SENSOR_ID = "SN-001";
const unsigned long READ_INTERVAL = 5000; // 5 seconds

// Sensor objects
DHT dht(DHT_PIN, DHT_TYPE);

// Variables
unsigned long lastRead = 0;
float temperature = 0;
float humidity = 0;
float vibration = 0;

float readVibration();

void writeRegister(uint8_t reg, uint8_t value) {
    Wire.beginTransmission(ADXL345_ADDR);
    Wire.write(reg);
    Wire.write(value);
    Wire.endTransmission();
}

void setup() {
    Serial.begin(9600);
    dht.begin();
    Wire.begin();
    pinMode(LED_STATUS, OUTPUT);

    // Initialize ADXL345 accelerometer
    writeRegister(ADXL345_DATA_FORMAT, 0x0B); // FULL_RES, +/-16 g, 4 mg/LSB
    writeRegister(ADXL345_POWER_CTL, 0x08);   // Measure mode

    digitalWrite(LED_STATUS, HIGH);
    delay(1000);
    digitalWrite(LED_STATUS, LOW);

    Serial.println("# Sensor node initialized");
}

void loop() {
    unsigned long now = millis();

    if (now - lastRead >= READ_INTERVAL) {
        lastRead = now;

        // Read DHT22
        temperature = dht.readTemperature();
        humidity = dht.readHumidity();

        // Read vibration (accelerometer magnitude)
        vibration = readVibration();

        // Validate readings
        if (isnan(temperature) || isnan(humidity)) {
            digitalWrite(LED_STATUS, HIGH);
            delay(100);
            digitalWrite(LED_STATUS, LOW);
            return;
        }

        // Send CSV: SENSOR_ID,TEMP,HUMIDITY,VIBRATION
        Serial.print(SENSOR_ID);
        Serial.print(",");
        Serial.print(temperature, 1);
        Serial.print(",");
        Serial.print(humidity, 1);
        Serial.print(",");
        Serial.println(vibration, 2);

        // Blink LED on successful read
        digitalWrite(LED_STATUS, HIGH);
        delay(50);
        digitalWrite(LED_STATUS, LOW);
    }
}

float readVibration() {
    // Read the six data registers starting at DATAX0
    Wire.beginTransmission(ADXL345_ADDR);
    Wire.write(ADXL345_DATAX0);
    Wire.endTransmission();
    Wire.requestFrom(ADXL345_ADDR, 6);

    if (Wire.available() >= 6) {
        // Read each byte into its own variable so the order is fixed
        uint8_t x0 = Wire.read();
        uint8_t x1 = Wire.read();
        uint8_t y0 = Wire.read();
        uint8_t y1 = Wire.read();
        uint8_t z0 = Wire.read();
        uint8_t z1 = Wire.read();

        return vibrationMagnitude(combineBytes(x0, x1),
                                  combineBytes(y0, y1),
                                  combineBytes(z0, z1));
    }

    return 0.0;
}
