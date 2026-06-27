from pydantic import BaseModel, Field

class Point(BaseModel):
    x: float = Field(description="X coordinate percentage (0.0 to 100.0, 0 is left, 100 is right)")
    y: float = Field(description="Y coordinate percentage (0.0 to 100.0, 0 is top, 100 is bottom)")

class DetectedFeature(BaseModel):
    concept_canonical_name: str = Field(description="The snake_case name of the concept found.")
    attribute_name: str = Field(description="The precise attribute observed")
    attribute_value: str = Field(description="The value of the attribute")
    path: list[Point] = Field(description="For lines, a list of 3-6 points tracing the line. For mounts or areas, 1 center point or a rough outline of 3-4 points.")

class HandAnalysis(BaseModel):
    detected_features: list[DetectedFeature] = Field(description="List of all palmistry features")
