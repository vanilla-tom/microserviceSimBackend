from __future__ import annotations

from pydantic import BaseModel, Field


class SourceDataItem(BaseModel):
    local_target_id: int
    azimuth_deg: float
    elevation_deg: float
    slant_range_km: float


class SensorDataPoint(BaseModel):
    time: int = Field(..., description="Timestamp in milliseconds")
    source_data: list[SourceDataItem]


class DetectorDatasResponse(BaseModel):
    """GET /detector — time series for one sensor."""

    datas: list[SensorDataPoint]


class DetectorListSensorItem(BaseModel):
    id: int = Field(..., description="传感器编号")
    status: bool = Field(
        ...,
        description="false 当探测目标序列为 destroyed，否则为 true",
    )


class DetectorListResponse(BaseModel):
    """GET /detectorList — sensor ids and destroyed status from sensor_view CSV."""

    sensor: list[DetectorListSensorItem]
