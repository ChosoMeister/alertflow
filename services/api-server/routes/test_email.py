"""
Test Email API - Send test emails with routing preview.
"""
from fastapi import APIRouter, Depends, HTTPException

from auth import User, get_current_user, require_operator
from models import TestEmailRequest, TestEmailResponse, RoutingTestResponse
from services.redis_service import get_redis_service
from services.routing_service import get_routing_result

router = APIRouter(prefix="/test-email", tags=["test"])


@router.post("", response_model=TestEmailResponse)
async def send_test_email(request: TestEmailRequest, user: User = Depends(require_operator)):
    """
    Send a test email to the queue with routing preview.

    The FROM email address is used to evaluate routing rules.
    Returns the matched routing rule (if any) and where the alert will be sent.
    """
    redis_svc = get_redis_service()
    rules = redis_svc.list_routing_rules()

    # Get routing preview
    routing_preview = get_routing_result(request.from_email, "from", rules)

    # Queue the test email
    email_data = {
        "from": request.from_email,
        "to": request.to_email,
        "subject": request.subject,
        "text": request.body,
        "html": "",
        "rcpt_tos": [request.to_email],
        "is_test": True,
    }

    trace_id = redis_svc.push_to_queue(email_data)

    redis_svc.add_log("INFO", "api", f"Test email queued: {request.from_email} -> {request.to_email}", {
        "trace_id": trace_id,
        "subject": request.subject[:50],
    })

    return TestEmailResponse(
        queued=True,
        trace_id=trace_id,
        routing_preview=routing_preview
    )


@router.post("/preview", response_model=RoutingTestResponse)
async def preview_routing(request: TestEmailRequest, user: User = Depends(get_current_user)):
    """
    Preview routing without sending the email.

    Use this to see which rule would match before sending.
    """
    redis_svc = get_redis_service()
    rules = redis_svc.list_routing_rules()

    return get_routing_result(request.from_email, "from", rules)
