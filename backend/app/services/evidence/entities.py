"""Upsert companies and people by Crustdata id, so one entity is always one record.

Callers own the transaction: these functions execute but never commit.
"""

from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.entities import Company, CompanyPerson, Person


def upsert_company(db: Session, company_data: dict[str, Any]) -> Company:
    """`company_data` is one Crustdata company record (as in `/company/enrich`)."""
    basic = company_data.get("basic_info") or {}
    crustdata_id = company_data.get("crustdata_company_id") or basic.get("crustdata_company_id")
    name = basic.get("name") or company_data.get("name")
    if crustdata_id is None or not name:
        raise ValueError("company record needs crustdata_company_id and a name")
    stmt = insert(Company).values(
        crustdata_company_id=crustdata_id, name=name, domain=basic.get("primary_domain")
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Company.crustdata_company_id],
        # a later record without a domain must not erase the one we have
        set_={"name": stmt.excluded.name,
              "domain": func.coalesce(stmt.excluded.domain, Company.domain)},
    )
    return db.scalars(
        stmt.returning(Company), execution_options={"populate_existing": True}
    ).one()


def upsert_person(db: Session, person_data: dict[str, Any]) -> Person:
    """`person_data` is one Crustdata person record (as in `/person/enrich`)."""
    basic = person_data.get("basic_profile") or {}
    crustdata_id = person_data.get("crustdata_person_id")
    name = basic.get("name") or person_data.get("name")
    if crustdata_id is None or not name:
        raise ValueError("person record needs crustdata_person_id and a name")
    handles = person_data.get("social_handles") or {}
    linkedin = (handles.get("professional_network_identifier") or {}).get("profile_url")
    stmt = insert(Person).values(
        crustdata_person_id=crustdata_id, name=name, linkedin_url=linkedin
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Person.crustdata_person_id],
        set_={"name": stmt.excluded.name,
              "linkedin_url": func.coalesce(stmt.excluded.linkedin_url, Person.linkedin_url)},
    )
    return db.scalars(
        stmt.returning(Person), execution_options={"populate_existing": True}
    ).one()


def link_person(db: Session, company: Company, person: Person, role: str) -> None:
    """Idempotent: linking the same (company, person, role) twice is a no-op."""
    db.execute(
        insert(CompanyPerson)
        .values(company_id=company.id, person_id=person.id, role=role)
        .on_conflict_do_nothing()
    )
