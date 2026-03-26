import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'change-this-to-a-random-secret-key')
    DATABASE_PATH = os.path.join(BASE_DIR, 'data', 'adidm.db')
    SCRAPE_URL = 'https://idm.0dy.ir/'
    SCRAPE_USER_AGENT = 'Mozilla/5.0 (Windows NT 6.1; Trident/7.0; rv:11.0) like Gecko'
    SCRAPE_HOUR = 8
    SCRAPE_MINUTE = 0
    REQUEST_TIMEOUT = 30
    PORT = 26300
