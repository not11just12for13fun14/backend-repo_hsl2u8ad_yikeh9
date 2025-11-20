import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import Hospital, Review

app = FastAPI(title="Hospital Bed Finder API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class NearbyQuery(BaseModel):
    lat: float
    lng: float
    radius_km: float = 25.0
    specialty: Optional[str] = None


def to_serializable(doc):
    if not doc:
        return doc
    d = dict(doc)
    if "_id" in d:
        d["id"] = str(d.pop("_id"))
    # Ensure location keys are serializable
    if "location" in d and isinstance(d["location"], dict):
        # leave as is
        pass
    return d


@app.get("/")
def read_root():
    return {"message": "Hospital Bed Finder Backend Running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, 'name') else "Unknown"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections
                response["database"] = "✅ Connected & Working"
                response["connection_status"] = "Connected"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# Seed random sample data if empty
@app.post("/seed")
def seed_data():
    import random
    from schemas import GeoLocation

    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    if db["hospital"].count_documents({}) > 0:
        return {"status": "exists", "count": db["hospital"].count_documents({})}

    specialties_pool = [
        "Cardiology", "Neurology", "Orthopedics", "Pediatrics", "Oncology", "Dermatology",
        "Emergency", "Gynecology", "Gastroenterology", "Psychiatry"
    ]
    images = [
        "https://images.unsplash.com/photo-1586773860418-d37222d8fce3",
        "https://images.unsplash.com/photo-1584433144859-1fc3ab64a957",
        "https://images.unsplash.com/photo-1576765608648-8c36509f63a3",
        "https://images.unsplash.com/photo-1576091160399-112ba8d25d1d"
    ]

    base_lat, base_lng = 28.6139, 77.2090  # New Delhi as sample

    for i in range(12):
        total = random.randint(50, 300)
        available = random.randint(0, total)
        hospital = Hospital(
            name=f"CityCare Hospital {i+1}",
            address=f"{100+i}, Healthcare Ave, Sector {i+2}, Delhi",
            location=GeoLocation(lat=base_lat + random.uniform(-0.2, 0.2), lng=base_lng + random.uniform(-0.2, 0.2)),
            specialties=random.sample(specialties_pool, k=random.randint(2, 5)),
            total_beds=total,
            available_beds=available,
            image_url=random.choice(images)
        )
        create_document("hospital", hospital)

    # Add a few reviews for random hospitals
    hospital_ids = [str(h["_id"]) for h in db["hospital"].find({}, {"_id": 1}).limit(12)]
    for hid in hospital_ids:
        for _ in range(random.randint(1, 4)):
            review_doc = {
                "hospital_id": hid,
                "user_name": random.choice(["Aarav", "Vihaan", "Diya", "Sara", "Arjun", "Maya"]),
                "rating": random.randint(3, 5),
                "comment": random.choice([
                    "Great staff and quick response.",
                    "Clean and well maintained.",
                    "Doctors are very attentive.",
                    "Slightly crowded but service is good."
                ])
            }
            create_document("review", review_doc)

    return {"status": "seeded", "count": db["hospital"].count_documents({})}


@app.get("/hospitals")
def list_hospitals(specialty: Optional[str] = None):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    query = {}
    if specialty:
        query["specialties"] = {"$regex": specialty, "$options": "i"}
    hospitals = [to_serializable(h) for h in db["hospital"].find(query).limit(100)]
    return hospitals


@app.get("/hospitals/nearby")
def hospitals_nearby(
    lat: float = Query(..., description="Latitude"),
    lng: float = Query(..., description="Longitude"),
    radius_km: float = Query(25.0, description="Search radius in km"),
    specialty: Optional[str] = Query(None, description="Filter by specialty")
):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    def haversine(lat1, lon1, lat2, lon2):
        from math import radians, sin, cos, asin, sqrt
        R = 6371
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        return R * c

    results = []
    for h in db["hospital"].find({}).limit(300):
        if specialty:
            has = False
            for s in h.get("specialties", []):
                if specialty.lower() in s.lower():
                    has = True
                    break
            if not has:
                continue
        loc = h.get("location", {})
        d_km = haversine(lat, lng, float(loc.get("lat", 0)), float(loc.get("lng", 0)))
        if d_km <= radius_km:
            h["distance_km"] = round(d_km, 2)
            results.append(to_serializable(h))

    # Sort by distance then by availability ratio desc
    results.sort(key=lambda x: (x.get("distance_km", 9999), -x.get("available_beds", 0)))
    return results


@app.get("/hospitals/{hospital_id}")
def get_hospital(hospital_id: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    try:
        doc = db["hospital"].find_one({"_id": ObjectId(hospital_id)})
        if not doc:
            raise HTTPException(status_code=404, detail="Hospital not found")
        # Attach average rating
        reviews = list(db["review"].find({"hospital_id": hospital_id}))
        avg = None
        if reviews:
            avg = round(sum(r.get("rating", 0) for r in reviews) / len(reviews), 1)
        d = to_serializable(doc)
        d["avg_rating"] = avg
        d["reviews_count"] = len(reviews)
        return d
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid hospital id")


@app.get("/hospitals/{hospital_id}/reviews")
def hospital_reviews(hospital_id: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    reviews = [to_serializable(r) for r in db["review"].find({"hospital_id": hospital_id}).limit(100)]
    return reviews


# Hospital-side updates
class UpdateBeds(BaseModel):
    available_beds: int


@app.post("/hospitals/{hospital_id}/beds")
def update_beds(hospital_id: str, payload: UpdateBeds):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    try:
        res = db["hospital"].update_one({"_id": ObjectId(hospital_id)}, {"$set": {"available_beds": payload.available_beds}})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Hospital not found")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid hospital id")


# Recommendation endpoint using specialties + rating + availability
@app.get("/recommend")
def recommend(
    lat: float = Query(...),
    lng: float = Query(...),
    specialty: Optional[str] = Query(None)
):
    nearby = hospitals_nearby(lat=lat, lng=lng, radius_km=50, specialty=specialty)
    # Sort with a simple score: availability ratio + rating weight
    scored = []
    for h in nearby:
        avail_ratio = (h.get("available_beds", 0) / max(1, h.get("total_beds", 1)))
        reviews = list(db["review"].find({"hospital_id": h["id"]}))
        rating = 0
        if reviews:
            rating = sum(r.get("rating", 0) for r in reviews) / len(reviews)
        score = avail_ratio * 0.6 + (rating / 5) * 0.4
        h["score"] = round(score, 3)
        h["avg_rating"] = round(rating, 1) if reviews else None
        scored.append(h)
    scored.sort(key=lambda x: -x.get("score", 0))
    return scored[:10]


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
