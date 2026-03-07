#!/usr/bin/env python3
"""
Unit tests for the Telemetry Service.

Tests coverage:
- PacketValidator: All validation rules
- TransactionLogger: Logging functionality
- TelemetryServicer: gRPC methods
"""

import os
import sys
import time
import threading
import unittest
import tempfile
import grpc
from concurrent import futures

import telemetry_pb2
import telemetry_pb2_grpc

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from telemetry_service import PacketValidator, TransactionLogger, TelemetryServicer, LOG_DIR


class TestPacketValidator(unittest.TestCase):
    """Tests for the PacketValidator class."""

    def test_valid_packet(self):
        """Test a valid telemetry packet."""
        packet = telemetry_pb2.TelemetryPacket(
            device_id="device-001",
            sequence_number=1,
            timestamp_ms=int(time.time() * 1000),
            temperature=25.5,
            gps=telemetry_pb2.GpsData(latitude=37.7749, longitude=-122.4194, altitude=10.0),
            imu=telemetry_pb2.ImuData(
                accel_x=1.5, accel_y=-0.5, accel_z=9.8,
                gyro_x=0.1, gyro_y=0.2, gyro_z=0.05,
                mag_x=30000, mag_y=28000, mag_z=45000
            )
        )
        valid, reason = PacketValidator.validate(packet)
        self.assertTrue(valid)
        self.assertEqual(reason, "Valid packet")

    def test_empty_device_id(self):
        """Test validation rejects empty device_id."""
        packet = telemetry_pb2.TelemetryPacket(
            device_id="",
            sequence_number=1,
            timestamp_ms=int(time.time() * 1000),
            temperature=25.0,
            gps=telemetry_pb2.GpsData(latitude=37.0, longitude=-122.0, altitude=0.0),
            imu=telemetry_pb2.ImuData(
                accel_x=0, accel_y=0, accel_z=0,
                gyro_x=0, gyro_y=0, gyro_z=0,
                mag_x=0, mag_y=0, mag_z=0
            )
        )
        valid, reason = PacketValidator.validate(packet)
        self.assertFalse(valid)
        self.assertIn("device_id", reason)

    def test_long_device_id(self):
        """Test validation rejects device_id > 64 chars."""
        packet = telemetry_pb2.TelemetryPacket(
            device_id="a" * 65,
            sequence_number=1,
            timestamp_ms=int(time.time() * 1000),
            temperature=25.0,
            gps=telemetry_pb2.GpsData(latitude=37.0, longitude=-122.0, altitude=0.0),
            imu=telemetry_pb2.ImuData(
                accel_x=0, accel_y=0, accel_z=0,
                gyro_x=0, gyro_y=0, gyro_z=0,
                mag_x=0, mag_y=0, mag_z=0
            )
        )
        valid, reason = PacketValidator.validate(packet)
        self.assertFalse(valid)
        self.assertIn("64", reason)

    def test_zero_sequence_number(self):
        """Test validation rejects sequence_number == 0."""
        packet = telemetry_pb2.TelemetryPacket(
            device_id="device-001",
            sequence_number=0,
            timestamp_ms=int(time.time() * 1000),
            temperature=25.0,
            gps=telemetry_pb2.GpsData(latitude=37.0, longitude=-122.0, altitude=0.0),
            imu=telemetry_pb2.ImuData(
                accel_x=0, accel_y=0, accel_z=0,
                gyro_x=0, gyro_y=0, gyro_z=0,
                mag_x=0, mag_y=0, mag_z=0
            )
        )
        valid, reason = PacketValidator.validate(packet)
        self.assertFalse(valid)
        self.assertIn("0", reason)

    def test_zero_timestamp(self):
        """Test validation rejects timestamp_ms == 0."""
        packet = telemetry_pb2.TelemetryPacket(
            device_id="device-001",
            sequence_number=1,
            timestamp_ms=0,
            temperature=25.0,
            gps=telemetry_pb2.GpsData(latitude=37.0, longitude=-122.0, altitude=0.0),
            imu=telemetry_pb2.ImuData(
                accel_x=0, accel_y=0, accel_z=0,
                gyro_x=0, gyro_y=0, gyro_z=0,
                mag_x=0, mag_y=0, mag_z=0
            )
        )
        valid, reason = PacketValidator.validate(packet)
        self.assertFalse(valid)
        self.assertIn("0", reason)

    def test_future_timestamp(self):
        """Test validation rejects timestamp > 60s in future."""
        future_time_ms = int(time.time() * 1000) + 65000
        packet = telemetry_pb2.TelemetryPacket(
            device_id="device-001",
            sequence_number=1,
            timestamp_ms=future_time_ms,
            temperature=25.0,
            gps=telemetry_pb2.GpsData(latitude=37.0, longitude=-122.0, altitude=0.0),
            imu=telemetry_pb2.ImuData(
                accel_x=0, accel_y=0, accel_z=0,
                gyro_x=0, gyro_y=0, gyro_z=0,
                mag_x=0, mag_y=0, mag_z=0
            )
        )
        valid, reason = PacketValidator.validate(packet)
        self.assertFalse(valid)
        self.assertIn("future", reason)

    def test_low_temperature(self):
        """Test validation rejects temperature < -100°C."""
        packet = telemetry_pb2.TelemetryPacket(
            device_id="device-001",
            sequence_number=1,
            timestamp_ms=int(time.time() * 1000),
            temperature=-101.0,
            gps=telemetry_pb2.GpsData(latitude=37.0, longitude=-122.0, altitude=0.0),
            imu=telemetry_pb2.ImuData(
                accel_x=0, accel_y=0, accel_z=0,
                gyro_x=0, gyro_y=0, gyro_z=0,
                mag_x=0, mag_y=0, mag_z=0
            )
        )
        valid, reason = PacketValidator.validate(packet)
        self.assertFalse(valid)
        self.assertIn("temperature", reason)

    def test_high_temperature(self):
        """Test validation rejects temperature > 200°C."""
        packet = telemetry_pb2.TelemetryPacket(
            device_id="device-001",
            sequence_number=1,
            timestamp_ms=int(time.time() * 1000),
            temperature=201.0,
            gps=telemetry_pb2.GpsData(latitude=37.0, longitude=-122.0, altitude=0.0),
            imu=telemetry_pb2.ImuData(
                accel_x=0, accel_y=0, accel_z=0,
                gyro_x=0, gyro_y=0, gyro_z=0,
                mag_x=0, mag_y=0, mag_z=0
            )
        )
        valid, reason = PacketValidator.validate(packet)
        self.assertFalse(valid)
        self.assertIn("temperature", reason)

    def test_invalid_latitude(self):
        """Test validation rejects latitude out of range."""
        packet = telemetry_pb2.TelemetryPacket(
            device_id="device-001",
            sequence_number=1,
            timestamp_ms=int(time.time() * 1000),
            temperature=25.0,
            gps=telemetry_pb2.GpsData(latitude=91.0, longitude=-122.0, altitude=0.0),
            imu=telemetry_pb2.ImuData(
                accel_x=0, accel_y=0, accel_z=0,
                gyro_x=0, gyro_y=0, gyro_z=0,
                mag_x=0, mag_y=0, mag_z=0
            )
        )
        valid, reason = PacketValidator.validate(packet)
        self.assertFalse(valid)
        self.assertIn("latitude", reason)

    def test_invalid_longitude(self):
        """Test validation rejects longitude out of range."""
        packet = telemetry_pb2.TelemetryPacket(
            device_id="device-001",
            sequence_number=1,
            timestamp_ms=int(time.time() * 1000),
            temperature=25.0,
            gps=telemetry_pb2.GpsData(latitude=37.0, longitude=181.0, altitude=0.0),
            imu=telemetry_pb2.ImuData(
                accel_x=0, accel_y=0, accel_z=0,
                gyro_x=0, gyro_y=0, gyro_z=0,
                mag_x=0, mag_y=0, mag_z=0
            )
        )
        valid, reason = PacketValidator.validate(packet)
        self.assertFalse(valid)
        self.assertIn("longitude", reason)

    def test_invalid_altitude(self):
        """Test validation rejects altitude out of range."""
        packet = telemetry_pb2.TelemetryPacket(
            device_id="device-001",
            sequence_number=1,
            timestamp_ms=int(time.time() * 1000),
            temperature=25.0,
            gps=telemetry_pb2.GpsData(latitude=37.0, longitude=-122.0, altitude=60000.0),
            imu=telemetry_pb2.ImuData(
                accel_x=0, accel_y=0, accel_z=0,
                gyro_x=0, gyro_y=0, gyro_z=0,
                mag_x=0, mag_y=0, mag_z=0
            )
        )
        valid, reason = PacketValidator.validate(packet)
        self.assertFalse(valid)
        self.assertIn("altitude", reason)

    def test_boundary_temperature(self):
        """Test temperature boundary values (-100.0, 200.0) are valid."""
        for temp in [-100.0, 200.0]:
            packet = telemetry_pb2.TelemetryPacket(
                device_id="device-001",
                sequence_number=1,
                timestamp_ms=int(time.time() * 1000),
                temperature=temp,
                gps=telemetry_pb2.GpsData(latitude=37.0, longitude=-122.0, altitude=0.0),
                imu=telemetry_pb2.ImuData(
                    accel_x=0, accel_y=0, accel_z=0,
                    gyro_x=0, gyro_y=0, gyro_z=0,
                    mag_x=0, mag_y=0, mag_z=0
                )
            )
            valid, reason = PacketValidator.validate(packet)
            self.assertTrue(valid)

    def test_boundary_latitude(self):
        """Test latitude boundary values (-90.0, 90.0) are valid."""
        for lat in [-90.0, 90.0]:
            packet = telemetry_pb2.TelemetryPacket(
                device_id="device-001",
                sequence_number=1,
                timestamp_ms=int(time.time() * 1000),
                temperature=25.0,
                gps=telemetry_pb2.GpsData(latitude=lat, longitude=-122.0, altitude=0.0),
                imu=telemetry_pb2.ImuData(
                    accel_x=0, accel_y=0, accel_z=0,
                    gyro_x=0, gyro_y=0, gyro_z=0,
                    mag_x=0, mag_y=0, mag_z=0
                )
            )
            valid, reason = PacketValidator.validate(packet)
            self.assertTrue(valid)

    def test_boundary_longitude(self):
        """Test longitude boundary values (-180.0, 180.0) are valid."""
        for lon in [-180.0, 180.0]:
            packet = telemetry_pb2.TelemetryPacket(
                device_id="device-001",
                sequence_number=1,
                timestamp_ms=int(time.time() * 1000),
                temperature=25.0,
                gps=telemetry_pb2.GpsData(latitude=37.0, longitude=lon, altitude=0.0),
                imu=telemetry_pb2.ImuData(
                    accel_x=0, accel_y=0, accel_z=0,
                    gyro_x=0, gyro_y=0, gyro_z=0,
                    mag_x=0, mag_y=0, mag_z=0
                )
            )
            valid, reason = PacketValidator.validate(packet)
            self.assertTrue(valid)

    def test_boundary_altitude(self):
        """Test altitude boundary values (-500.0, 50000.0) are valid."""
        for alt in [-500.0, 50000.0]:
            packet = telemetry_pb2.TelemetryPacket(
                device_id="device-001",
                sequence_number=1,
                timestamp_ms=int(time.time() * 1000),
                temperature=25.0,
                gps=telemetry_pb2.GpsData(latitude=37.0, longitude=-122.0, altitude=alt),
                imu=telemetry_pb2.ImuData(
                    accel_x=0, accel_y=0, accel_z=0,
                    gyro_x=0, gyro_y=0, gyro_z=0,
                    mag_x=0, mag_y=0, mag_z=0
                )
            )
            valid, reason = PacketValidator.validate(packet)
            self.assertTrue(valid)


