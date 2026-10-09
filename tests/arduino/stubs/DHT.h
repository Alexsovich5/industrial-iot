/*
 * Host-side stand-in for the Adafruit DHT sensor library. Readings come
 * from fake::dht_temperature and fake::dht_humidity, which tests set
 * (NAN models a failed read).
 */
#ifndef FAKE_DHT_H
#define FAKE_DHT_H

#include <stdint.h>

#define DHT11 11
#define DHT22 22

namespace fake {

float dht_temperature = 0.0f;
float dht_humidity = 0.0f;

}  // namespace fake

class DHT {
public:
    DHT(uint8_t pin, uint8_t type) : pin_(pin), type_(type) {}

    void begin() {}

    float readTemperature(bool fahrenheit = false, bool force = false) {
        (void)fahrenheit;
        (void)force;
        return fake::dht_temperature;
    }

    float readHumidity(bool force = false) {
        (void)force;
        return fake::dht_humidity;
    }

    uint8_t pin() const { return pin_; }
    uint8_t type() const { return type_; }

private:
    uint8_t pin_;
    uint8_t type_;
};

#endif
