/*
 * Host-side stand-in for the Arduino Wire (I2C) library.
 *
 * - Each beginTransmission()/write()/endTransmission() sequence is
 *   recorded in fake::wire_log as the device address and the bytes
 *   written. A two-byte transmission is a register write
 *   (register, value).
 * - read() returns bytes from fake::wire_rx, a queue the test scripts.
 */
#ifndef FAKE_WIRE_H
#define FAKE_WIRE_H

#include <stdint.h>
#include <stddef.h>
#include <deque>
#include <vector>

namespace fake {

struct WireTransmission {
    uint8_t address;
    std::vector<uint8_t> bytes;
};

std::vector<WireTransmission> wire_log;
std::deque<uint8_t> wire_rx;

/* True if a completed transmission to `address` wrote `value` to `reg`. */
inline bool wire_wrote(uint8_t address, uint8_t reg, uint8_t value) {
    for (size_t i = 0; i < wire_log.size(); ++i) {
        const WireTransmission &t = wire_log[i];
        if (t.address == address && t.bytes.size() == 2
                && t.bytes[0] == reg && t.bytes[1] == value) {
            return true;
        }
    }
    return false;
}

}  // namespace fake

class FakeWire {
public:
    void begin() {}

    void beginTransmission(uint8_t address) {
        pending_.address = address;
        pending_.bytes.clear();
    }

    void beginTransmission(int address) { beginTransmission((uint8_t)address); }

    size_t write(uint8_t value) {
        pending_.bytes.push_back(value);
        return 1;
    }

    size_t write(int value) { return write((uint8_t)value); }

    uint8_t endTransmission() {
        fake::wire_log.push_back(pending_);
        pending_.bytes.clear();
        return 0;
    }

    uint8_t requestFrom(int address, int quantity) {
        (void)address;
        int queued = (int)fake::wire_rx.size();
        return (uint8_t)(queued < quantity ? queued : quantity);
    }

    int available() { return (int)fake::wire_rx.size(); }

    int read() {
        if (fake::wire_rx.empty()) {
            return -1;
        }
        uint8_t value = fake::wire_rx.front();
        fake::wire_rx.pop_front();
        return value;
    }

private:
    fake::WireTransmission pending_;
};

FakeWire Wire;

#endif
