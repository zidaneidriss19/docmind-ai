import argparse
from time import sleep

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import database_engine
from app.documents import recover_storage


def recover_once() -> int:
    try:
        with Session(database_engine()) as db:
            recovered, failed = recover_storage(db)
    except SQLAlchemyError:
        print("Document storage recovery could not reach PostgreSQL.", flush=True)
        return 1
    if recovered or failed:
        print(
            f"Storage operations recovered: {recovered}; still pending: {failed}",
            flush=True,
        )
    return int(failed > 0)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recover interrupted document storage operations."
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Retry pending operations every 30 seconds.",
    )
    if not parser.parse_args().watch:
        return recover_once()

    try:
        while True:
            recover_once()
            sleep(30)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
