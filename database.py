import urllib.parse
import os
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base


def load_environment_from_dotenv() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#") or "=" not in candidate:
            continue

        key, value = candidate.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_environment_from_dotenv()

# 1. Server Name và Database Name
SERVER_NAME = os.environ.get("SQLSERVER_HOST", "localhost")
DATABASE_NAME = os.environ.get("SQLSERVER_DATABASE", "AgricultureDB")
ODBC_DRIVER = os.environ.get("SQLSERVER_DRIVER", "ODBC Driver 17 for SQL Server")

# 2. Tao chuoi ket noi ODBC an toan (Ma hoa tu dong cac ky tu dac biet nhi \\ va khoang trang)
params = urllib.parse.quote_plus(
    f"DRIVER={{{ODBC_DRIVER}}};"
    f"SERVER={SERVER_NAME};"
    f"DATABASE={DATABASE_NAME};"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)

DATABASE_URL = f"mssql+pyodbc:///?odbc_connect={params}"

# 3. Khởi tạo Engine và Session
engine = create_engine(
    DATABASE_URL,
    echo=os.environ.get("SQLALCHEMY_ECHO", "false").lower() == "true",
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_chat_history_user_id():
    with engine.begin() as connection:
        connection.execute(text("""
            IF COL_LENGTH(N'dbo.chat_history', N'user_id') IS NULL
                ALTER TABLE dbo.chat_history ADD user_id INT NULL;

            IF OBJECT_ID(N'dbo.users', N'U') IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1
                   FROM sys.foreign_keys
                   WHERE name = N'FK_chat_history_users_user_id'
               )
                ALTER TABLE dbo.chat_history
                ADD CONSTRAINT FK_chat_history_users_user_id
                FOREIGN KEY (user_id) REFERENCES dbo.users(id);
        """))


def migrate_parcels_user_id():
    """Thêm cột user_id vào bảng parcels nếu chưa có."""
    with engine.begin() as connection:
        connection.execute(text("""
            IF COL_LENGTH(N'dbo.parcels', N'user_id') IS NULL
                ALTER TABLE dbo.parcels ADD user_id INT NULL;

            IF OBJECT_ID(N'dbo.users', N'U') IS NOT NULL
               AND NOT EXISTS (
                  SELECT 1
                  FROM sys.foreign_keys
                  WHERE name = N'FK_parcels_users_user_id'
               )
                ALTER TABLE dbo.parcels
                ADD CONSTRAINT FK_parcels_users_user_id
                FOREIGN KEY (user_id) REFERENCES dbo.users(id);
        """))


def migrate_user_location_cols():
    """Thêm cột lưu vị trí GPS vào bảng users nếu chưa có."""
    with engine.begin() as connection:
        connection.execute(text("""
            IF COL_LENGTH(N'dbo.users', N'latitude') IS NULL
                ALTER TABLE dbo.users ADD latitude FLOAT NULL;

            IF COL_LENGTH(N'dbo.users', N'longitude') IS NULL
                ALTER TABLE dbo.users ADD longitude FLOAT NULL;

            IF COL_LENGTH(N'dbo.users', N'location_updated_at') IS NULL
                ALTER TABLE dbo.users ADD location_updated_at DATETIME NULL;
        """))


def migrate_unicode_text_columns() -> int:
    """Convert user-facing text fields to SQL Server Unicode storage."""
    column_lengths = {
        "users": {"full_name": 100},
        "chat_history": {
            "user_message": None,
            "bot_response": None,
            "intent": 100,
        },
        "crop_logs": {
            "ten_cay_trong": 100,
            "ghi_chu": None,
        },
        "parcels": {
            "name": 100,
            "crop_type": 100,
            "geometry_geojson": None,
            "notes": None,
        },
        "map_objects": {
            "name": 100,
            "object_type": 50,
            "description": None,
            "geometry_geojson": None,
        },
        "ai_error_logs": {
            "model": 100,
            "error_type": 200,
            "error_message": None,
        },
    }
    migrated_columns = 0

    with engine.begin() as connection:
        for table_name, columns in column_lengths.items():
            for column_name, expected_length in columns.items():
                column = connection.execute(
                    text("""
                        SELECT DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
                        FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_SCHEMA = N'dbo'
                          AND TABLE_NAME = :table_name
                          AND COLUMN_NAME = :column_name
                    """),
                    {"table_name": table_name, "column_name": column_name},
                ).mappings().first()
                if column is None:
                    continue

                expected_database_length = -1 if expected_length is None else expected_length
                if (
                    column["DATA_TYPE"].lower() == "nvarchar"
                    and column["CHARACTER_MAXIMUM_LENGTH"] == expected_database_length
                ):
                    continue

                target_length = "MAX" if expected_length is None else expected_length
                nullable = "NULL" if column["IS_NULLABLE"] == "YES" else "NOT NULL"
                connection.execute(text(
                    f"ALTER TABLE [dbo].[{table_name}] "
                    f"ALTER COLUMN [{column_name}] NVARCHAR({target_length}) {nullable}"
                ))
                migrated_columns += 1

    return migrated_columns


