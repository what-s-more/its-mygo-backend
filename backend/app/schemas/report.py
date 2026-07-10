from datetime import datetime

from pydantic import BaseModel, Field


class ReportTimeRange(BaseModel):
    date_from: str
    date_to: str
    granularity: str = "day"


class ReportMetric(BaseModel):
    key: str
    label: str
    value: int | float
    unit: str = ""


class ReportSeriesPoint(BaseModel):
    date: str
    order_count: int = 0
    gmv_cent: int = 0
    refund_amount_cent: int = 0


class ReportNameValue(BaseModel):
    name: str
    value: int | float
    id: int | None = None
    amount_cent: int | None = None


class ReportTopProduct(BaseModel):
    product_id: int
    product_name: str
    quantity: int
    amount_cent: int


class ReportOverviewResponse(BaseModel):
    scope: str
    scope_id: int | None = None
    time_range: ReportTimeRange
    generated_at: datetime
    summary: list[ReportMetric]
    sales_trend: list[ReportSeriesPoint]
    order_status: list[ReportNameValue]
    top_products: list[ReportTopProduct]
    top_merchants: list[ReportNameValue]
    refund_status: list[ReportNameValue]
    promotion_summary: list[ReportMetric]
    community_summary: list[ReportMetric]
    member_summary: list[ReportMetric] = Field(default_factory=list)
    member_level_distribution: list[ReportNameValue] = Field(default_factory=list)
    points_summary: list[ReportMetric] = Field(default_factory=list)
