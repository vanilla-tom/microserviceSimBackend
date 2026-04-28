from __future__ import annotations

import bisect
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any, Optional

from app.services.type_callchain_parse import (
    biz_matches_target,
    distinct_biz_types,
    parse_type_callchain_dataset,
    type_callchain_to_target_hist_record,
)

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


def _min_positive(values: list[float]) -> float:
    pos = [v for v in values if v > 0]
    return min(pos) if pos else 0.0


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


def _decode_jsonl_line(line: bytes) -> str:
    """Decode one JSONL line; tolerate UTF-8 vs GB18030 (common on Windows)."""
    if not line:
        return ""
    text: str
    for enc in ("utf-8", "gb18030"):
        try:
            text = line.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = line.decode("utf-8", errors="replace")
        logger.warning(
            "JSONL line could not be decoded as utf-8 or gb18030; using utf-8 replacement characters"
        )
    return text.lstrip("\ufeff")


class IncrementalJsonlReader:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self._data = SimulationData()
        self._offset = 0
        self._pending_bytes = b""
        self._last_size = 0

    def refresh(self) -> SimulationData:
        if not self.file_path.exists():
            return self._data

        size = self.file_path.stat().st_size
        if size < self._offset:
            self._data = SimulationData()
            self._offset = 0
            self._pending_bytes = b""

        if size == self._offset:
            return self._data

        with open(self.file_path, "rb") as handle:
            handle.seek(self._offset)
            chunk = handle.read()
            self._offset = handle.tell()

        self._last_size = size
        payload = self._pending_bytes + chunk
        parts = payload.split(b"\n")
        self._pending_bytes = parts[-1]

        for raw_line in parts[:-1]:
            raw_line = raw_line.rstrip(b"\r")
            if not raw_line.strip():
                continue

            candidate = _decode_jsonl_line(raw_line).strip()
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

    _SNAPSHOT_HOST_COUNT = 16

    @staticmethod
    def _snapshot_host_slot(host_id: Any) -> Optional[str]:
        """Map raw host_id to canonical '0'..'9' if in range; else None."""
        if host_id is None:
            return None
        try:
            n = int(str(host_id).strip())
        except (TypeError, ValueError):
            return None
        if 0 <= n < SimulationDataProcessor._SNAPSHOT_HOST_COUNT:
            return str(n)
        return None

    def get_all_hosts_snapshot(self, sim_time: int) -> dict[str, Any]:
        snapshot = self.get_snapshot_at_time(sim_time)
        crashed_hosts = self._host_ids_with_lifecycle_crash_at_or_before(sim_time)

        by_slot: dict[str, dict[str, Any]] = {}
        if snapshot is not None:
            for host in snapshot.get("hosts", []) or []:
                slot = self._snapshot_host_slot(host.get("host_id"))
                if slot is None:
                    continue
                vms = []
                for vm in host.get("vms", []) or []:
                    vms.append({
                        "vm_id": str(vm.get("vm_id", "unknown")),
                        "vm_type": str(vm.get("vm_type", "unknown")),
                        "memory_usage": _safe_float(vm.get("memory_usage")),
                        "queue_length": _safe_int(vm.get("queue_length")),
                        "running_length": _safe_int(vm.get("running_length")),
                    })
                by_slot[slot] = {
                    "host_id": slot,
                    "status": slot not in crashed_hosts,
                    "cpu_usage": _safe_float(host.get("cpu_usage")),
                    "memory_usage": _safe_float(host.get("memory_usage")),
                    "vm_count": _safe_int(host.get("vm_count"), len(vms)),
                    "vms": vms,
                }

        hosts: list[dict[str, Any]] = []
        for i in range(self._SNAPSHOT_HOST_COUNT):
            slot = str(i)
            if slot in by_slot:
                hosts.append(by_slot[slot])
            else:
                hosts.append({
                    "host_id": slot,
                    "status": False,
                    "cpu_usage": 0.0,
                    "memory_usage": 0.0,
                    "vm_count": 0,
                    "vms": [],
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

    @staticmethod
    def _tag_history_time_ms(raw_t: Any, event_t_ms: int) -> Optional[int]:
        """Map tag_history `t` to wall-clock ms (either sim seconds or ms; disambiguate vs event `t`)."""
        try:
            t = float(raw_t)
        except (TypeError, ValueError):
            return None
        cand_sec = int(round(t * 1000))
        cand_ms = int(round(t))
        d_sec = abs(cand_sec - event_t_ms)
        d_ms = abs(cand_ms - event_t_ms)
        if d_sec < d_ms:
            return cand_sec
        if d_ms < d_sec:
            return cand_ms
        if t != int(t):
            return cand_sec
        return cand_ms

    def _collect_algorithm_messages(
        self,
        sim_time: int,
        *,
        field: str,
        algorithm_name: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        rows: list[tuple[int, int, str]] = []
        seq = 0
        for ev in self.data.by_type.get("algorithm_event", []):
            t = ev["t"]
            if t > sim_time:
                continue
            if algorithm_name is not None and ev.get("algorithm_name") != algorithm_name:
                continue
            msg = ev.get(field)
            if isinstance(msg, str) and msg.strip():
                text = msg.strip()
            else:
                raw = (ev.get("details") or {}).get(field)
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

    def get_algorithm_resource_messages(self, sim_time: int) -> list[dict[str, Any]]:
        """algorithm_event rows with message_zh, at or before sim_time; newest 100 by t, then ascending."""
        return self._collect_algorithm_messages(sim_time, field="message_zh")

    def get_algorithm_tag_messages(self, sim_time: int) -> list[dict[str, Any]]:
        """Expand details.tag_history from stream_tag events with tags/layer fields; each step is one line."""
        rows: list[tuple[int, int, str]] = []
        seq = 0
        for ev in self.data.by_type.get("algorithm_event", []):
            ev_t = ev["t"]
            if ev_t > sim_time:
                continue
            if ev.get("algorithm_name") != "stream_tag":
                continue
            details = ev.get("details") if isinstance(ev.get("details"), dict) else {}
            hist = details.get("tag_history")
            if not isinstance(hist, list):
                continue
            for item in hist:
                if not isinstance(item, dict):
                    continue
                t_ms = self._tag_history_time_ms(item.get("t"), ev_t)
                if t_ms is None or t_ms > sim_time:
                    continue
                sid = item.get("id")
                tags_raw = item.get("tags")
                if tags_raw is None:
                    tags_raw = []
                if isinstance(tags_raw, list):
                    tags_str = ", ".join(str(x) for x in tags_raw)
                else:
                    tags_str = str(tags_raw)
                layer_raw = item.get("layer")
                if layer_raw is None:
                    layer_raw = "-"
                if isinstance(layer_raw, list):
                    layer_str = ", ".join(str(x) for x in layer_raw)
                else:
                    layer_str = str(layer_raw)
                msg = f"流数据 {sid} 标识为{tags_str}, 下游发往 {layer_str}"
                rows.append((t_ms, seq, msg))
                seq += 1

        rows.sort(key=lambda item: (-item[0], -item[1]))
        rows = rows[: self._RESOURCE_LOG_MAX]
        rows.sort(key=lambda item: (item[0], item[1]))
        ret = [{"time": t, "message": text} for t, _, text in rows]
        ret.reverse()
        return ret

    def get_targets(self, sim_time: int) -> list[int]:
        """从契约版 type_callchain（v2）成功解析记录中抽取目标 biz_type 列表。"""
        records, _ = parse_type_callchain_dataset(self.data.events, sim_time=sim_time)
        return distinct_biz_types(records)

    def get_target_call_chain(self, sim_time: int, target_id: int) -> dict[str, Any]:
        """按 target_id 过滤 v2 成功记录，并映射为既有 target-hist API（含 reason_event -> event 中文）。"""
        records, _errors = parse_type_callchain_dataset(self.data.events, sim_time=sim_time)
        filtered = [rec for rec in records if biz_matches_target(rec["bizType"], target_id)]
        api_records = [type_callchain_to_target_hist_record(rec) for rec in filtered]
        return {"sim_time": sim_time, "records": api_records}

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
        resource_hi: list[float] = []
        resource_lo: list[float] = []
        host_counts: list[int] = []
        vm_counts: list[int] = []
        queue_lengths: list[int] = []

        for snapshot in snapshots:
            hosts = snapshot.get("hosts", []) or []
            host_counts.append(len(hosts))
            total_vms = 0
            for host in hosts:
                c = _safe_float(host.get("cpu_usage"))
                m = _safe_float(host.get("memory_usage"))
                cpu_values.append(c)
                memory_values.append(m)
                resource_hi.append(max(c, m))
                resource_lo.append(max(c, m))
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
            "resource_stats": {
                "peak": max(resource_hi) if resource_hi else 0.0,
                "valley": _min_positive(resource_lo),
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
