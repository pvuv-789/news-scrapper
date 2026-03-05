"""
Database seed script — populates initial Publication, Editions, and Sections.
Run once after migrations: uv run python seed.py
"""
import asyncio
import uuid

from sqlalchemy import select

from core.database import AsyncSessionFactory
from models.db_models import Edition, Publication, Section


PUBLICATION = {
    "id": uuid.UUID("00000000-0000-0000-0000-000000000001"),
    "name": "Daily Thanthi",
    "paper_type": "epaper",
    "base_url": "https://epaper.dailythanthi.com",
    "is_active": True,
}

EDITIONS = [
    # ── Existing (preserved) ───────────────────────────────────────────────────
    {"display_name": "Chennai",                        "city_code": "chennai"},
    {"display_name": "Madurai",                        "city_code": "madurai"},
    {"display_name": "Coimbatore",                     "city_code": "coimbatore"},
    {"display_name": "Trichy",                         "city_code": "trichy"},
    {"display_name": "Salem",                          "city_code": "salem"},
    {"display_name": "Tirunelveli",                    "city_code": "tirunelveli"},
    {"display_name": "Vellore",                        "city_code": "vellore"},
    {"display_name": "Erode",                          "city_code": "erode"},
    {"display_name": "Pondicherry",                    "city_code": "pondicherry"},
    # ── All other districts ────────────────────────────────────────────────────
    {"display_name": "Andhra",                         "city_code": "andhra"},
    {"display_name": "Bengaluru",                      "city_code": "bengaluru"},
    {"display_name": "Chengalpattu",                   "city_code": "chengalpattu"},
    {"display_name": "Chidambaram & Virudhachalam",    "city_code": "chidambaram-virudhachalam"},
    {"display_name": "Colombo",                        "city_code": "colombo"},
    {"display_name": "Cuddalore",                      "city_code": "cuddalore"},
    {"display_name": "Dharampuri",                     "city_code": "dharampuri"},
    {"display_name": "Dindigul",                       "city_code": "dindigul"},
    {"display_name": "Dindigul District",              "city_code": "dindigul-district"},
    {"display_name": "Dubai",                          "city_code": "dubai"},
    {"display_name": "Erode District",                 "city_code": "erode-district"},
    {"display_name": "Hosur",                          "city_code": "hosur"},
    {"display_name": "Kallakurichi",                   "city_code": "kallakurichi"},
    {"display_name": "Kancheepuram",                   "city_code": "kancheepuram"},
    {"display_name": "Kangeyam, Dharapuram, U.Malai",  "city_code": "kangeyam-dharapuram"},
    {"display_name": "Karur",                          "city_code": "karur"},
    {"display_name": "Kerala & Theni",                 "city_code": "kerala-theni"},
    {"display_name": "Kerala Coimbatore",              "city_code": "kerala-coimbatore"},
    {"display_name": "Kerala Nagarcoil",               "city_code": "kerala-nagarcoil"},
    {"display_name": "Krishnagiri",                    "city_code": "krishnagiri"},
    {"display_name": "Kumbakonam & Pattukottai",       "city_code": "kumbakonam-pattukottai"},
    {"display_name": "Kunnatur, Ch.Palli, U.Kuli",     "city_code": "kunnatur"},
    {"display_name": "Mangalore & Raichur",            "city_code": "mangalore-raichur"},
    {"display_name": "Mumbai",                         "city_code": "mumbai"},
    {"display_name": "Mysore & KGF",                   "city_code": "mysore-kgf"},
    {"display_name": "Nagai & Karaikal",               "city_code": "nagai-karaikal"},
    {"display_name": "Nagarcoil",                      "city_code": "nagarcoil"},
    {"display_name": "Nagarcoil District",             "city_code": "nagarcoil-district"},
    {"display_name": "Namakkal",                       "city_code": "namakkal"},
    {"display_name": "Nilgiris (Ooty)",                "city_code": "nilgiris"},
    {"display_name": "Perambalur & Ariyalur",          "city_code": "perambalur-ariyalur"},
    {"display_name": "Pollachi & Mettupalayam",        "city_code": "pollachi-mettupalayam"},
    {"display_name": "Pudukkottai",                    "city_code": "pudukkottai"},
    {"display_name": "Ramnad & Sivagangai",            "city_code": "ramnad-sivagangai"},
    {"display_name": "Ranipet & Tirupathur District",  "city_code": "ranipet-tirupathur"},
    {"display_name": "Salem District",                 "city_code": "salem-district"},
    {"display_name": "Tanjore",                        "city_code": "tanjore"},
    {"display_name": "Thoothukudi (Tuticorin)",        "city_code": "thoothukudi"},
    {"display_name": "Tirunelveli District",           "city_code": "tirunelveli-district"},
    {"display_name": "Tirupur",                        "city_code": "tirupur"},
    {"display_name": "Tirupur District",               "city_code": "tirupur-district"},
    {"display_name": "Tiruvallur",                     "city_code": "tiruvallur"},
    {"display_name": "Tiruvannamalai",                 "city_code": "tiruvannamalai"},
    {"display_name": "Tiruvarur",                      "city_code": "tiruvarur"},
    {"display_name": "Villupuram",                     "city_code": "villupuram"},
    {"display_name": "Villupuram & Cuddalore",         "city_code": "villupuram-cuddalore"},
    {"display_name": "Virudhunagar",                   "city_code": "virudhunagar"},
]

SECTIONS = [
    {"name": "Politics", "slug": "politics"},
    {"name": "Crime", "slug": "crime"},
    {"name": "Sports", "slug": "sports"},
    {"name": "Business", "slug": "business"},
    {"name": "Technology", "slug": "technology"},
    {"name": "Health", "slug": "health"},
    {"name": "Weather", "slug": "weather"},
    {"name": "Education", "slug": "education"},
    {"name": "Tamil Nadu", "slug": "tamil-nadu"},
    {"name": "India", "slug": "india"},
    {"name": "World", "slug": "world"},
]


async def seed() -> None:
    async with AsyncSessionFactory() as session:
        # Publication
        existing = await session.execute(
            select(Publication).where(Publication.id == PUBLICATION["id"])
        )
        if not existing.scalar_one_or_none():
            pub = Publication(**PUBLICATION)
            session.add(pub)
            print(f"✔ Publication '{pub.name}' seeded  (id={pub.id})")
        else:
            print("ℹ Publication already exists — skipping.")

        await session.flush()

        # Editions
        for ed_data in EDITIONS:
            existing = await session.execute(
                select(Edition).where(
                    Edition.publication_id == PUBLICATION["id"],
                    Edition.city_code == ed_data["city_code"],
                )
            )
            if not existing.scalar_one_or_none():
                edition = Edition(
                    publication_id=PUBLICATION["id"],
                    **ed_data,
                    is_active=True,
                )
                session.add(edition)
                print(f"  ✔ Edition '{ed_data['display_name']}' seeded.")

        # Sections
        for sec_data in SECTIONS:
            existing = await session.execute(
                select(Section).where(Section.slug == sec_data["slug"])
            )
            if not existing.scalar_one_or_none():
                section = Section(**sec_data)
                session.add(section)
                print(f"  ✔ Section '{sec_data['name']}' seeded.")

        await session.commit()
        print("\n✅ Seed complete.")
        print(f"\n📌 Use this publication_id in Celery tasks:\n   {PUBLICATION['id']}")


if __name__ == "__main__":
    asyncio.run(seed())
