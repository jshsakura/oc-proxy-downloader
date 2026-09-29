# 🚀 OC Proxy Downloader

![Project Banner](https://raw.githubusercontent.com/jshsakura/oc-proxy-downloader/main/docs/banner.png)

**1fichier · MEGA · file-host download manager — proxy-based, runs as a Docker container or a Windows app**

A FastAPI + Svelte web app that resolves file-host links, queues downloads, and shows their status.

## ✨ Key Features

- 🚀 **1fichier Optimized**: Automatic wait time detection and cooldown management (up to 24-hour wait), with a visible quota-recovery countdown
- 🔐 **MEGA Support**: Public-link download with client-side AES decryption (filename, size, progress)
- 🧩 **Host-specific link resolution**: DataNodes, MegaUp, MediaFire, Pixeldrain, Bunkr, AkiraBox, VikingFile, Rootz, and more (see limits below)
- 🔄 **Smart Proxy**: Auto-rotation, failure detection, mixed local/proxy downloads
- 📊 **Real-time Monitoring**: SSE-based real-time status updates and progress display
- 🎯 **Concurrent Download Limits**: 8 global and 3 per host by default; one free 1fichier transfer per egress
- 📱 **Telegram Notifications**: Download completion/failure notification support
- 🌙 **Theme Support**: Dark/Light/Dracula themes
- 🌐 **Multilingual**: 18 bundled UI languages
- 📱 **Responsive UI**: Mobile/Desktop optimized
- 🛡️ **Optional Authentication**: JWT-based security (optional)

## 🐳 Runtime (Docker is the target)

**This project is built for Docker.** Some hosts gate their downloads behind a
Cloudflare Turnstile widget embedded in the page, and clearing it takes a **real
browser** — headless never gets a token, so Chromium has to run against a virtual
display (Xvfb). Both ship **only in the Docker image**.

Running with `docker compose` brings **FlareSolverr up alongside the app**. There is
nothing to install or configure: the app reaches it by service name
(`http://flaresolverr:8191`).

```bash
docker compose up -d      # app + FlareSolverr together
```

> Installing the containers **separately** — TrueNAS or Synology apps, for instance —
> means service-name DNS does not resolve. Set **Settings → FlareSolverr URL** to
> `http://<host IP>:<published port>` instead.

The Windows executable **bundles no browser**, to stay a single portable file. Hosts
marked ❌ below are unsupported there, and adding such a link reports that right away.

## 🌩️ Host support

| Host | Requires | Windows app |
|------|----------|-------------|
| 1fichier, MEGA | nothing | ✅ Works |
| Pixeldrain | nothing (public API) | ✅ Works |
| GoFile | a residential IP (datacenter IPs are blocked) | ✅ Works from a home IP/NAS |
| MediaFire | FlareSolverr when Cloudflare-challenged | 🟡 Works unless challenged |
| MegaUp | FlareSolverr (always) | ❌ Needs an external FlareSolverr |
| Bunkr | FlareSolverr when challenged | 🟡 Encrypted-CDN links may not resolve |
| **DataNodes** | **a browser (Turnstile captcha)** | ❌ **Docker only** |
| Send.now | FlareSolverr, or a browser when captcha-gated | 🟡 Fails if a captcha appears |
| **AkiraBox** (`akirabox.com`, `akirabox.to`) | **Browser to issue a short-lived download URL** | ❌ **Docker only** |
| **VikingFile** (`vikingfile.com`, `vik1ngfile.site`) | **Browser and Turnstile captcha** | ❌ **Docker only** |
| **Rootz** (`rootz.so`) | **Browser to verify metadata and resolve the file URL** | ❌ **Docker only** |
| DataVaults | reCAPTCHA v2 on the free-download step | ❌ Automated downloads unsupported |

Browser-based link resolution runs **one link at a time per site**. Waiting for a
turn does not consume a failure retry. AkiraBox, VikingFile, and Rootz resolve
their file URL once when the download slot is available; a failed resolution does
not cycle through multiple proxies. Each of these hosts allows up to three
concurrent transfers. Their domain aliases share the same limit.

The defaults are 8 global transfers and 3 per host. Set `max_concurrent_downloads`
and `max_per_host_downloads` in `/config/config.json` or the web settings to lower
them. Free 1fichier transfers are limited to one per egress; DataNodes and
MultiUp are limited to one per host.

> Turnstile and free-download limits vary by host and egress address. A resolved
> link can still be refused by the file server when the transfer begins.

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
docker compose up -d
```

### 🪟 Windows Executable

We provide a standalone executable for Windows users:

1. Download the latest Windows version from **[Releases](https://github.com/jshsakura/oc-proxy-downloader/releases)**
2. Run `oc-proxy-downloader-windows.exe`
3. Access **http://localhost:8000** to use

> **Note**: The Windows executable runs without Docker, but does not include Chromium or Xvfb. Docker-only hosts in the table above are unavailable there.

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
| `TZ` | `Asia/Seoul` (Docker image) | System timezone setting |
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
| `API_TOKEN` | generated if unset | Server-to-server `/api/*` token (`X-API-Key`) |
| `FLARESOLVERR_URL` | `http://flaresolverr:8191` (Compose) | FlareSolverr endpoint |

Download concurrency is configured in `/config/config.json` or the web settings,
not through environment variables. Defaults: `max_concurrent_downloads=8`,
`max_per_host_downloads=3`.

## 📁 Directory Structure

```
oc-proxy-downloader/
├── downloads/           # Downloaded files storage
├── backend/config/      # Configuration files and database
│   ├── downloads.db    # SQLite database
│   └── config.json     # App configuration file
└── docker-compose.yml  # Docker Compose configuration
```

## 🚀 Usage

1. Access **http://localhost:8000**
2. Add proxies in **Settings** → **Proxy Management** if needed
3. Enter a supported host URL and start the download
4. Monitor **real-time progress** and **proxy status**

## 🔧 Development Environment

```bash
# Clone repository
git clone https://github.com/jshsakura/oc-proxy-downloader.git
cd oc-proxy-downloader

# Run development environment
docker compose up -d --build

# Check logs
docker compose logs -f
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
docker compose logs -f

# Health check
curl http://localhost:8000/api/auth/status
```

## 🆘 Troubleshooting

### Container Startup Failure
```bash
# Check logs
docker compose logs oc-proxy-downloader

# Permission issues (Linux/macOS)
sudo chown -R 1000:1000 downloads backend/config
```

### Port Conflicts
```bash
# Change the Compose ports mapping to "8080:8000", then restart
docker compose up -d
```

### Cache Issues
```bash
# Rebuild without cache
docker compose build --no-cache
docker compose up -d
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
