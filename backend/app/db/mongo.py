from typing import Any

from pymongo import MongoClient

from app.core.config import get_settings

mongo_client: MongoClient[dict[str, Any]] = MongoClient(get_settings().mongo_url)
mongo_db = mongo_client[get_settings().mongo_db]
