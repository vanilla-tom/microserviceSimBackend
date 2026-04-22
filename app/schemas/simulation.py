from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class SimulationLaunchParams(BaseModel):
    """Frontend launch options (nested under `target_distribution` in the API body)."""

    model_config = ConfigDict(populate_by_name=True)

    scenario: str = Field(
        ...,
        validation_alias=AliasChoices("scenario", "senario"),
        serialization_alias="scenario",
    )
    data_source: str = Field(
        ...,
        validation_alias=AliasChoices("dataSource", "data_source"),
        serialization_alias="dataSource",
    )
    enable_sensor_failure: bool = Field(
        ...,
        validation_alias=AliasChoices(
            "enableSensorFailure", "enable_sensor_failure"
        ),
        serialization_alias="enableSensorFailure",
    )
    enable_node_failure: bool = Field(
        ...,
        validation_alias=AliasChoices("enableNodeFailure", "enable_node_failure"),
        serialization_alias="enableNodeFailure",
    )


class CreateSimulationRequest(BaseModel):
    target_distribution: SimulationLaunchParams = Field(
        ...,
        description="Scenario, data source, and failure flags for HOCON overrides",
    )


# === Simulation Replay API Schemas ===


class ErrorResponse(BaseModel):
    error: str


class ResourceLogEntry(BaseModel):
    time: int
    message: str


class VmTypeInfo(BaseModel):
    """VM类型信息"""
    name: str
    layer: str
    spec_id: int
    cpu_cores: int
    cpu_mips: int
    memory_mb: int
    description: Optional[str] = None


class SimulationMetadataResponse(BaseModel):
    """仿真元数据响应"""
    sim_time_min: int  # 仿真最小时间（毫秒）
    sim_time_max: int  # 仿真最大时间（毫秒）
    duration_ms: int  # 仿真时长（毫秒）
    host_ids: List[str]  # Host ID列表
    vm_types: List[VmTypeInfo]  # VM类型注册表
    layer_order: List[str]  # Layer调用顺序
    event_counts: Dict[str, int]  # 各类型事件数量
    parse_errors: int = 0


class VmSnapshot(BaseModel):
    """VM快照数据"""
    vm_id: str
    vm_type: str
    memory_usage: float
    queue_length: int
    running_length: int


class HostSnapshot(BaseModel):
    """Host快照数据"""
    host_id: str
    status: bool  # True=节点正常；False=该 host 在 sim_time 前发生过 vm_lifecycle crash
    cpu_usage: float
    memory_usage: float
    vm_count: int
    vms: List[VmSnapshot]


class AllHostsSnapshotResponse(BaseModel):
    """所有Host快照响应"""
    sim_time: int  # 仿真时间（毫秒）
    hosts: List[HostSnapshot]


class SeriesData(BaseModel):
    """ECharts系列数据"""
    name: str
    data: List[List[float]]  # [[time, value], ...]


class TimeRange(BaseModel):
    """时间范围"""
    start: int
    end: int


class HostHistoryResponse(BaseModel):
    """Host历史数据响应（ECharts格式）"""
    time_range: TimeRange
    series: Dict[str, SeriesData]


class VmHistoryResponse(BaseModel):
    """VM历史数据响应（ECharts格式）"""
    time_range: TimeRange
    series: Dict[str, SeriesData]


class CallChainVmNode(BaseModel):
    """调用链中的VM节点"""
    id: str
    name: str
    vm_type: str
    layer: str
    host_id: str
    memory_usage: float
    queue_length: int
    running_length: int


class CallChainHost(BaseModel):
    """调用链中的Host容器"""
    id: str
    name: str
    layers: List[str]
    cpu_usage: float
    memory_usage: float
    vm_count: int
    vms: List[CallChainVmNode]


class CallChainResponse(BaseModel):
    """调用链数据响应（Host容器 + VM级拓扑）"""
    sim_time: int
    hosts: List[CallChainHost]
    layer_order: List[str]


class TimelinePointResponse(BaseModel):
    sim_time: int
    hosts: List[HostSnapshot]


class TimelineResponse(BaseModel):
    start: int
    end: int
    interval_ms: int
    points: List[TimelinePointResponse]


class SummaryBucket(BaseModel):
    avg: float = 0.0
    peak: float = 0.0


class QueueSummary(BaseModel):
    peak: int = 0


class LatencySummary(BaseModel):
    avg: float = 0.0
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    count: int = 0


class SimulationSummaryResponse(BaseModel):
    sim_time_min: int
    sim_time_max: int
    duration_ms: int
    snapshot_count: int
    host_stats: SummaryBucket
    vm_stats: SummaryBucket
    cpu_stats: SummaryBucket
    memory_stats: SummaryBucket
    queue_stats: QueueSummary
    latency_stats: LatencySummary
    event_counts: Dict[str, int]
    parse_errors: int = 0
    detector_count: int = 0
    target_count_peak: int = 0


class TargetsResponse(BaseModel):
    targets: List[int]


class TargetCallChainRecord(BaseModel):
    time: int
    recognition_mods: List[str]
    fusion_mods: List[str]
    event: str


class TargetCallChainResponse(BaseModel):
    sim_time: int
    records: List[TargetCallChainRecord]
