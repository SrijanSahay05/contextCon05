"""Imports every module that registers a job handler, so the worker knows all job kinds.

Each phase adds its handler module here (integrator-owned).
"""

from app.services.onboarding import identity_job  # noqa: E402,F401
from app.services.onboarding import thesis_job  # noqa: E402,F401
from app.services.search import search_job  # noqa: E402,F401
