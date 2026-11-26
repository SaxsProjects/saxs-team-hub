"""Projects, contributor work shares, client payments, costs and payouts (README §4.5)."""

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user, require_admin
from ..models import PROJECT_STATUSES, ClientPayment, Payout, Project, ProjectContributor, ProjectCost, User
from ..numbering import allocate_number
from ..payouts import Instalment, calculate_payout_by_instalment
from ..pdf import payout_statement_pdf, task_fee_statement_pdf
from ..schemas import (
    ContributorIn,
    ContributorOut,
    CostIn,
    CostOut,
    MarkPaidIn,
    PaymentIn,
    PaymentRecordedOut,
    PayoutOut,
    ProjectCreate,
    ProjectDetailOut,
    ProjectOut,
    ProjectUpdate,
)
from ..services import audit, payout_due_date, today_local
from ..terms import rate_at, release_deferred_fees
from .people import get_person

router = APIRouter(prefix="/api", tags=["projects & payouts"])

ELIGIBLE_STAGES = ("accepted", "agreement_signed", "onboarded")


def get_project(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


def project_detail(project: Project) -> ProjectDetailOut:
    received = sum(p.amount_cents for p in project.payments)
    costs = sum(c.amount_cents for c in project.costs)
    return ProjectDetailOut.model_validate(
        {
            **ProjectOut.model_validate(project).model_dump(),
            "contributors": project.contributors,
            "payments": project.payments,
            "costs": project.costs,
            "received_cents": received,
            "costs_cents": costs,
            "net_income_cents": received - costs,
        }
    )


def lock_contributors(db: Session, project: Project, actor: str) -> int:
    now = datetime.now(UTC)
    locked = 0
    for c in project.contributors:
        if c.locked_at is None:
            c.locked_at = now
            locked += 1
    if locked:
        audit(
            db,
            actor,
            "project.lock_shares",
            "project",
            project.id,
            after={"shares": {c.person_id: c.work_share_bp for c in project.contributors}},
        )
    return locked


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.scalars(select(Project).order_by(Project.created_at.desc())).all()


@router.post("/projects", response_model=ProjectDetailOut, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    project = Project(**body.model_dump())
    db.add(project)
    db.flush()
    audit(db, admin.email, "project.create", "project", project.id, after={"name": project.name})
    db.commit()
    return project_detail(project)


@router.get("/projects/{project_id}", response_model=ProjectDetailOut)
def read_project(project_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return project_detail(get_project(db, project_id))


@router.patch("/projects/{project_id}", response_model=ProjectDetailOut)
def update_project(project_id: int, body: ProjectUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    project = get_project(db, project_id)
    changes = body.model_dump(exclude_unset=True)
    if "status" in changes and changes["status"] not in PROJECT_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"status must be one of {PROJECT_STATUSES}")
    for key, value in changes.items():
        setattr(project, key, value)
    if changes.get("status") == "in_progress":
        lock_contributors(db, project, admin.email)  # shares are locked once work begins
    audit(db, admin.email, "project.update", "project", project.id, after=changes)
    db.commit()
    return project_detail(project)


@router.put("/projects/{project_id}/contributors", response_model=ContributorOut)
def set_contributor(project_id: int, body: ContributorIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    project = get_project(db, project_id)
    person = get_person(db, body.person_id)
    if person.status not in ELIGIBLE_STAGES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only people who accepted an offer can be contributors")
    existing = next((c for c in project.contributors if c.person_id == person.id), None)
    if existing and existing.locked_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "This work share is locked because work has begun")
    others = sum(c.work_share_bp for c in project.contributors if c.person_id != person.id)
    if others + body.work_share_bp > 10_000:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Work shares would add up to {(others + body.work_share_bp) / 100:g}% (max 100%)"
        )
    current_rate = rate_at(db, person.id, today_local())
    if existing:
        before = {"work_share_bp": existing.work_share_bp}
        existing.work_share_bp = body.work_share_bp
        existing.rate_bp = current_rate
        contributor = existing
    else:
        before = None
        contributor = ProjectContributor(
            project_id=project.id, person_id=person.id, work_share_bp=body.work_share_bp, rate_bp=current_rate
        )
        db.add(contributor)
    db.flush()
    audit(
        db,
        admin.email,
        "project.set_contributor",
        "project",
        project.id,
        before,
        {"person_id": person.id, "work_share_bp": body.work_share_bp, "rate_bp": current_rate},
    )
    db.commit()
    return contributor


@router.delete("/projects/{project_id}/contributors/{person_id}", status_code=204)
def remove_contributor(project_id: int, person_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    project = get_project(db, project_id)
    contributor = next((c for c in project.contributors if c.person_id == person_id), None)
    if not contributor:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not a contributor")
    if contributor.locked_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "This work share is locked because work has begun")
    db.delete(contributor)
    audit(db, admin.email, "project.remove_contributor", "project", project.id, after={"person_id": person_id})
    db.commit()


@router.post("/projects/{project_id}/lock", response_model=ProjectDetailOut)
def lock_shares(project_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    project = get_project(db, project_id)
    if not project.contributors:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Add contributors first")
    lock_contributors(db, project, admin.email)
    db.commit()
    return project_detail(project)


@router.post("/projects/{project_id}/costs", response_model=CostOut, status_code=201)
def add_cost(project_id: int, body: CostIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    project = get_project(db, project_id)
    cost = ProjectCost(project_id=project.id, **body.model_dump())
    db.add(cost)
    db.flush()
    audit(
        db,
        admin.email,
        "project.add_cost",
        "project_cost",
        cost.id,
        after={"project_id": project.id, "amount_cents": cost.amount_cents},
    )
    db.commit()
    return cost


def next_statement_number(db: Session) -> str:
    year = today_local().year

    def existing() -> int:  # statements numbered before the sequence table existed
        return db.scalar(select(func.count(Payout.id)).where(Payout.statement_number.like(f"SP-PS-{year}-%"))) or 0

    return allocate_number(db, "PS", year, seed=existing)


def record_client_payment(
    db: Session, project: Project, *, amount_cents: int, received_at: date, reference: str, actor: str
) -> tuple[ClientPayment, list[Payout]]:
    """Record money received from the client (excluding VAT) and create the payouts it triggers. The caller commits."""
    lock_contributors(db, project, actor)
    payment = ClientPayment(project_id=project.id, amount_cents=amount_cents, received_at=received_at, reference=reference)
    db.add(payment)
    db.flush()
    audit(
        db,
        actor,
        "project.record_payment",
        "client_payment",
        payment.id,
        after={"project_id": project.id, "amount_cents": payment.amount_cents},
    )

    instalments = db.scalars(
        select(ClientPayment).where(ClientPayment.project_id == project.id).order_by(ClientPayment.received_at, ClientPayment.id)
    ).all()
    costs_to_date = db.scalar(select(func.sum(ProjectCost.amount_cents)).where(ProjectCost.project_id == project.id)) or 0
    payouts = []
    for c in project.contributors:
        allocated = (
            db.scalar(
                select(func.sum(Payout.amount_cents)).where(Payout.project_id == project.id, Payout.person_id == c.person_id)
            )
            or 0
        )
        # Each instalment is shared at the rate in force on the day it was received (agreement clause 5).
        calc = calculate_payout_by_instalment(
            instalments=[
                Instalment(p.amount_cents, rate_at(db, c.person_id, p.received_at), p.received_at.isoformat())
                for p in instalments
            ],
            costs_to_date_cents=costs_to_date,
            work_share_bp=c.work_share_bp,
            previously_allocated_cents=allocated,
        )
        if calc.payout_cents <= 0:
            continue
        payout = Payout(
            project_id=project.id,
            person_id=c.person_id,
            client_payment_id=payment.id,
            amount_cents=calc.payout_cents,
            due_at=payout_due_date(payment.received_at),
            statement_number=next_statement_number(db),
            calculation=calc.as_dict(),
        )
        db.add(payout)
        db.flush()
        audit(
            db,
            actor,
            "payout.create",
            "payout",
            payout.id,
            after={"person_id": c.person_id, "amount_cents": payout.amount_cents, "due_at": str(payout.due_at)},
        )
        payouts.append(payout)
    release_deferred_fees(db, actor)
    return payment, payouts


@router.post("/projects/{project_id}/payments", response_model=PaymentRecordedOut, status_code=201)
def record_payment(project_id: int, body: PaymentIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Record money received from the client and create the payouts it triggers."""
    project = get_project(db, project_id)
    if not project.contributors:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Add contributors (with agreed work shares) first")
    payment, payouts = record_client_payment(db, project, actor=admin.email, **body.model_dump())
    db.commit()
    return PaymentRecordedOut(payment=payment, payouts=payouts)


@router.get("/payouts", response_model=list[PayoutOut])
def list_payouts(unpaid: bool = False, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    q = select(Payout).order_by(Payout.due_at.asc().nulls_last(), Payout.id)
    if unpaid:
        q = q.where(Payout.paid_at.is_(None))
    return db.scalars(q).all()


@router.post("/payouts/{payout_id}/paid", response_model=PayoutOut)
def mark_paid(payout_id: int, body: MarkPaidIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    payout = db.get(Payout, payout_id)
    if not payout:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payout not found")
    if payout.paid_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already marked as paid")
    payout.paid_at = datetime.now(UTC)
    payout.eft_reference = body.eft_reference.strip()
    audit(db, admin.email, "payout.paid", "payout", payout.id, after={"eft_reference": payout.eft_reference})
    db.commit()
    return payout


@router.get("/payouts/{payout_id}/statement.pdf")
def payout_statement(payout_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    payout = db.get(Payout, payout_id)
    # Members may only see their own statements; don't reveal whether other ids exist.
    if not payout or (user.role != "admin" and payout.person_id != user.person_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Statement not found")
    if user.role == "admin":
        require_admin(user)
    if payout.kind == "task_fee":
        order = payout.task_order
        pdf = task_fee_statement_pdf(
            statement_number=payout.statement_number,
            contributor=payout.person.full_name,
            task_number=order.number,
            title=order.title,
            deliverable=order.deliverable,
            fee_cents=payout.amount_cents,
            accepted_on=order.accepted_on.isoformat(),
            due_at=payout.due_at.isoformat() if payout.due_at else None,
            paid_at=payout.paid_at.date().isoformat() if payout.paid_at else None,
            eft_reference=payout.eft_reference,
            issued_on=payout.created_at.date(),
        )
        headers = {"Content-Disposition": f'inline; filename="{payout.statement_number}.pdf"'}
        return Response(pdf, media_type="application/pdf", headers=headers)
    pdf = payout_statement_pdf(
        statement_number=payout.statement_number,
        project_name=payout.project.name,
        client_name=payout.project.client_name,
        contributor=payout.person.full_name,
        payment_date=payout.client_payment.received_at.isoformat(),
        payment_reference=payout.client_payment.reference,
        calc=payout.calculation,
        due_at=payout.due_at.isoformat(),
        paid_at=payout.paid_at.date().isoformat() if payout.paid_at else None,
        eft_reference=payout.eft_reference,
        issued_on=payout.created_at.date(),
    )
    return Response(
        pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{payout.statement_number}.pdf"'}
    )
