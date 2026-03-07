#!/usr/bin/env python3
"""
Telemetry Agent — Python implementation for rapid prototyping.

Packs sensor data into gRPC TelemetryPacket messages and sends them
to the Telemetry Service using either unary RPC or client streaming RPC.

Usage:
    # Mock data
    python telemetry_agent.py --device-id agent-001 --mode mock

    # With hardware interface
    python telemetry_agent.py --device-id hw-device --mode hardware

"""

import os
import sys
import time
import argparse
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import grpc

import telemetry_pb2
import telemetry_pb2_grpc

from data_generator import DataGenerator, SensorData


@dataclass
class TransactionRecord:
    """Record of a successful packet transmission."""
    seq: int
    send_time_ms: int
    ack_time_ms: int
    rtt_ms: float
    throughput_kbps: float


class TransactionLogger:
    """Thread-safe transaction logger for the agent."""

    def __init__(self, device_id: str, log_dir: str = "./logs"):
        self.device_id = device_id
        self.log_dir = log_dir
        self._records: List[TransactionRecord] = []
        self._lock = __import__('threading').Lock()
        self._log_file: Optional[object] = None
        os.makedirs(log_dir, exist_ok=True)

    def _get_log_file(self) -> str:
        """Get log file path."""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        return os.path.join(self.log_dir, f"agent_{self.device_id}_{timestamp}.log")

    def _write_line(self, line: str):
        """Write a log line."""
        try:
            with open(self._get_log_file(), 'a') as f:
                f.write(line + '\n')
        except Exception:
            pass  # Silent fail on write errors

    def log_packet_created(self, seq: int, device_id: str, 
                          timestamp_ms: int, payload_bytes: int) -> None:
        """Log packet creation event."""
        line = f"[{time.strftime('%H:%M:%S')}] [INFO] [{device_id}] [{seq}] " \
               f"PACKET_CREATED  seq={seq} device_id={device_id[:8]} " \
               f"timestamp_ms={timestamp_ms} payload_bytes={payload_bytes}"
        self._write_line(line)

    def log_send_start(self, seq: int, send_time_ms: int) -> float:
        """Log send start event and return send time."""
        line = f"[{time.strftime('%H:%M:%S')}] [INFO] [AGNT] [{seq}] " \
               f"SEND_START  seq={seq} send_time={send_time_ms}"
        self._write_line(line)
        return send_time_ms

    def log_ack_received(self, seq: int, send_time_ms: int, 
                        payload_bytes: int, ack_time_ms: int) -> None:
        """Log ACK received event."""
        rtt_ms = ack_time_ms - send_time_ms
        # Avoid division by zero for very fast responses
        if rtt_ms < 0.001:
            rtt_ms = 0.001
        throughput_kbps = (payload_bytes * 2 * 1000) / rtt_ms / 1024
        line = f"[{time.strftime('%H:%M:%S')}] [INFO] [{seq}] " \
               f"ACK_RECEIVED  rtt_ms={rtt_ms:.2f} throughput_kbps={throughput_kbps:.1f}"
        self._write_line(line)

    def log_error(self, seq: int, error: str) -> None:
        """Log error event."""
        line = f"[{time.strftime('%H:%M:%S')}] [ERROR] [{seq}] " \
               f"SEND_ERROR  error={error[:50]}"
        self._write_line(line)

    def write_session_summary(self, records: List[TransactionRecord]) -> None:
        """Write session summary at shutdown."""
        if not records:
            return

        total_packets = len(records)
        total_bytes = sum(
            (len(telemetry_pb2.TelemetryPacket.SerializeToString(
                telemetry_pb2.TelemetryPacket(
                    device_id=self.device_id,
                    sequence_number=r.seq,
                    timestamp_ms=1,
                    temperature=0.0,
                    gps=telemetry_pb2.GpsData(latitude=0, longitude=0, altitude=0),
                    imu=telemetry_pb2.ImuData(
                        accel_x=0, accel_y=0, accel_z=0,
                        gyro_x=0, gyro_y=0, gyro_z=0,
                        mag_x=0, mag_y=0, mag_z=0
                    )
                ))) for r in records)
        )
        
        avg_rtt = sum(r.rtt_ms for r in records) / total_packets
        avg_throughput = sum(r.throughput_kbps for r in records) / total_packets
        duration_s = (records[-1].ack_time_ms - records[0].send_time_ms) / 1000

        summary = f"""
========== SESSION SUMMARY ==========
Device ID       : {self.device_id}
Total Packets   : {total_packets}
Total Bytes Sent: {total_bytes:,} bytes
Duration        : {duration_s:.2f} seconds
Avg RTT         : {avg_rtt:.2f} ms
Min RTT         : {min(r.rtt_ms for r in records):.2f} ms
Max RTT         : {max(r.rtt_ms for r in records):.2f} ms
Avg Throughput  : {avg_throughput:.1f} KB/s
=====================================
"""
        self._write_line(summary)


