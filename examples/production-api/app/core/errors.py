class ApplicationError(Exception):
    code = "application_error"
    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ConflictError(ApplicationError):
    code = "conflict"
    status_code = 409


class NotFoundError(ApplicationError):
    code = "not_found"
    status_code = 404
