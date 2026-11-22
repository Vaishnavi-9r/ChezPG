from pydantic import BaseModel


class AuthMessageOut(BaseModel):
    message: str
