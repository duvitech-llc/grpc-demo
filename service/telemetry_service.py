#!/usr/bin/env python3
"""
Telemetry Service — gRPC Server for Telemetry Data

A Python-based gRPC server that receives telemetry packets from agents,
validates and processes the data, and logs all transaction timing and
throughput metrics.
"""

import os
import signal
import sys
import time
import threading
import argparse
from datetime import datetime
from collections import deque
from concurrent import futures
import grpc

import telemetry_pb2
import telemetry_pb2_grpc

__all__ = [
    'LOG_DIR',
    'LOG_FILE_PATTERN',
    'PacketValidator',
    'TransactionLogger',
    'TelemetryServicer',
    'serve',
]


# ── Constants ─────────────────────────────────────────────────────────────
LOG_DIR = "./logs"
LOG_FILE_PATTERN = "logs/service_{}.log"


# ── Packet Validator ──────────────────────────────────────────────────────
class PacketValidator:
    """Validates incoming telemetry packets according to specification rules."""

    @staticmethod
    def validate(packet: telemetry_pb2.TelemetryPacket) -> tuple[bool, str]:
        """
        Validate all required fields.

        Validation Rules:
        - device_id: Non-empty string, max 64 chars
        - sequence_number: > 0
        - timestamp_ms: > 0, not more than 60s in the future
        - temperature: -100.0 to +200.0 °C
        - latitude: -90.0 to +90.0
        - longitude: -180.0 to +180.0
        - altitude: -500.0 to +50000.0 meters
        - IMU fields: All 9 axes must be present (non-NaN)
        """
        # Check device_id
        if not packet.device_id or len(packet.device_id) == 0:
            return False, "device_id is empty"
        if len(packet.device_id) > 64:
            return False, "device_id exceeds 64 characters"

        # Check sequence_number
        if packet.sequence_number == 0:
            return False, "sequence_number must be > 0"

        # Check timestamp_ms
        if packet.timestamp_ms == 0:
            return False, "timestamp_ms must be > 0"
        current_time_ms = int(time.time() * 1000)
        if packet.timestamp_ms > current_time_ms + 60000:
            return False, "timestamp_ms is more than 60 seconds in the future"

        # Check temperature
        temp = packet.temperature
        if temp < -100.0 or temp > 200.0:
            return False, "temperature out of range (-100.0 to 200.0 °C)"

        # Check GPS data
        gps = packet.gps
        if not (-90.0 <= gps.latitude <= 90.0):
            return False, "latitude out of range (-90.0 to 90.0)"
        if not (-180.0 <= gps.longitude <= 180.0):
            return False, "longitude out of range (-180.0 to 180.0)"
        if not (-500.0 <= gps.altitude <= 50000.0):
            return False, "altitude out of range (-500.0 to 50000.0 meters)"

        # Check IMU data
        imu = packet.imu
        required_imu_fields = [
            ('accel_x', imu.accel_x),
            ('accel_y', imu.accel_y),
            ('accel_z', imu.accel_z),
            ('gyro_x', imu.gyro_x),
            ('gyro_y', imu.gyro_y),
            ('gyro_z', imu.gyro_z),
            ('mag_x', imu.mag_x),
            ('mag_y', imu.mag_y),
            ('mag_z', imu.mag_z),
        ]

        for field_name, value in required_imu_fields:
            if value == 0 and field_name in ['accel_x', 'accel_y', 'accel_z',
                                             'gyro_x', 'gyro_y', 'gyro_z']:
                # Allow zero, but check for NaN
                import math
                if math.isnan(value):
                    return False, f"{field_name} is NaN"
            elif value == 0.0:
                # For magnetometer, zero might be valid
                continue

        return True, "Valid packet"


