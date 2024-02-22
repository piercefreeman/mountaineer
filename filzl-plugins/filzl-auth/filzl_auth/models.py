from uuid import UUID, uuid4

import bcrypt
from sqlmodel import Field, SQLModel


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password=password.encode(), salt=bcrypt.gensalt()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        password=plain_password.encode(), hashed_password=hashed_password.encode()
    )


class UserAuthMixin(SQLModel):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    email: str
    hashed_password: str
    is_verified: bool = False
    is_admin: bool = False

    def verify_password(self, plain_password: str) -> bool:
        return verify_password(plain_password, self.hashed_password)

    @staticmethod
    def get_password_hash(password: str) -> str:
        return hash_password(password)
