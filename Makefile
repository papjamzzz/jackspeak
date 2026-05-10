.PHONY: run setup push zip

PROJECT = jackspeak

run:
	python3 app.py

setup:
	python3 -m pip install -r requirements.txt
	cp -n .env.example .env || true

push:
	git add .
	git commit -m "$(m)"
	git push origin main

zip:
	zip -r ../$(PROJECT).zip . --exclude "*.pyc" --exclude ".env" --exclude "data/*" --exclude ".DS_Store"
