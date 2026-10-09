/*
 * Host-side stand-in for the Arduino core, used to compile and test
 * arduino/sensor_node.ino with g++.
 *
 * - millis() returns fake::now_ms, which tests set directly; delay()
 *   advances it, as on the board.
 * - Serial appends everything printed to fake::serial_out.
 * - Serial.print(float, digits) is a port of Print::printFloat from the
 *   Arduino AVR Boards core 1.6.20. On AVR, double is a 32-bit float, so
 *   the port does its arithmetic in float to match the board's rounding.
 */
#ifndef FAKE_ARDUINO_H
#define FAKE_ARDUINO_H

#include <stdint.h>
#include <stddef.h>
#include <math.h>
#include <string>

#define HIGH 0x1
#define LOW 0x0
#define INPUT 0x0
#define OUTPUT 0x1

namespace fake {

unsigned long now_ms = 0;
std::string serial_out;
int pin_modes[64];
int pin_levels[64];

}  // namespace fake

inline unsigned long millis() { return fake::now_ms; }

inline void delay(unsigned long ms) { fake::now_ms += ms; }

inline void pinMode(uint8_t pin, uint8_t mode) { fake::pin_modes[pin] = mode; }

inline void digitalWrite(uint8_t pin, uint8_t value) { fake::pin_levels[pin] = value; }

class FakeSerial {
public:
    unsigned long baud;

    FakeSerial() : baud(0) {}

    void begin(unsigned long rate) { baud = rate; }

    size_t print(const char *s) {
        std::string text(s);
        fake::serial_out += text;
        return text.size();
    }

    size_t print(char c) {
        fake::serial_out += c;
        return 1;
    }

    size_t print(unsigned long n) {
        std::string text = std::to_string(n);
        fake::serial_out += text;
        return text.size();
    }

    size_t print(unsigned int n) { return print((unsigned long)n); }

    size_t print(double number, int digits = 2) {
        return printFloat((float)number, (uint8_t)digits);
    }

    size_t println() { return print("\r\n"); }

    size_t println(const char *s) {
        size_t n = print(s);
        return n + println();
    }

    size_t println(double number, int digits = 2) {
        size_t n = print(number, digits);
        return n + println();
    }

private:
    /* Print::printFloat, Arduino AVR Boards core 1.6.20, with double
     * replaced by float (they are the same type on AVR). */
    size_t printFloat(float number, uint8_t digits) {
        size_t n = 0;

        if (isnan(number)) return print("nan");
        if (isinf(number)) return print("inf");
        if (number > 4294967040.0f) return print("ovf");
        if (number < -4294967040.0f) return print("ovf");

        if (number < 0.0f) {
            n += print('-');
            number = -number;
        }

        float rounding = 0.5f;
        for (uint8_t i = 0; i < digits; ++i)
            rounding /= 10.0f;

        number += rounding;

        unsigned long int_part = (unsigned long)number;
        float remainder = number - (float)int_part;
        n += print(int_part);

        if (digits > 0) {
            n += print('.');
        }

        while (digits-- > 0) {
            remainder *= 10.0f;
            unsigned int toPrint = (unsigned int)(remainder);
            n += print(toPrint);
            remainder -= toPrint;
        }

        return n;
    }
};

FakeSerial Serial;

#endif
