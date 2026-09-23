web: bash scripts/start.sh
release: python manage.py migrate --noinput && python manage.py initadmin && python manage.py load_demo_data && python manage.py collectstatic --noinput && cd whatsapp_service && npm install --omit=dev

