from __future__ import annotations

import bisect
import json
import logging
from dataclasses import dataclass, field
from itertools import groupby
from pathlib import Path
from statistics import mean
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    idx = min(len(values) - 1, max(0, int(round((len(values) - 1) * q))))
    return values[idx]


@dataclass
class SimulationData:
    events: list[dict[str, Any]] = field(default_factory=list)
    by_type: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    min_time: Optional[int] = None
    max_time: Optional[int] = None
    parse_errors: int = 0

    def append_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type", "unknown")
        timestamp = _safe_int(event.get("t"), 0)
        event["t"] = timestamp
        self.events.append(event)
        self.by_type.setdefault(event_type, []).append(event)

        if self.min_time is None or timestamp < self.min_time:
            self.min_time = timestamp
        if self.max_time is None or timestamp > self.max_time:
            self.max_time = timestamp

    def get_events_in_range(
        self,
        start_time: int,
        end_time: int,
        event_types: Optional[set[str]] = None,
    ) -> list[dict[str, Any]]:
        if start_time > end_time:
            start_time, end_time = end_time, start_time

        if event_types:
            result: list[dict[str, Any]] = []
            for event_type in event_types:
                events = self.by_type.get(event_type, [])
                times = [event["t"] for event in events]
                left = bisect.bisect_left(times, start_time)
                right = bisect.bisect_right(times, end_time)
                result.extend(events[left:right])
            result.sort(key=lambda item: item["t"])
            return result

        times = [event["t"] for event in self.events]
        left = bisect.bisect_left(times, start_time)
        right = bisect.bisect_right(times, end_time)
        return self.events[left:right]

    def get_last_event_before(
        self,
        sim_time: int,
        event_type: str,
    ) -> Optional[dict[str, Any]]:
        events = self.by_type.get(event_type, [])
        if not events:
            return None
        times = [event["t"] for event in events]
        idx = bisect.bisect_right(times, sim_time)
        if idx == 0:
            return None
        return events[idx - 1]


class IncrementalJsonlReader:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self._data = SimulationData()
        self._offset = 0
        self._pending = ""
        self._last_size = 0

    def refresh(self) -> SimulationData:
        if not self.file_path.exists():
            return self._data

        size = self.file_path.stat().st_size
        if size < self._offset:
            self._data = SimulationData()
            self._offset = 0
            self._pending = ""

        if size == self._offset:
            return self._data

        with open(self.file_path, "r", encoding="utf-8") as handle:
            handle.seek(self._offset)
            chunk = handle.read()
            self._offset = handle.tell()

        self._last_size = size
        payload = self._pending + chunk
        lines = payload.splitlines(keepends=True)
        self._pending = ""

        for line in lines:
            if not line.endswith("\n") and not line.endswith("\r"):
                self._pending = line
                continue

            candidate = line.strip()
            if not candidate:
                continue

            try:
                event = json.loads(candidate)
            except json.JSONDecodeError:
                self._data.parse_errors += 1
                logger.warning("Skipping malformed JSONL line in %s", self.file_path)
                continue

            self._data.append_event(event)

        return self._data

    def get_data(self) -> SimulationData:
        return self.refresh()


