from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.path_constants import TASK_LAUNCH_PARAMS_FILENAME
from app.models.task import Task
from app.schemas.detector import (
    DetectorDatasResponse,
    DetectorListResponse,
    DetectorListSensorItem,
    SensorDataPoint,
    SourceDataItem,
)

_REQUIRED_DETECTOR_COLUMNS = (
    "时间戳_ms",
    "传感器编号",
    "本地记录ID",
    "方位角_deg",
    "俯仰角_deg",
    "斜距_km",
)

_SEQUENCE_COLUMNS = ("探测目标序列", "探测器序列")


class DetectorError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def read_launch_params(task: Task) -> dict[str, Any]:
    out = task.output_dir
    if not out:
        raise DetectorError("Task has no output directory", 400)
    launch_path = Path(out).parent / TASK_LAUNCH_PARAMS_FILENAME
    if not launch_path.is_file():
        raise DetectorError(
            f"Launch params not found for task (expected {launch_path})",
            404,
        )
    try:
        data = json.loads(launch_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise DetectorError(f"Invalid launch params JSON: {launch_path}") from e
    if not isinstance(data, dict):
        raise DetectorError("Launch params must be a JSON object", 400)
    return data


def workload_csv_path_from_launch(data: dict[str, Any]) -> Path:
    rp = data.get("resourcePath")
    if not rp or not isinstance(rp, str):
        raise DetectorError("Launch params missing resourcePath", 400)
    p = Path(rp)
    if not p.is_file():
        raise DetectorError(f"Workload CSV not found: {p}", 404)
    return p


def csv_path_for_simulation_task(task: Task) -> Path:
    return workload_csv_path_from_launch(read_launch_params(task))


def _workload_stem_from_launch(data: dict[str, Any]) -> str:
    fn = data.get("filename")
    if isinstance(fn, str) and fn.strip():
        s = fn.strip()
        return s[:-4] if s.lower().endswith(".csv") else s
    rp = data.get("resourcePath")
    if isinstance(rp, str) and rp.strip():
        return Path(rp.strip()).stem
    raise DetectorError("Launch params missing filename / resourcePath", 400)


def sensor_view_csv_path_from_launch(data: dict[str, Any]) -> Path:
    """sensor_view_{simulation_csv_basename_without_suffix}.csv next to workload CSV."""
    workload = workload_csv_path_from_launch(data)
    parent = workload.resolve().parent
    stem = _workload_stem_from_launch(data)
    candidates = [parent / f"sensor_view_{stem}.csv"]
    if stem.startswith("datastream_"):
        candidates.append(parent / f"sensor_view_{stem[len('datastream_'):]}.csv")
    for p in candidates:
        if p.is_file():
            return p
    tried = ", ".join(str(c) for c in candidates)
    raise DetectorError(f"Sensor view CSV not found (tried: {tried})", 404)


def _parse_row(row: dict[str, str]) -> tuple[int, int, SourceDataItem]:
    try:
        ts = int(float(row["时间戳_ms"]))
    except (TypeError, ValueError) as e:
        raise DetectorError(f"Invalid 时间戳_ms: {row.get('时间戳_ms')!r}") from e
    try:
        sid = int(float(row["传感器编号"]))
    except (TypeError, ValueError) as e:
        raise DetectorError(f"Invalid 传感器编号: {row.get('传感器编号')!r}") from e
    try:
        lid = int(float(row["本地记录ID"]))
    except (TypeError, ValueError) as e:
        raise DetectorError(f"Invalid 本地记录ID: {row.get('本地记录ID')!r}") from e
    try:
        az = float(row["方位角_deg"])
        el = float(row["俯仰角_deg"])
        dist = float(row["斜距_km"])
    except (TypeError, ValueError) as e:
        raise DetectorError("Invalid numeric field in detector row") from e
    item = SourceDataItem(
        local_target_id=lid,
        azimuth_deg=az,
        elevation_deg=el,
        slant_range_km=dist,
    )
    return sid, ts, item


def build_sensor_datas_by_id(csv_path: Path, sim_time: int) -> dict[int, list[SensorDataPoint]]:
    buckets: defaultdict[int, defaultdict[int, list[SourceDataItem]]] = defaultdict(
        lambda: defaultdict(list)
    )

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise DetectorError("CSV has no header row", 400)
        missing = [c for c in _REQUIRED_DETECTOR_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise DetectorError(
                f"CSV missing columns: {', '.join(missing)}",
                400,
            )
        for row in reader:
            sid, ts, item = _parse_row(row)
            if ts > sim_time:
                continue
            buckets[sid][ts].append(item)

    out: dict[int, list[SensorDataPoint]] = {}
    for sid in sorted(buckets):
        ts_map = buckets[sid]
        out[sid] = [
            SensorDataPoint(time=ts, source_data=ts_map[ts])
            for ts in sorted(ts_map)
        ]
    return out


def load_detector_datas(task: Task, sim_time: int, sensor_id: int) -> DetectorDatasResponse:
    path = csv_path_for_simulation_task(task)
    by_id = build_sensor_datas_by_id(path, sim_time)
    if sensor_id not in by_id:
        return DetectorDatasResponse(datas=[])
    return DetectorDatasResponse(datas=by_id[sensor_id])


def _target_sequence_value(row: dict[str, str]) -> str:
    for col in _SEQUENCE_COLUMNS:
        if col in row and row.get(col) is not None:
            return str(row.get(col) or "").strip()
    raise DetectorError(
        f"CSV missing target sequence column ({' / '.join(_SEQUENCE_COLUMNS)})",
        400,
    )


def build_detector_list(sensor_view_path: Path) -> DetectorListResponse:
    by_id: dict[int, DetectorListSensorItem] = {}
    with sensor_view_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise DetectorError("Sensor view CSV has no header row", 400)
        if "传感器编号" not in reader.fieldnames:
            raise DetectorError("Sensor view CSV missing column: 传感器编号", 400)
        if not any(c in reader.fieldnames for c in _SEQUENCE_COLUMNS):
            raise DetectorError(
                f"Sensor view CSV missing column: {' / '.join(_SEQUENCE_COLUMNS)}",
                400,
            )
        for row in reader:
            raw_id = row.get("传感器编号")
            if raw_id is None or str(raw_id).strip() == "":
                continue
            try:
                sid = int(float(raw_id))
            except (TypeError, ValueError) as e:
                raise DetectorError(f"Invalid 传感器编号: {raw_id!r}") from e
            seq = _target_sequence_value(row)
            status = seq != "destroyed"
            by_id[sid] = DetectorListSensorItem(id=sid, status=status)
    items = [by_id[k] for k in sorted(by_id)]
    return DetectorListResponse(sensor=items)


def load_detector_list(task: Task) -> DetectorListResponse:
    launch = read_launch_params(task)
    path = sensor_view_csv_path_from_launch(launch)
    return build_detector_list(path)


def undamaged_detector_count_for_task(task: Task) -> int:
    """Count sensors whose sequence is not ``destroyed`` (sensor_view CSV). Returns 0 if unavailable."""
    try:
        return sum(1 for item in load_detector_list(task).sensor if item.status)
    except DetectorError:
        return 0


def workload_peak_packets_per_second_for_task(task: Task) -> int:
    """Peak CSV row count per wall-clock second using ``时间戳_ms`` on the workload CSV. Returns 0 if unavailable."""
    try:
        launch = read_launch_params(task)
        path = workload_csv_path_from_launch(launch)
    except DetectorError:
        return 0
    per_second: dict[int, int] = defaultdict(int)
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or "时间戳_ms" not in reader.fieldnames:
                return 0
            for row in reader:
                raw = row.get("时间戳_ms")
                if raw is None or str(raw).strip() == "":
                    continue
                try:
                    ts_ms = int(float(raw))
                except (TypeError, ValueError):
                    continue
                per_second[ts_ms // 1000] += 1
    except OSError:
        return 0
    return max(per_second.values()) if per_second else 0
