# userbot/core/exceptions.py

class DatabaseError(Exception):
    pass

class DBConnectionError(DatabaseError):
    pass

class QueryError(DatabaseError):
    pass