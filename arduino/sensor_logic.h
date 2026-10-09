/*
 * Pure sensor math for the sensor node, kept free of hardware calls so it
 * can be compiled and tested on the host.
 */
#ifndef SENSOR_LOGIC_H
#define SENSOR_LOGIC_H

#include <stdint.h>
#include <math.h>

/* ADXL345 in FULL_RES mode: 4 mg per LSB at every range. */
const float ADXL345_G_PER_LSB = 0.004f;

/* Join the two data registers of one ADXL345 axis (LSB first). */
inline int16_t combineBytes(uint8_t lsb, uint8_t msb) {
    return (int16_t)((uint16_t)lsb | ((uint16_t)msb << 8));
}

/*
 * Vibration magnitude in g from raw axis counts, with 1 g of gravity
 * removed from Z (the sensor is mounted flat).
 */
inline float vibrationMagnitude(int16_t x, int16_t y, int16_t z) {
    float xg = x * ADXL345_G_PER_LSB;
    float yg = y * ADXL345_G_PER_LSB;
    float zg = z * ADXL345_G_PER_LSB - 1.0f;
    return sqrt(xg * xg + yg * yg + zg * zg);
}

#endif
