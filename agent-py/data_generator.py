#!/usr/bin/env python3
"""
Data Generator for Telemetry Agent.

Provides sensor data from various sources:
- Mock data generator for testing
- Hardware abstraction interface for real sensors

Usage:
    # Mock data
    python data_generator.py --mode mock --device-id hw-device

    # Hardware interface (when connected)
    python data_generator.py --mode hardware --device-id hw-device
"""

import time
import math
import random
import argparse
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any, Callable
import serial
import json


@dataclass
class SensorData:
    """Container for sensor readings."""
    temperature: float
    latitude: float
    longitude: float
    altitude: float
    accel_x: float
    accel_y: float
    accel_z: float
    gyro_x: float
    gyro_y: float
    gyro_z: float
    mag_x: float
    mag_y: float
    mag_z: float


class SensorInterface(ABC):
    """Abstract base class for hardware sensor interfaces."""

    def __init__(self, device_id: str):
        self.device_id = device_id
        self._device: Optional[Any] = None

    @abstractmethod
    def connect(self) -> None:
        """Establish connection to the hardware device."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Disconnect from the hardware device."""
        pass

    @abstractmethod
    def read(self) -> SensorData:
        """Read current sensor values."""
        pass


class MockSensor(SensorInterface):
    """Mock sensor data generator for testing."""

    def __init__(self, device_id: str, seed: int = 42):
        super().__init__(device_id)
        self._rng = random.Random(seed)
        self._base_lat = 37.7749
        self._base_lon = -122.4194
        self._base_alt = 10.0

    def connect(self) -> None:
        """Mock connection - no action needed."""
        print(f"[{self.device_id}] Mock sensor connected")

    def close(self) -> None:
        """Mock close - no action needed."""
        pass

    def read(self) -> SensorData:
        """Generate mock sensor readings."""
        # Temperature: -50 to 50 °C with some variation
        temp = 25.0 + self._rng.gauss(0, 2.0)
        
        # GPS: Near San Francisco with small jitter
        lat = self._base_lat + self._rng.gauss(0, 0.001)
        lon = self._base_lon + self._rng.gauss(0, 0.001)
        alt = self._base_alt + self._rng.uniform(-5.0, 5.0)
        
        # IMU: Near static with small noise
        accel_x = self._rng.uniform(-0.1, 0.1)
        accel_y = self._rng.uniform(-0.1, 0.1)
        accel_z = 9.81 + self._rng.gauss(0, 0.05)  # Gravity
        gyro_x = self._rng.uniform(-0.01, 0.01)
        gyro_y = self._rng.uniform(-0.01, 0.01)
        gyro_z = self._rng.uniform(-0.01, 0.01)
        
        # Magnetometer: Near Earth's field (~50000 µT)
        mag_x = 45000 + self._rng.gauss(0, 500)
        mag_y = 40000 + self._rng.gauss(0, 500)
        mag_z = 48000 + self._rng.gauss(0, 500)
        
        return SensorData(
            temperature=temp,
            latitude=round(lat, 6),
            longitude=round(lon, 6),
            altitude=round(alt, 2),
            accel_x=round(accel_x, 4),
            accel_y=round(accel_y, 4),
            accel_z=round(accel_z, 4),
            gyro_x=round(gyro_x, 6),
            gyro_y=round(gyro_y, 6),
            gyro_z=round(gyro_z, 6),
            mag_x=round(mag_x, 2),
            mag_y=round(mag_y, 2),
            mag_z=round(mag_z, 2),
        )


class SerialIMUSensor(SensorInterface):
    """IMU sensor connected via serial port."""

    def __init__(self, device_id: str, port: str = "/dev/ttyUSB0", baud: int = 115200):
        super().__init__(device_id)
        self._port = port
        self._baud = baud

    def connect(self) -> None:
        """Connect to serial port."""
        try:
            import serial
            self._device = serial.Serial(self._port, self._baud, timeout=1.0)
            self._device.flushInput()
            self._device.flushOutput()
            print(f"[{self.device_id}] Connected to {self._port}")
        except Exception as e:
            print(f"[{self.device_id}] Failed to connect to {self._port}: {e}")
            raise

    def close(self) -> None:
        """Disconnect from serial port."""
        if self._device and self._device.is_open:
            self._device.close()

    def read(self) -> SensorData:
        """Read IMU data from serial."""
        # Read raw bytes (assumes 48-byte packet format)
        try:
            data = self._device.read(48)
            if len(data) < 48:
                raise Exception("Incomplete packet")
            
            # Parse IMU data (assume little-endian float32)
            import struct
            accel_x = struct.unpack('<f', data[0:4])[0]
            accel_y = struct.unpack('<f', data[4:8])[0]
            accel_z = struct.unpack('<f', data[8:12])[0]
            gyro_x = struct.unpack('<f', data[12:16])[0]
            gyro_y = struct.unpack('<f', data[16:20])[0]
            gyro_z = struct.unpack('<f', data[20:24])[0]
            mag_x = struct.unpack('<f', data[24:28])[0]
            mag_y = struct.unpack('<f', data[28:32])[0]
            mag_z = struct.unpack('<f', data[32:36])[0]
            seq = struct.unpack('<H', data[36:38])[0]
            
            # Read temperature and GPS from separate I2C (simplified)
            temp_data = self._device.read(4)
            temperature = struct.unpack('<f', temp_data)[0]
            
            # GPS data (simplified)
            lat = 37.7749 + seq * 0.0001
            lon = -122.4194 + seq * 0.0001
            alt = 10.0 + seq * 0.1
            
            return SensorData(
                temperature=round(temperature, 2),
                latitude=round(lat, 6),
                longitude=round(lon, 6),
                altitude=round(alt, 2),
                accel_x=round(accel_x, 4),
                accel_y=round(accel_y, 4),
                accel_z=round(accel_z, 4),
                gyro_x=round(gyro_x, 6),
                gyro_y=round(gyro_y, 6),
                gyro_z=round(gyro_z, 6),
                mag_x=round(mag_x, 2),
                mag_y=round(mag_y, 2),
                mag_z=round(mag_z, 2),
            )
        except Exception as e:
            print(f"[{self.device_id}] Read error: {e}")
            raise


