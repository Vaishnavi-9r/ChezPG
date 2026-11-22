import unittest
from unittest.mock import patch

from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.auth import change_password, login, register
from app.api.v1.dependencies import require_admin_account, require_owner
from app.core.config import settings
from app.core.security import verify_password
from app.db.base import Base
from app.models import Owner
from app.schemas.owner import (
    AuthLoginRequest,
    ChangePasswordRequest,
    OwnerRegistration,
)


class AuthWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.secret_patch = patch.object(
            settings,
            "owner_token_secret",
            "a-test-token-secret-that-is-at-least-32-bytes",
        )
        self.secret_patch.start()

    def tearDown(self):
        self.secret_patch.stop()
        self.db.close()
        self.engine.dispose()

    def registration(self, **overrides):
        values = {
            "full_name": "Test Account",
            "phone_number": "0091 (98765) 43210",
            "password": "a-very-safe-password",
            "account_type": "owner",
            "relationship_type": "property_owner",
            "email": None,
        }
        values.update(overrides)
        return OwnerRegistration(**values)

    def register_and_login(self):
        registered = register(self.registration(), self.db)
        account = self.db.get(Owner, registered.id)
        result = login(
            AuthLoginRequest(
                phone_number=" +91 98765-43210 ",
                password="a-very-safe-password",
            ),
            self.db,
        )
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=result.access_token,
        )
        return registered, account, credentials, result

    def test_registration_normalizes_phone_hashes_password_and_does_not_verify(self):
        response, account, _, _ = self.register_and_login()

        self.assertEqual(response.phone_number, "+919876543210")
        self.assertEqual(account.phone_number, "+919876543210")
        self.assertEqual(account.role, "owner")
        self.assertFalse(account.phone_verified)
        self.assertEqual(response.verification_status, "unverified")
        self.assertTrue(verify_password("a-very-safe-password", account.password_hash))
        self.assertNotIn("password_hash", response.model_dump())
        self.assertNotIn("token_version", response.model_dump())

    def test_user_registration_cannot_assign_admin_or_owner_relationship(self):
        with self.assertRaises(ValidationError):
            self.registration(account_type="admin")
        with self.assertRaises(ValidationError):
            self.registration(account_type="user", relationship_type="property_owner")
        user = register(
            self.registration(account_type="user", relationship_type=None),
            self.db,
        )
        self.assertEqual(user.role, "user")

    def test_duplicate_normalized_phone_is_rejected(self):
        register(self.registration(), self.db)
        with self.assertRaises(HTTPException) as raised:
            register(
                self.registration(phone_number="+91-98765-43210"),
                self.db,
            )
        self.assertEqual(raised.exception.status_code, status.HTTP_409_CONFLICT)

    def test_login_rejects_bad_credentials_and_inactive_accounts_generically(self):
        register(self.registration(), self.db)
        for credentials in (
            ("+919876543210", "incorrect-password"),
            ("+919999999999", "incorrect-password"),
        ):
            with self.subTest(phone=credentials[0]):
                with self.assertRaises(HTTPException) as raised:
                    login(
                        AuthLoginRequest(
                            phone_number=credentials[0],
                            password=credentials[1],
                        ),
                        self.db,
                    )
                self.assertEqual(
                    raised.exception.status_code,
                    status.HTTP_401_UNAUTHORIZED,
                )
                self.assertEqual(
                    raised.exception.detail,
                    "Invalid phone number or password",
                )
        account = self.db.query(Owner).one()
        account.is_active = False
        self.db.commit()
        with self.assertRaises(HTTPException) as raised:
            login(
                AuthLoginRequest(
                    phone_number="+919876543210",
                    password="a-very-safe-password",
                ),
                self.db,
            )
        self.assertEqual(raised.exception.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_profile_requires_token_and_owner_role(self):
        _, account, credentials, _ = self.register_and_login()
        self.assertEqual(require_owner(credentials, self.db).id, account.id)
        with self.assertRaises(HTTPException) as missing:
            require_owner(None, self.db)
        self.assertEqual(missing.exception.status_code, status.HTTP_401_UNAUTHORIZED)

        user = register(
            self.registration(
                phone_number="+919123456789",
                account_type="user",
                relationship_type=None,
                email="user@example.com",
            ),
            self.db,
        )
        user_account = self.db.get(Owner, user.id)
        token = login(
            AuthLoginRequest(
                phone_number=user_account.phone_number,
                password="a-very-safe-password",
            ),
            self.db,
        )
        with self.assertRaises(HTTPException) as denied:
            require_owner(
                HTTPAuthorizationCredentials(
                    scheme="Bearer",
                    credentials=token.access_token,
                ),
                self.db,
            )
        self.assertEqual(denied.exception.status_code, status.HTTP_403_FORBIDDEN)
        with self.assertRaises(HTTPException) as admin_denied:
            require_admin_account(
                HTTPAuthorizationCredentials(
                    scheme="Bearer",
                    credentials=token.access_token,
                ),
                self.db,
            )
        self.assertEqual(
            admin_denied.exception.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_admin_role_is_not_publicly_assignable_and_required_for_admin(self):
        with self.assertRaises(ValidationError):
            self.registration(role="admin")
        account = self.db.query(Owner).filter_by(role="owner").first()
        if account is None:
            _, account, _, _ = self.register_and_login()
        token = login(
            AuthLoginRequest(
                phone_number=account.phone_number,
                password="a-very-safe-password",
            ),
            self.db,
        )
        with self.assertRaises(HTTPException) as denied:
            require_admin_account(
                HTTPAuthorizationCredentials(
                    scheme="Bearer",
                    credentials=token.access_token,
                ),
                self.db,
            )
        self.assertEqual(denied.exception.status_code, status.HTTP_403_FORBIDDEN)

    def test_password_change_hashes_new_password_and_revokes_old_token(self):
        _, account, old_credentials, _ = self.register_and_login()
        result = change_password(
            ChangePasswordRequest(
                current_password="a-very-safe-password",
                new_password="another-safe-password",
            ),
            account,
            self.db,
        )
        self.assertIn("sign in again", result.message)
        self.assertTrue(verify_password("another-safe-password", account.password_hash))
        self.assertFalse(verify_password("a-very-safe-password", account.password_hash))
        with self.assertRaises(HTTPException):
            require_owner(old_credentials, self.db)

    def test_password_change_requires_current_password(self):
        _, account, _, _ = self.register_and_login()
        with self.assertRaises(HTTPException) as raised:
            change_password(
                ChangePasswordRequest(
                    current_password="wrong-current-password",
                    new_password="another-safe-password",
                ),
                account,
                self.db,
            )
        self.assertEqual(raised.exception.status_code, status.HTTP_400_BAD_REQUEST)


if __name__ == "__main__":
    unittest.main()
