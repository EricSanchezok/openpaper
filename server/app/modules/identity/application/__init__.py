"""Identity application contracts."""

from .contracts import BlockUserRequest
from .onboarding_contracts import CreateOnboardingRequest, OnboardingResponse

__all__ = ["BlockUserRequest", "CreateOnboardingRequest", "OnboardingResponse"]
