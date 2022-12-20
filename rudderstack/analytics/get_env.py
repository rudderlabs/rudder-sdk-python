import os
from dotenv import load_dotenv

load_dotenv()

TEST_SECRET = os.getenv('TEST_SECRET')
TEST_DATA_PLANE_URL = os.getenv('TEST_DATA_PLANE_URL')
