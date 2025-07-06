import pytest
from core.exceptions import DatabaseError, DBConnectionError, QueryError

class TestCustomExceptions:
    """
    Loyiha uchun maxsus yaratilgan xatolik klasslarini test qilish.
    """

    def test_database_error_can_be_raised(self):
        """DatabaseError xatoligini ko'tarishni tekshirish."""
        with pytest.raises(DatabaseError):
            raise DatabaseError("Umumiy baza xatoligi")

    def test_db_connection_error_can_be_raised(self):
        """DBConnectionError xatoligini ko'tarishni tekshirish."""
        with pytest.raises(DBConnectionError):
            raise DBConnectionError("Ulanishda xato")

    def test_query_error_can_be_raised(self):
        """QueryError xatoligini ko'tarishni tekshirish."""
        with pytest.raises(QueryError):
            raise QueryError("So'rovda xato")

    def test_inheritance_hierarchy(self):
        """Xatoliklarning meros zanjiri to'g'riligini tekshirish."""
        # DBConnectionError va QueryError -> DatabaseError'dan meros olishi kerak
        assert issubclass(DBConnectionError, DatabaseError)
        assert issubclass(QueryError, DatabaseError)
        
        # Ular bir-biridan mustaqil bo'lishi kerak
        assert not issubclass(QueryError, DBConnectionError)
        assert not issubclass(DBConnectionError, QueryError)

