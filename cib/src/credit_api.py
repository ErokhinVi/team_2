"""CIB credit decisions using the documented backend application endpoints."""
import os
from decimal import Decimal
from typing import Annotated
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.credit import MissingClientData, decide

router = APIRouter()


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    application_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")


class Application(BaseModel):
    id: str
    client_id: str = Field(min_length=1)
    amount_rub: Decimal = Field(ge=50000, le=1500000, max_digits=9, decimal_places=2)
    term_months: int = Field(ge=6, le=60, strict=True)
    status: str


async def backend_client():
    url = os.environ.get("BACKEND_URL", "http://localhost:8003").rstrip("/")
    async with httpx.AsyncClient(base_url=url, timeout=10) as client:
        yield client


async def request_backend(client, method, path, **kwargs):
    try:
        response = await client.request(method, path, **kwargs)
    except httpx.HTTPError:
        raise HTTPException(503, detail={"code": "backend_unavailable"}) from None
    if response.status_code == 404:
        raise HTTPException(404, detail={"code": "backend_resource_not_found"})
    if response.status_code == 409:
        raise HTTPException(409, detail={"code": "decision_conflict"})
    if not response.is_success:
        raise HTTPException(502, detail={"code": "backend_rejected_request"})
    try:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except ValueError:
        raise HTTPException(502, detail={"code": "invalid_backend_response"}) from None


RESULT_FIELDS = ("decision", "reason_code", "reason", "approved_amount_rub",
                 "approved_term_months", "personal_rate_pct", "monthly_payment_rub")


def saved_result(data, application_id):
    if (data.get("id") != application_id or data.get("status") != "decided"
            or data.get("decision") not in ("approved", "rejected")
            or any(key not in data for key in RESULT_FIELDS)):
        raise HTTPException(502, detail={"code": "invalid_saved_decision"})
    return {"application_id": application_id, **{key: data[key] for key in RESULT_FIELDS}}


@router.post("/credit/decide")
async def credit_decide(body: DecisionRequest,
                        client: Annotated[httpx.AsyncClient, Depends(backend_client)]):
    path = "/credit-applications/" + quote(body.application_id, safe="")
    raw = await request_backend(client, "GET", path)
    try:
        application = Application.model_validate(raw)
    except ValidationError:
        raise HTTPException(502, detail={"code": "invalid_application_data"}) from None
    if application.id != body.application_id:
        raise HTTPException(502, detail={"code": "application_id_mismatch"})
    if application.status == "decided":
        return saved_result(raw, body.application_id)
    if application.status != "pending":
        raise HTTPException(409, detail={"code": "application_not_pending"})
    customer = await request_backend(client, "GET", "/clients/" + quote(application.client_id, safe=""))
    if customer.get("id") != application.client_id:
        raise HTTPException(502, detail={"code": "client_id_mismatch"})
    try:
        result = decide(customer, application.amount_rub, application.term_months)
    except MissingClientData as exc:
        raise HTTPException(409, detail={"code": "client_data_incomplete", "fields": exc.fields}) from None
    saved = await request_backend(client, "PATCH", path + "/decision", json=result)
    returned = saved_result(saved, body.application_id)
    if any(returned[key] != result[key] for key in RESULT_FIELDS):
        raise HTTPException(409, detail={"code": "decision_conflict"})
    return returned
