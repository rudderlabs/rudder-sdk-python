import os
from dotenv import load_dotenv

load_dotenv()

TEST_SECRET = os.getenv('TEST_SECRET')
HOST_URL = os.getenv('HOST_URL')
