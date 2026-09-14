from __future__ import annotations

from typing import Optional


class DomainError(Exception):
    """Lỗi nghiệp vụ có mã HTTP và code cố định để API map trực tiếp."""

    http_status: int = 400
    code: str = "DOMAIN_ERROR"

    def __init__(self, message: str, *, code: Optional[str] = None, http_status: Optional[int] = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if http_status:
            self.http_status = http_status


class UnauthorizedError(DomainError):
    http_status = 401
    code = "UNAUTHORIZED"


class ForbiddenError(DomainError):
    http_status = 403
    code = "FORBIDDEN"


class ValidationDomainError(DomainError):
    http_status = 422
    code = "VALIDATION_ERROR"


class IdempotencyConflictError(DomainError):
    """Cùng khóa nhưng payload khác — theo mục 7, trả 409, không thay lệnh trước."""

    http_status = 409
    code = "IDEMPOTENCY_KEY_CONFLICT"


class PreviewInvalidError(DomainError):
    http_status = 422
    code = "PREVIEW_INVALID"


class BudgetExceededError(DomainError):
    http_status = 422
    code = "BUDGET_EXCEEDED"


class UnknownCostBlockedError(DomainError):
    http_status = 422
    code = "UNKNOWN_COST_BLOCKED"


class UnsupportedListingTypeError(DomainError):
    http_status = 422
    code = "UNSUPPORTED_LISTING_TYPE"


class PaymentAuthRequiredError(DomainError):
    http_status = 422
    code = "PAYMENT_AUTH_REQUIRED"


class LiveActionsDisabledError(DomainError):
    http_status = 422
    code = "LIVE_ACTIONS_DISABLED"


class CommandNotCancellableError(DomainError):
    http_status = 409
    code = "COMMAND_NOT_CANCELLABLE"


class NotFoundError(DomainError):
    http_status = 404
    code = "NOT_FOUND"
