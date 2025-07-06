import pytest
from core.db_whitelists import DB_TABLE_WHITELIST, DB_COLUMN_WHITELIST

class TestDatabaseWhitelists:
    """
    Ma'lumotlar bazasi uchun xavfsizlik ro'yxatlarining
    mavjudligi va to'g'riligini tekshirish.
    """

    def test_table_whitelist_is_not_empty(self):
        """DB_TABLE_WHITELIST ro'yxati bo'sh emasligini tekshirish."""
        assert isinstance(DB_TABLE_WHITELIST, list)
        assert len(DB_TABLE_WHITELIST) > 0, "Jadvallar ro'yxati bo'sh bo'lmasligi kerak."
        assert "accounts" in DB_TABLE_WHITELIST, "'accounts' jadvali ro'yxatda bo'lishi shart."

    def test_column_whitelist_is_not_empty(self):
        """DB_COLUMN_WHITELIST lug'ati bo'sh emasligini tekshirish."""
        assert isinstance(DB_COLUMN_WHITELIST, dict)
        assert len(DB_COLUMN_WHITELIST) > 0, "Ustunlar ro'yxati bo'sh bo'lmasligi kerak."
        assert "accounts" in DB_COLUMN_WHITELIST, "'accounts' jadvali ustunlari ro'yxatda bo'lishi shart."

    def test_all_tables_in_column_whitelist_exist_in_table_whitelist(self):
        """Ustunlar ro'yxatidagi har bir jadval, jadvallar ro'yxatida ham borligini tekshirish."""
        table_whitelist_set = set(DB_TABLE_WHITELIST)
        for table_name in DB_COLUMN_WHITELIST.keys():
            assert table_name in table_whitelist_set, \
                f"'{table_name}' jadvali DB_COLUMN_WHITELIST'da bor, lekin DB_TABLE_WHITELIST'da yo'q."

    def test_column_whitelist_values_are_lists_of_strings(self):
        """Ustunlar ro'yxatining qiymatlari stringlar ro'yxati ekanligini tekshirish."""
        for table, columns in DB_COLUMN_WHITELIST.items():
            assert isinstance(columns, list), f"'{table}' jadvali uchun ustunlar ro'yxat emas."
            assert all(isinstance(col, str) for col in columns), \
                f"'{table}' jadvali uchun barcha ustun nomlari string bo'lishi kerak."