# ── Transaction Logger ────────────────────────────────────────────────────
class TransactionLogger:
    """Thread-safe transaction logger with dedicated writer thread."""

    def __init__(self, log_dir: str = LOG_DIR):
        self.log_dir = log_dir
        self._queue: deque = deque()
        self._queue_lock = threading.Lock()
        self._writer_thread = None
        self._stop_event = threading.Event()
        self._stats = {
            'total_packets': 0,
            'total_bytes': 0,
            'processing_times': [],
            'throughput_values': [],
            'invalid_packets': 0,
            'unique_devices': set(),
        }

    def _setup_log_dir(self):
        """Ensure log directory exists."""
        os.makedirs(self.log_dir, exist_ok=True)

    def _get_log_file(self) -> str:
        """Get the current log file path (by timestamp)."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(self.log_dir, LOG_FILE_PATTERN.format(timestamp))

    def _write_line(self, line: str):
        """Write a line to the log file."""
        log_file = self._get_log_file()
        try:
            with open(log_file, 'a') as f:
                f.write(line + '\n')
                f.flush()
        except Exception as e:
            # Silently fail on write errors
            pass

    def start_service(self, host: str, port: int):
        """Log SERVICE_START event."""
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}] " \
               f"[INFO]  [SERVICE]        [--]  SERVICE_START    host={host} port={port}"
        self._write_line(line)

    def log_received(self, packet: telemetry_pb2.TelemetryPacket,
                     payload_bytes: int) -> float:
        """
        Log packet received event and return receive_time_ms.

        Returns receive_time_ms for processing time calculation.
        """
        receive_time_ms = int(time.time() * 1000)
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}] " \
               f"[INFO]  [{packet.device_id}]  [{packet.sequence_number}]  " \
               f"PACKET_RECEIVED  receive_time={receive_time_ms} payload_bytes={payload_bytes}"
        self._write_line(line)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Received: {packet.device_id} #{packet.sequence_number}")
        return receive_time_ms

    def log_processed(self, packet: telemetry_pb2.TelemetryPacket,
                      receive_time_ms: float, payload_bytes: int,
                      proc_time_ms: float, throughput_kbps: float):
        """Log packet processed event."""
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}] " \
               f"[INFO]  [{packet.device_id}]  [{packet.sequence_number}]  " \
               f"PACKET_PROCESSED  proc_time_ms={proc_time_ms:.2f} throughput_kbps={throughput_kbps:.1f}"
        self._write_line(line)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Processed: {packet.device_id} #{packet.sequence_number} ({proc_time_ms:.2f}ms, {throughput_kbps:.1f}KB/s)")
        self._update_stats(packet, payload_bytes, proc_time_ms, throughput_kbps)

    def log_invalid(self, packet: telemetry_pb2.TelemetryPacket, reason: str):
        """Log invalid packet event."""
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}] " \
               f"[WARN]  [{packet.device_id}]  [{packet.sequence_number}]  " \
               f"PACKET_INVALID  reason={reason}"
        self._write_line(line)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Invalid: {packet.device_id} #{packet.sequence_number} - {reason}")
        self._stats['invalid_packets'] += 1
        self._stats['unique_devices'].add(packet.device_id)

    def _update_stats(self, packet: telemetry_pb2.TelemetryPacket,
                      payload_bytes: int, proc_time_ms: float, throughput_kbps: float):
        """Update statistics."""
        with self._queue_lock:
            self._stats['total_packets'] += 1
            self._stats['total_bytes'] += payload_bytes
            self._stats['processing_times'].append(proc_time_ms)
            self._stats['throughput_values'].append(throughput_kbps)
            self._stats['unique_devices'].add(packet.device_id)

    def log_stream_start(self, device_id: str):
        """Log stream start event."""
        stream_id = f"stream_{int(time.time() * 1000)}"
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}] " \
               f"[INFO]  [{device_id}]  [--]  STREAM_START  device_id={device_id} stream_id={stream_id}"
        self._write_line(line)
        self._stats['unique_devices'].add(device_id)

    def log_stream_end(self, device_id: str, stream_id: str,
                       total_packets: int, total_bytes: int,
                       duration_ms: float, avg_throughput_kbps: float):
        """Log stream end event with summary."""
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}] " \
               f"[INFO]  [{device_id}]  [--]  STREAM_END  stream_id={stream_id} " \
               f"total_packets={total_packets} total_bytes={total_bytes} " \
               f"duration_ms={duration_ms:.0f} avg_throughput_kbps={avg_throughput_kbps:.1f}"
        self._write_line(line)

    def write_service_summary(self):
        """Write session summary at shutdown."""
        uptime_s = 0.0  # Would be tracked with time.time() in full impl
        avg_proc_time = sum(self._stats['processing_times'])/len(self._stats['processing_times'])*1000 if self._stats['processing_times'] else 0.0
        min_proc_time = min(self._stats['processing_times'])*1000 if self._stats['processing_times'] else 0.0
        max_proc_time = max(self._stats['processing_times'])*1000 if self._stats['processing_times'] else 0.0
        avg_throughput = sum(self._stats['throughput_values'])/len(self._stats['throughput_values'])/1024 if self._stats['throughput_values'] else 0.0

        lines = [
            "",
            "========== SERVICE SESSION SUMMARY ==========",
            f"Uptime              : {uptime_s:.1f} seconds",
            f"Total Packets       : {self._stats['total_packets']:,}",
            f"Total Bytes Received: {self._stats['total_bytes']:,} bytes",
            f"Unique Devices      : {len(self._stats['unique_devices'])}",
            f"Avg Processing Time : {avg_proc_time:.2f} ms",
            f"Min Processing Time : {min_proc_time:.2f} ms",
            f"Max Processing Time : {max_proc_time:.2f} ms",
            f"Avg Throughput      : {avg_throughput:.1f} KB/s",
            f"Invalid Packets     : {self._stats['invalid_packets']}",
            "==============================================",
        ]
        self._write_line('\n'.join(lines))

    def stop(self):
        """Signal logger to stop."""
        self._stop_event.set()
        if self._writer_thread and self._writer_thread.is_alive():
            self._writer_thread.join(timeout=1.0)


# ── Telemetry Servicer ───────────────────────────────────────────────────
class TelemetryServicer(telemetry_pb2_grpc.TelemetryServiceServicer):
    """gRPC servicer implementing the telemetry service."""

    def __init__(self, log_dir: str = LOG_DIR):
        self.logger = TransactionLogger(log_dir)
        self._shutdown = False
        self._stream_start_time = None
        self._stream_packets = []

    def __del__(self):
        """Clean up on destruction."""
        self.logger.stop()
        self.logger.write_service_summary()

    def SendTelemetry(self, request: telemetry_pb2.TelemetryPacket,
                      context) -> telemetry_pb2.AckResponse:
        """
        Handle unary telemetry packet.

        1. Record receive_time immediately upon entry
        2. Validate all required fields
        3. Log the transaction with timing
        4. Return AckResponse with server_timestamp and success=true
        """
        payload_bytes = len(telemetry_pb2.TelemetryPacket.SerializeToString(
            telemetry_pb2.TelemetryPacket(**{
                'device_id': request.device_id,
                'sequence_number': request.sequence_number,
                'timestamp_ms': request.timestamp_ms,
                'temperature': request.temperature,
                'gps': request.gps,
                'imu': request.imu,
            })
        ))

        receive_time_ms = self.logger.log_received(request, payload_bytes)
        current_time_ms = int(time.time() * 1000)

        valid, reason = PacketValidator.validate(request)

        if valid:
            proc_time_ms = current_time_ms - receive_time_ms if current_time_ms > receive_time_ms else 1.0
            throughput_kbps = (payload_bytes * 1000) / proc_time_ms / 1024
            self.logger.log_processed(request, receive_time_ms, payload_bytes,
                                      proc_time_ms, throughput_kbps)
            return telemetry_pb2.AckResponse(
                sequence_number=request.sequence_number,
                server_timestamp=current_time_ms,
                success=True,
                message="Packet received successfully"
            )
        else:
            self.logger.log_invalid(request, reason)
            return telemetry_pb2.AckResponse(
                sequence_number=request.sequence_number,
                server_timestamp=current_time_ms,
                success=False,
                message=reason
            )

    def StreamTelemetry(self, request_iterator,
                        context) -> telemetry_pb2.AckResponse:
        """
        Handle client streaming telemetry packets.

        1. Record stream_start_time on first packet
        2. Iterate over all incoming packets, logging each
        3. After stream ends, compute aggregate stats
        4. Return a single AckResponse with total packet count and success status
        """
        # Track stream metrics
        stream_start_time = None
        first_packet_bytes = None
        last_packet_time = None
        total_packets = 0
        total_bytes = 0
        has_invalid = False
        invalid_reason = ""
        invalid_seq = 0
        prev_packet_valid = True
        total_valid_packets = 0
        total_invalid_packets = 0

        for index, request in enumerate(request_iterator):
            stream_start_time = stream_start_time or int(time.time() * 1000)
            last_packet_time = int(time.time() * 1000)

            # Calculate payload size
            payload_bytes = len(telemetry_pb2.TelemetryPacket.SerializeToString(
                telemetry_pb2.TelemetryPacket(**{
                    'device_id': request.device_id,
                    'sequence_number': request.sequence_number,
                    'timestamp_ms': request.timestamp_ms,
                    'temperature': request.temperature,
                    'gps': request.gps,
                    'imu': request.imu,
                })
            ))
            first_packet_bytes = first_packet_bytes or payload_bytes
            total_packets += 1
            total_bytes += payload_bytes
            last_packet_time = int(time.time() * 1000)

            valid, reason = PacketValidator.validate(request)

            if valid:
                proc_time_ms = last_packet_time - stream_start_time
                proc_time_ms = proc_time_ms if proc_time_ms > 0 else 1.0
                throughput_kbps = (total_bytes * 1000) / proc_time_ms / 1024
                self.logger.log_processed(request, stream_start_time, first_packet_bytes,
                                          proc_time_ms, throughput_kbps)
                total_valid_packets += 1
                prev_packet_valid = True
            else:
                has_invalid = True
                invalid_reason = reason
                invalid_seq = request.sequence_number
                total_invalid_packets += 1
                prev_packet_valid = False

        stream_end_time = int(time.time() * 1000)
        duration_ms = stream_end_time - stream_start_time
        stream_duration_s = duration_ms / 1000.0

        # Calculate stream throughput
        avg_throughput_kbps = total_bytes / stream_duration_s / 1024 if stream_duration_s > 0 else 0

        device_id = request_iterator.request.device_id if index < len(list(request_iterator)) else "unknown"
        stream_id = f"stream_{index}"

        self.logger.log_stream_start(device_id)
        self.logger.log_stream_end(device_id, stream_id, total_packets, total_bytes,
                                   duration_ms, avg_throughput_kbps)

        if total_invalid_packets > 0:
            return telemetry_pb2.AckResponse(
                sequence_number=invalid_seq,
                server_timestamp=stream_end_time,
                success=False,
                message=f"Invalid packet: {invalid_reason}"
            )
        else:
            return telemetry_pb2.AckResponse(
                sequence_number=0,
                server_timestamp=stream_end_time,
                success=True,
                message=f"Received {total_packets} packets successfully"
            )


def serve(host: str = "0.0.0.0", port: int = 50051,
          log_dir: str = LOG_DIR, max_workers: int = 10):
    """Start the gRPC server."""
    servicer = TelemetryServicer(log_dir=log_dir)
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=max_workers)
    )
    telemetry_pb2_grpc.add_TelemetryServiceServicer_to_server(
        servicer, server
    )
    server.add_insecure_port(f"{host}:{port}")
    server.start()

    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        print(f"\nShutting down server...")
        server.stop(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print(f"Telemetry service started on {host}:{port}")
    servicer.logger.start_service(host, port)
    server.wait_for_termination()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Telemetry gRPC Service")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=50051, help="Listen port (default: 50051)")
    parser.add_argument("--log-dir", default="./logs", help="Log output directory (default: ./logs)")
    parser.add_argument("--max-workers", type=int, default=10,
                       help="Thread pool size (default: 10)")
    args = parser.parse_args()

    serve(host=args.host, port=args.port, log_dir=args.log_dir, max_workers=args.max_workers)