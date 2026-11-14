"""API error type: carries an HTTP status, a stable machine-readable code and optional details."""


class ApiError(Exception):
    def __init__(self, status, code, message, details=None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details

    def to_dict(self):
        d = {"error": {"code": self.code, "message": self.message}}
        if self.details is not None:
            d["error"]["details"] = self.details
        return d


def bad(code, message, details=None):
    return ApiError(422, code, message, details)


def conflict(code, message, details=None):
    return ApiError(409, code, message, details)


def not_found(what, key):
    return ApiError(404, "NOT_FOUND", "%s '%s' does not exist" % (what, key))


def forbidden(code, message, details=None):
    return ApiError(403, code, message, details)
