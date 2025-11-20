"""
Database Schemas for Hospital Finder

Each Pydantic model corresponds to a collection with the lowercase class name.
- Hospital -> "hospital"
- Review   -> "review"

Use these models for validation when inserting/updating documents.
"""
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from datetime import datetime


class GeoLocation(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Latitude")
    lng: float = Field(..., ge=-180, le=180, description="Longitude")


class Hospital(BaseModel):
    name: str = Field(..., description="Hospital name")
    address: str = Field(..., description="Full address")
    location: GeoLocation = Field(..., description="Geo coordinates")
    specialties: List[str] = Field(default_factory=list, description="Medical specialties")
    total_beds: int = Field(..., ge=0, description="Total bed capacity")
    available_beds: int = Field(..., ge=0, description="Currently available beds")
    image_url: Optional[str] = Field(None, description="Display image URL")
    
    @field_validator("available_beds")
    @classmethod
    def validate_available_beds(cls, v, info):
        total = info.data.get("total_beds")
        if total is not None and v > total:
            raise ValueError("available_beds cannot exceed total_beds")
        return v


class Review(BaseModel):
    hospital_id: str = Field(..., description="Reference to hospital _id as string")
    user_name: str = Field(..., description="Reviewer name")
    rating: int = Field(..., ge=1, le=5, description="Rating 1-5")
    comment: Optional[str] = Field(None, description="Review text")
    visit_date: Optional[datetime] = Field(default=None, description="Date of visit")
