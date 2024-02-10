from filzl.exceptions import APIException


class UnauthorizedError(APIException):
    status_code = 401
    detail = "You're not authorized to access this resource."
