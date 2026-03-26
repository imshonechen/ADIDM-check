import sys
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')

sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from app.config import Config


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == 'init-admin':
        import argparse
        parser = argparse.ArgumentParser(description='Initialize admin user')
        parser.add_argument('command')
        parser.add_argument('--username', required=True)
        parser.add_argument('--password', required=True)
        args = parser.parse_args()

        from app.models import init_db, create_admin
        db_path = Config.DATABASE_PATH
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        init_db(db_path)
        create_admin(db_path, args.username, args.password)
        print(f'Admin user "{args.username}" created/updated successfully.')
        return

    app = create_app()
    app.run(host='0.0.0.0', port=Config.PORT, debug=True, use_reloader=False)


if __name__ == '__main__':
    main()