class SimulationDataProcessor:
    def __init__(self, reader: IncrementalJsonlReader):
        self.reader = reader

    @property
    def data(self) -> SimulationData:
        return self.reader.get_data()

    def refresh(self) -> SimulationData:
        return self.reader.refresh()

    @staticmethod
    def _resolve_vm_layer(vm_type: str, vm_type_layers: dict[str, str]) -> str:
        layer = vm_type_layers.get(vm_type, "")
        if layer:
            return layer
        return vm_type.split("-")[0].upper() if "-" in vm_type else ""

    def _layer_rank_map(self, layer_order: list[str]) -> dict[str, int]:
        return {layer: index for index, layer in enumerate(layer_order)}

    def _sort_layers(self, layers: set[str], layer_order: list[str]) -> list[str]:
        layer_rank = self._layer_rank_map(layer_order)
        return sorted(layers, key=lambda layer: (layer_rank.get(layer, len(layer_rank)), layer))

    def get_metadata(self) -> dict[str, Any]:
        data = self.data
        vm_types = []
        vm_type_registry = data.by_type.get("vm_type_registry", [])
        if vm_type_registry:
            vm_types = vm_type_registry[0].get("vm_types", []) or []

        first_snapshot = data.by_type.get("resource_snapshot", [])
        hosts = first_snapshot[0].get("hosts", []) if first_snapshot else []
        host_ids = [str(host.get("host_id", "unknown")) for host in hosts]

        layer_order: list[str] = []
        seen_layers: set[str] = set()
        for vm_type in vm_types:
            layer = str(vm_type.get("layer", "")).upper()
            if layer and layer not in seen_layers:
                seen_layers.add(layer)
                layer_order.append(layer)

        if not layer_order and first_snapshot:
            for host in hosts:
                for vm in host.get("vms", []) or []:
                    vm_type = str(vm.get("vm_type", ""))
                    layer = vm_type.split("-")[0].upper() if "-" in vm_type else ""
                    if layer and layer not in seen_layers:
                        seen_layers.add(layer)
                        layer_order.append(layer)

        sim_time_min = data.min_time or 0
        sim_time_max = data.max_time or sim_time_min
        return {
            "sim_time_min": sim_time_min,
            "sim_time_max": sim_time_max,
            "duration_ms": max(0, sim_time_max - sim_time_min),
            "host_ids": host_ids,
            "vm_types": vm_types,
            "layer_order": layer_order,
            "event_counts": {
                event_type: len(events)
                for event_type, events in data.by_type.items()
            },
            "parse_errors": data.parse_errors,
        }

    def get_snapshot_at_time(self, sim_time: int) -> Optional[dict[str, Any]]:
        return self.data.get_last_event_before(sim_time, "resource_snapshot")

    def get_latest_snapshot_time_at_or_before(self, sim_time: int) -> Optional[int]:
        snapshot = self.get_snapshot_at_time(sim_time)
        if snapshot is None:
            return None
        return _safe_int(snapshot.get("t"))

    def get_next_snapshot_time_after(self, sim_time: int) -> Optional[int]:
        events = self.data.by_type.get("resource_snapshot", [])
        if not events:
            return None
        times = [event["t"] for event in events]
        idx = bisect.bisect_right(times, sim_time)
        if idx >= len(times):
            return None
        return times[idx]

    def _host_ids_with_lifecycle_crash_at_or_before(self, sim_time: int) -> set[str]:
        """Hosts that have at least one vm_lifecycle crash event at or before sim_time."""
        crashed: set[str] = set()
        for ev in self.data.get_events_in_range(0, sim_time, {"vm_lifecycle"}):
            if ev.get("operation") != "crash":
                continue
            hid = ev.get("host_id")
            if hid is None and isinstance(ev.get("details"), dict):
                hid = ev["details"].get("host_id")
            if hid is None or hid == "":
                continue
            crashed.add(str(hid))
        return crashed

    def get_all_hosts_snapshot(self, sim_time: int) -> dict[str, Any]:
        snapshot = self.get_snapshot_at_time(sim_time)
        if snapshot is None:
            return {"sim_time": sim_time, "hosts": []}

        crashed_hosts = self._host_ids_with_lifecycle_crash_at_or_before(sim_time)
        hosts = []
        for host in snapshot.get("hosts", []) or []:
            vms = []
            for vm in host.get("vms", []) or []:
                vms.append({
                    "vm_id": str(vm.get("vm_id", "unknown")),
                    "vm_type": str(vm.get("vm_type", "unknown")),
                    "memory_usage": _safe_float(vm.get("memory_usage")),
                    "queue_length": _safe_int(vm.get("queue_length")),
                    "running_length": _safe_int(vm.get("running_length")),
                })
            host_id = str(host.get("host_id", "unknown"))
            hosts.append({
                "host_id": host_id,
                "status": host_id not in crashed_hosts,
                "cpu_usage": _safe_float(host.get("cpu_usage")),
                "memory_usage": _safe_float(host.get("memory_usage")),
                "vm_count": _safe_int(host.get("vm_count"), len(vms)),
                "vms": vms,
            })
        return {"sim_time": sim_time, "hosts": hosts}

    def get_host_history(self, host_id: str, start_time: int, end_time: int) -> dict[str, Any]:
        events = self.data.get_events_in_range(start_time, end_time, {"resource_snapshot"})
        timestamps = []
        cpu_usage = []
        memory_usage = []
        vm_count = []

        for event in events:
            for host in event.get("hosts", []) or []:
                if str(host.get("host_id")) != str(host_id):
                    continue
                timestamps.append(event["t"] / 1000)
                cpu_usage.append(_safe_float(host.get("cpu_usage")))
                memory_usage.append(_safe_float(host.get("memory_usage")))
                vm_count.append(_safe_int(host.get("vm_count")))
                break

        return {
            "time_range": {"start": start_time, "end": end_time},
            "series": {
                "cpu": {"name": "CPU利用率", "data": list(zip(timestamps, cpu_usage))},
                "memory": {"name": "内存利用率", "data": list(zip(timestamps, memory_usage))},
                "vm_count": {"name": "VM数量", "data": list(zip(timestamps, vm_count))},
            },
        }

    def get_vm_history(self, vm_id: str, start_time: int, end_time: int) -> dict[str, Any]:
        events = self.data.get_events_in_range(start_time, end_time, {"resource_snapshot"})
        timestamps = []
        memory_usage = []
        queue_length = []
        running_length = []

        for event in events:
            found = None
            for host in event.get("hosts", []) or []:
                for vm in host.get("vms", []) or []:
                    if str(vm.get("vm_id")) == str(vm_id):
                        found = vm
                        break
                if found:
                    break
            if found is None:
                continue
            timestamps.append(event["t"] / 1000)
            memory_usage.append(_safe_float(found.get("memory_usage")))
            queue_length.append(_safe_int(found.get("queue_length")))
            running_length.append(_safe_int(found.get("running_length")))

        return {
            "time_range": {"start": start_time, "end": end_time},
            "series": {
                "memory": {"name": "内存利用率", "data": list(zip(timestamps, memory_usage))},
                "queue": {"name": "队列长度", "data": list(zip(timestamps, queue_length))},
                "running": {"name": "运行任务数", "data": list(zip(timestamps, running_length))},
            },
        }

    def get_call_chain_data(self, sim_time: int) -> dict[str, Any]:
        metadata = self.get_metadata()
        layer_order = metadata.get("layer_order", [])
        snapshot = self.get_snapshot_at_time(sim_time)
        if snapshot is None:
            return {
                "sim_time": sim_time,
                "hosts": [],
                "layer_order": layer_order,
            }

        vm_type_layers = {
            str(vm_type.get("name", "")): str(vm_type.get("layer", "")).upper()
            for vm_type in metadata.get("vm_types", [])
        }
        layer_rank = self._layer_rank_map(layer_order)

        host_entries = []
        layer_vms: dict[str, list[dict[str, Any]]] = {}
        for host in snapshot.get("hosts", []) or []:
            host_id = str(host.get("host_id", "unknown"))
            host_layers = set()
            vm_entries = []
            for vm in host.get("vms", []) or []:
                vm_type = str(vm.get("vm_type", ""))
                vm_id = str(vm.get("vm_id", "unknown"))
                layer = self._resolve_vm_layer(vm_type, vm_type_layers)
                if layer:
                    host_layers.add(layer)
                vm_entry = {
                    "id": vm_id,
                    "name": vm_id,
                    "vm_type": vm_type,
                    "layer": layer,
                    "host_id": host_id,
                    "memory_usage": _safe_float(vm.get("memory_usage")),
                    "queue_length": _safe_int(vm.get("queue_length")),
                    "running_length": _safe_int(vm.get("running_length")),
                }
                vm_entries.append(vm_entry)
                if layer:
                    layer_vms.setdefault(layer, []).append(vm_entry)

            vm_entries.sort(
                key=lambda item: (
                    layer_rank.get(item["layer"], len(layer_rank)),
                    item["vm_type"],
                    item["id"],
                )
            )
            host_entries.append({
                "id": host_id,
                "name": f"Host {host_id}",
                "layers": self._sort_layers(host_layers, layer_order),
                "cpu_usage": _safe_float(host.get("cpu_usage")),
                "memory_usage": _safe_float(host.get("memory_usage")),
                "vm_count": _safe_int(host.get("vm_count"), len(vm_entries)),
                "vms": vm_entries,
            })

        host_entries.sort(
            key=lambda host: (
                layer_rank.get(host["layers"][0], len(layer_rank)) if host["layers"] else len(layer_rank),
                host["id"] if not host["id"].isdigit() else f"{int(host['id']):08d}",
            )
        )

        return {"sim_time": sim_time, "hosts": host_entries, "layer_order": layer_order}

    _RESOURCE_LOG_MAX = 100

    def get_algorithm_resource_messages(self, sim_time: int) -> list[dict[str, Any]]:
        """algorithm_event rows with message_zh, at or before sim_time; newest 100 by t, then ascending."""
        rows: list[tuple[int, int, str]] = []
        seq = 0
        for ev in self.data.by_type.get("algorithm_event", []):
            t = ev["t"]
            if t > sim_time:
                continue
            msg = ev.get("message_zh")
            if isinstance(msg, str) and msg.strip():
                text = msg.strip()
            else:
                raw = (ev.get("details") or {}).get("message_zh")
                if not isinstance(raw, str) or not raw.strip():
                    continue
                text = raw.strip()
            rows.append((t, seq, text))
            seq += 1

        rows.sort(key=lambda item: (-item[0], -item[1]))
        rows = rows[: self._RESOURCE_LOG_MAX]
        rows.sort(key=lambda item: (item[0], item[1]))
        li = [{"time": t, "message": text} for t, _, text in rows]
        li.reverse()
        return li

    def _iter_type_callchain_events(self) -> list[dict[str, Any]]:
        return [
            ev for ev in self.data.by_type.get("algorithm_event", [])
            if ev.get("algorithm_name") == "type_callchain"
        ]

    _CRASH_WINDOW_MS = 1000

    def _build_crash_index(self) -> dict[str, list[int]]:
        """Map vm_id -> sorted list of crash timestamps."""
        index: dict[str, list[int]] = {}
        for ev in self.data.by_type.get("vm_lifecycle", []):
            if ev.get("operation") == "crash":
                vm_id = str(ev.get("vm_id", ""))
                index.setdefault(vm_id, []).append(ev["t"])
        for times in index.values():
            times.sort()
        return index

    def _is_crash(self, vm_id: str, timestamp: int, crash_index: dict[str, list[int]]) -> bool:
        times = crash_index.get(vm_id)
        if not times:
            return False
        idx = bisect.bisect_left(times, timestamp - self._CRASH_WINDOW_MS)
        return idx < len(times) and times[idx] <= timestamp + self._CRASH_WINDOW_MS

    def get_targets(self, sim_time: int) -> list[int]:
        targets: set[int] = set()
        for ev in self._iter_type_callchain_events():
            if ev["t"] > sim_time:
                continue
            details = ev.get("details") or {}
            raw = details.get("type")
            if raw is not None:
                try:
                    targets.add(int(raw))
                except (TypeError, ValueError):
                    pass
        return sorted(targets)

    def get_target_call_chain(self, sim_time: int, target_id: int) -> dict[str, Any]:
        target_str = str(target_id)
        crash_index = self._build_crash_index()

        relevant = [
            ev for ev in self._iter_type_callchain_events()
            if ev["t"] <= sim_time
            and (ev.get("details") or {}).get("type") == target_str
        ]
        relevant.sort(key=lambda ev: ev["t"])

        recognition_mods: set[str] = set()
        fusion_mods: set[str] = set()
        records: list[dict[str, Any]] = []

        for timestamp, group in groupby(relevant, key=lambda ev: ev["t"]):
            events_in_group = list(group)
            had_modules = bool(recognition_mods or fusion_mods)
            has_crash = False
            has_added = False
            has_removed_non_crash = False

            for ev in events_in_group:
                details = ev.get("details") or {}
                vm_id = str(details.get("vmId", ""))
                layer = str(details.get("layer", "")).upper()
                decision = ev.get("decision_type", "")

                if decision == "ADDED":
                    has_added = True
                    if layer == "RECOGNIZER":
                        recognition_mods.add(vm_id)
                    elif layer == "ANALYZER":
                        fusion_mods.add(vm_id)
                elif decision == "REMOVED":
                    if self._is_crash(vm_id, timestamp, crash_index):
                        has_crash = True
                    else:
                        has_removed_non_crash = True
                        recognition_mods.discard(vm_id)
                        fusion_mods.discard(vm_id)

            event_label = self._determine_event_label(
                had_modules=had_modules,
                has_added=has_added,
                has_crash=has_crash,
                has_removed_non_crash=has_removed_non_crash,
                modules_remain=bool(recognition_mods or fusion_mods),
            )

            records.append({
                "time": timestamp,
                "recognition_mods": sorted(recognition_mods),
                "fusion_mods": sorted(fusion_mods),
                "event": event_label,
            })

        return {"sim_time": sim_time, "records": records}

    @staticmethod
    def _determine_event_label(
        *,
        had_modules: bool,
        has_added: bool,
        has_crash: bool,
        has_removed_non_crash: bool,
        modules_remain: bool,
    ) -> str:
        """Pick the most significant event label for a timestamp group.

        Priority: 节点损毁 > 初始分配 > 负载均衡/微服务扩容 > 微服务缩容 > 处理完毕
        """
        if has_crash:
            return "节点损毁"
        if has_added and not had_modules:
            return "初始分配"
        if has_added:
            return "负载均衡/微服务扩容"
        if has_removed_non_crash and modules_remain:
            return "微服务缩容"
        if has_removed_non_crash and not modules_remain:
            return "处理完毕"
        return "未知"

    def get_timeline(self, start_time: int, end_time: int, interval_ms: int = 1000) -> dict[str, Any]:
        if interval_ms <= 0:
            interval_ms = 1000
        current = start_time
        points = []
        while current <= end_time:
            points.append(self.get_all_hosts_snapshot(current))
            current += interval_ms
        return {"start": start_time, "end": end_time, "interval_ms": interval_ms, "points": points}

    def get_summary(self) -> dict[str, Any]:
        data = self.data
        snapshots = data.by_type.get("resource_snapshot", [])
        cpu_values: list[float] = []
        memory_values: list[float] = []
        host_counts: list[int] = []
        vm_counts: list[int] = []
        queue_lengths: list[int] = []

        for snapshot in snapshots:
            hosts = snapshot.get("hosts", []) or []
            host_counts.append(len(hosts))
            total_vms = 0
            for host in hosts:
                cpu_values.append(_safe_float(host.get("cpu_usage")))
                memory_values.append(_safe_float(host.get("memory_usage")))
                total_vms += _safe_int(host.get("vm_count"), len(host.get("vms", []) or []))
                for vm in host.get("vms", []) or []:
                    queue_lengths.append(_safe_int(vm.get("queue_length")))
            vm_counts.append(total_vms)

        cloudlet_events = data.by_type.get("cloudlet_event", [])
        latencies = []
        for event in cloudlet_events:
            finish_t = _safe_float(event.get("finish_t"))
            entry_t = _safe_float(event.get("entry_t"))
            latency = finish_t - entry_t
            if latency >= 0:
                latencies.append(latency / 1000)
        latencies.sort()

        sim_time_min = data.min_time or 0
        sim_time_max = data.max_time or sim_time_min
        return {
            "sim_time_min": sim_time_min,
            "sim_time_max": sim_time_max,
            "duration_ms": max(0, sim_time_max - sim_time_min),
            "snapshot_count": len(snapshots),
            "host_stats": {
                "avg": mean(host_counts) if host_counts else 0,
                "peak": max(host_counts) if host_counts else 0,
            },
            "vm_stats": {
                "avg": mean(vm_counts) if vm_counts else 0,
                "peak": max(vm_counts) if vm_counts else 0,
            },
            "cpu_stats": {
                "avg": mean(cpu_values) if cpu_values else 0,
                "peak": max(cpu_values) if cpu_values else 0,
            },
            "memory_stats": {
                "avg": mean(memory_values) if memory_values else 0,
                "peak": max(memory_values) if memory_values else 0,
            },
            "queue_stats": {
                "peak": max(queue_lengths) if queue_lengths else 0,
            },
            "latency_stats": {
                "avg": mean(latencies) if latencies else 0,
                "p50": _percentile(latencies, 0.5),
                "p95": _percentile(latencies, 0.95),
                "p99": _percentile(latencies, 0.99),
                "count": len(latencies),
            },
            "event_counts": {
                event_type: len(events)
                for event_type, events in data.by_type.items()
            },
            "parse_errors": data.parse_errors,
        }
