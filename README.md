# Industrial IoT Sensor Network

![Project Status](https://img.shields.io/badge/Status-Complete-brightgreen)
![Timeline](https://img.shields.io/badge/Timeline-August%202017%20--%20December%202017-blue)
![Technology](https://img.shields.io/badge/Tech-Raspberry%20Pi%20%7C%20Arduino%20%7C%20MQTT%20%7C%20InfluxDB-orange)

## Project Overview

Industrial IoT sensor network for manufacturing floor monitoring using Raspberry Pi gateways, Arduino sensor nodes, MQTT messaging, and InfluxDB time-series storage with Grafana dashboards.

**Role**: IT Administrator
**Organization**: Zambaiti
**Duration**: August 2017 - December 2017
**Project**: #23 of 30 in IT Career Portfolio

## Business Impact

- **Real-time Floor Monitoring**: Temperature, humidity, vibration across production zones
- **Predictive Maintenance Alerts**: Early warning for equipment degradation
- **15% Energy Savings**: Environmental optimization based on sensor data
- **Historical Analytics**: Trend analysis for operational improvement

## Technology Stack

- **Raspberry Pi 3**: Edge gateway devices
- **Arduino Uno/Mega**: Sensor data collection nodes
- **MQTT (Mosquitto)**: Lightweight pub/sub messaging
- **InfluxDB 1.3**: Time-series database
- **Grafana 4.x**: Monitoring dashboards

## Project Structure

```
industrial-iot/
├── README.md
├── requirements.txt
├── docker-compose.yml
├── src/
│   ├── sensor_gateway.py
│   ├── mqtt_broker.py
│   └── data_processor.py
├── arduino/
│   └── sensor_node.ino
├── config/
│   ├── influxdb.conf
│   └── mosquitto.conf
└── grafana/
    └── dashboard.json
```

## Contributing

This is a historical project from August 2017 - December 2017, preserved for portfolio purposes.

## License

Professional portfolio project - Zambaiti

---

**Developed during August 2017 - December 2017**
*Part of Alexander Efrem's IT Career Portfolio (2012-2024)*
