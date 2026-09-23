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

// Pin definitions
#define DHT_PIN 2
#define DHT_TYPE DHT22
#define VIBRATION_PIN A0
#define LED_STATUS 13

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

void setup() {
    Serial.begin(9600);
    dht.begin();
    Wire.begin();
    pinMode(LED_STATUS, OUTPUT);
    pinMode(VIBRATION_PIN, INPUT);

    // Initialize ADXL345 accelerometer
    Wire.beginTransmission(0x53);
    Wire.write(0x2D); // Power control register
    Wire.write(8);    // Measure mode
    Wire.endTransmission();

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
    // Read ADXL345 accelerometer
    Wire.beginTransmission(0x53);
    Wire.write(0x32); // Start at register 0x32
    Wire.endTransmission();
    Wire.requestFrom(0x53, 6);

    if (Wire.available() >= 6) {
        int16_t x = Wire.read() | (Wire.read() << 8);
        int16_t y = Wire.read() | (Wire.read() << 8);
        int16_t z = Wire.read() | (Wire.read() << 8);

        // Convert to g-force and calculate magnitude
        float xg = x * 0.004;
        float yg = y * 0.004;
        float zg = z * 0.004;

        // Subtract gravity (Z-axis) and return magnitude
        zg -= 1.0;
        return sqrt(xg * xg + yg * yg + zg * zg);
    }

    return 0.0;
}