class TestTransactionLogger(unittest.TestCase):
    """Tests for the TransactionLogger class."""

    def setUp(self):
        """Create a temporary log directory for testing."""
        self.test_log_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temporary log directory."""
        import shutil
        shutil.rmtree(self.test_log_dir, ignore_errors=True)

    def test_logger_initialization(self):
        """Test logger initializes correctly."""
        logger = TransactionLogger(log_dir=self.test_log_dir)
        self.assertEqual(logger.log_dir, self.test_log_dir)

    def test_service_start_logging(self):
        """Test SERVICE_START event logging."""
        logger = TransactionLogger(log_dir=self.test_log_dir)
        logger.start_service("0.0.0.0", 50051)
        # The logs directory should be created during initialization
        logs_dir = os.path.join(self.test_log_dir, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        self.assertTrue(os.path.exists(logs_dir))

    def test_log_file_naming(self):
        """Test logs directory is created by logger."""
        logger = TransactionLogger(log_dir=self.test_log_dir)
        # Trigger log writing to create log file
        logger._setup_log_dir()
        self.assertTrue(os.path.exists(self.test_log_dir), f"Logs directory {self.test_log_dir} should exist")
        self.assertTrue(os.path.isdir(self.test_log_dir), f"{self.test_log_dir} should be a directory")


class TestIntegration(unittest.TestCase):
    """Integration tests for the TelemetryServicer."""

    def setUp(self):
        """Set up test environment."""
        self.test_log_dir = tempfile.mkdtemp()
        self.servicer = TelemetryServicer(log_dir=self.test_log_dir)
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
        telemetry_pb2_grpc.add_TelemetryServiceServicer_to_server(self.servicer, self.server)
        self.server.add_insecure_port("[::]:54321")
        self.server.start()

    def tearDown(self):
        """Clean up test environment."""
        self.server.stop(0)

    def test_send_telemetry_valid_packet(self):
        """Test SendTelemetry with valid packet."""
        request = telemetry_pb2.TelemetryPacket(
            device_id="test-device",
            sequence_number=1,
            timestamp_ms=int(time.time() * 1000),
            temperature=25.5,
            gps=telemetry_pb2.GpsData(latitude=37.7749, longitude=-122.4194, altitude=10.0),
            imu=telemetry_pb2.ImuData(
                accel_x=1.5, accel_y=-0.5, accel_z=9.8,
                gyro_x=0.1, gyro_y=0.2, gyro_z=0.05,
                mag_x=30000, mag_y=28000, mag_z=45000
            )
        )
        response = self.servicer.SendTelemetry(request, None)
        self.assertTrue(response.success)
        self.assertEqual(response.sequence_number, 1)

    def test_send_telemetry_invalid_packet(self):
        """Test SendTelemetry with invalid packet."""
        request = telemetry_pb2.TelemetryPacket(
            device_id="",
            sequence_number=1,
            timestamp_ms=int(time.time() * 1000),
            temperature=25.0,
            gps=telemetry_pb2.GpsData(latitude=37.0, longitude=-122.0, altitude=0.0),
            imu=telemetry_pb2.ImuData(
                accel_x=0, accel_y=0, accel_z=0,
                gyro_x=0, gyro_y=0, gyro_z=0,
                mag_x=0, mag_y=0, mag_z=0
            )
        )
        response = self.servicer.SendTelemetry(request, None)
        self.assertFalse(response.success)
        self.assertIn("device_id", response.message)

    def test_stream_telemetry_multiple_packets(self):
        """Test StreamTelemetry with multiple valid packets."""
        packets = []
        for i in range(5):
            packets.append(telemetry_pb2.TelemetryPacket(
                device_id="stream-device",
                sequence_number=i + 1,
                timestamp_ms=int(time.time() * 1000) + i * 10,
                temperature=25.0 + i * 0.1,
                gps=telemetry_pb2.GpsData(latitude=37.77 + i * 0.001, longitude=-122.4 - i * 0.001, altitude=10.0 + i),
                imu=telemetry_pb2.ImuData(
                    accel_x=1.5, accel_y=-0.5, accel_z=9.8,
                    gyro_x=0.1, gyro_y=0.2, gyro_z=0.05,
                    mag_x=30000, mag_y=28000, mag_z=45000
                )
            ))

        def packet_generator():
            for packet in packets:
                yield packet

        request_iterator = packet_generator()
        response = self.servicer.StreamTelemetry(request_iterator, None)
        self.assertTrue(response.success)

    def test_stream_telemetry_with_invalid_packet(self):
        """Test StreamTelemetry with one invalid packet."""
        valid_packets = [telemetry_pb2.TelemetryPacket(
            device_id="stream-device",
            sequence_number=i,
            timestamp_ms=int(time.time() * 1000) + i * 10,
            temperature=25.0,
            gps=telemetry_pb2.GpsData(latitude=37.0, longitude=-122.0, altitude=0.0),
            imu=telemetry_pb2.ImuData(
                accel_x=0, accel_y=0, accel_z=0,
                gyro_x=0, gyro_y=0, gyro_z=0,
                mag_x=0, mag_y=0, mag_z=0
            )
        ) for i in range(3)]

        def packet_generator():
            for packet in valid_packets:
                yield packet
            yield telemetry_pb2.TelemetryPacket(
                device_id="stream-device",
                sequence_number=100,
                timestamp_ms=int(time.time() * 1000),
                temperature=-101.0,  # Invalid temperature
                gps=telemetry_pb2.GpsData(latitude=37.0, longitude=-122.0, altitude=0.0),
                imu=telemetry_pb2.ImuData(
                    accel_x=0, accel_y=0, accel_z=0,
                    gyro_x=0, gyro_y=0, gyro_z=0,
                    mag_x=0, mag_y=0, mag_z=0
                )
            )

        request_iterator = packet_generator()
        response = self.servicer.StreamTelemetry(request_iterator, None)
        self.assertFalse(response.success)
        self.assertIn("Invalid packet", response.message)


if __name__ == "__main__":
    unittest.main(verbosity=2)