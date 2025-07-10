### 가상 환경 생성

python -m venv venv

### 가상 환경 활성화 (Windows)

.\venv\Scripts\activate

### 가상 환경 활성화 (macOS/Linux)

source venv/bin/activate

pip freeze > requirements.txt

pip install "fastapi[all]"
pip install requests

npx https://github.com/google-gemini/gemini-cli
