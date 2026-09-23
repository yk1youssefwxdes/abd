web: bash scripts/start.sh
release: python manage.py migrate --noinput && python manage.py initadmin && python manage.py abd_prof && python manage.py collectstatic --noinput && cd whatsapp_service && npm install --omit=dev

