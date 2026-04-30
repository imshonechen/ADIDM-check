import sys
import os
import logging
from getpass import getpass

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
        parser.add_argument('--password')
        args = parser.parse_args()

        password = args.password
        if password is None:
            password = getpass('Password: ')
            password_confirm = getpass('Confirm password: ')
            if password != password_confirm:
                print('Error: passwords do not match.')
                sys.exit(1)
        if not password:
            print('Error: password cannot be empty.')
            sys.exit(1)

        from app.models import init_db, create_admin
        db_path = Config.DATABASE_PATH
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        init_db(db_path)
        create_admin(db_path, args.username, password)
        print(f'Admin user "{args.username}" created/updated successfully.')
        return

    app = create_app()
    app.run(host='0.0.0.0', port=Config.PORT, debug=True, use_reloader=False)


if __name__ == '__main__':
    main()
