"""Persist the Acme demo into the local database."""

from gateway.main import SessionLocal
from gateway.seed import seed_tenant

if __name__ == "__main__":
    session = SessionLocal()
    try:
        result = seed_tenant(session, "demo")
        session.commit()
        print(result)
    finally:
        session.close()
