# 🚀 OC Proxy Downloader

![Project Banner](https://raw.githubusercontent.com/jshsakura/oc-proxy-downloader/main/docs/banner.png)

**Proxy-based 1fichier Download Management System**

A web application built with FastAPI + Svelte that provides stable file downloads through proxy servers.

## ✨ Key Features

- 🚀 **1fichier Optimized**: Automatic wait time detection and cooldown management (up to 24-hour wait)
- 🔄 **Smart Proxy**: Auto-rotation, failure detection, mixed local/proxy downloads
- 📊 **Real-time Monitoring**: SSE-based real-time status updates and progress display
- 🎯 **Concurrent Download Limits**: Semaphore-based limits for system stability
- 📱 **Telegram Notifications**: Download completion/failure notification support
- 🌙 **Theme Support**: Dark/Light/Dracula themes
- 🌐 **Multilingual**: Full Korean/English support
- 📱 **Responsive UI**: Mobile/Desktop optimized
- 🛡️ **Optional Authentication**: JWT-based security (optional)

---

<div align="center">
  <img src="https://github.com/jshsakura/oc-proxy-downloader/blob/main/docs/preview/preview1.png?raw=true" alt="OC Proxy Downloader" style="max-width: 700px; border-radius: 12px; margin-bottom: 1rem;" />
  <br/>
  <a href="https://www.opencourse.kr/1fichier-oc-proxy-downloader/">📚 Detailed Installation Guide</a> | <a href="README_KR.md">🇰🇷 한국어 문서</a>
</div>

---

## 🛠️ Tech Stack

### Backend
- **FastAPI**: High-performance async web framework
- **SQLAlchemy**: ORM and database management
- **SQLite**: Main database
- **aiohttp**: Async HTTP client (download/proxy)
- **SSE**: Server-Sent Events for real-time communication

### Frontend
- **Svelte**: Compile-based reactive framework
- **Vite**: Fast development server and build tool
- **SSE**: Real-time status update reception

### Infrastructure
- **Docker**: Containerized deployment
- **Docker Compose**: Development/production environment management

## 🚀 Installation

### 🐳 Docker Compose Installation (Recommended)

```bash
# 1. Download project
curl -O https://raw.githubusercontent.com/jshsakura/oc-proxy-downloader/main/docker-compose.yml

# 2. Create directories
mkdir -p downloads backend/config

# 3. Run
docker-compose up -d
```

### 🪟 Windows Executable

We provide a standalone executable for Windows users:

1. Download the latest Windows version from **[Releases](https://github.com/jshsakura/oc-proxy-downloader/releases)**
2. Run `oc-proxy-downloader-windows.exe`
3. Access **http://localhost:8000** to use

> **Note**: The Windows version is a standalone executable with all features included. No Docker installation required.

### 🔧 Docker Compose Configuration Examples

#### General Linux Environment

```yaml
# docker-compose.yml
version: "3.8"
services:
  oc-proxy-downloader:
    image: jshsakura/oc-proxy-downloader:latest
    container_name: oc-proxy-downloader
    environment:
      - TZ=Asia/Seoul
      - PUID=1000
      - PGID=1000
      # Security (optional)
      # - AUTH_USERNAME=admin
      # - AUTH_PASSWORD=secure123
      # - JWT_SECRET_KEY=your-random-secret-key
    volumes:
      - ./downloads:/downloads
      - ./backend/config:/config
    ports:
      - "8000:8000"
    restart: unless-stopped
```

#### Synology NAS Environment

```yaml
# docker-compose.yml (Synology)
version: "3.8"
services:
  oc-proxy-downloader:
    image: jshsakura/oc-proxy-downloader:latest
    container_name: oc-proxy-downloader
    environment:
      - TZ=Asia/Seoul
      - PUID=1026    # Synology user ID (check with id command)
      - PGID=100     # Synology users group ID
      # Security (optional)
      # - AUTH_USERNAME=admin
      # - AUTH_PASSWORD=secure123
      # - JWT_SECRET_KEY=your-random-secret-key
    volumes:
      - /volume1/docker/oc-proxy/downloads:/downloads
      - /volume1/docker/oc-proxy/config:/config
    ports:
      - "8000:8000"
    restart: unless-stopped
```

> **Synology Users Note**: SSH into your NAS and use the `id` command to check your PUID

## ⚙️ Environment Variables

### Basic Configuration
| Variable | Default | Description |
|----------|---------|-------------|
| `TZ` | `UTC` | System timezone setting |
| `PUID` | `1000` | File owner ID (permission management) |
| `PGID` | `1000` | File group ID (permission management) |

### Security Settings (Optional)
| Variable | Default | Description |
|----------|---------|-------------|
| `AUTH_USERNAME` | - | Web login ID (no auth if not set) |
| `AUTH_PASSWORD` | - | Web login password |
| `JWT_SECRET_KEY` | default | JWT token encryption key (must change in production) |

> **⚠️ Security Warning**: In production, always set `JWT_SECRET_KEY` to a secure random string.

### Advanced Settings (Optional)
| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_TOTAL_DOWNLOADS` | `5` | Maximum total concurrent downloads |
| `MAX_LOCAL_DOWNLOADS` | `1` | Maximum concurrent 1fichier local downloads |

## 📁 Directory Structure

```
oc-proxy-downloader/
├── downloads/           # Downloaded files storage
├── backend/config/      # Configuration files and database
│   ├── downloads.db    # SQLite database
│   ├── config.json     # App configuration file
│   └── proxies.txt     # Proxy list
└── docker-compose.yml  # Docker Compose configuration
```

## 🚀 Usage

1. Access **http://localhost:8000**
2. **Settings** → **Proxy Management** to add proxies
3. Enter **1fichier URL** and start download
4. Monitor **real-time progress** and **proxy status**

## 🔧 Development Environment

```bash
# Clone repository
git clone https://github.com/jshsakura/oc-proxy-downloader.git
cd oc-proxy-downloader

# Run development environment
docker-compose -f docker-compose.dev.yml up -d --build

# Check logs
docker-compose logs -f
```

### Backend Development
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### Frontend Development
```bash
cd frontend
npm install
npm run dev
```

## 📊 Monitoring

```bash
# Check container status
docker ps

# Check resource usage
docker stats oc-proxy-downloader

# Real-time logs
docker-compose logs -f

# Health check
curl http://localhost:8000/api/settings
```

## 🆘 Troubleshooting

### Container Startup Failure
```bash
# Check logs
docker-compose logs oc-proxy-downloader

# Permission issues (Linux/macOS)
sudo chown -R 1000:1000 downloads backend/config
```

### Port Conflicts
```bash
# Use different port (e.g., 8080)
docker-compose up -d -p 8080:8000
```

### Cache Issues
```bash
# Rebuild without cache
docker-compose build --no-cache
docker-compose up -d
```

## 📞 Support

- 📋 **Report Issues**: [GitHub Issues](https://github.com/jshsakura/oc-proxy-downloader/issues)
- 💬 **Discussions**: [GitHub Discussions](https://github.com/jshsakura/oc-proxy-downloader/discussions)
- 📖 **Detailed Guide**: [Installation Guide](https://www.opencourse.kr/1fichier-oc-proxy-downloader/)
- 🇰🇷 **Korean Documentation**: [README_KR.md](README_KR.md)

## 📄 License

This project is distributed under the MIT License.

---

**⭐ If this project helped you, please give it a Star!**