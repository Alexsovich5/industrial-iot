/*
 * Host-side tests for arduino/sensor_node.ino.
 *
 * Built with the fake Arduino, Wire and DHT headers in tests/arduino/stubs:
 *   g++ -std=c++11 -Wall -Werror -Itests/arduino/stubs -Iarduino \
 *       -x c++ tests/arduino/test_sensor_node.cpp -o build/test_sensor_node
 */
#include <Arduino.h>
#include <math.h>
#include <stdio.h>
#include <string>

#include "sensor_node.ino"

static int failures = 0;
static int checks = 0;

#define CHECK(cond) check((cond), #cond, __FILE__, __LINE__)

static void check(bool ok, const char *expr, const char *file, int line) {
    ++checks;
    if (!ok) {
        ++failures;
        fprintf(stderr, "%s:%d: check failed: %s\n", file, line, expr);
    }
}

static void check_equal(const std::string &actual, const std::string &expected,
                        const char *what) {
    ++checks;
    if (actual != expected) {
        ++failures;
        fprintf(stderr, "%s: expected \"%s\", got \"%s\"\n",
                what, expected.c_str(), actual.c_str());
    }
}

static bool near(float a, float b) { return fabs(a - b) < 1e-4; }

/* Little-endian byte pairs for x, y, z, as the ADXL345 returns them. */
static void script_axes(int16_t x, int16_t y, int16_t z) {
    int16_t axes[3] = {x, y, z};
    for (int i = 0; i < 3; ++i) {
        uint16_t raw = (uint16_t)axes[i];
        fake::wire_rx.push_back((uint8_t)(raw & 0xFF));
        fake::wire_rx.push_back((uint8_t)(raw >> 8));
    }
}

static void reset_board() {
    fake::now_ms = 0;
    fake::serial_out.clear();
    fake::wire_log.clear();
    fake::wire_rx.clear();
    fake::dht_temperature = 0.0f;
    fake::dht_humidity = 0.0f;
    lastRead = 0;
}

/* Run setup() and drop its banner so tests see only loop() output. */
static void boot() {
    reset_board();
    setup();
    fake::serial_out.clear();
}

static void test_vibration_at_rest_is_zero() {
    CHECK(near(vibrationMagnitude(0, 0, 250), 0.0f));
}

static void test_vibration_one_g_on_x() {
    CHECK(near(vibrationMagnitude(250, 0, 250), 1.0f));
}

static void test_combine_bytes_negative() {
    CHECK(combineBytes(0x18, 0xFC) == -1000);
    CHECK(combineBytes(0xFA, 0x00) == 250);
}

static void test_setup_prints_banner() {
    reset_board();
    setup();
    CHECK(fake::serial_out.find("# Sensor node initialized\r\n") != std::string::npos);
    CHECK(Serial.baud == 9600);
}

static void test_setup_configures_adxl345() {
    reset_board();
    setup();
    CHECK(fake::wire_wrote(0x53, 0x31, 0x0B));
    CHECK(fake::wire_wrote(0x53, 0x2D, 0x08));
}

static void test_no_output_before_interval() {
    boot();
    fake::dht_temperature = 23.44f;
    fake::dht_humidity = 41.26f;
    script_axes(0, 0, 250);
    fake::now_ms = 4999;
    loop();
    check_equal(fake::serial_out, "", "output before 5000 ms");
}

static void test_reading_line_format() {
    boot();
    fake::dht_temperature = 23.44f;
    fake::dht_humidity = 41.26f;
    script_axes(300, -1000, 250);  /* 1.2 g, -4.0 g, 0 g after gravity */
    fake::now_ms = 5000;
    loop();
    check_equal(fake::serial_out, "SN-001,23.4,41.3,4.18\r\n", "reading line");
}

static void test_next_reading_waits_for_interval() {
    boot();
    fake::dht_temperature = 23.44f;
    fake::dht_humidity = 41.26f;
    script_axes(0, 0, 250);
    fake::now_ms = 5000;
    loop();
    fake::serial_out.clear();

    script_axes(0, 0, 250);
    fake::now_ms = 9999;
    loop();
    check_equal(fake::serial_out, "", "output before next interval");

    fake::now_ms = 10000;
    loop();
    check_equal(fake::serial_out, "SN-001,23.4,41.3,0.00\r\n", "second reading line");
}

static void test_nan_temperature_emits_nothing() {
    boot();
    fake::dht_temperature = NAN;
    fake::dht_humidity = 41.26f;
    script_axes(0, 0, 250);
    fake::now_ms = 5000;
    loop();
    check_equal(fake::serial_out, "", "output on NaN temperature");
}

static void test_nan_humidity_emits_nothing() {
    boot();
    fake::dht_temperature = 23.44f;
    fake::dht_humidity = NAN;
    script_axes(0, 0, 250);
    fake::now_ms = 5000;
    loop();
    check_equal(fake::serial_out, "", "output on NaN humidity");
}

static void test_print_float_uses_arduino_rounding() {
    /* printFloat adds half of the last digit in float arithmetic and then
     * truncates digit by digit, which differs from printf("%.Nf") on
     * these values (printf gives 2.67, 0.3 and 0.62). */
    fake::serial_out.clear();
    Serial.print(2.675f, 2);
    check_equal(fake::serial_out, "2.68", "print(2.675, 2)");

    fake::serial_out.clear();
    Serial.print(0.35f, 1);
    check_equal(fake::serial_out, "0.4", "print(0.35, 1)");

    fake::serial_out.clear();
    Serial.print(0.615f, 2);
    check_equal(fake::serial_out, "0.61", "print(0.615, 2)");

    fake::serial_out.clear();
    Serial.print(1.999f, 2);
    check_equal(fake::serial_out, "2.00", "print(1.999, 2)");

    fake::serial_out.clear();
    Serial.print(-3.25f, 1);
    check_equal(fake::serial_out, "-3.2", "print(-3.25, 1)");

    fake::serial_out.clear();
    Serial.print((float)NAN, 2);
    check_equal(fake::serial_out, "nan", "print(NAN, 2)");

    fake::serial_out.clear();
    Serial.print(5e9f, 2);
    check_equal(fake::serial_out, "ovf", "print(5e9, 2)");
}

int main() {
    test_vibration_at_rest_is_zero();
    test_vibration_one_g_on_x();
    test_combine_bytes_negative();
    test_setup_prints_banner();
    test_setup_configures_adxl345();
    test_no_output_before_interval();
    test_reading_line_format();
    test_next_reading_waits_for_interval();
    test_nan_temperature_emits_nothing();
    test_nan_humidity_emits_nothing();
    test_print_float_uses_arduino_rounding();

    if (failures) {
        fprintf(stderr, "%d of %d checks failed\n", failures, checks);
        return 1;
    }
    printf("sensor_node: %d checks passed\n", checks);
    return 0;
}
