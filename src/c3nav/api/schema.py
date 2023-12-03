from typing import Annotated, Literal, Union, Any

from ninja import Schema
from pydantic import Discriminator
from pydantic import Field as APIField

from c3nav.api.utils import NonEmptyStr


class APIErrorSchema(Schema):
    """
    An error has occured with this request
    """
    detail: NonEmptyStr = APIField(
        description="A human-readable error description"
    )


class PolygonSchema(Schema):
    """
    A GeoJSON Polygon
    """
    type: Literal["Polygon"]
    coordinates: list[list[tuple[float, float]]] = APIField(
        example=[[[1.5, 1.5], [1.5, 2.5], [2.5, 2.5], [2.5, 2.5]]]
    )


class LineStringSchema(Schema):
    """
    A GeoJSON LineString
    """
    type: Literal["LineString"]
    coordinates: list[tuple[float, float]] = APIField(
        example=[[1.5, 1.5], [2.5, 2.5], [5, 8.7]]
    )


class LineSchema(Schema):
    """
    A GeoJSON LineString with only two points
    """
    type: Literal["LineString"]
    coordinates: tuple[tuple[float, float], tuple[float, float]] = APIField(
        example=[[1.5, 1.5], [5, 8.7]]
    )


class PointSchema(Schema):
    """
    A GeoJSON Point
    """
    type: Literal["Point"]
    coordinates: tuple[float, float] = APIField(
        example=[1, 2.5]
    )


GeometrySchema = Annotated[
    Union[
        PolygonSchema,
        LineStringSchema,
        PointSchema,],
    Discriminator("type"),
]

class AnyGeometrySchema(Schema):
    """
    A GeoJSON Geometry
    """
    type: NonEmptyStr
    coordinates: Any