class MockGPS:
    """Mock GPS data generator."""

    def __init__(self, base_lat: float = 37.7749, base_lon: float = -122.4194):
        self._base_lat = base_lat
        self._base_lon = base_lon

    def read(self, offset: Optional[float] = None) -> tuple:
        """Read mock GPS coordinates."""
        lat = self._base_lat + (offset or random.gauss(0, 0.001))
        lon = self._base_lon + (offset or random.gauss(0, 0.001))
        return round(lat, 6), round(lon, 6)


class MockTemperature:
    """Mock temperature sensor."""

    def __init__(self, nominal: float = 25.0):
        self._nominal = nominal

    def read(self) -> float:
        """Read mock temperature."""
        return round(self._nominal + random.gauss(0, 1.5), 2)


class MockAltitude:
    """Mock altitude sensor (barometric)."""

    def __init__(self, nominal: float = 10.0):
        self._nominal = nominal

    def read(self) -> float:
        """Read mock altitude."""
        return round(self._nominal + random.uniform(-2.0, 2.0), 2)


class HardwareSensorInterface:
    """Hardware abstraction interface for connecting to real sensors."""

    def __init__(self, device_id: str):
        self.device_id = device_id
        self._sensor: Optional[SensorInterface] = None
        self._temp = MockTemperature()
        self._gps = MockGPS()
        self._alt = MockAltitude()

    def connect(self, sensor_mode: str = "mock") -> None:
        """Connect to hardware sensors."""
        if sensor_mode == "mock":
            self._sensor = MockSensor(self.device_id)
        else:
            self._sensor = SerialIMUSensor(self.device_id)
        self._sensor.connect()

    def close(self) -> None:
        """Disconnect from sensors."""
        if self._sensor:
            self._sensor.close()

    def read(self) -> SensorData:
        """Read all sensor data."""
        sensor_data = self._sensor.read()
        
        # Update temperature, GPS, and altitude from mock sources
        # (In real implementation, these would come from actual sensors)
        temp = self._temp.read()
        lat, lon = self._gps.read()
        alt = self._alt.read()
        
        return SensorData(
            temperature=temp,
            latitude=lat,
            longitude=lon,
            altitude=alt,
            accel_x=sensor_data.accel_x,
            accel_y=sensor_data.accel_y,
            accel_z=sensor_data.accel_z,
            gyro_x=sensor_data.gyro_x,
            gyro_y=sensor_data.gyro_y,
            gyro_z=sensor_data.gyro_z,
            mag_x=sensor_data.mag_x,
            mag_y=sensor_data.mag_y,
            mag_z=sensor_data.mag_z,
        )


class DataGenerator:
    """Data generator for telemetry packets."""

    def __init__(self, device_id: str, sensor_mode: str = "mock"):
        self.device_id = device_id
        self._interface = HardwareSensorInterface(device_id)
        self._sensor_mode = sensor_mode

    def connect(self) -> None:
        """Connect to sensors."""
        self._interface.connect(self._sensor_mode)

    def close(self) -> None:
        """Disconnect from sensors."""
        self._interface.close()

    def read(self) -> SensorData:
        """Read sensor data."""
        return self._interface.read()

    def read_mock(self) -> SensorData:
        """Read mock sensor data (no hardware connection needed)."""
        self._sensor_mode = "mock"
        self._interface.connect("mock")
        return self._interface.read()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Telemetry Data Generator")
    parser.add_argument("--device-id", default="hw-device", help="Device identifier")
    parser.add_argument("--mode", choices=["mock", "hardware"], default="mock",
                       help="Data source mode")
    parser.add_argument("--output", choices=["json", "text"], default="text",
                       help="Output format")
    args = parser.parse_args()

    generator = DataGenerator(args.device_id, args.mode)
    generator.connect()

    print(f"[{args.device_id}] Data generator ready (mode: {args.mode})")
    print("=" * 60)

    try:
        for i in range(10):
            sensor_data = generator.read()
            if args.output == "json":
                print(json.dumps(sensor_data.__dict__, indent=2))
            else:
                print(f"Packet {i+1}:")
                print(f"  Temperature:    {sensor_data.temperature:.2f} °C")
                print(f"  Latitude:       {sensor_data.latitude:.6f}")
                print(f"  Longitude:      {sensor_data.longitude:.6f}")
                print(f"  Altitude:       {sensor_data.altitude:.2f} m")
                print(f"  Accel X:        {sensor_data.accel_x:.4f} m/s²")
                print(f"  Accel Y:        {sensor_data.accel_y:.4f} m/s²")
                print(f"  Accel Z:        {sensor_data.accel_z:.4f} m/s²")
                print(f"  Gyro X:         {sensor_data.gyro_x:.6f} rad/s")
                print(f"  Gyro Y:         {sensor_data.gyro_y:.6f} rad/s")
                print(f"  Gyro Z:         {sensor_data.gyro_z:.6f} rad/s")
                print(f"  Mag X:          {sensor_data.mag_x:.2f} µT")
                print(f"  Mag Y:          {sensor_data.mag_y:.2f} µT")
                print(f"  Mag Z:          {sensor_data.mag_z:.2f} µT")
            print()
            time.sleep(0.5)  # Small delay between reads
    finally:
        generator.close()


if __name__ == "__main__":
    main()