class TelemetryAgent:
    """
    Telemetry Agent for sending telemetry packets to the gRPC service.

    Provides methods to:
    - Build telemetry packets from sensor data
    - Send packets via unary RPC or client streaming RPC
    - Handle connection errors with exponential backoff
    """

    def __init__(self, host: str = "localhost", port: int = 50051,
                 device_id: str = "agent-py-001", log_dir: str = "./logs"):
        self.host = host
        self.port = port
        self.device_id = device_id
        self.log_dir = log_dir
        self._channel: Optional[grpc.Channel] = None
        self._stub: Optional[telemetry_pb2_grpc.TelemetryServiceStub] = None
        self._logger = TransactionLogger(device_id, log_dir)

    def connect(self) -> None:
        """Connect to the Telemetry Service."""
        try:
            self._channel = grpc.insecure_channel(f"{self.host}:{self.port}")
            self._stub = telemetry_pb2_grpc.TelemetryServiceStub(self._channel)
            print(f"[{self.device_id}] Connected to {self.host}:{self.port}")
        except Exception as e:
            print(f"[{self.device_id}] Failed to connect: {e}")
            raise

    def close(self) -> None:
        """Close the gRPC channel."""
        if self._channel:
            self._channel.close()
            print(f"[{self.device_id}] Disconnected")

    def build_packet(self, seq: int, sensor_data: SensorData, timestamp_ms: Optional[int] = None) -> telemetry_pb2.TelemetryPacket:
        """
        Build a TelemetryPacket from sensor data.

        Args:
            seq: Sequence number for the packet
            sensor_data: SensorData object with all sensor readings
            timestamp_ms: Optional timestamp (defaults to current time if not provided)

        Returns:
            TelemetryPacket protobuf message
        """
        timestamp = timestamp_ms or int(time.time() * 1000)
        
        packet = telemetry_pb2.TelemetryPacket(
            device_id=self.device_id,
            sequence_number=seq,
            timestamp_ms=timestamp,
            temperature=sensor_data.temperature,
            gps=telemetry_pb2.GpsData(
                latitude=sensor_data.latitude,
                longitude=sensor_data.longitude,
                altitude=sensor_data.altitude,
            ),
            imu=telemetry_pb2.ImuData(
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
        )
        
        payload_bytes = len(telemetry_pb2.TelemetryPacket.SerializeToString(packet))
        self._logger.log_packet_created(seq, self.device_id, timestamp, payload_bytes)
        
        return packet

    def send_unary(self, packet: telemetry_pb2.TelemetryPacket) -> TransactionRecord:
        """
        Send a single packet via unary RPC.

        Args:
            packet: TelemetryPacket to send

        Returns:
            TransactionRecord with timing metrics

        Raises:
            grpc.RpcError: If service is unavailable
        """
        try:
            send_time_ms = int(time.time() * 1000)
            self._logger.log_send_start(packet.sequence_number, send_time_ms)

            response = self._stub.SendTelemetry(packet, timeout=5.0)

            ack_time_ms = int(time.time() * 1000)
            rtt_ms = ack_time_ms - send_time_ms
            # Avoid division by zero
            payload_bytes = len(telemetry_pb2.TelemetryPacket.SerializeToString(packet))
            if rtt_ms < 0.001:
                rtt_ms = 0.001
            throughput_kbps = (payload_bytes * 2 * 1000) / rtt_ms / 1024

            self._logger.log_ack_received(
                packet.sequence_number, send_time_ms, payload_bytes, ack_time_ms
            )

            print(f"[{self.device_id}] Packet {packet.sequence_number}: RTT={rtt_ms:.2f}ms "
                  f"Throughput={throughput_kbps:.1f}KB/s "
                  f"{'[SUCCESS]' if response.success else f'[FAILED: {response.message}]'}")

            return TransactionRecord(
                seq=packet.sequence_number,
                send_time_ms=send_time_ms,
                ack_time_ms=ack_time_ms,
                rtt_ms=rtt_ms,
                throughput_kbps=throughput_kbps,
            )

        except grpc.RpcError as e:
            error_code = getattr(e, 'code()', 'UNKNOWN')
            error_msg = str(e)
            self._logger.log_error(packet.sequence_number, error_msg)
            print(f"[{self.device_id}] Packet {packet.sequence_number}: "
                  f"SendError: {error_msg}")
            raise

    def send_stream(self, packets: List[telemetry_pb2.TelemetryPacket]) -> TransactionRecord:
        """
        Send a stream of packets via client streaming RPC.

        Args:
            packets: List of TelemetryPacket messages to send

        Returns:
            TransactionRecord with aggregate timing metrics

        Raises:
            grpc.RpcError: If service is unavailable
        """
        try:
            send_time_ms = int(time.time() * 1000)
            total_packets = len(packets)
            total_bytes = sum(
                len(telemetry_pb2.TelemetryPacket.SerializeToString(
                    telemetry_pb2.TelemetryPacket(
                        device_id=p.device_id,
                        sequence_number=p.sequence_number,
                        timestamp_ms=0,
                        temperature=p.temperature,
                        gps=p.gps,
                        imu=p.imu,
                    )
                )) for p in packets
            )

            # Log first packet
            first_packet = packets[0]
            self._logger.log_send_start(first_packet.sequence_number, send_time_ms)

            response = self._stub.StreamTelemetry(packets, timeout=60.0)

            ack_time_ms = int(time.time() * 1000)
            duration_ms = ack_time_ms - send_time_ms
            throughput_kbps = (total_bytes * 1000) / duration_ms / 1024

            print(f"[{self.device_id}] Stream completed: {total_packets} packets "
                  f"Duration={duration_ms:.0f}ms Throughput={throughput_kbps:.1f}KB/s "
                  f"{'[SUCCESS]' if response.success else f'[FAILED: {response.message}]'}")

            return TransactionRecord(
                seq=0,  # Stream returns aggregate
                send_time_ms=send_time_ms,
                ack_time_ms=ack_time_ms,
                rtt_ms=duration_ms,
                throughput_kbps=throughput_kbps,
            )

        except grpc.RpcError as e:
            error_code = getattr(e, 'code()', 'UNKNOWN')
            error_msg = str(e)
            self._logger.log_error(0, error_msg)
            print(f"[{self.device_id}] Stream send error: {error_msg}")
            raise


def main():
    """Main entry point for the telemetry agent."""
    parser = argparse.ArgumentParser(description="Telemetry Agent")
    parser.add_argument("--host", default="localhost", help="gRPC service host")
    parser.add_argument("--port", type=int, default=50051, help="gRPC service port")
    parser.add_argument("--device-id", default="agent-py-001", help="Device identifier")
    parser.add_argument("--packets", type=int, default=100, help="Number of packets to send")
    parser.add_argument("--interval", type=float, default=0.1, help="Delay between packets (seconds)")
    parser.add_argument("--mode", choices=["unary", "stream"], default="unary",
                       help="Transmission mode (unary or stream)")
    parser.add_argument("--log-dir", default="./logs", help="Log output directory")
    parser.add_argument("--sensor-mode", choices=["mock", "hardware"], default="mock",
                       help="Sensor data source (mock or hardware)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for mock data")
    parser.add_argument("--output", choices=["text", "json"], default="text",
                       help="Output format")
    parser.add_argument("--json-separator", choices=["newline", "stream"], default="newline",
                       help="JSON output separator")
    args = parser.parse_args()

    print("=" * 70)
    print("Telemetry Agent")
    print("=" * 70)
    print(f"Device ID      : {args.device_id}")
    print(f"Service Host   : {args.host}:{args.port}")
    print(f"Transmission   : {args.mode}")
    print(f"Packets        : {args.packets}")
    print(f"Interval       : {args.interval}s")
    print(f"Sensor Mode    : {args.sensor_mode}")
    print("=" * 70)

    # Initialize agent
    agent = TelemetryAgent(
        host=args.host,
        port=args.port,
        device_id=args.device_id,
        log_dir=args.log_dir,
    )

    # Connect to service
    agent.connect()

    # Initialize data generator
    generator = DataGenerator(args.device_id, args.sensor_mode)
    generator.connect()

    try:
        records = []
        start_time = time.time()

        for seq in range(1, args.packets + 1):
            # Read sensor data
            sensor_data = generator.read()

            # Build packet
            packet = agent.build_packet(seq, sensor_data)

            # Send packet
            if args.mode == "unary":
                record = agent.send_unary(packet)
            else:  # stream mode
                if seq == 1:
                    print(f"[{args.device_id}] Starting stream transmission of {args.packets} packets...")
                records.append(packet)
                time.sleep(args.interval)

            if args.output == "json":
                print(json.dumps({
                    "device_id": args.device_id,
                    "sequence": seq,
                    "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                    "temperature": sensor_data.temperature,
                    "latitude": sensor_data.latitude,
                    "longitude": sensor_data.longitude,
                    "altitude": sensor_data.altitude,
                }, indent=2) + ("\n" if args.json_separator == "newline" else ""))
            else:
                print(f"[{args.device_id}] Sent packet {seq}")

            # Print final record if in stream mode
            if args.mode == "stream" and record:
                records.append(record)

        # Handle stream mode summary
        if args.mode == "stream" and records:
            agent.send_stream(records)
            records = []  # Already sent

        # Calculate and print summary
        end_time = time.time()
        duration_s = end_time - start_time

        print("\n" + "=" * 70)
        print("SESSION SUMMARY")
        print("=" * 70)
        print(f"Device ID       : {args.device_id}")
        print(f"Total Packets   : {args.packets}")
        print(f"Duration        : {duration_s:.2f} seconds")

        # Write session summary to log
        agent._logger.write_session_summary(records)

    except KeyboardInterrupt:
        print(f"\n[{args.device_id}] Interrupted by user")
    finally:
        agent.close()
        generator.close()

        print(f"\n[{args.device_id}] Agent closed. Check logs in {args.log_dir}/")


if __name__ == "__main__":
    main()