# Database abstraction layer
# Swap between implementations by changing the import below

# SQLite (original):
from app.db_sqlite3 import *

# Firestore (requires composite indexes in GCP):
# from app.db_firestore import *
