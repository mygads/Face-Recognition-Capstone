from typing import NoReturn

from presensi_api.api.errors import ApiProblem


def feature_not_implemented(resource: str) -> NoReturn:
    raise ApiProblem(
        status_code=501,
        code="feature_not_implemented",
        message=f"The {resource} API is a contract placeholder and is not implemented.",
    )
