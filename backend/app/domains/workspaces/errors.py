"""Workspace integration binding errors."""

from __future__ import annotations


class WorkspaceBindingError(Exception):
    """Base error for workspace integration binding operations."""


class WorkspaceBindingValidationError(WorkspaceBindingError):
    """Raised when a workspace binding model or configuration is invalid."""


class WorkspaceBindingNotFoundError(WorkspaceBindingError):
    """Raised when a requested workspace binding is not found."""


class WorkspaceBindingDuplicateError(WorkspaceBindingError):
    """Raised when an active binding for the same workspace and provider already exists."""


class WorkspaceBindingStateError(WorkspaceBindingError):
    """Raised when a binding or provider is in an invalid lifecycle state for an operation."""


class WorkspaceBindingPermissionError(WorkspaceBindingValidationError):
    """Raised when granted permission scopes are incompatible with provider requirements."""
