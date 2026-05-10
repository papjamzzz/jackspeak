from flask import Flask, render_template, jsonify
from dotenv import load_dotenv
import os

load_dotenv()
app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def status():
    return jsonify({'status': 'ok', 'project': 'jackspeak'})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5568, debug=False)
