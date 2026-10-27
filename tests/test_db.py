from sqlalchemy import text


def test_test_database_has_postgis(db_engine):
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1
        # This confirms migrations had been run
        assert conn.execute(text("SELECT postgis_version()")).scalar()
