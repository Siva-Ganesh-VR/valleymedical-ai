"""Roles and permissions.

POC ONLY: the caller identifies itself with X-Demo-User / X-Demo-Role headers.
Production must replace this with SSO/OIDC and server-side role assignment.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    PROVIDER = "provider"
    BILLER = "biller"
    BILLING_APPROVER = "billing_approver"
    ADMIN = "admin"
    SYSTEM = "system"


@dataclass(frozen=True)
class Actor:
    username: str
    role: Role


BILLING_AGENT = Actor("billing-agent", Role.SYSTEM)


class Permission(str, Enum):
    CLINICAL_READ = "clinical:read"
    BILLING_READ = "billing:read"
    BILLING_WORK = "billing:work"
    BILLING_CLASSIFY_REVIEW = "billing:classify_review"
    BILLING_APPROVE = "billing:approve"
    EXCEPTIONS_READ = "exceptions:read"
    EXCEPTIONS_RESOLVE = "exceptions:resolve"
    AUDIT_READ = "audit:read"
    DOC_AUDIT_RUN = "doc_audit:run"
    DOC_AUDIT_REVIEW = "doc_audit:review"
    BILLING_INSIGHTS = "billing:insights"
    BASELINE_EDIT = "billing:baseline_edit"
    ACCEPTANCE_READ = "acceptance:read"
    ACCEPTANCE_RUN = "acceptance:run"
    AI_USAGE_READ = "ai:usage_read"
    AI_CONTROL = "ai:control"
    DEMO_WORKLOAD = "billing:demo_workload"


_GRANTS: dict[Permission, frozenset[Role]] = {
    Permission.CLINICAL_READ: frozenset({Role.PROVIDER, Role.ADMIN}),
    Permission.BILLING_READ: frozenset({Role.BILLER, Role.BILLING_APPROVER, Role.ADMIN}),
    Permission.BILLING_WORK: frozenset({Role.BILLER, Role.BILLING_APPROVER}),
    Permission.BILLING_CLASSIFY_REVIEW: frozenset({Role.BILLER, Role.BILLING_APPROVER}),
    Permission.BILLING_APPROVE: frozenset({Role.BILLING_APPROVER}),
    Permission.EXCEPTIONS_READ: frozenset(
        {Role.PROVIDER, Role.BILLER, Role.BILLING_APPROVER, Role.ADMIN}
    ),
    Permission.EXCEPTIONS_RESOLVE: frozenset({Role.PROVIDER, Role.BILLING_APPROVER, Role.ADMIN}),
    Permission.AUDIT_READ: frozenset({Role.ADMIN}),
    Permission.DOC_AUDIT_RUN: frozenset({Role.PROVIDER, Role.ADMIN}),
    Permission.DOC_AUDIT_REVIEW: frozenset({Role.PROVIDER}),
    Permission.BILLING_INSIGHTS: frozenset({Role.BILLER, Role.BILLING_APPROVER, Role.ADMIN}),
    Permission.BASELINE_EDIT: frozenset({Role.BILLING_APPROVER, Role.ADMIN}),
    Permission.ACCEPTANCE_READ: frozenset({Role.PROVIDER, Role.BILLER, Role.BILLING_APPROVER, Role.ADMIN}),
    Permission.ACCEPTANCE_RUN: frozenset({Role.ADMIN}),
    Permission.AI_USAGE_READ: frozenset({Role.ADMIN, Role.BILLING_APPROVER}),
    Permission.AI_CONTROL: frozenset({Role.ADMIN}),
    Permission.DEMO_WORKLOAD: frozenset({Role.BILLING_APPROVER, Role.ADMIN}),
}


def has_permission(actor: Actor, permission: Permission) -> bool:
    return actor.role in _GRANTS[permission]


def permissions_for(role: Role) -> list[str]:
    return sorted(p.value for p, roles in _GRANTS.items() if role in roles)
